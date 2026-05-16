"""FastAPI routes for NCL brain service."""

import asyncio
import html as html_mod
import ipaddress
import json
import os
import secrets
import sys
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import logging
import logging.config

# ---------------------------------------------------------------------------
# Early logging configuration.
#
# When this module is the launchd entrypoint (`python -m runtime.api.routes`),
# uvicorn only configures its own `uvicorn.*` loggers. Everything else inherits
# the Python default root level (WARNING), so every `log.info(...)` emitted by
# `ncl.autonomous`, `ncl.council`, `ncl.intelligence`, etc. is silently
# dropped — including the scheduler startup banner and per-loop tick logs.
#
# Configure stderr logging here, BEFORE any FastAPI / scheduler code runs, so
# that lifespan-startup logs and background-task logs both reach the launchd
# stderr file (`logs/ncl-brain-stderr.log`). Honor NCL_LOG_LEVEL for overrides.
# ---------------------------------------------------------------------------
_NCL_LOG_LEVEL = os.environ.get("NCL_LOG_LEVEL", "INFO").upper()

# When NCL_LOG_FORMAT=json, emit JSON-structured logs (for log-aggregation
# pipelines and structured-search). Otherwise fall back to the human-readable
# text format. python-json-logger is a hard dependency in pyproject.toml so
# the import should always succeed; we still guard against ImportError so the
# brain can boot in a stripped-down env.
_NCL_LOG_FORMAT = os.environ.get("NCL_LOG_FORMAT", "text").lower()
_log_formatter: dict
if _NCL_LOG_FORMAT == "json":
    try:
        from pythonjsonlogger import jsonlogger  # noqa: F401  (importability check)
        _log_formatter = {
            "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
            "format": "%(asctime)s %(name)s %(levelname)s %(message)s",
            "rename_fields": {"asctime": "ts", "levelname": "level", "name": "logger"},
        }
    except ImportError:
        _log_formatter = {
            "format": "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        }
else:
    _log_formatter = {
        "format": "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    }

logging.config.dictConfig({
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "ncl": _log_formatter,
    },
    "handlers": {
        "stderr": {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stderr",
            "formatter": "ncl",
            "level": _NCL_LOG_LEVEL,
        },
    },
    "root": {
        "handlers": ["stderr"],
        "level": _NCL_LOG_LEVEL,
    },
})
# Uvicorn will (re)configure its own `uvicorn.*` loggers with its own
# handlers + formatters when uvicorn.run() executes. Its loggers default to
# propagate=False, so they won't double-emit through our root handler.

import aiofiles
import urllib.request
from fastapi import FastAPI, HTTPException, Header, Query, Body, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field

# Rate limiting
try:
    from slowapi import Limiter, _rate_limit_exceeded_handler
    from slowapi.util import get_remote_address
    from slowapi.errors import RateLimitExceeded
    _limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])
    _has_slowapi = True
except ImportError:
    _limiter = None
    _has_slowapi = False

from .config import load_config, create_config_file, validate_config
from ..ncl_brain.brain import NCLBrain
from ..ncl_brain.models import (
    PumpPrompt,
    Mandate,
    CouncilSession,
    FeedbackReport,
    PillarType,
    MandateStatus,
    NCLEvent,
    EventType,
)
from ..search.indexer import SearchIndexer

# Sprint 2 — Telemetry, Governance, Evaluation
from ..telemetry.schema import TelemetryConfig, TelemetryLevel
from ..telemetry.collector import TelemetryCollector
from ..telemetry.availability import AvailabilityTracker, AvailabilityConfig
from ..governance.models import ActionTier, ConsentStatus, PolicyVerdict, Action
from ..governance.policy_kernel import PolicyKernel
from ..governance.action_router import ActionRouter
from ..governance.emergency_stop import EmergencyStop
from ..evaluation.models import SuiteResult
from ..evaluation.runner import GoldenTaskRunner

# Sprint 3 — Review Queue
from ..review_queue.manager import ReviewQueueManager

# Sprint 4 — Council Runner v1
from ..council_runner.models import CouncilRunRecord, ReplayConfig
from ..council_runner.agents import run_parallel_council
from ..council_runner.replay import ReplayEngine
from ..council_runner.store import CouncilRunStore

# Global brain instance + search indexer
brain: NCLBrain | None = None
search_index: SearchIndexer | None = None
config = load_config()

# Sprint 2 globals
_telemetry: TelemetryCollector | None = None
_availability: AvailabilityTracker | None = None
_policy_kernel: PolicyKernel | None = None
_action_router: ActionRouter | None = None
_emergency_stop: EmergencyStop | None = None
_eval_runner: GoldenTaskRunner | None = None

# Sprint 3+4 globals
_review_queue: ReviewQueueManager | None = None
_council_store: CouncilRunStore | None = None
_replay_engine: ReplayEngine | None = None

# Pipeline Hardening globals
_research_cortex = None  # lazy import to avoid circular
_memory_bridge = None
_deployment_monitor = None

# Autonomous Scheduler
from ..autonomous.scheduler import AutonomousScheduler
_autonomous: AutonomousScheduler | None = None

# Intelligence Engine
from ..intelligence.engine import IntelligenceEngine
_intelligence: IntelligenceEngine | None = None

# Module-level logger — used throughout this file as `log`
log = logging.getLogger(__name__)

# Strike point authentication token — load from config (.env) FIRST, then env var, then auto-gen
STRIKE_TOKEN = config.strike_auth_token or os.getenv("STRIKE_AUTH_TOKEN", "")
if not STRIKE_TOKEN:
    # Auto-generate and log so NATRIX can copy it into the iOS Shortcut
    STRIKE_TOKEN = secrets.token_urlsafe(32)
    _masked = f"...{STRIKE_TOKEN[-4:]}"
    logging.getLogger("ncl.strike").warning(
        f"No STRIKE_AUTH_TOKEN set. Auto-generated token ending in {_masked} — "
        f"Set this in .env and in the iOS Shortcut."
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan context manager for startup/shutdown."""
    global brain

    # Startup — validate required config before initialising anything
    validate_config(config)
    create_config_file(config.config_dir)
    brain = NCLBrain(
        data_dir=config.data_dir,
        claude_api_key=config.anthropic_api_key,
        anthropic_base_url=config.anthropic_base_url,
        xai_api_key=config.xai_api_key,
        google_api_key=config.google_api_key,
        perplexity_api_key=config.perplexity_api_key,
        openai_api_key=config.openai_api_key,
        copilot_api_key=config.copilot_api_key,
        x_bearer_token=config.x_bearer_token,
        youtube_api_key=config.youtube_api_key,
        reddit_client_id=config.reddit_client_id,
        reddit_client_secret=config.reddit_client_secret,
        ollama_host=config.ollama_host,
        paperclip_host=config.paperclip_host,
        paperclip_port=config.paperclip_port,
    )
    await brain.init()

    # Initialize search indexer and build index from existing data
    global search_index
    search_index = SearchIndexer(data_dir=config.data_dir)
    await search_index.load()

    # Sprint 2 — Telemetry
    global _telemetry, _availability
    _telemetry = TelemetryCollector(data_dir=config.data_dir, config=TelemetryConfig())
    await _telemetry.init()
    _availability = AvailabilityTracker(data_dir=config.data_dir)
    await _availability.init()

    # Sprint 2 — Governance
    global _policy_kernel, _action_router, _emergency_stop
    _emergency_stop = EmergencyStop(data_dir=config.data_dir)
    await _emergency_stop.init()
    _policy_kernel = PolicyKernel(data_dir=config.data_dir)
    await _policy_kernel.init()
    _action_router = ActionRouter(policy_kernel=_policy_kernel)

    # Wire governance into brain (closes the architectural gap where
    # brain.policy_kernel and brain.emergency_stop stayed None)
    brain.policy_kernel = _policy_kernel
    brain.emergency_stop = _emergency_stop

    # Cross-register subsystems so EmergencyStop.activate() actually freezes
    # the kernel/scheduler/swarm/intelligence engine instead of silently
    # no-op'ing through None handles. PolicyKernel also learns about the
    # stop so its own evaluate() sees a consistent flag.
    try:
        _policy_kernel.register_emergency_stop(_emergency_stop)
    except Exception as _exc:
        log.warning(f"[lifespan] PolicyKernel.register_emergency_stop failed: {_exc}")
    try:
        _emergency_stop.register_subsystems(
            policy_kernel=_policy_kernel,
            scheduler=getattr(brain, "_scheduler", None),
            swarm_orchestrator=getattr(brain, "swarm", None),
            intelligence_engine=getattr(brain, "intelligence_engine", None),
        )
    except Exception as _exc:
        log.warning(f"[lifespan] EmergencyStop.register_subsystems failed: {_exc}")

    # Sprint 2 — Evaluation
    global _eval_runner
    _eval_runner = GoldenTaskRunner(data_dir=config.data_dir)

    # Sprint 3 — Review Queue
    global _review_queue
    _review_queue = ReviewQueueManager(data_dir=str(Path(config.data_dir) / "review_queue"))
    await _review_queue.init()

    # Sprint 4 — Council Runner
    global _council_store, _replay_engine
    _council_store = CouncilRunStore(data_dir=config.data_dir)
    _replay_engine = ReplayEngine(data_dir=config.data_dir)

    # Pipeline Hardening — UNI Research Cortex
    global _research_cortex, _memory_bridge, _deployment_monitor
    from ..uni.cortex import ResearchCortex
    _research_cortex = ResearchCortex(
        data_dir=config.data_dir,
        claude_api_key=config.anthropic_api_key,
        xai_api_key=config.xai_api_key,
        ollama_host=config.ollama_host,
    )

    # Wire Research Cortex into brain for integrated research dispatch
    brain.research_cortex = _research_cortex

    # Pipeline Hardening — Memory Dashboard Bridge
    from ..memory.dashboard_bridge import MemoryDashboardBridge
    if brain and brain.memory_store:
        _memory_bridge = MemoryDashboardBridge(memory_store=brain.memory_store)

    # Pipeline Hardening — Deployment Monitor
    from ..deployment.monitor import ServiceMonitor
    from ..deployment.manager import DeploymentManager
    _dm = DeploymentManager()
    _deployment_monitor = ServiceMonitor(
        data_dir=config.data_dir, services=_dm.config.services,
    )

    # Intelligence Engine — real-time actionable intelligence
    global _intelligence
    _intelligence = IntelligenceEngine(config=config)
    await _intelligence.initialize()

    # Bridge: connect intelligence engine to brain's MemoryStore
    # so intelligence signals get written for the predictor to consume
    if hasattr(brain, 'memory_store') and brain.memory_store is not None:
        _intelligence.set_memory_store(brain.memory_store)

    # Autonomous Scheduler — makes NCL a true second brain
    global _autonomous
    _autonomous = AutonomousScheduler(brain=brain, config=config, intelligence_engine=_intelligence)
    _autonomous.council_trigger_threshold = config.council_trigger_threshold
    _autonomous.council_min_signals = config.council_min_signals
    if config.autonomous_enabled:
        await _autonomous.start()
    else:
        import logging
        logging.getLogger("ncl.autonomous").info(
            "Autonomous scheduler DISABLED (set autonomous_enabled: true to enable)"
        )

    yield

    # Shutdown
    if _intelligence:
        await _intelligence.close()
    if _autonomous:
        await _autonomous.stop()
    if _telemetry:
        await _telemetry.shutdown()
    if brain:
        await brain.shutdown()


app = FastAPI(
    title=config.service_name,
    version=config.service_version,
    description="NCL Brain - Think, Research, Plan, Decide",
    lifespan=lifespan,
)

# Rate limiting middleware
if _has_slowapi and _limiter:
    app.state.limiter = _limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS middleware
_allowed_origins_env = os.getenv("ALLOWED_ORIGINS", os.getenv("CORS_ALLOWED_ORIGINS", ""))
if _allowed_origins_env:
    allowed_origins = [o.strip() for o in _allowed_origins_env.split(",") if o.strip()]
else:
    allowed_origins = [
        "http://localhost:3000",
        "http://localhost:8000",
        "http://localhost:8800",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:8000",
        "http://127.0.0.1:8800",
    ]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# NOTE: BodySizeLimitMiddleware is registered after its definition below.

# ---------------------------------------------------------------------------
# Simple in-memory rate limiter — fallback when slowapi is not installed.
# Limits sensitive endpoints to 30 req/minute per IP.
# Uses sliding window with non-blocking lock (trylock pattern).
# ---------------------------------------------------------------------------
import threading as _threading
import time as _time
from collections import defaultdict, deque

_rate_limit_store: dict[str, deque] = defaultdict(lambda: deque())
_rate_limit_lock = _threading.Lock()
_RATE_LIMIT_WINDOW = 60  # seconds
_RATE_LIMIT_MAX = 30     # requests per window


def _check_rate_limit(request: Request, limit: int = _RATE_LIMIT_MAX) -> None:
    """Raise HTTP 429 if the calling IP exceeds `limit` requests per minute.

    Uses a short-held blocking lock (microsecond critical section) so the
    sliding-window bookkeeping cannot be bypassed under contention.  Eviction
    of stale per-IP buckets is performed on every call to bound memory growth.
    """
    client_ip = request.client.host if request.client else "unknown"
    now = _time.monotonic()
    window_start = now - _RATE_LIMIT_WINDOW
    with _rate_limit_lock:
        # Periodic GC: drop IPs that haven't been seen this window so the
        # store cannot grow unbounded under sustained probe traffic.
        if len(_rate_limit_store) > 4096:
            _stale = [ip for ip, dq in _rate_limit_store.items() if not dq or dq[-1] < window_start]
            for ip in _stale:
                _rate_limit_store.pop(ip, None)
        bucket = _rate_limit_store[client_ip]
        # Sliding window: remove timestamps outside the window
        while bucket and bucket[0] < window_start:
            bucket.popleft()
        if len(bucket) >= limit:
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded: max {limit} requests per {_RATE_LIMIT_WINDOW}s",
            )
        bucket.append(now)


# ---------------------------------------------------------------------------
# Body size limit middleware
# ---------------------------------------------------------------------------
_MAX_BODY_SIZE = 1 * 1024 * 1024  # 1 MB default

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject request bodies exceeding a configurable maximum size."""

    def __init__(self, app_instance, max_size: int = _MAX_BODY_SIZE):
        super().__init__(app_instance)
        self.max_size = max_size

    async def dispatch(self, request: StarletteRequest, call_next):
        if request.method in ("POST", "PUT", "PATCH"):
            content_length = request.headers.get("content-length")
            if content_length and int(content_length) > self.max_size:
                return JSONResponse(
                    status_code=413,
                    content={"detail": f"Request body too large. Max: {self.max_size} bytes"},
                )
        return await call_next(request)


app.add_middleware(BodySizeLimitMiddleware, max_size=_MAX_BODY_SIZE)

# ---------------------------------------------------------------------------
# SSRF prevention — validate URLs against allowlist
# ---------------------------------------------------------------------------
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
]


def _validate_url(url: str) -> str:
    """Validate a URL is safe (http/https only, no private IPs). Returns the URL or raises."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid URL scheme '{parsed.scheme}'. Only http and https are allowed.",
        )
    hostname = parsed.hostname
    if not hostname:
        raise HTTPException(status_code=400, detail="URL missing hostname")
    # Resolve and check against blocked ranges
    import socket
    try:
        resolved = socket.getaddrinfo(hostname, None)
        for _family, _type, _proto, _canonname, sockaddr in resolved:
            ip = ipaddress.ip_address(sockaddr[0])
            for network in _BLOCKED_NETWORKS:
                if ip in network:
                    raise HTTPException(
                        status_code=400,
                        detail=f"URL resolves to a blocked private IP range.",
                    )
    except socket.gaierror:
        raise HTTPException(status_code=400, detail=f"Cannot resolve hostname: {hostname}")
    return url


# ---------------------------------------------------------------------------
# Token/key masking helper
# ---------------------------------------------------------------------------
def _mask_token(token: str) -> str:
    """Mask a token showing only the last 4 characters."""
    if not token or len(token) <= 4:
        return "****"
    return f"****{token[-4:]}"


# Health check
@app.get("/health")
async def health_check() -> dict:
    """Health check endpoint."""
    if not brain:
        raise HTTPException(status_code=503, detail="Service not initialized")
    return await brain.health_check()


# ── Service Health Proxy (server-side checks, avoids browser CORS) ──

MONITORED_SERVICES = [
    {"name": "NCL Brain", "port": 8800, "path": "/health"},
    {"name": "NCC Relay", "port": 8787, "path": "/health"},
    {"name": "NCC Master", "port": 8765, "path": "/health"},
    {"name": "One-Drop", "port": 8123, "path": "/health"},
    {"name": "AAC Monitor", "port": 8080, "path": "/health"},
    {"name": "BRS Dashboard", "port": 8000, "path": "/health"},
    {"name": "Paperclip", "port": 3100, "path": "/health"},
    {"name": "Ollama", "port": 11434, "path": "/api/tags"},
]


@app.get("/services/status")
async def services_status() -> dict:
    """Check all monitored services server-side and return status."""
    results = []

    def _check_sync(svc: dict) -> dict:
        url = f"http://localhost:{svc['port']}{svc['path']}"
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=3) as resp:
                return {**svc, "online": resp.status < 400}
        except Exception as e:
            log.debug("Service health check failed for %s: %s", svc["name"], e)
            return {**svc, "online": False}

    async def _check(svc: dict) -> dict:
        return await asyncio.to_thread(_check_sync, svc)

    checks = [_check(svc) for svc in MONITORED_SERVICES]
    try:
        # Outer 5s safety net: each per-service check already has 3s urllib
        # timeout, but wrap gather() so the endpoint is bounded even if
        # asyncio.to_thread + urllib misbehaves.
        results = await asyncio.wait_for(asyncio.gather(*checks), timeout=5.0)
    except asyncio.TimeoutError:
        log.warning("/services/status gather exceeded 5s budget")
        results = [{**svc, "online": False, "error": "timeout"} for svc in MONITORED_SERVICES]
    online = sum(1 for r in results if r["online"])
    return {"services": list(results), "online": online, "total": len(MONITORED_SERVICES)}


@app.get("/network/info")
async def network_info():
    """Return the server's LAN IP for iPhone shortcut configuration."""
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            lan_ip = s.getsockname()[0]
    except Exception as e:
        log.debug("Could not determine LAN IP, falling back to localhost: %s", e)
        lan_ip = "localhost"
    return {
        "lan_ip": lan_ip,
        "port": config.port,
        "base_url": f"http://{lan_ip}:{config.port}",
        "shortcuts_setup": f"http://{lan_ip}:{config.port}/shortcuts/setup?host={lan_ip}",
    }


# Strike Point Authentication
def _verify_strike_token(authorization: str = Header(default="")):
    """Verify the strike point auth token from iPhone."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    token = authorization.replace("Bearer ", "").strip()
    if not secrets.compare_digest(token, STRIKE_TOKEN):
        raise HTTPException(status_code=403, detail="Invalid strike token")


# Pump Prompt endpoint — THE SOLE STRIKE POINT INTO NCL
@app.post("/pump")
async def receive_pump_prompt(
    request: Request,
    body: dict = Body(...),
    auto_flow: bool = Query(default=True, description="Run council→mandate pipeline (stops before NCC dispatch)"),
    authorization: str = Header(default=""),
) -> dict:
    """
    Receive pump prompt from iPhone via Grok or Command Center dashboard.

    Accepts two body formats:
    1. Full PumpPrompt: { prompt_id, source, intent, context, ... }
    2. Simple dashboard: { prompt: "text" }  (auto-generates PumpPrompt fields)

    This is the SOLE entry point into the NCL brain from NATRIX.
    Authenticated via Bearer token (STRIKE_AUTH_TOKEN).

    When auto_flow=True (default), runs the pipeline UP TO mandate creation:
    1. Store pump in memory
    2. Spawn council session (Claude chairs, Grok/Gemini/GPT debate)
    3. Extract mandates from council consensus
    4. Create mandates as PENDING_APPROVAL in Paperclip
    5. STOPS — returns council output + proposed mandates for NATRIX review

    NATRIX then calls /pump/approve/{pump_id} to dispatch to NCC,
    or /pump/reject/{pump_id} to discard.
    """
    _verify_strike_token(authorization)
    _check_rate_limit(request)

    if not brain:
        raise HTTPException(status_code=503, detail="Service not initialized")

    # Validate body has at least a prompt or intent
    if not body.get("prompt") and not body.get("intent"):
        raise HTTPException(status_code=400, detail="Missing required field: 'prompt' or 'intent'")

    # Accept simple { "prompt": "text" } from dashboard and convert to PumpPrompt
    if "prompt" in body and "prompt_id" not in body:
        import uuid
        prompt = PumpPrompt(
            prompt_id=f"pump-dash-{uuid.uuid4().hex[:8]}",
            source="command-center-dashboard",
            intent=body["prompt"][:200],
            context={"raw_prompt": body["prompt"], "origin": "dashboard"},
            urgency=body.get("urgency", "normal"),
        )
    else:
        try:
            prompt = PumpPrompt(**body)
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Invalid PumpPrompt: {e}")

    if auto_flow:
        # Council pipeline can run for several minutes (multi-LLM rebuttal rounds
        # falling back to local Ollama). Detach so callers (e.g. pump_watcher)
        # don't block past their HTTP timeout. Errors are logged via the
        # task-done callback installed in the autonomous scheduler pattern.
        async def _run_auto_flow() -> None:
            try:
                await brain.receive_pump_prompt(prompt, auto_flow=True)
            except Exception:
                log.exception(
                    f"[/pump] background auto_flow failed for {prompt.prompt_id}"
                )

        task = asyncio.create_task(_run_auto_flow())

        def _pump_task_done(t: asyncio.Task) -> None:
            if t.cancelled():
                return
            exc = t.exception()
            if exc is not None:
                log.error(
                    f"[/pump] auto_flow task for {prompt.prompt_id} died: {exc!r}"
                )

        task.add_done_callback(_pump_task_done)
        return {
            "pump_id": prompt.prompt_id,
            "intent": prompt.intent,
            "urgency": prompt.urgency,
            "mode": "background",
            "status": "accepted",
        }

    result = await brain.receive_pump_prompt(prompt, auto_flow=False)
    return result


# ---------------------------------------------------------------------------
# NATRIX Approval Gate — Review / Approve / Reject before NCC dispatch
# ---------------------------------------------------------------------------

@app.get("/pump/pending")
async def list_pending_pumps(
    authorization: str = Header(default=""),
) -> dict:
    """
    List all pump prompts awaiting NATRIX approval.

    Returns pump IDs, proposed mandate counts, and council session refs.
    """
    _verify_strike_token(authorization)

    if not brain:
        raise HTTPException(status_code=503, detail="Service not initialized")

    pending = {}
    async with brain._pending_dispatches_lock:
        snapshot = list(brain._pending_dispatches.items())
    for pump_id, data in snapshot:
        pending[pump_id] = {
            "council_session_id": data.get("council_session_id"),
            "mandates_proposed": len(data.get("mandates", [])),
            "created_at": data.get("created_at"),
        }

    return {"pending_count": len(pending), "pending": pending}


@app.get("/pump/review/{pump_id}")
async def review_pump(
    pump_id: str,
    authorization: str = Header(default=""),
) -> dict:
    """
    Review proposed mandates from a pump prompt before approving.

    Returns full council output + proposed mandates + consensus data
    so NATRIX can make an informed decision.
    """
    _verify_strike_token(authorization)

    if not brain:
        raise HTTPException(status_code=503, detail="Service not initialized")

    async with brain._pending_dispatches_lock:
        pending = brain._pending_dispatches.get(pump_id)
    if not pending:
        raise HTTPException(status_code=404, detail=f"No pending dispatch for pump {pump_id}")

    # Get council session for full context
    session_id = pending.get("council_session_id", "")
    session = brain.council_sessions.get(session_id)

    review = {
        "pump_id": pump_id,
        "created_at": pending.get("created_at"),
        "proposed_mandates": pending.get("mandates", []),
    }

    if session:
        review["council"] = {
            "session_id": session.session_id,
            "topic": session.topic,
            "synthesis": session.synthesis,
            "consensus": session.consensus,
            "recommendations": session.recommendations,
            "dissents": session.dissents,
            "consensus_score": {
                "agreement_pct": session.consensus_score.agreement_pct,
                "convergence_delta": session.consensus_score.convergence_delta,
                "confidence_weighted": session.consensus_score.confidence_weighted,
                "threshold_met": session.consensus_score.threshold_met,
                "dissent_strength": session.consensus_score.dissent_strength,
            } if session.consensus_score else None,
        }

    review["actions"] = {
        "approve_all": f"POST /pump/approve/{pump_id}",
        "approve_some": f"POST /pump/approve/{pump_id} with body: {{\"mandate_ids\": [...]}}",
        "modify_and_approve": f"POST /pump/approve/{pump_id} with body: {{\"modifications\": {{\"mandate_id\": {{\"priority\": N}}}}}}",
        "reject": f"POST /pump/reject/{pump_id}",
    }

    return review


class ApprovalRequest(BaseModel):
    """Request body for pump approval."""
    mandate_ids: list[str] | None = None  # None = approve all
    modifications: dict[str, dict] | None = None  # mandate_id → field overrides


class RejectionRequest(BaseModel):
    """Request body for pump rejection."""
    reason: str = ""


@app.post("/pump/approve/{pump_id}")
async def approve_pump(
    pump_id: str,
    body: ApprovalRequest | None = None,
    authorization: str = Header(default=""),
) -> dict:
    """
    NATRIX approves proposed mandates and dispatches to NCC.

    Nothing reaches NCC without this explicit approval.

    Options:
    - Empty body: approve all proposed mandates as-is
    - mandate_ids: approve only specific mandates (rest get cancelled)
    - modifications: override fields before dispatch (priority, objective, etc.)

    Args:
        pump_id: Pump prompt ID
        body: Optional approval constraints
        authorization: Bearer token
    """
    _verify_strike_token(authorization)

    if not brain:
        raise HTTPException(status_code=503, detail="Service not initialized")

    result = await brain.approve_and_dispatch(
        pump_id=pump_id,
        approved_mandate_ids=body.mandate_ids if body and body.mandate_ids else None,
        modifications=body.modifications if body and body.modifications else None,
    )

    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])

    return result


@app.post("/pump/reject/{pump_id}")
async def reject_pump(
    pump_id: str,
    body: RejectionRequest | None = None,
    authorization: str = Header(default=""),
) -> dict:
    """
    NATRIX rejects proposed mandates — nothing dispatched to NCC.

    All pending mandates for this pump are cancelled.
    """
    _verify_strike_token(authorization)

    if not brain:
        raise HTTPException(status_code=503, detail="Service not initialized")

    result = await brain.reject_pump(
        pump_id=pump_id,
        reason=body.reason if body else "",
    )

    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])

    return result


class CouncilSpawnBody(BaseModel):
    topic: str = ""
    prompt: str = ""
    members: list[str] | None = None
    priority: str = "P2"


# Council endpoints
@app.post("/council/spawn")
async def spawn_council_session(
    request: Request,
    body: CouncilSpawnBody | None = None,
    topic: str = Query(default=""),
    prompt: str = Query(default=""),
    members: str = Query(default=""),
    authorization: str = Header(default=""),
) -> dict:
    """
    Spawn a new council debate session.

    Accepts topic/prompt/members as query params OR as JSON body.
    JSON body takes precedence when present.

    Returns:
        Dict with session details
    """
    _verify_strike_token(authorization)
    _check_rate_limit(request)
    if not brain:
        raise HTTPException(status_code=503, detail="Service not initialized")

    # Merge: body fields override query params
    _topic = (body.topic if body and body.topic else topic) or "General council session"
    _prompt = (body.prompt if body and body.prompt else prompt) or _topic
    _members = (body.members if body and body.members else
                ([m.strip() for m in members.split(",") if m.strip()] if members else None))

    # Generate a session ID upfront so we can return immediately
    session_id = f"council-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{str(uuid.uuid4())[:8]}"

    async def _run_council():
        try:
            session = await brain.spawn_council_session(_topic, _prompt, _members)
            await brain._log_event(
                "council_spawn_complete",
                f"Council session complete: {session.session_id} — {session.topic}",
                metadata={
                    "session_id": session.session_id,
                    "consensus": session.consensus,
                },
            )
        except Exception as e:
            log.exception(f"[/council/spawn] background council failed: {e}")
            await brain._log_event(
                "council_spawn_error",
                f"Council session failed: {e}",
            )

    task = asyncio.create_task(_run_council())
    task.add_done_callback(lambda t: log.error(f"Council spawn task died: {t.exception()!r}") if not t.cancelled() and t.exception() else None)

    return {
        "session_id": session_id,
        "topic": _topic,
        "status": "queued",
        "consensus": None,
        "recommendations": [],
        "message": "Council session queued — running in background. Poll /council/session/{session_id} for results.",
    }


@app.get("/council/session/{session_id}")
async def get_council_session(
    session_id: str,
    authorization: str = Header(default=""),
) -> dict:
    """
    Get council session details.

    Args:
        session_id: Council session ID

    Returns:
        Session details
    """
    _verify_strike_token(authorization)
    if not brain:
        raise HTTPException(status_code=503, detail="Service not initialized")

    session = brain.council_sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    return {
        "session_id": session.session_id,
        "topic": session.topic,
        "status": session.status.value,
        "responses": session.responses,
        "synthesis": session.synthesis,
        "consensus": session.consensus,
        "recommendations": session.recommendations,
        "created_at": session.created_at.isoformat(),
        "completed_at": session.completed_at.isoformat() if session.completed_at else None,
    }


# ── YouTube Council endpoints ─────────────────────────────────────────────
# Channel subscription management + report access for FirstStrike YTC tab.

_YTC_CHANNEL_CONFIG = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL"))) / "config" / "youtube_channels.json"


def _load_ytc_channels() -> list[dict]:
    """Load youtube_channels.json → list of channel dicts."""
    if not _YTC_CHANNEL_CONFIG.exists():
        return []
    try:
        data = json.loads(_YTC_CHANNEL_CONFIG.read_text())
        channels = data.get("channels", []) if isinstance(data, dict) else data
        # Normalise: accept both plain strings and {"url": ..., "name": ...} dicts
        result = []
        for ch in channels:
            if isinstance(ch, str):
                result.append({"url": ch, "name": ch.rstrip("/").split("@")[-1] if "@" in ch else ch})
            elif isinstance(ch, dict):
                result.append(ch)
        return result
    except Exception:
        return []


def _save_ytc_channels(channels: list[dict]) -> None:
    """Persist channel list to youtube_channels.json."""
    _YTC_CHANNEL_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    # Keep backwards-compat: write both "channels" (url strings) and "channel_details"
    payload = {
        "_comment": "Managed by YouTube Council API — follow/unfollow from FirstStrike.",
        "channels": [ch["url"] for ch in channels],
        "channel_details": channels,
    }
    _YTC_CHANNEL_CONFIG.write_text(json.dumps(payload, indent=2))


@app.get("/council/youtube/channels")
async def list_youtube_channels(
    authorization: str = Header(default=""),
) -> dict:
    """List all followed YouTube channels."""
    _verify_strike_token(authorization)
    channels = _load_ytc_channels()
    return {"channels": channels, "count": len(channels)}


class YouTubeChannelBody(BaseModel):
    url: str
    name: str = ""


@app.post("/council/youtube/channels")
async def follow_youtube_channel(
    body: YouTubeChannelBody,
    authorization: str = Header(default=""),
) -> dict:
    """Follow a new YouTube channel."""
    _verify_strike_token(authorization)

    url = body.url.strip()
    if not url:
        raise HTTPException(status_code=422, detail="Channel URL required")

    # Normalise: ensure it looks like a YouTube channel URL
    if not url.startswith("http"):
        # Could be "@handle" or "handle" format
        handle = url.lstrip("@")
        url = f"https://www.youtube.com/@{handle}"

    channels = _load_ytc_channels()

    # Check for duplicates
    existing_urls = {ch["url"].lower().rstrip("/") for ch in channels}
    if url.lower().rstrip("/") in existing_urls:
        return {"status": "already_following", "channel": url}

    name = body.name.strip() or (url.rstrip("/").split("@")[-1] if "@" in url else url)
    new_channel = {
        "url": url,
        "name": name,
        "added_at": datetime.now(timezone.utc).isoformat(),
    }
    channels.append(new_channel)
    _save_ytc_channels(channels)

    log.info(f"[YTC] Followed channel: {name} ({url})")
    return {"status": "followed", "channel": new_channel, "total": len(channels)}


@app.delete("/council/youtube/channels")
async def unfollow_youtube_channel(
    url: str = Query(..., description="Channel URL or handle to unfollow"),
    authorization: str = Header(default=""),
) -> dict:
    """Unfollow a YouTube channel."""
    _verify_strike_token(authorization)

    url_clean = url.strip().lower().rstrip("/")
    if not url_clean:
        raise HTTPException(status_code=422, detail="Channel URL required")

    channels = _load_ytc_channels()
    before = len(channels)
    channels = [ch for ch in channels if ch["url"].lower().rstrip("/") != url_clean]
    after = len(channels)

    if before == after:
        raise HTTPException(status_code=404, detail=f"Channel not found: {url}")

    _save_ytc_channels(channels)
    log.info(f"[YTC] Unfollowed channel: {url}")
    return {"status": "unfollowed", "url": url, "remaining": after}


@app.get("/council/youtube/reports")
async def list_youtube_reports(
    limit: int = Query(default=50, ge=1, le=200),
    authorization: str = Header(default=""),
) -> dict:
    """List YouTube Council reports from intelligence-scan/council-reports/."""
    _verify_strike_token(authorization)

    ncl_base = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
    reports_dir = ncl_base / "intelligence-scan" / "council-reports"

    reports: list[dict] = []
    if reports_dir.exists():
        for rpt_path in sorted(reports_dir.glob("*youtube*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                content = rpt_path.read_text(errors="replace")
                # Extract title from first heading
                title = rpt_path.stem.replace("-", " ").replace("_", " ").title()
                for line in content.split("\n"):
                    if line.startswith("# "):
                        title = line[2:].strip()
                        break

                # Extract channel from content if present
                channel = "Unknown"
                for line in content.split("\n"):
                    if "channel:" in line.lower() or "source:" in line.lower():
                        channel = line.split(":", 1)[-1].strip()
                        break

                reports.append({
                    "filename": rpt_path.name,
                    "title": title,
                    "channel": channel,
                    "date": datetime.fromtimestamp(rpt_path.stat().st_mtime, tz=timezone.utc).isoformat(),
                    "size_bytes": rpt_path.stat().st_size,
                    "status": "complete",
                })
            except Exception as e:
                log.warning(f"Failed to read report {rpt_path}: {e}")

            if len(reports) >= limit:
                break

    # Also check for JSON reports (newer format)
    json_reports_dir = ncl_base / "intelligence-scan" / "youtube-reports"
    if json_reports_dir.exists():
        for rpt_path in sorted(json_reports_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                data = json.loads(rpt_path.read_text())
                reports.append({
                    "filename": rpt_path.name,
                    "title": data.get("title", data.get("video_title", rpt_path.stem)),
                    "channel": data.get("channel", data.get("channel_name", "Unknown")),
                    "video_url": data.get("video_url", data.get("url", "")),
                    "date": data.get("published_at", data.get("date", datetime.fromtimestamp(
                        rpt_path.stat().st_mtime, tz=timezone.utc).isoformat())),
                    "transcript_summary": data.get("transcript_summary", data.get("summary", "")),
                    "analysis": data.get("analysis", ""),
                    "status": data.get("status", "complete"),
                })
            except Exception as e:
                log.warning(f"Failed to read JSON report {rpt_path}: {e}")

            if len(reports) >= limit:
                break

    # Sort all by date descending
    reports.sort(key=lambda r: r.get("date", ""), reverse=True)
    return {"reports": reports[:limit], "count": len(reports[:limit])}


@app.get("/council/youtube/reports/{filename}")
async def get_youtube_report(
    filename: str,
    authorization: str = Header(default=""),
) -> dict:
    """Get a specific YouTube Council report by filename."""
    _verify_strike_token(authorization)

    ncl_base = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))

    # Check both directories
    for reports_dir in [
        ncl_base / "intelligence-scan" / "council-reports",
        ncl_base / "intelligence-scan" / "youtube-reports",
    ]:
        rpt_path = reports_dir / filename
        if rpt_path.exists():
            content = rpt_path.read_text(errors="replace")
            if filename.endswith(".json"):
                try:
                    return {"report": json.loads(content), "filename": filename}
                except json.JSONDecodeError:
                    pass
            return {"report": {"content": content, "filename": filename}, "filename": filename}

    raise HTTPException(status_code=404, detail=f"Report not found: {filename}")


@app.post("/council/youtube/run")
async def trigger_youtube_council(
    authorization: str = Header(default=""),
) -> dict:
    """Trigger a YouTube Council run (scrape → transcribe → analyze → report)."""
    _verify_strike_token(authorization)

    session_id = f"ytc-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{str(uuid.uuid4())[:8]}"

    async def _run():
        try:
            from ..councils.runner import run_youtube_council
            report = await run_youtube_council(session_id)
            if report:
                # Save report as JSON for the new format
                ncl_base = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
                json_dir = ncl_base / "intelligence-scan" / "youtube-reports"
                json_dir.mkdir(parents=True, exist_ok=True)
                out_path = json_dir / f"{session_id}.json"
                out_path.write_text(json.dumps({
                    "session_id": session_id,
                    "title": getattr(report, "title", "YouTube Council Report"),
                    "status": "complete",
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                }, default=str, indent=2))
                log.info(f"[YTC] Council run complete: {session_id}")
            else:
                log.info(f"[YTC] Council run produced no report: {session_id}")
        except Exception as e:
            log.exception(f"[YTC] Council run failed: {e}")

    task = asyncio.create_task(_run())
    task.add_done_callback(lambda t: log.error(f"YTC run died: {t.exception()!r}") if not t.cancelled() and t.exception() else None)

    return {
        "session_id": session_id,
        "status": "running",
        "message": "YouTube Council pipeline started. Poll /council/youtube/reports for results.",
    }


# Mandate endpoints
@app.post("/mandates")
async def create_mandate(
    pillar: str,
    priority: int,
    title: str,
    objective: str,
    success_criteria: list[str],
    deadline: str | None = None,
    source_pump_id: str | None = None,
    status: str | None = None,
    force: bool = False,
    authorization: str = Header(default=""),
) -> dict:
    """
    Create a new mandate.

    By default, mandates land in PENDING_APPROVAL and require explicit
    NATRIX approval before dispatch. Setting status='active' requires
    force=true, which is audit-logged. Any other status passes through
    the normal MWP state machine via brain.create_mandate.
    """
    _verify_strike_token(authorization)
    if not brain:
        raise HTTPException(status_code=503, detail="Service not initialized")

    if not (1 <= priority <= 10):
        raise HTTPException(status_code=400, detail="Priority must be between 1 and 10")

    try:
        pillar_enum = PillarType(pillar)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid pillar: {pillar}")

    # Resolve and validate status (default PENDING_APPROVAL post 2026-05-15 audit)
    if status is None:
        status_enum = MandateStatus.PENDING_APPROVAL
    else:
        try:
            status_enum = MandateStatus(status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

    if status_enum == MandateStatus.ACTIVE and not force:
        raise HTTPException(
            status_code=400,
            detail="status=active requires force=true; default is pending_approval",
        )

    if status_enum == MandateStatus.ACTIVE and force:
        log.warning(
            f"[mandates] force-active create requested: pillar={pillar} title={title!r} "
            f"source_pump_id={source_pump_id} — audit"
        )

    from datetime import datetime

    deadline_dt = None
    if deadline:
        try:
            deadline_dt = datetime.fromisoformat(deadline)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid deadline format")

    mandate = await brain.create_mandate(
        pillar=pillar_enum,
        priority=priority,
        title=title,
        objective=objective,
        success_criteria=success_criteria,
        deadline=deadline_dt,
        source_pump_id=source_pump_id,
        status=status_enum,
    )

    return {
        "mandate_id": mandate.mandate_id,
        "pillar": mandate.pillar.value,
        "priority": mandate.priority,
        "title": mandate.title,
        "objective": mandate.objective,
        "status": mandate.status.value,
        "created_at": mandate.created_at.isoformat(),
    }


@app.get("/mandates")
async def list_mandates(
    pillar: str | None = None,
    status: str | None = None,
    authorization: str = Header(default=""),
) -> dict:
    """
    List mandates with optional filters.

    Args:
        pillar: Filter by pillar
        status: Filter by status

    Returns:
        Dict with mandates list
    """
    _verify_strike_token(authorization)
    if not brain:
        raise HTTPException(status_code=503, detail="Service not initialized")

    pillar_enum = None
    if pillar:
        try:
            pillar_enum = PillarType(pillar)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid pillar: {pillar}")

    status_enum = None
    if status:
        try:
            status_enum = MandateStatus(status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

    mandates = await brain.list_mandates(pillar=pillar_enum, status=status_enum)

    return {
        "count": len(mandates),
        "mandates": [
            {
                "mandate_id": m.mandate_id,
                "pillar": m.pillar.value,
                "priority": m.priority,
                "title": m.title,
                "status": m.status.value,
                "deadline": m.deadline.isoformat() if m.deadline else None,
            }
            for m in mandates
        ],
    }


@app.get("/mandates/{mandate_id}")
async def get_mandate(
    mandate_id: str,
    authorization: str = Header(default=""),
) -> dict:
    """
    Get mandate details.

    Args:
        mandate_id: Mandate ID

    Returns:
        Mandate details
    """
    _verify_strike_token(authorization)
    if not brain:
        raise HTTPException(status_code=503, detail="Service not initialized")

    mandate = await brain.get_mandate(mandate_id)
    if not mandate:
        raise HTTPException(status_code=404, detail="Mandate not found")

    return {
        "mandate_id": mandate.mandate_id,
        "pillar": mandate.pillar.value,
        "priority": mandate.priority,
        "title": mandate.title,
        "objective": mandate.objective,
        "status": mandate.status.value,
        "success_criteria": mandate.success_criteria,
        "deadline": mandate.deadline.isoformat() if mandate.deadline else None,
        "created_at": mandate.created_at.isoformat(),
        "updated_at": mandate.updated_at.isoformat(),
    }


@app.post("/mandates/{mandate_id}/complete")
async def complete_mandate(
    mandate_id: str,
    notes: str | None = None,
    authorization: str = Header(default=""),
) -> dict:
    """
    Mark mandate as completed.

    Args:
        mandate_id: Mandate ID
        notes: Optional completion notes

    Returns:
        Status dict
    """
    _verify_strike_token(authorization)
    if not brain:
        raise HTTPException(status_code=503, detail="Service not initialized")

    await brain.complete_mandate(mandate_id, notes)
    return {"mandate_id": mandate_id, "status": "completed"}


@app.post("/mandates/{mandate_id}/approve")
async def approve_mandate(
    mandate_id: str,
    reason: str = "Approved by NATRIX",
    authorization: str = Header(default=""),
) -> dict:
    """
    Approve a pending_approval mandate, transitioning it to ACTIVE.

    Used to dispatch mandates directly without going through the pump
    approval flow (useful for backfilling approvals on orphaned mandates
    or bulk-approving a triaged set).
    """
    _verify_strike_token(authorization)
    if not brain:
        raise HTTPException(status_code=503, detail="Service not initialized")

    # Atomic compare-and-swap: lookup + transition under a single lock hold
    async with brain._mandates_lock:
        mandate = brain.mandates.get(mandate_id)
        if not mandate:
            raise HTTPException(status_code=404, detail=f"Mandate not found: {mandate_id}")

        # Governance gates — emergency stop + policy kernel before activation
        if await brain._emergency_stop_engaged():
            raise HTTPException(status_code=423, detail="Emergency stop engaged; approval blocked")
        try:
            allowed = await brain._policy_allows_dispatch(mandate)
        except Exception as exc:
            log.error(f"[approve] PolicyKernel raised; FAIL CLOSED: {exc}")
            allowed = False
        if not allowed:
            raise HTTPException(status_code=403, detail="PolicyKernel blocked approval")

        try:
            mandate.transition_to(MandateStatus.ACTIVE, reason=reason)
        except ValueError as e:
            raise HTTPException(status_code=409, detail=f"Invalid transition: {e}")
        await brain._persist_mandates_unlocked()

    return {"mandate_id": mandate_id, "status": "active", "reason": reason}


@app.post("/mandates/{mandate_id}/cancel")
async def cancel_mandate(
    mandate_id: str,
    reason: str = "Cancelled by NATRIX",
    authorization: str = Header(default=""),
) -> dict:
    """
    Cancel a mandate (valid from DRAFT or PENDING_APPROVAL).

    Used to dismiss stale or obsolete pending_approval mandates without
    going through the pump approval flow. Requires mandate to be in a
    cancellable state.
    """
    _verify_strike_token(authorization)
    if not brain:
        raise HTTPException(status_code=503, detail="Service not initialized")

    # Atomic compare-and-swap: lookup + transition under a single lock hold
    async with brain._mandates_lock:
        mandate = brain.mandates.get(mandate_id)
        if not mandate:
            raise HTTPException(status_code=404, detail=f"Mandate not found: {mandate_id}")
        try:
            mandate.transition_to(MandateStatus.CANCELLED, reason=reason)
        except ValueError as e:
            raise HTTPException(status_code=409, detail=f"Invalid transition: {e}")
        await brain._persist_mandates_unlocked()

    return {"mandate_id": mandate_id, "status": "cancelled", "reason": reason}


@app.post("/mandates/purge")
async def purge_mandates(
    status: str = Query(..., description="Status to purge (e.g. 'pending_approval')"),
    older_than_hours: int = Query(24, ge=0, description="Only purge entries older than N hours"),
    confirm: bool = Query(False, description="Must be true to actually delete"),
    authorization: str = Header(default=""),
) -> dict:
    """
    Purge stale mandates from in-memory store and persisted state.

    Used to recover from accumulation bugs (e.g. orphaned pending_approval
    mandates from pumps that never reached the approval gate). Requires
    explicit confirm=true to actually mutate state.
    """
    _verify_strike_token(authorization)
    if not brain:
        raise HTTPException(status_code=503, detail="Service not initialized")

    try:
        target = MandateStatus(status)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown status: {status}")

    cutoff = datetime.now(timezone.utc).timestamp() - (older_than_hours * 3600)

    async with brain._mandates_lock:
        candidates = [
            mid for mid, m in brain.mandates.items()
            if m.status == target and m.created_at.timestamp() < cutoff
        ]
        if not confirm:
            return {
                "would_purge": len(candidates),
                "total_in_memory": len(brain.mandates),
                "status_filter": status,
                "older_than_hours": older_than_hours,
                "confirm_required": True,
            }
        for mid in candidates:
            brain.mandates.pop(mid, None)
        await brain._persist_mandates_unlocked()

    return {
        "purged": len(candidates),
        "remaining": len(brain.mandates),
        "status_filter": status,
    }


# Memory endpoints
@app.get("/memory/query")
async def query_memory(
    tags: list[str] | None = None,
    importance_threshold: float = 0.0,
    days_back: int | None = None,
    authorization: str = Header(default=""),
) -> dict:
    """
    Query memory system.

    Args:
        tags: Optional tag filters (AND logic)
        importance_threshold: Minimum importance score
        days_back: Optional days back filter

    Returns:
        Query results
    """
    _verify_strike_token(authorization)
    if not brain:
        raise HTTPException(status_code=503, detail="Service not initialized")

    return await brain.query_memory(
        tags=tags,
        importance_threshold=importance_threshold,
        days_back=days_back,
    )


# Feedback endpoint
@app.post("/feedback")
async def receive_feedback(
    feedback: FeedbackReport,
    authorization: str = Header(default=""),
) -> dict:
    """
    Receive feedback report from downstream pillar.

    Args:
        feedback: FeedbackReport

    Returns:
        Dict with report_id
    """
    _verify_strike_token(authorization)
    if not brain:
        raise HTTPException(status_code=503, detail="Service not initialized")

    report_id = await brain.receive_feedback(feedback)
    return {
        "report_id": report_id,
        "origin": feedback.origin.value,
        "status": "received",
    }


# Feedback synthesis endpoint (receives from feedback-loop server)
@app.post("/feedback/synthesis")
async def receive_synthesis(
    synthesis: dict,
    authorization: str = Header(default=""),
) -> dict:
    """
    Receive Claude-validated synthesis from feedback loop server.

    This is the ONLY path for interpreted feedback to enter NCL.
    Raw data never reaches here — only synthesized insights.

    Args:
        synthesis: Synthesis result dict from feedback-loop server

    Returns:
        Acceptance status
    """
    _verify_strike_token(authorization)
    if not synthesis.get("synthesis_id"):
        raise HTTPException(status_code=400, detail="Missing required field: synthesis_id")
    if not synthesis.get("narrative"):
        raise HTTPException(status_code=400, detail="Missing required field: narrative")
    if not brain:
        raise HTTPException(status_code=503, detail="Service not initialized")

    synthesis_id = synthesis.get("synthesis_id", "unknown")
    narrative = synthesis.get("narrative", "")
    contradictions = synthesis.get("contradictions", [])
    mandate_adjustments = synthesis.get("mandate_adjustments", [])

    # Store synthesis in memory
    await brain.memory_store.create_unit(
        content=f"Feedback synthesis {synthesis_id}: {narrative[:500]}",
        source=f"feedback-loop:{synthesis_id}",
        importance=80.0 if contradictions else 60.0,
        tags=["synthesis", "feedback-loop", "interpreted"],
    )

    # Log critical contradictions
    for c in contradictions:
        if c.get("severity") in ("high", "critical"):
            await brain.memory_store.create_unit(
                content=f"CONTRADICTION [{c.get('severity')}]: {c.get('type')} — {c.get('recommendation', '')}",
                source=f"feedback-loop:{synthesis_id}",
                importance=90.0,
                tags=["contradiction", c.get("severity", "unknown"), "alert"],
            )

    # Create PENDING_APPROVAL mandates from suggested adjustments so they
    # actually surface in the review queue instead of being silently dropped.
    created_mandates: list[str] = []
    for adj in mandate_adjustments:
        if not isinstance(adj, dict):
            continue
        pillar_str = (adj.get("pillar") or "").lower()
        try:
            pillar_enum = PillarType(pillar_str)
        except ValueError:
            log.warning(f"[/feedback/synthesis] skipping adjustment with invalid pillar: {pillar_str!r}")
            continue
        try:
            new_mandate = await brain.create_mandate(
                pillar=pillar_enum,
                priority=int(adj.get("priority", 5)),
                title=str(adj.get("title") or f"Adjustment from synthesis {synthesis_id}")[:200],
                objective=str(adj.get("objective") or adj.get("rationale") or narrative[:500]),
                success_criteria=list(adj.get("success_criteria") or []),
                source_pump_id=f"synthesis:{synthesis_id}",
                # Default PENDING_APPROVAL — NATRIX must approve before dispatch
            )
            created_mandates.append(new_mandate.mandate_id)
        except Exception as exc:
            log.error(f"[/feedback/synthesis] mandate creation failed: {exc}")

    return {
        "status": "accepted",
        "synthesis_id": synthesis_id,
        "contradictions_flagged": len(contradictions),
        "adjustments_queued": len(mandate_adjustments),
        "mandates_created": created_mandates,
    }


@app.post("/feedback/scan-now")
async def feedback_scan_now(authorization: str = Header(default="")) -> dict:
    """
    Manually trigger one feedback scan + apply cycle. For ops/debug.

    Runs FeedbackScanner.scan_once() then immediately calls
    AutonomousScheduler._apply_synthesis_to_mandates against the live brain,
    bypassing the 5-minute loop interval.
    """
    _verify_strike_token(authorization)
    if not brain or not _autonomous:
        raise HTTPException(status_code=503, detail="Service not initialized")

    import os
    from pathlib import Path
    from ..feedback.scanner import FeedbackScanner

    env_override = os.environ.get("NCL_FEEDBACK_DIR")
    candidates = []
    if env_override:
        candidates.append(Path(env_override).expanduser())
    candidates.append(Path.cwd() / "feedback-synthesis")
    candidates.append(brain.data_dir.parent / "feedback-synthesis")

    def _is_real(p: Path) -> bool:
        return p.exists() and any(
            (p / sub).exists() for sub in ("aac-reports", "brs-reports", "ncc-reports")
        )

    base = next((c for c in candidates if _is_real(c)), None)
    if base is None:
        raise HTTPException(
            status_code=500,
            detail=f"No valid feedback-synthesis dir found (tried: {[str(c) for c in candidates]})",
        )

    scanner = FeedbackScanner(base_dir=base)
    note = scanner.scan_once()
    if note is None:
        return {"status": "no_reports", "base_dir": str(base)}

    mandates_before = len(brain.mandates)
    await _autonomous._apply_synthesis_to_mandates(note)
    mandates_after = len(brain.mandates)

    return {
        "status": "applied",
        "base_dir": str(base),
        "synthesis_id": note.synthesis_id,
        "reports_consumed": note.reports_consumed,
        "blockers": len(note.open_blockers),
        "suggestions": len(note.suggested_adjustments),
        "mandates_created": mandates_after - mandates_before,
    }


class AwarebotScanRequest(BaseModel):
    queries: list[str] = Field(..., min_length=1)


# Awarebot endpoints
@app.post("/awarebot/scan")
async def run_awarebot_scan(
    body: AwarebotScanRequest,
    authorization: str = Header(default=""),
) -> dict:
    """
    Run Awarebot intelligence scan.

    Args:
        body: JSON with "queries" list of search strings

    Returns:
        Scan results
    """
    _verify_strike_token(authorization)
    if not brain:
        raise HTTPException(status_code=503, detail="Service not initialized")

    return await brain.run_awarebot_scan(body.queries)


# Prediction endpoint
@app.post("/prediction")
async def run_prediction(
    topic: str,
    authorization: str = Header(default=""),
) -> dict:
    """
    Run Future Predictor ensemble forecast.

    Args:
        topic: Prediction topic

    Returns:
        Prediction results
    """
    _verify_strike_token(authorization)
    if not brain:
        raise HTTPException(status_code=503, detail="Service not initialized")

    return await brain.run_prediction(topic)


# Strike Point Orchestrator endpoints
@app.post("/orchestrator/dispatch/{mandate_id}")
async def orchestrator_dispatch(mandate_id: str, authorization: str = Header(default="")) -> dict:
    """Manually dispatch a mandate via Strike Point Orchestrator."""
    _verify_strike_token(authorization)
    # Import and call dispatch_mandate from strike_point_orchestrator
    from ..strike_point_orchestrator import dispatch_mandate
    mandate = await brain.get_mandate(mandate_id)
    if not mandate:
        raise HTTPException(status_code=404, detail="Mandate not found")
    result = await dispatch_mandate(mandate.model_dump())
    return result


@app.get("/orchestrator/status")
async def orchestrator_status(authorization: str = Header(default="")) -> dict:
    """Get full pipeline status from Strike Point Orchestrator."""
    _verify_strike_token(authorization)
    from ..strike_point_orchestrator import get_pipeline_status
    return get_pipeline_status()


@app.post("/orchestrator/feedback/{pump_id}")
async def orchestrator_feedback(
    pump_id: str,
    authorization: str = Header(default=""),
) -> dict:
    """Process execution feedback for a pump."""
    _verify_strike_token(authorization)
    from ..strike_point_orchestrator import process_execution_feedback
    return await process_execution_feedback(pump_id)


# Root endpoint
@app.get("/")
async def root() -> dict:
    """Root endpoint with service info."""
    return {
        "service": config.service_name,
        "version": config.service_version,
        "description": "RESONANCE ENERGY NCL Brain Service",
        "docs": "/docs",
    }


# ────────────────────────────────────────────────────────────────────────────
# DASHBOARD API ENDPOINTS
# ────────────────────────────────────────────────────────────────────────────


@app.get("/dashboard/ui")
async def dashboard_ui() -> HTMLResponse:
    """Serve the main NCL Pipeline Dashboard HTML."""
    dashboard_path = Path(__file__).parent.parent.parent / "dashboard" / "index.html"
    if not dashboard_path.exists():
        raise HTTPException(status_code=404, detail="Dashboard not found")
    async with aiofiles.open(dashboard_path, "r") as f:
        html = await f.read()
    return HTMLResponse(content=html)


@app.get("/dashboard")
async def get_dashboard_data(authorization: str = Header(default="")) -> dict:
    """
    Aggregate all dashboard data in a single call.

    Returns:
        Dict with pipeline_status, services, councils, memory, mandates,
        recent_events, and orchestrator stage counts.
    """
    _verify_strike_token(authorization)
    if not brain:
        raise HTTPException(status_code=503, detail="Service not initialized")

    # ── Pipeline Status ────────────────────────────────────────────────────
    async with brain._pending_dispatches_lock:
        pending_count = len(brain._pending_dispatches)
    active_mandates = sum(
        1
        for m in brain.mandates.values()
        if m.status in (MandateStatus.ACTIVE, MandateStatus.IN_PROGRESS)
    )
    completed_mandates = sum(
        1 for m in brain.mandates.values() if m.status == MandateStatus.COMPLETED
    )
    council_count = len(brain.council_sessions)

    pipeline_status = {
        "pending_pumps": pending_count,
        "active_mandates": active_mandates,
        "completed_mandates": completed_mandates,
        "council_sessions": council_count,
    }

    # ── Services ───────────────────────────────────────────────────────────
    services = [
        {"name": "NCL Brain", "port": 8800, "status": "running"},
        {"name": "NCC Relay", "port": 8787, "status": "unknown"},
        {"name": "NCC Master", "port": 8765, "status": "unknown"},
        {"name": "One-Drop", "port": 8123, "status": "unknown"},
        {"name": "AAC Monitor", "port": 8080, "status": "unknown"},
        {"name": "BRS Dashboard", "port": 8000, "status": "unknown"},
        {"name": "Paperclip", "port": 3100, "status": "unknown"},
        {"name": "Ollama", "port": 11434, "status": "unknown"},
        {"name": "FirstStrike Relay", "port": 8443, "status": "unknown"},
    ]

    # ── Councils ───────────────────────────────────────────────────────────
    latest_council = None
    if brain.council_sessions:
        latest = max(
            brain.council_sessions.values(),
            key=lambda s: s.created_at,
        )
        latest_council = {
            "session_id": latest.session_id,
            "topic": latest.topic,
            "status": latest.status.value,
            "created_at": latest.created_at.isoformat(),
        }

    councils_data = {
        "total_sessions": council_count,
        "latest_session": latest_council,
    }

    # ── Memory Stats ───────────────────────────────────────────────────────
    memory_stats = {
        "total_units": len(brain.memory_store.memory_units) if hasattr(brain.memory_store, "memory_units") else 0,
        "recent_units": [],
    }

    # Try to get recent memory units
    try:
        recent_units = await brain.memory_store.search_units(days_back=1)
        memory_stats["recent_units"] = [
            {
                "content": (u.content if hasattr(u, "content") else u.get("content", ""))[:200],
                "importance": u.importance if hasattr(u, "importance") else u.get("importance", 0),
                "created_at": (
                    u.created_at.isoformat() if hasattr(u, "created_at") and u.created_at
                    else u.get("created_at", "") if isinstance(u, dict) else ""
                ),
            }
            for u in (recent_units or [])[:5]
        ]
    except Exception as e:
        logging.getLogger("ncl.api").warning("memory recent-units fetch failed: %s", e)

    # ── Mandates ───────────────────────────────────────────────────────────
    mandates_data = [
        {
            "mandate_id": m.mandate_id,
            "title": m.title,
            "pillar": m.pillar.value,
            "priority": m.priority,
            "status": m.status.value,
            "deadline": m.deadline.isoformat() if m.deadline else None,
            "created_at": m.created_at.isoformat() if hasattr(m, "created_at") and m.created_at else None,
        }
        for m in brain.mandates.values()
    ]

    # ── Recent Events ──────────────────────────────────────────────────────
    recent_events = []
    try:
        if brain.events_file.exists():
            async with aiofiles.open(brain.events_file, "r") as f:
                lines = await f.readlines()
                # Read last 20 events
                for line in lines[-20:]:
                    try:
                        event = json.loads(line)
                        recent_events.append(event)
                    except json.JSONDecodeError:
                        pass
    except Exception as e:
        log.warning("Failed to read recent events from events file: %s", e)

    # ── Orchestrator Pipeline Stages ───────────────────────────────────────
    orchestrator_stages = {}
    # Derive NCL base from brain.data_dir (e.g., ~/dev/NCL/data → ~/dev/NCL)
    ncl_base = Path(brain.data_dir).parent
    exec_pipeline = ncl_base / "workspaces" / "execution-pipeline"

    for stage_dir in ["01-Input", "02-Planning", "03-Execution", "04-Review", "05-Output"]:
        stage_path = exec_pipeline / stage_dir
        if stage_path.exists():
            try:
                file_count = len(list(stage_path.glob("**/*")))
                orchestrator_stages[stage_dir] = file_count
            except Exception as e:
                log.debug("Failed to count files in orchestrator stage %s: %s", stage_dir, e)
                orchestrator_stages[stage_dir] = 0
        else:
            orchestrator_stages[stage_dir] = 0

    # ── Council Reports Count ─────────────────────────────────────────────
    youtube_reports = 0
    x_reports = 0
    council_reports_dir = ncl_base / "intelligence-scan" / "council-reports"
    if council_reports_dir.exists():
        for rpt in council_reports_dir.glob("*.md"):
            name_lower = rpt.name.lower()
            if "youtube" in name_lower or "yt-" in name_lower:
                youtube_reports += 1
            elif "x-" in name_lower or "twitter" in name_lower:
                x_reports += 1

    # ── Notification Count ────────────────────────────────────────────────
    notification_count = 0
    notif_dir = ncl_base / "notifications"
    if notif_dir.exists():
        notification_count = len(list(notif_dir.glob("notif-*.json")))

    # ── Pipeline stage statuses (derive from data availability) ───────────
    has_pumps = pending_count > 0 or orchestrator_stages.get("01-Input", 0) > 0
    has_council = council_count > 0
    has_mandates = len(mandates_data) > 0
    has_feedback = orchestrator_stages.get("05-Output", 0) > 0

    # ── Build flat response matching dashboard expectations ───────────────
    return {
        # Pipeline stats (flat)
        "pump_count": pending_count + orchestrator_stages.get("01-Input", 0),
        "active_mandates": active_mandates,
        "completed_count": completed_mandates,
        "council_sessions": council_count,

        # Pipeline overall status
        "pipeline_status": "online" if active_mandates > 0 or has_pumps else "degraded" if has_mandates else "offline",

        # Stage statuses (1-8)
        "stage_1_status": "ok" if has_pumps else "warn",
        "stage_2_status": "ok",  # Brain is running if this endpoint works
        "stage_3_status": "ok" if has_council else "warn",
        "stage_4_status": "ok" if has_mandates else "warn",
        "stage_5_status": "ok" if has_mandates else "warn",
        "stage_6_status": "ok" if orchestrator_stages.get("03-Execution", 0) > 0 else "warn",
        "stage_7_status": "ok" if orchestrator_stages.get("04-Review", 0) > 0 else "warn",
        "stage_8_status": "ok" if has_feedback else "warn",

        # Councils
        "youtube_reports": youtube_reports,
        "x_reports": x_reports,
        "latest_council_type": latest_council["topic"] if latest_council else None,
        "latest_council_time": latest_council["created_at"] if latest_council else None,

        # Orchestrator
        "dispatched_count": completed_mandates + active_mandates,
        "pending_count": pending_count,
        "notification_count": notification_count,

        # Mandates (array of objects with 'id' field)
        "mandates": [
            {**m, "id": m["mandate_id"]} for m in mandates_data
        ],

        # Events
        "recent_events": recent_events[-50:],

        # Services (for reference)
        "services": services,

        # Memory
        "memory": memory_stats,

        # Orchestrator raw stages
        "orchestrator_stages": orchestrator_stages,

        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ────────────────────────────────────────────────────────────────────────────
# COUNCIL RUNNER TRIGGER ENDPOINTS
# ────────────────────────────────────────────────────────────────────────────


class CouncilRunRequest(BaseModel):
    """Request body for council runner trigger."""

    council_type: str = Field(
        ..., description="Council type: 'youtube', 'x', or 'both'"
    )
    dry_run: bool = Field(default=False, description="Dry run (scrape only, no AI)")


@app.post("/councils/run")
async def trigger_council_run(
    request: Request,
    body: CouncilRunRequest,
    authorization: str = Header(default=""),
) -> dict:
    """
    Trigger council runner to execute YouTube and/or X councils.

    The council runs in the background and returns immediately with a session ID.

    Args:
        body: CouncilRunRequest with council_type and dry_run flag

    Returns:
        Dict with session_id and status
    """
    _verify_strike_token(authorization)
    _check_rate_limit(request)
    if not brain:
        raise HTTPException(status_code=503, detail="Service not initialized")

    # Validate council_type
    if body.council_type not in ("youtube", "x", "both"):
        raise HTTPException(
            status_code=400,
            detail="council_type must be 'youtube', 'x', or 'both'",
        )

    # Generate session ID
    session_id = f"council-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{str(uuid.uuid4())[:8]}"

    # Define background task function
    async def run_council_background():
        try:
            from ..councils.runner import (
                run_youtube_council,
                run_x_council,
                run_both,
            )

            if body.council_type == "youtube":
                await run_youtube_council(session_id, dry_run=body.dry_run)
            elif body.council_type == "x":
                await run_x_council(session_id, dry_run=body.dry_run)
            else:  # both
                await run_both(session_id, dry_run=body.dry_run)

            # Log completion
            await brain._log_event(
                "council_run_complete",
                f"Council run ({body.council_type}) completed: {session_id}",
            )
        except Exception as e:
            log.exception(f"[/councils/run] council background task failed: {e}")
            await brain._log_event(
                "council_run_error",
                f"Council run ({body.council_type}) failed: {str(e)}",
            )

    task = asyncio.create_task(run_council_background())
    task.add_done_callback(lambda t: log.error(f"Council task died: {t.exception()!r}") if not t.cancelled() and t.exception() else None)

    return {
        "session_id": session_id,
        "council_type": body.council_type,
        "dry_run": body.dry_run,
        "status": "queued",
    }


@app.get("/councils/reports")
async def list_council_reports(authorization: str = Header(default="")) -> dict:
    """
    List available council reports from the intelligence-scan/council-reports/ directory.

    Returns:
        Dict with list of report filenames, dates, and types
    """
    _verify_strike_token(authorization)
    if not brain:
        raise HTTPException(status_code=503, detail="Service not initialized")

    # Check multiple possible locations for council reports
    ncl_base = Path(brain.data_dir).parent
    project_root = Path(__file__).parent.parent.parent  # NCL/runtime/api → NCL
    candidates = [
        ncl_base / "intelligence-scan" / "council-reports",
        project_root / "intelligence-scan" / "council-reports",
        ncl_base / "data" / "council-reports",
        Path.home() / "dev" / "NCL" / "intelligence-scan" / "council-reports",
    ]
    reports_dir = None
    for c in candidates:
        if c.exists():
            reports_dir = c
            break

    reports = []

    if reports_dir:
        try:
            for report_file in sorted(reports_dir.glob("*.md"), reverse=True):
                stat = report_file.stat()
                # Read first 200 chars as preview
                try:
                    preview = report_file.read_text()[:200]
                except Exception as e:
                    log.debug("Could not read preview for report %s: %s", report_file.name, e)
                    preview = ""
                reports.append(
                    {
                        "filename": report_file.name,
                        "path": str(report_file),
                        "size_bytes": stat.st_size,
                        "preview": preview,
                        "modified_at": datetime.fromtimestamp(
                            stat.st_mtime
                        ).isoformat(),
                    }
                )
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to list council reports: {str(e)}",
            )
    else:
        return {"count": 0, "reports": [], "note": "No council reports directory found yet. Run a council session first."}

    return {
        "count": len(reports),
        "reports": reports,
    }


@app.get("/councils/reports/{filename}")
async def get_council_report(filename: str) -> dict:
    """
    Get the content of a specific council report.

    Args:
        filename: Report filename (e.g., 'PIPELINE-SIMULATION-2026-04-06.md')

    Returns:
        Dict with report content and metadata
    """
    if not brain:
        raise HTTPException(status_code=503, detail="Service not initialized")

    # Security: prevent directory traversal
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    project_root = Path(__file__).parent.parent.parent
    candidates = [
        Path(brain.data_dir).parent / "intelligence-scan" / "council-reports" / filename,
        project_root / "intelligence-scan" / "council-reports" / filename,
        Path.home() / "dev" / "NCL" / "intelligence-scan" / "council-reports" / filename,
    ]
    report_path = None
    for c in candidates:
        if c.exists():
            report_path = c
            break

    if not report_path:
        raise HTTPException(status_code=404, detail=f"Report not found: {filename}")

    try:
        async with aiofiles.open(report_path, "r") as f:
            content = await f.read()

        stat = report_path.stat()

        return {
            "filename": filename,
            "content": content,
            "size_bytes": stat.st_size,
            "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to read report: {str(e)}",
        )


# ── Knowledge Base, Vector Store & Multi-Agent Endpoints ──────────────────

# Global instances (initialized in lifespan)
council_vector_store = None
council_knowledge_base = None
_council_vector_store_lock = asyncio.Lock()
_council_knowledge_base_lock = asyncio.Lock()


class RAGQueryRequest(BaseModel):
    """RAG query across council knowledge."""
    query: str = Field(..., min_length=1)
    top_k: int = Field(default=10, ge=1, le=100)
    filter_type: str | None = Field(default=None, description="insight, transcript, report_summary")
    filter_source: str | None = Field(default=None, description="youtube or x")


class MultiAgentRequest(BaseModel):
    """Request to run multi-agent council analysis."""
    source_material: str = Field(..., min_length=10, description="Content to analyze")
    pipeline: str = Field(default="youtube", description="youtube or x")


@app.post("/councils/rag")
async def council_rag_query(req: RAGQueryRequest, authorization: str = Header(default="")):
    """
    Semantic search across all council knowledge (insights, transcripts, reports).

    Uses ChromaDB → LanceDB → TF-IDF fallback chain.
    """
    _verify_strike_token(authorization)
    global council_vector_store
    if not council_vector_store:
        async with _council_vector_store_lock:
            if not council_vector_store:
                from ..councils.shared.vector_store import CouncilVectorStore
                council_vector_store = CouncilVectorStore(data_dir=config.data_dir)
                await council_vector_store.init()

    results = await council_vector_store.query(
        query_text=req.query,
        top_k=req.top_k,
        filter_type=req.filter_type,
        filter_source=req.filter_source,
    )
    return {
        "query": req.query,
        "total": len(results),
        "backend": council_vector_store._backend,
        "results": [r.to_dict() for r in results],
    }


@app.get("/councils/knowledge-base/stats")
async def knowledge_base_stats():
    """Return knowledge base statistics."""
    global council_knowledge_base
    if not council_knowledge_base:
        async with _council_knowledge_base_lock:
            if not council_knowledge_base:
                from ..councils.shared.knowledge_base import KnowledgeBase
                council_knowledge_base = KnowledgeBase()

    return council_knowledge_base.get_stats()


@app.get("/councils/vector-store/stats")
async def vector_store_stats():
    """Return vector store statistics."""
    global council_vector_store
    if not council_vector_store:
        async with _council_vector_store_lock:
            if not council_vector_store:
                from ..councils.shared.vector_store import CouncilVectorStore
                council_vector_store = CouncilVectorStore(data_dir=config.data_dir)
                await council_vector_store.init()

    return council_vector_store.get_stats()


@app.post("/councils/multi-agent")
async def run_multi_agent_council(
    req: MultiAgentRequest,
):
    """
    Run multi-agent council analysis (Analyst → Researcher → Strategist → Synthesizer).

    Each role uses its preferred AI model with fallback chain.
    Runs in background and returns session ID.
    """
    if not brain:
        raise HTTPException(status_code=503, detail="Service not initialized")

    session_id = f"multi-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{str(uuid.uuid4())[:8]}"

    async def run_orchestrator_background():
        from ..councils.shared.orchestrator import run_multi_agent_analysis
        try:
            result = await run_multi_agent_analysis(
                source_material=req.source_material,
                session_id=session_id,
                pipeline=req.pipeline,
            )
            await brain._log_event(
                "multi_agent_council_complete",
                f"Multi-agent council ({req.pipeline}) complete: {len(result.insights_json)} insights, "
                f"{result.duration_seconds:.1f}s, models: {result.models_used}",
                metadata={
                    "session_id": session_id,
                    "pipeline": req.pipeline,
                    "insights_count": len(result.insights_json),
                    "agents_run": len(result.agents_run),
                    "models_used": result.models_used,
                    "duration_seconds": result.duration_seconds,
                },
            )
        except Exception as e:
            log.exception(f"[/councils/multi-agent] background task failed: {e}")
            await brain._log_event(
                "multi_agent_council_error",
                f"Multi-agent council failed: {e}",
            )

    task = asyncio.create_task(run_orchestrator_background())
    task.add_done_callback(lambda t: log.error(f"Multi-agent task died: {t.exception()!r}") if not t.cancelled() and t.exception() else None)

    return {
        "session_id": session_id,
        "pipeline": req.pipeline,
        "agents": ["Insight Analyst", "Deep Researcher", "Strategist", "Synthesizer"],
        "status": "queued",
    }


# ── Living Doctrine Engine (LDE) Endpoints ────────────────────────────────

# Global LDE engine instance + persistent results store
_lde_engine = None
_lde_results_file = Path(config.data_dir).expanduser() / "lde_results.jsonl"
_lde_results_lock = asyncio.Lock()  # Guards concurrent appends to lde_results.jsonl


def _sync_save_lde_result(session_id: str, result: dict) -> None:
    """Synchronous file-write helper for LDE results (run via asyncio.to_thread)."""
    import json as _json
    entry = {"session_id": session_id, "timestamp": datetime.now(timezone.utc).isoformat(), "result": result}
    with open(_lde_results_file, "a") as f:
        f.write(_json.dumps(entry) + "\n")


async def _save_lde_result(session_id: str, result: dict) -> None:
    """Persist LDE result to disk off the event loop.

    Callers must hold _lde_results_lock before calling to prevent concurrent writes.
    """
    await asyncio.to_thread(_sync_save_lde_result, session_id, result)


def _load_lde_result(session_id: str) -> dict | None:
    """Load a specific LDE result from disk."""
    import json as _json
    if not _lde_results_file.exists():
        return None
    with open(_lde_results_file, "r") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                entry = _json.loads(line)
                if entry.get("session_id") == session_id:
                    return entry.get("result")
            except _json.JSONDecodeError:
                continue
    return None


_lde_init_lock = asyncio.Lock()


async def _get_lde():
    """Lazy-initialize the LDE engine (thread-safe with async lock)."""
    global _lde_engine
    if _lde_engine is not None:
        return _lde_engine
    async with _lde_init_lock:
        # Double-check after acquiring lock
        if _lde_engine is None:
            from ..lde.engine import LivingDoctrineEngine
            _lde_engine = LivingDoctrineEngine()
            await _lde_engine.init()
    return _lde_engine


class LDEProcessRequest(BaseModel):
    """Request to process a URL through the Living Doctrine Engine."""
    url: str = Field(..., min_length=5, description="URL to process (YouTube, article, etc.)")
    source_type: str | None = Field(default=None, description="Override: youtube, article, video, audio")


class LDESearchRequest(BaseModel):
    """Search the LDE sandbox for prior insights."""
    query: str = Field(..., min_length=1)
    top_k: int = Field(default=10, ge=1, le=100)


@app.post("/lde/process")
async def lde_process_url(
    req: LDEProcessRequest,
    authorization: str = Header(default=""),
):
    """
    Process a URL through the full LDE pipeline.

    URL → Transcribe → Extract Insights → Analyze Against Sandbox →
    Update Living Trading Doctrine.

    Runs in background. Returns session tracking info immediately.
    """
    _verify_strike_token(authorization)
    if not brain:
        raise HTTPException(status_code=503, detail="Service not initialized")

    # SSRF prevention: validate URL scheme and block private IPs
    _validate_url(req.url)

    lde = await _get_lde()
    session_id = f"lde-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{str(uuid.uuid4())[:8]}"

    async def run_lde_background():
        try:
            result = await lde.process_url(req.url, source_type=req.source_type)
            async with _lde_results_lock:
                await _save_lde_result(session_id, result)

            await brain._log_event(
                "lde_pipeline_complete",
                f"LDE processed {req.url}: {result.get('stages', {}).get('extract', {}).get('insights_count', 0)} insights, "
                f"{result.get('total_elapsed_seconds', 0)}s",
                metadata={
                    "session_id": session_id,
                    "url": req.url,
                    "insights_count": result.get("stages", {}).get("extract", {}).get("insights_count", 0),
                    "market_bias": result.get("stages", {}).get("analyze", {}).get("market_bias_shift", "unknown"),
                    "doctrine_changes": result.get("stages", {}).get("doctrine_update", {}).get("changes_summary", ""),
                },
                tags=["lde", "doctrine"],
                importance=75.0,
            )
        except Exception as e:
            async with _lde_results_lock:
                await _save_lde_result(session_id, {"status": "failed", "error": str(e)})
            await brain._log_event(
                "lde_pipeline_error",
                f"LDE failed for {req.url}: {e}",
                tags=["lde", "error"],
            )

    task = asyncio.create_task(run_lde_background())
    task.add_done_callback(lambda t: log.error(f"LDE task died: {t.exception()!r}") if not t.cancelled() and t.exception() else None)

    return {
        "session_id": session_id,
        "url": req.url,
        "source_type": req.source_type or "auto-detect",
        "status": "queued",
        "pipeline": ["ingest", "extract", "analyze", "doctrine_update"],
    }


@app.get("/lde/doctrine")
async def get_living_doctrine():
    """Return the current Living Trading Doctrine."""
    lde = await _get_lde()
    return lde.get_doctrine()


@app.get("/lde/stats")
async def lde_stats():
    """Return LDE engine statistics."""
    lde = await _get_lde()
    return lde.get_stats()


@app.get("/lde/doctrine/rules")
async def get_doctrine_rules():
    """Return just the active rules from the doctrine."""
    lde = await _get_lde()
    doctrine = lde.get_doctrine()
    rules = doctrine.get("core_rules", [])
    active = [r for r in rules if r.get("status", "active") == "active"]
    return {
        "total_rules": len(rules),
        "active_rules": len(active),
        "rules": active,
    }


@app.get("/lde/doctrine/signals")
async def get_doctrine_signals():
    """Return active signals from the doctrine."""
    lde = await _get_lde()
    doctrine = lde.get_doctrine()
    return {
        "total_signals": len(doctrine.get("active_signals", [])),
        "signals": doctrine.get("active_signals", []),
        "market_bias": doctrine.get("market_bias", "neutral"),
    }


@app.get("/lde/doctrine/trends")
async def get_doctrine_trends():
    """Return monitored trends from the doctrine."""
    lde = await _get_lde()
    doctrine = lde.get_doctrine()
    return {
        "total_trends": len(doctrine.get("monitored_trends", [])),
        "trends": doctrine.get("monitored_trends", []),
    }


@app.post("/lde/search")
async def lde_search(req: LDESearchRequest):
    """Search the LDE sandbox for prior insights."""
    lde = await _get_lde()
    results = await lde.sandbox.search_insights(req.query, top_k=req.top_k)
    return {
        "query": req.query,
        "total": len(results),
        "results": results,
    }


@app.get("/lde/dashboard")
async def lde_dashboard_page():
    """Serve the LDE dashboard HTML."""
    from fastapi.responses import FileResponse
    dashboard_path = Path(__file__).parent.parent.parent / "dashboard" / "lde.html"
    if not dashboard_path.exists():
        raise HTTPException(status_code=404, detail="LDE dashboard not found")
    return FileResponse(dashboard_path, media_type="text/html")


@app.get("/lde/history")
async def lde_history(limit: int = Query(default=20, ge=1, le=100)):
    """Return recent LDE processing history."""
    lde = await _get_lde()
    history = await lde.sandbox.get_recent_history(limit=limit)
    return {
        "total": len(history),
        "entries": history,
    }


# ── Shortcuts Pack Endpoints ───────────────────────────────────────────────


@app.get("/shortcuts/config")
async def get_shortcuts_config(
    host: str = Query(default=None, description="Override NCL host (e.g., your Tailscale IP)"),
):
    """
    Return all iOS Shortcut definitions with auth tokens baked in.

    Call from your Mac to get the JSON, then import into Shortcuts app.
    Optionally pass ?host=your-tailscale-ip to override localhost.
    """
    from ..shortcuts.definitions import get_shortcut_definitions

    ncl_host = host or config.host
    if ncl_host == "0.0.0.0":
        ncl_host = "localhost"

    shortcuts = get_shortcut_definitions(
        ncl_host=ncl_host,
        ncl_port=config.port,
        strike_token=STRIKE_TOKEN,
    )
    # Mask tokens in shortcut definitions before returning
    sanitized_shortcuts = []
    for s in shortcuts:
        s_copy = dict(s)
        if s_copy.get("auth_header"):
            raw = s_copy["auth_header"]
            if "Bearer " in raw:
                token_part = raw.replace("Bearer ", "").strip()
                s_copy["auth_header"] = f"Bearer {_mask_token(token_part)}"
            else:
                s_copy["auth_header"] = _mask_token(raw)
        sanitized_shortcuts.append(s_copy)
    return {
        "pack_version": "1.0",
        "ncl_host": ncl_host,
        "ncl_port": config.port,
        "total_shortcuts": len(sanitized_shortcuts),
        "shortcuts": sanitized_shortcuts,
        "setup_instructions": {
            "step_1": "Open this URL on your iPhone to see shortcut definitions",
            "step_2": "Create each shortcut in the Shortcuts app using the 'actions' array",
            "step_3": "Set the Siri trigger phrases listed in each shortcut",
            "step_4": "Test with: 'Hey Siri, NCL status'",
        },
    }


@app.get("/shortcuts/test/{shortcut_id}")
async def test_shortcut(shortcut_id: str):
    """Test a shortcut endpoint by simulating what the iOS Shortcut would call."""
    from ..shortcuts.definitions import get_shortcut_definitions

    shortcuts = get_shortcut_definitions(
        ncl_host="localhost",
        ncl_port=config.port,
        strike_token=STRIKE_TOKEN,
    )
    shortcut = next((s for s in shortcuts if s["id"] == shortcut_id), None)
    if not shortcut:
        raise HTTPException(status_code=404, detail=f"Shortcut '{shortcut_id}' not found")

    # Mask auth header in test output
    masked_shortcut = dict(shortcut)
    if masked_shortcut.get("auth_header"):
        raw = masked_shortcut["auth_header"]
        if "Bearer " in raw:
            token_part = raw.replace("Bearer ", "").strip()
            masked_shortcut["auth_header"] = f"Bearer {_mask_token(token_part)}"
        else:
            masked_shortcut["auth_header"] = _mask_token(raw)

    return {
        "shortcut": masked_shortcut["name"],
        "endpoint": masked_shortcut["endpoint"],
        "method": masked_shortcut["method"],
        "requires_auth": shortcut["auth_header"] is not None,
        "input_fields": masked_shortcut["input_fields"],
        "test_curl": _build_test_curl(masked_shortcut),
    }


def _build_test_curl(shortcut: dict) -> str:
    """Build a curl command for testing a shortcut endpoint."""
    parts = [f"curl -X {shortcut['method']}"]
    if shortcut.get("auth_header"):
        parts.append(f'-H "Authorization: {shortcut["auth_header"]}"')
    if shortcut["method"] == "POST":
        parts.append('-H "Content-Type: application/json"')
        if body := shortcut.get("body_template"):
            import json as _json
            # Replace template vars with example values
            example = _json.dumps(body).replace("{{intent}}", "Test pump from shortcuts").replace("{{urgency}}", "normal").replace("{{council_type}}", "both").replace("{{query}}", "test search").replace("{{UUID}}", "shortcut-test-001")
            parts.append(f"-d '{example}'")
    parts.append(shortcut["endpoint"])
    return " \\\n  ".join(parts)


@app.get("/shortcuts/setup", response_class=HTMLResponse)
async def shortcuts_setup_page(
    host: str = Query(default=None, description="Override NCL host IP"),
):
    """
    Mobile-first setup wizard for FirstStrike iOS Shortcuts.
    Open this URL on your iPhone Safari → follow the guided steps.
    Generates Apple Shortcuts URL-scheme links for one-tap creation.
    """
    from ..shortcuts.definitions import get_shortcut_definitions

    ncl_host = host or config.host
    if ncl_host in ("0.0.0.0", "127.0.0.1", "localhost"):
        ncl_host = "localhost"
    # Escape for safe HTML embedding (XSS prevention on user-supplied host param)
    ncl_host = html_mod.escape(ncl_host)

    shortcuts = get_shortcut_definitions(
        ncl_host=ncl_host,
        ncl_port=config.port,
        strike_token=STRIKE_TOKEN,
    )

    shortcut_cards = ""
    for s in shortcuts:
        actions_json = html_mod.escape(json.dumps(s["actions"], indent=2))
        test_endpoint = html_mod.escape(s["endpoint"])
        method = html_mod.escape(s["method"])
        # Mask the actual token — copy STRIKE_AUTH_TOKEN from your .env file
        _raw_auth = s.get("auth_header") or ""
        if _raw_auth and "Bearer " in _raw_auth:
            _masked_auth = "Bearer ****  (copy STRIKE_AUTH_TOKEN from your .env)"
        elif _raw_auth:
            _masked_auth = "****  (copy STRIKE_AUTH_TOKEN from your .env)"
        else:
            _masked_auth = None
        auth = html_mod.escape(f'Authorization: {_masked_auth}' if _masked_auth else "None required")
        # Escape all user-controllable fields for XSS prevention
        s_name = html_mod.escape(s.get('name', ''))
        s_color = html_mod.escape(s.get('color', '#888'))
        s_icon = html_mod.escape(s.get('icon', '⚡'))
        s_siri = html_mod.escape(s.get('siri_phrase', ''))
        s_desc = html_mod.escape(s.get('description', ''))
        s_trigger = html_mod.escape(s.get('trigger_phrase', ''))

        shortcut_cards += f"""
        <div class="card">
          <div class="card-header" style="border-left: 4px solid {s_color}">
            <span class="icon">{s_icon}</span>
            <div>
              <h3>{s_name}</h3>
              <p class="siri-phrase">"{s_siri}"</p>
            </div>
          </div>
          <p class="desc">{s_desc}</p>
          <details>
            <summary>Setup Instructions</summary>
            <div class="steps">
              <ol>
                <li>Open <b>Shortcuts</b> app → tap <b>+</b></li>
                <li>Name it: <b>{s_name}</b></li>
                <li>Add actions per the flow below</li>
                <li>Tap <b>ⓘ</b> → set Siri phrase: <code>{s_trigger}</code></li>
              </ol>
              <h4>Actions Flow:</h4>
              <pre>{actions_json}</pre>
              <h4>Quick Test:</h4>
              <pre>curl -X {method} {test_endpoint}</pre>
              <p class="auth-note">Auth: {auth}</p>
            </div>
          </details>
        </div>
        """

    from ..strike_point_orchestrator import NTFY_TOPIC, NTFY_SERVER
    ntfy_subscribe_url = f"{NTFY_SERVER}/{NTFY_TOPIC}"

    push_section = f"""
    <div class="section">
      <h2>📱 Push Notifications</h2>
      <p>NCL pushes intelligence briefs and hot signal alerts to your phone automatically. Free, no account needed.</p>
      <div class="card">
        <div class="card-header" style="border-left: 4px solid #22c55e">
          <span class="icon">🔔</span>
          <div>
            <h3>Subscribe to NCL Alerts (30 sec)</h3>
          </div>
        </div>
        <ol>
          <li>Install <a href="https://apps.apple.com/app/ntfy/id1625396347">ntfy</a> from App Store (FREE)</li>
          <li>Open this link on your phone: <a href="{ntfy_subscribe_url}">{ntfy_subscribe_url}</a></li>
          <li>Tap <b>Subscribe</b> when prompted</li>
          <li>Done. Test it: <a href="http://{ncl_host}:{config.port}/notifications/test">Send Test Notification</a></li>
        </ol>
        <p class="auth-note">Topic: <code>{NTFY_TOPIC}</code> — NCL auto-pushes briefs every 4 hours and hot signal alerts instantly.</p>
      </div>
    </div>
    """

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
  <title>NCL FirstStrike Setup</title>
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'SF Pro', sans-serif;
      background: #0a0a0a;
      color: #e5e5e5;
      padding: 16px;
      padding-bottom: 80px;
      -webkit-text-size-adjust: 100%;
    }}
    .header {{
      text-align: center;
      padding: 24px 0;
      border-bottom: 1px solid #222;
      margin-bottom: 24px;
    }}
    .header h1 {{
      font-size: 28px;
      font-weight: 700;
      background: linear-gradient(135deg, #38bdf8, #ef4444);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
    }}
    .header p {{ color: #888; margin-top: 8px; font-size: 14px; }}
    .status {{
      background: #111;
      border: 1px solid #22c55e44;
      border-radius: 12px;
      padding: 16px;
      margin-bottom: 24px;
      display: flex;
      align-items: center;
      gap: 12px;
    }}
    .status .dot {{
      width: 12px; height: 12px;
      background: #22c55e;
      border-radius: 50%;
      box-shadow: 0 0 8px #22c55e88;
      animation: pulse 2s infinite;
    }}
    @keyframes pulse {{
      0%, 100% {{ opacity: 1; }}
      50% {{ opacity: 0.5; }}
    }}
    .section {{ margin-bottom: 32px; }}
    .section h2 {{
      font-size: 20px;
      margin-bottom: 16px;
      color: #fff;
    }}
    .card {{
      background: #151515;
      border: 1px solid #2a2a2a;
      border-radius: 12px;
      padding: 16px;
      margin-bottom: 12px;
    }}
    .card-header {{
      display: flex;
      align-items: center;
      gap: 12px;
      padding-left: 12px;
      margin-bottom: 8px;
    }}
    .card-header .icon {{ font-size: 24px; }}
    .card-header h3 {{ font-size: 17px; color: #fff; }}
    .siri-phrase {{
      font-size: 13px;
      color: #38bdf8;
      font-style: italic;
    }}
    .desc {{ font-size: 14px; color: #999; margin-bottom: 8px; }}
    details {{
      margin-top: 8px;
    }}
    details summary {{
      color: #38bdf8;
      cursor: pointer;
      font-size: 14px;
      font-weight: 600;
    }}
    .steps {{
      margin-top: 12px;
      padding: 12px;
      background: #0d0d0d;
      border-radius: 8px;
    }}
    .steps ol {{ padding-left: 20px; }}
    .steps li {{
      margin-bottom: 8px;
      font-size: 14px;
      line-height: 1.5;
    }}
    .steps h4 {{
      margin-top: 12px;
      margin-bottom: 6px;
      color: #f59e0b;
      font-size: 14px;
    }}
    pre {{
      background: #0a0a0a;
      border: 1px solid #333;
      border-radius: 6px;
      padding: 8px;
      font-size: 11px;
      overflow-x: auto;
      white-space: pre-wrap;
      word-break: break-all;
      color: #22c55e;
      margin: 4px 0;
    }}
    code {{
      background: #222;
      padding: 2px 6px;
      border-radius: 4px;
      font-size: 12px;
      color: #f59e0b;
    }}
    .auth-note {{
      font-size: 12px;
      color: #666;
      margin-top: 8px;
      font-style: italic;
    }}
    a {{ color: #38bdf8; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .quick-start {{
      background: linear-gradient(135deg, #1a1a2e, #16213e);
      border: 1px solid #38bdf844;
      border-radius: 12px;
      padding: 20px;
      margin-bottom: 24px;
    }}
    .quick-start h2 {{ color: #38bdf8; margin-bottom: 12px; }}
    .quick-start ol {{ padding-left: 20px; }}
    .quick-start li {{
      margin-bottom: 10px;
      font-size: 15px;
      line-height: 1.5;
    }}
  </style>
</head>
<body>
  <div class="header">
    <h1>⚡ NCL FirstStrike</h1>
    <p>Intelligence Engine → iPhone Pipeline</p>
  </div>

  <div class="status">
    <div class="dot"></div>
    <div>
      <strong>Brain Online</strong> — {len(shortcuts)} shortcuts ready
      <br><span style="color:#888;font-size:12px">Host: {ncl_host}:{config.port}</span>
    </div>
  </div>

  <div class="quick-start">
    <h2>⚡ Quick Start</h2>
    <ol>
      <li><b>Shortcuts:</b> Open each card below → follow the setup steps in the Shortcuts app</li>
      <li><b>Pushover:</b> Install the app → add tokens to .env (see below)</li>
      <li><b>Test:</b> Say "Hey Siri, NCL status" to verify</li>
    </ol>
  </div>

  <div class="section">
    <h2>🎯 Siri Shortcuts ({len(shortcuts)})</h2>
    {shortcut_cards}
  </div>

  {push_section}

  <div class="section">
    <h2>🔗 Endpoints</h2>
    <div class="card">
      <pre>Dashboard:  http://{ncl_host}:{config.port}/dashboard/ui
Shortcuts:  http://{ncl_host}:{config.port}/shortcuts/config
Intel:      http://{ncl_host}:{config.port}/intelligence/latest
Signals:    http://{ncl_host}:{config.port}/intelligence/signals/top
Health:     http://{ncl_host}:{config.port}/health</pre>
    </div>
  </div>
</body>
</html>"""
    return HTMLResponse(content=html)


# ── Search & Indexing Endpoints ────────────────────────────────────────────


class SearchRequest(BaseModel):
    """Full-text search request."""
    query: str = Field(..., min_length=1, description="Search query")
    limit: int = Field(default=20, ge=1, le=200)
    doc_types: list[str] | None = Field(default=None, description="Filter: event, memory, mandate")
    days_back: int | None = Field(default=None, ge=1, description="Only return results from past N days")


class EventSearchRequest(BaseModel):
    """Structured event search request."""
    event_type: str | None = None
    correlation_id: str | None = None
    pump_id: str | None = None
    mandate_id: str | None = None
    days_back: int | None = Field(default=None, ge=1)
    limit: int = Field(default=50, ge=1, le=500)


@app.post("/search")
async def full_text_search(req: SearchRequest):
    """Full-text search across events, memory, and mandates."""
    if not search_index:
        raise HTTPException(status_code=503, detail="Search index not initialized")

    results = await search_index.search(
        query=req.query,
        limit=req.limit,
        doc_types=req.doc_types,
        days_back=req.days_back,
    )
    return {
        "query": req.query,
        "total": len(results),
        "results": [r.to_dict() for r in results],
    }


@app.post("/search/events")
async def search_events(req: EventSearchRequest):
    """Structured search across events by type, correlation, pump, or mandate."""
    if not search_index:
        raise HTTPException(status_code=503, detail="Search index not initialized")

    results = await search_index.search_events(
        event_type=req.event_type,
        correlation_id=req.correlation_id,
        pump_id=req.pump_id,
        mandate_id=req.mandate_id,
        days_back=req.days_back,
        limit=req.limit,
    )
    return {
        "filters": req.model_dump(exclude_none=True),
        "total": len(results),
        "results": [r.to_dict() for r in results],
    }


@app.get("/search/chain/{correlation_id}")
async def get_causality_chain(correlation_id: str):
    """Retrieve the full causality chain for a correlation ID (chronological)."""
    if not search_index:
        raise HTTPException(status_code=503, detail="Search index not initialized")

    results = await search_index.get_chain(correlation_id)
    return {
        "correlation_id": correlation_id,
        "chain_length": len(results),
        "events": [r.to_dict() for r in results],
    }


@app.get("/search/stats")
async def search_stats():
    """Return search index statistics."""
    if not search_index:
        raise HTTPException(status_code=503, detail="Search index not initialized")
    return search_index.get_stats()


# Error handlers
@app.exception_handler(Exception)
async def exception_handler(request, exc: Exception):
    """Global exception handler.

    Logs the full traceback server-side (with a short correlation ID) and
    returns a sanitized JSON envelope to the client.  In production mode the
    raw exception detail is suppressed to avoid leaking internals.
    """
    import uuid as _uuid
    err_id = _uuid.uuid4().hex[:12]
    try:
        log.error(
            "[%s] unhandled exception on %s %s",
            err_id,
            getattr(getattr(request, "method", None), "upper", lambda: "?")() if request else "?",
            getattr(getattr(request, "url", None), "path", "?") if request else "?",
            exc_info=True,
        )
    except Exception:  # pragma: no cover — never let logging crash the handler
        pass
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "error_id": err_id,
            "detail": str(exc) if config.debug else "An error occurred",
        },
    )


# ===========================================================================
# Sprint 2 — Telemetry Endpoints
# ===========================================================================


@app.get("/telemetry/config")
async def get_telemetry_config() -> dict:
    """Get current telemetry configuration."""
    if not _telemetry:
        raise HTTPException(status_code=503, detail="Telemetry not initialized")
    return _telemetry.config.model_dump()


@app.post("/telemetry/config")
async def update_telemetry_config(level: str = Query(default="standard")) -> dict:
    """Update telemetry level (off/minimal/standard/verbose)."""
    if not _telemetry:
        raise HTTPException(status_code=503, detail="Telemetry not initialized")
    try:
        _telemetry.config.level = TelemetryLevel(level)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid level: {level}. Use: off, minimal, standard, verbose")
    return {"status": "updated", "level": _telemetry.config.level.value}


@app.get("/telemetry/stats")
async def get_telemetry_stats(hours_back: int = Query(default=24, ge=1, le=8760)) -> dict:
    """Get aggregated telemetry stats per workflow."""
    if not _telemetry:
        raise HTTPException(status_code=503, detail="Telemetry not initialized")
    stats = _telemetry.get_all_workflow_stats(hours_back=hours_back)
    return {"workflows": [s.model_dump() for s in stats], "hours_back": hours_back}


@app.get("/telemetry/recent")
async def get_recent_telemetry(n: int = Query(default=100, le=1000)) -> dict:
    """Get recent telemetry records."""
    if not _telemetry:
        raise HTTPException(status_code=503, detail="Telemetry not initialized")
    records = _telemetry.get_recent(n=n)
    return {"records": [r.model_dump() for r in records], "count": len(records)}


@app.post("/telemetry/flush")
async def flush_telemetry() -> dict:
    """Force-flush telemetry buffer to disk."""
    if not _telemetry:
        raise HTTPException(status_code=503, detail="Telemetry not initialized")
    await _telemetry.flush()
    return {"status": "flushed"}


# ===========================================================================
# Sprint 2 — Availability Tracker Endpoints
# ===========================================================================


@app.get("/availability/dashboard")
async def availability_dashboard() -> dict:
    """Dashboard-ready availability summary for all workflows."""
    if not _availability:
        raise HTTPException(status_code=503, detail="Availability tracker not initialized")
    return _availability.get_dashboard_summary()


@app.get("/availability/workflow/{workflow}")
async def get_workflow_availability(workflow: str) -> dict:
    """Get availability health for a specific workflow."""
    if not _availability:
        raise HTTPException(status_code=503, detail="Availability tracker not initialized")
    health = _availability.get_workflow_health(workflow)
    return health.model_dump()


@app.get("/availability/alerts")
async def get_availability_alerts(acknowledged: bool = Query(default=None)) -> dict:
    """Get availability alerts."""
    if not _availability:
        raise HTTPException(status_code=503, detail="Availability tracker not initialized")
    alerts = _availability.get_alerts(acknowledged=acknowledged)
    return {"alerts": [a.model_dump() for a in alerts], "count": len(alerts)}


@app.post("/availability/alerts/{alert_id}/acknowledge")
async def acknowledge_availability_alert(alert_id: str) -> dict:
    """Acknowledge an availability alert."""
    if not _availability:
        raise HTTPException(status_code=503, detail="Availability tracker not initialized")
    if _availability.acknowledge_alert(alert_id):
        return {"status": "acknowledged", "alert_id": alert_id}
    raise HTTPException(status_code=404, detail=f"Alert {alert_id} not found")


# ===========================================================================
# Sprint 2 — Governance / Action Permission Model Endpoints
# ===========================================================================


@app.get("/governance/policy/rules")
async def list_policy_rules(authorization: str = Header(default="")) -> dict:
    """List all policy rules."""
    _verify_strike_token(authorization)
    if not _policy_kernel:
        raise HTTPException(status_code=503, detail="PolicyKernel not initialized")
    rules = _policy_kernel.get_rules()
    return {"rules": [r.model_dump() for r in rules], "count": len(rules)}


@app.post("/governance/action/suggest")
async def create_suggest_action(
    name: str,
    source_agent: str = "ncl-brain",
    description: str = "",
    authorization: str = Header(default=""),
) -> dict:
    """Create a Suggest-tier action (informational only, always allowed)."""
    _verify_strike_token(authorization)
    if not _action_router:
        raise HTTPException(status_code=503, detail="ActionRouter not initialized")
    action = _action_router.suggest(name=name, source_agent=source_agent, description=description)
    return action.model_dump()


@app.post("/governance/action/draft")
async def create_draft_action(
    name: str,
    source_agent: str = "ncl-brain",
    description: str = "",
    authorization: str = Header(default=""),
) -> dict:
    """Create a Draft-tier action (creates artifacts, no side effects)."""
    _verify_strike_token(authorization)
    if not _action_router:
        raise HTTPException(status_code=503, detail="ActionRouter not initialized")
    action = _action_router.draft(name=name, source_agent=source_agent, description=description)
    return action.model_dump()


@app.post("/governance/action/execute")
async def create_execute_action(
    name: str,
    source_agent: str = "ncl-brain",
    description: str = "",
    pump_id: str = None,
    mandate_id: str = None,
    authorization: str = Header(default=""),
) -> dict:
    """Create an Execute-tier action (requires NATRIX consent)."""
    _verify_strike_token(authorization)
    if not _action_router:
        raise HTTPException(status_code=503, detail="ActionRouter not initialized")
    action = _action_router.execute(
        name=name, source_agent=source_agent, description=description,
        pump_id=pump_id, mandate_id=mandate_id,
    )
    return action.model_dump()


@app.get("/governance/actions/pending")
async def list_pending_actions(authorization: str = Header(default="")) -> dict:
    """List Execute-tier actions awaiting NATRIX consent."""
    _verify_strike_token(authorization)
    if not _action_router:
        raise HTTPException(status_code=503, detail="ActionRouter not initialized")
    pending = _action_router.get_pending()
    return {"pending": [a.model_dump() for a in pending], "count": len(pending)}


@app.post("/governance/actions/{action_id}/approve")
async def approve_action(
    action_id: str,
    authorization: str = Header(default=""),
) -> dict:
    """NATRIX approves an Execute-tier action."""
    _verify_strike_token(authorization)
    if not _action_router:
        raise HTTPException(status_code=503, detail="ActionRouter not initialized")
    try:
        action = _action_router.approve(action_id, approver="NATRIX")
        return {"status": "approved", "action": action.model_dump()}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/governance/actions/{action_id}/reject")
async def reject_action(
    action_id: str,
    reason: str = Query(default="Rejected by NATRIX"),
    authorization: str = Header(default=""),
) -> dict:
    """NATRIX rejects an Execute-tier action."""
    _verify_strike_token(authorization)
    if not _action_router:
        raise HTTPException(status_code=503, detail="ActionRouter not initialized")
    try:
        action = _action_router.reject(action_id, reason=reason)
        return {"status": "rejected", "action": action.model_dump()}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/governance/audit")
async def get_governance_audit(
    n: int = Query(default=100, le=1000),
    authorization: str = Header(default=""),
) -> dict:
    """Get governance audit log."""
    _verify_strike_token(authorization)
    if not _policy_kernel:
        raise HTTPException(status_code=503, detail="PolicyKernel not initialized")
    entries = _policy_kernel.get_audit_log(n=n)
    return {"entries": [e.model_dump() for e in entries], "count": len(entries)}


# ===========================================================================
# Sprint 2 — Emergency Stop (Kill Switch) Endpoints
# ===========================================================================


@app.get("/governance/emergency-stop")
async def get_emergency_stop_status() -> dict:
    """Get current emergency stop status."""
    if not _emergency_stop:
        raise HTTPException(status_code=503, detail="EmergencyStop not initialized")
    return await _emergency_stop.get_stats()


@app.post("/governance/emergency-stop/activate")
async def activate_emergency_stop(
    reason: str = Query(default="Manual emergency stop"),
    authorization: str = Header(default=""),
) -> dict:
    """ONE-TAP STOP — immediately disable all Execute-tier actions."""
    _verify_strike_token(authorization)
    if not _emergency_stop:
        raise HTTPException(status_code=503, detail="EmergencyStop not initialized")
    state = await _emergency_stop.activate(actor="NATRIX", reason=reason)
    return {"status": "activated", "state": state.model_dump()}


@app.post("/governance/emergency-stop/deactivate")
async def deactivate_emergency_stop(
    reason: str = Query(default="Manual deactivation"),
    authorization: str = Header(default=""),
) -> dict:
    """Deactivate emergency stop — re-enable Execute-tier actions."""
    _verify_strike_token(authorization)
    if not _emergency_stop:
        raise HTTPException(status_code=503, detail="EmergencyStop not initialized")
    state = await _emergency_stop.deactivate(actor="NATRIX", reason=reason)
    return {"status": "deactivated", "state": state.model_dump()}


@app.get("/governance/emergency-stop/ledger")
async def get_emergency_stop_ledger(
    n: int = Query(default=100, le=1000),
    authorization: str = Header(default=""),
) -> dict:
    """Get emergency stop audit ledger."""
    _verify_strike_token(authorization)
    if not _emergency_stop:
        raise HTTPException(status_code=503, detail="EmergencyStop not initialized")
    entries = await _emergency_stop.get_ledger(n=n)
    return {"entries": [e.model_dump() for e in entries], "count": len(entries)}


# ===========================================================================
# Sprint 2 — Golden Task Suite / Evaluation Endpoints
# ===========================================================================


@app.post("/evaluation/run")
async def run_golden_task_suite(
    authorization: str = Header(default=""),
) -> dict:
    """Run the full Golden Task Suite (50 deterministic tasks)."""
    _verify_strike_token(authorization)
    if not _eval_runner:
        raise HTTPException(status_code=503, detail="EvalRunner not initialized")

    async def _run():
        try:
            result = await _eval_runner.run_suite()
            _eval_runner.save_results(result)
        except Exception as e:
            log.exception(f"[/evaluation/run] Golden Task Suite failed: {e}")

    task = asyncio.create_task(_run())
    task.add_done_callback(lambda t: log.error(f"Eval task died: {t.exception()!r}") if not t.cancelled() and t.exception() else None)
    return {"status": "started", "message": "Golden Task Suite running in background. Check /evaluation/results for output."}


@app.get("/evaluation/results")
async def get_evaluation_results() -> dict:
    """Get the most recent Golden Task Suite results."""
    if not _eval_runner:
        raise HTTPException(status_code=503, detail="EvalRunner not initialized")
    result = _eval_runner.load_previous_results()
    if not result:
        return {"status": "no_results", "message": "No evaluation results found. Run POST /evaluation/run first."}
    return result.model_dump()


@app.get("/evaluation/summary")
async def get_evaluation_summary() -> dict:
    """Quick summary of last evaluation run."""
    if not _eval_runner:
        raise HTTPException(status_code=503, detail="EvalRunner not initialized")
    result = _eval_runner.load_previous_results()
    if not result:
        return {"status": "no_results"}
    return {
        "suite_version": result.suite_version,
        "total_tasks": result.total_tasks,
        "passed": result.passed,
        "failed": result.failed,
        "pass_rate": result.pass_rate,
        "regression_detected": result.regression_detected,
        "regression_tasks": result.regression_tasks,
        "timestamp": result.timestamp.isoformat(),
    }


# ===========================================================================
# Sprint 3 — Review Queue UI Endpoints
# ===========================================================================


@app.get("/review-queue/items")
async def get_review_queue_items(
    type_filter: str = Query(default=None),
    urgency_filter: str = Query(default=None),
    tag_filter: str = Query(default=None),
    archived: bool = Query(default=False),
) -> dict:
    """Get all review queue items with optional filters."""
    if not _review_queue:
        raise HTTPException(status_code=503, detail="ReviewQueue not initialized")
    items = _review_queue.get_items(
        type_filter=type_filter, urgency_filter=urgency_filter,
        tag_filter=tag_filter, archived=archived,
    )
    return {"items": [i.model_dump() for i in items], "count": len(items)}


@app.get("/review-queue/items/{item_id}")
async def get_review_queue_item(item_id: str) -> dict:
    """Get a single review queue item by ID."""
    if not _review_queue:
        raise HTTPException(status_code=503, detail="ReviewQueue not initialized")
    item = _review_queue.get_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail=f"Item {item_id} not found")
    return item.model_dump()


@app.post("/review-queue/refresh")
async def refresh_review_queue() -> dict:
    """Refresh the review queue — pull latest items, deduplicate, regenerate suggestions."""
    if not _review_queue:
        raise HTTPException(status_code=503, detail="ReviewQueue not initialized")
    items = await _review_queue.refresh()
    return {"items": [i.model_dump() for i in items], "count": len(items)}


@app.post("/review-queue/ingest/pump")
async def ingest_pump_to_queue(pump_data: dict) -> dict:
    """Ingest a pending pump prompt into the review queue."""
    if not _review_queue:
        raise HTTPException(status_code=503, detail="ReviewQueue not initialized")
    item = await _review_queue.ingest_pump(pump_data)
    return {"status": "ingested", "item": item.model_dump()}


@app.post("/review-queue/ingest/action")
async def ingest_action_to_queue(action_data: dict) -> dict:
    """Ingest a pending governance action into the review queue."""
    if not _review_queue:
        raise HTTPException(status_code=503, detail="ReviewQueue not initialized")
    item = await _review_queue.ingest_action(action_data)
    return {"status": "ingested", "item": item.model_dump()}


@app.post("/review-queue/ingest/council")
async def ingest_council_to_queue(session_data: dict) -> dict:
    """Ingest a council session into the review queue."""
    if not _review_queue:
        raise HTTPException(status_code=503, detail="ReviewQueue not initialized")
    item = await _review_queue.ingest_council(session_data)
    return {"status": "ingested", "item": item.model_dump()}


@app.post("/review-queue/tag")
async def batch_tag_items(item_ids: list[str], tags: list[str]) -> dict:
    """Tag multiple items in the review queue."""
    if not _review_queue:
        raise HTTPException(status_code=503, detail="ReviewQueue not initialized")
    items = await _review_queue.batch_tag(item_ids, tags)
    return {"status": "tagged", "items": [i.model_dump() for i in items], "count": len(items)}


@app.post("/review-queue/link")
async def batch_link_items(item_ids: list[str]) -> dict:
    """Link/associate multiple review queue items together."""
    if not _review_queue:
        raise HTTPException(status_code=503, detail="ReviewQueue not initialized")
    items = await _review_queue.batch_link(item_ids)
    return {"status": "linked", "items": [i.model_dump() for i in items], "count": len(items)}


@app.post("/review-queue/archive")
async def batch_archive_items(item_ids: list[str]) -> dict:
    """Archive multiple items from the review queue."""
    if not _review_queue:
        raise HTTPException(status_code=503, detail="ReviewQueue not initialized")
    items = await _review_queue.batch_archive(item_ids)
    return {"status": "archived", "items": [i.model_dump() for i in items], "count": len(items)}


@app.post("/review-queue/batch/approve")
async def batch_approve_items(
    item_ids: list[str],
    authorization: str = Header(default=""),
) -> dict:
    """Batch-approve items in the review queue (pumps + actions)."""
    _verify_strike_token(authorization)
    if not _review_queue:
        raise HTTPException(status_code=503, detail="ReviewQueue not initialized")
    results = await _review_queue.batch_approve(item_ids)
    return {"status": "processed", "results": results}


@app.post("/review-queue/batch/reject")
async def batch_reject_items(
    item_ids: list[str],
    reason: str = Query(default="Rejected by NATRIX"),
    authorization: str = Header(default=""),
) -> dict:
    """Batch-reject items in the review queue."""
    _verify_strike_token(authorization)
    if not _review_queue:
        raise HTTPException(status_code=503, detail="ReviewQueue not initialized")
    results = await _review_queue.batch_reject(item_ids, reason)
    return {"status": "processed", "results": results}


@app.get("/review-queue/stats")
async def get_review_queue_stats() -> dict:
    """Get review queue statistics."""
    if not _review_queue:
        raise HTTPException(status_code=503, detail="ReviewQueue not initialized")
    return _review_queue.get_stats()


@app.get("/review-queue/dashboard")
async def review_queue_dashboard() -> HTMLResponse:
    """Serve the Review Queue UI dashboard."""
    dashboard_path = Path(__file__).parent.parent.parent / "dashboard" / "review-queue.html"
    if not dashboard_path.exists():
        raise HTTPException(status_code=404, detail="Review Queue dashboard not found")
    async with aiofiles.open(dashboard_path, "r") as f:
        html = await f.read()
    return HTMLResponse(content=html)


# ===========================================================================
# Sprint 4 — Council Runner v1 Endpoints
# ===========================================================================


@app.post("/council-runner/run")
async def run_council_runner(
    request: Request,
    topic: str,
    prompt: str,
    authorization: str = Header(default=""),
) -> dict:
    """Run the Planner/Skeptic/Risk parallel council on a topic."""
    _verify_strike_token(authorization)
    _check_rate_limit(request)
    if not _council_store:
        raise HTTPException(status_code=503, detail="CouncilRunner not initialized")

    run_id = str(uuid.uuid4())

    async def _run():
        try:
            record = await run_parallel_council(topic=topic, prompt=prompt)
            await _council_store.save_run(record)
        except Exception as e:
            log.exception(f"[/council-runner/run] council run failed: {e}")

    task = asyncio.create_task(_run())
    task.add_done_callback(lambda t: log.error(f"Council runner task died: {t.exception()!r}") if not t.cancelled() and t.exception() else None)
    return {"status": "started", "run_id": run_id, "message": "Council running in background. Check /council-runner/runs for results."}


@app.get("/council-runner/runs")
async def list_council_runs(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """List council runner runs."""
    if not _council_store:
        raise HTTPException(status_code=503, detail="CouncilRunner not initialized")
    runs = await _council_store.list_runs(limit=limit, offset=offset)
    return {"runs": [r.model_dump() for r in runs], "count": len(runs)}


@app.get("/council-runner/runs/{run_id}")
async def get_council_run(run_id: str) -> dict:
    """Get a specific council run record."""
    if not _council_store:
        raise HTTPException(status_code=503, detail="CouncilRunner not initialized")
    record = await _council_store.get_run(run_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return record.model_dump()


@app.get("/council-runner/runs/{run_id}/provenance")
async def get_council_run_provenance(run_id: str) -> dict:
    """Get full provenance chain for a council run."""
    if not _council_store:
        raise HTTPException(status_code=503, detail="CouncilRunner not initialized")
    provenance = await _council_store.get_provenance(run_id)
    if not provenance:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return provenance


@app.post("/council-runner/replay/{run_id}")
async def replay_council_run(
    run_id: str,
    temperature_override: float = Query(default=None),
) -> dict:
    """Replay a previous council run for deterministic comparison."""
    if not _replay_engine:
        raise HTTPException(status_code=503, detail="ReplayEngine not initialized")

    async def _replay():
        try:
            record = await _replay_engine.replay(
                run_id=run_id, temperature_override=temperature_override,
            )
            if _council_store:
                await _council_store.save_run(record)
        except Exception as e:
            log.exception(f"[/council-runner/replay] replay failed: {e}")

    task = asyncio.create_task(_replay())
    task.add_done_callback(lambda t: log.error(f"Replay task died: {t.exception()!r}") if not t.cancelled() and t.exception() else None)
    return {"status": "replay_started", "original_run_id": run_id}


@app.get("/council-runner/compare/{run_id_a}/{run_id_b}")
async def compare_council_runs(run_id_a: str, run_id_b: str) -> dict:
    """Compare two council runs side-by-side."""
    if not _replay_engine:
        raise HTTPException(status_code=503, detail="ReplayEngine not initialized")
    comparison = await _replay_engine.compare_runs(run_id_a, run_id_b)
    return comparison


@app.get("/council-runner/search")
async def search_council_runs(
    q: str = Query(..., description="Search query for topic/prompt"),
    limit: int = Query(default=20, le=100),
) -> dict:
    """Search council runs by topic/prompt text."""
    if not _council_store:
        raise HTTPException(status_code=503, detail="CouncilRunner not initialized")
    runs = await _council_store.search_runs(topic_query=q, limit=limit)
    return {"runs": [r.model_dump() for r in runs], "count": len(runs), "query": q}


@app.get("/council-runner/stats")
async def get_council_runner_stats() -> dict:
    """Get council runner statistics."""
    if not _council_store:
        raise HTTPException(status_code=503, detail="CouncilRunner not initialized")
    return await _council_store.get_stats()


# ===========================================================================
# Pipeline Hardening — UNI Research Cortex Endpoints
# ===========================================================================


@app.post("/uni/research")
async def run_research(
    query: str,
    depth: str = Query(default="standard"),
    priority: int = Query(default=5, ge=1, le=10),
    authorization: str = Header(default=""),
) -> dict:
    """Run a deep research task via the UNI Research Cortex."""
    _verify_strike_token(authorization)
    if not _research_cortex:
        raise HTTPException(status_code=503, detail="ResearchCortex not initialized")
    from ..uni.models import ResearchDepth
    try:
        rd = ResearchDepth(depth)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid depth: {depth}. Use: quick, standard, deep, exhaustive")

    task_id = str(uuid.uuid4())

    async def _run():
        try:
            await _research_cortex.research(query=query, depth=rd, priority=priority)
        except Exception as e:
            log.exception(f"[/uni/research] research task failed: {e}")

    bg_task = asyncio.create_task(_run())
    bg_task.add_done_callback(lambda t: log.error(f"Research task died: {t.exception()!r}") if not t.cancelled() and t.exception() else None)
    return {"status": "started", "task_id": task_id, "query": query, "depth": depth}


@app.get("/uni/results")
async def list_research_results(limit: int = Query(default=50, le=200)) -> dict:
    """List recent research results."""
    if not _research_cortex:
        raise HTTPException(status_code=503, detail="ResearchCortex not initialized")
    results = await _research_cortex.list_results(limit=limit)
    return {"results": results, "count": len(results)}


@app.get("/uni/results/{task_id}")
async def get_research_result(task_id: str) -> dict:
    """Get a specific research result."""
    if not _research_cortex:
        raise HTTPException(status_code=503, detail="ResearchCortex not initialized")
    result = await _research_cortex.get_result(task_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"Research {task_id} not found")
    return result.model_dump()


@app.get("/uni/stats")
async def get_research_stats() -> dict:
    """Get UNI Research Cortex statistics."""
    if not _research_cortex:
        raise HTTPException(status_code=503, detail="ResearchCortex not initialized")
    return await _research_cortex.get_stats()


# ===========================================================================
# Pipeline Hardening — Memory Dashboard Endpoints
# ===========================================================================


@app.get("/memory/stats")
async def get_memory_stats() -> dict:
    """Get memory store statistics for the dashboard."""
    if not _memory_bridge:
        raise HTTPException(status_code=503, detail="MemoryBridge not initialized")
    return await _memory_bridge.get_stats()


@app.get("/memory/timeline")
async def get_memory_timeline(limit: int = Query(default=50, le=200)) -> dict:
    """Get memory event timeline."""
    if not _memory_bridge:
        raise HTTPException(status_code=503, detail="MemoryBridge not initialized")
    events = await _memory_bridge.get_timeline(limit=limit)
    return {"events": events, "count": len(events)}


@app.post("/memory/search")
async def search_memory(
    body: dict,
    authorization: str = Header(default=""),
) -> dict:
    """Search memory units with text, tags, importance, and date filters."""
    _verify_strike_token(authorization)
    if not body.get("query_text") and not body.get("tags"):
        raise HTTPException(status_code=400, detail="Missing required field: 'query_text' or 'tags'")
    if not _memory_bridge:
        raise HTTPException(status_code=503, detail="MemoryBridge not initialized")
    results = await _memory_bridge.search(
        query_text=body.get("query_text"),
        tags=body.get("tags"),
        importance_threshold=body.get("importance_threshold", 0),
        days_back=body.get("days_back", 30),
    )
    return {"results": results, "count": len(results)}


@app.post("/memory/semantic")
async def semantic_search_memory(body: dict) -> dict:
    """Semantic similarity search over memory units using vector embeddings."""
    if not brain:
        raise HTTPException(status_code=503, detail="Brain not initialized")
    query = body.get("query", "")
    if not query:
        raise HTTPException(status_code=400, detail="query is required")
    results = await brain.memory_store.semantic_search(
        query=query,
        n_results=body.get("n_results", 10),
        importance_threshold=body.get("importance_threshold", 0.0),
    )
    return {
        "results": [r.model_dump(mode="json") for r in results],
        "count": len(results),
        "query": query,
    }


@app.post("/memory/reindex")
async def reindex_memory(authorization: str = Header(default="")) -> dict:
    """Rebuild the vector search index from all stored memory units."""
    _verify_strike_token(authorization)
    if not brain:
        raise HTTPException(status_code=503, detail="Brain not initialized")
    return await brain.memory_store.reindex_all()


@app.get("/memory/dashboard")
async def memory_dashboard() -> HTMLResponse:
    """Serve the Memory Dashboard."""
    dashboard_path = Path(__file__).parent.parent.parent / "dashboard" / "memory.html"
    if not dashboard_path.exists():
        raise HTTPException(status_code=404, detail="Memory dashboard not found")
    async with aiofiles.open(dashboard_path, "r") as f:
        html = await f.read()
    return HTMLResponse(content=html)


# ===========================================================================
# Pipeline Hardening — Deployment & Monitoring Endpoints
# ===========================================================================


@app.get("/deployment/status")
async def get_deployment_status() -> dict:
    """Get status of all NCL daemon services."""
    if not _deployment_monitor:
        raise HTTPException(status_code=503, detail="DeploymentMonitor not initialized")
    states = await _deployment_monitor.check_all_health()
    from dataclasses import asdict
    from enum import Enum as _Enum

    def _serialize(s):
        d = asdict(s)
        # Convert enums to their .value and datetime to ISO string
        for k, v in d.items():
            if isinstance(v, _Enum):
                d[k] = v.value
            elif isinstance(v, datetime):
                d[k] = v.isoformat()
        return d

    return {"services": [_serialize(s) for s in states], "count": len(states)}


@app.get("/deployment/service/{service_name}")
async def get_service_status(service_name: str) -> dict:
    """Get status of a specific service."""
    if not _deployment_monitor:
        raise HTTPException(status_code=503, detail="DeploymentMonitor not initialized")
    from ..deployment.models import ServiceName
    try:
        sn = ServiceName(service_name)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown service: {service_name}")
    state = await _deployment_monitor.check_health(sn)
    return state.model_dump()


@app.get("/deployment/uptime")
async def get_uptime_report() -> dict:
    """Get uptime report for all services."""
    if not _deployment_monitor:
        raise HTTPException(status_code=503, detail="DeploymentMonitor not initialized")
    return await _deployment_monitor.get_uptime_report()


@app.get("/deployment/logs/{service_name}")
async def get_service_logs(
    service_name: str,
    lines: int = Query(default=50, le=500),
) -> dict:
    """Get recent log lines for a service."""
    if not _deployment_monitor:
        raise HTTPException(status_code=503, detail="DeploymentMonitor not initialized")
    from ..deployment.models import ServiceName
    try:
        sn = ServiceName(service_name)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown service: {service_name}")
    return await _deployment_monitor.get_log_tail(sn, lines=lines)


@app.get("/deployment/dashboard")
async def deployment_dashboard() -> dict:
    """Dashboard-ready deployment summary."""
    if not _deployment_monitor:
        raise HTTPException(status_code=503, detail="DeploymentMonitor not initialized")
    return await _deployment_monitor.get_dashboard_data()


# ─── Autonomous Scheduler Endpoints ────────────────────────────────


@app.get("/autonomous/status")
async def autonomous_status() -> dict:
    """Get autonomous scheduler status and statistics."""
    if not _autonomous:
        raise HTTPException(status_code=503, detail="Autonomous scheduler not initialized")
    return _autonomous.get_stats()


@app.post("/autonomous/stop")
async def autonomous_stop(authorization: str = Header(default="")) -> dict:
    """Stop the autonomous scheduler (manual override)."""
    _verify_strike_token(authorization)
    if not _autonomous:
        raise HTTPException(status_code=503, detail="Autonomous scheduler not initialized")
    await _autonomous.stop()
    return {"status": "stopped", "message": "Autonomous scheduler stopped"}


@app.post("/autonomous/start")
async def autonomous_start(authorization: str = Header(default="")) -> dict:
    """Restart the autonomous scheduler after a stop."""
    _verify_strike_token(authorization)
    if not _autonomous:
        raise HTTPException(status_code=503, detail="Autonomous scheduler not initialized")
    await _autonomous.start()
    return {"status": "started", "message": "Autonomous scheduler started"}


@app.get("/autonomous/signals")
async def autonomous_signals(limit: int = Query(50, ge=1, le=500)) -> dict:
    """Get recent autonomous signals and events."""
    if not _autonomous:
        raise HTTPException(status_code=503, detail="Autonomous scheduler not initialized")
    events_file = _autonomous.signals_dir / "events.ndjson"
    events = []
    if events_file.exists():
        async with aiofiles.open(events_file, "r") as f:
            content = await f.read()
            for line in content.strip().split("\n"):
                if line.strip():
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    # Return most recent first
    events.reverse()
    return {"events": events[:limit], "total": len(events)}


@app.get("/autonomous/council-flags")
async def autonomous_council_flags() -> dict:
    """Get pending council trigger flags."""
    if not _autonomous:
        raise HTTPException(status_code=503, detail="Autonomous scheduler not initialized")
    flags = await _autonomous._get_council_flags()
    return {"flags": flags, "count": len(flags)}


@app.post("/autonomous/trigger-council")
async def autonomous_trigger_council(
    prompt: str = Query(..., min_length=10),
    authorization: str = Header(default=""),
) -> dict:
    """Manually trigger an autonomous council session."""
    _verify_strike_token(authorization)
    if not _autonomous:
        raise HTTPException(status_code=503, detail="Autonomous scheduler not initialized")
    await _autonomous._flag_for_council(
        trigger="manual",
        data={"prompt": prompt},
        importance=100,
    )
    return {"status": "flagged", "message": "Council trigger flagged for next cycle"}


@app.post("/autonomous/scan-now")
async def autonomous_scan_now(authorization: str = Header(default="")) -> dict:
    """Trigger an immediate intelligence scan (outside normal schedule)."""
    _verify_strike_token(authorization)
    if not brain:
        raise HTTPException(status_code=503, detail="Brain not initialized")
    try:
        signals = []
        platform_status = {}
        for platform in ["x", "youtube", "reddit"]:
            method = getattr(brain.scanner, f"scan_{platform}", None)
            if not method:
                platform_status[platform] = "no_method"
                continue
            # Check if credentials are configured
            cred_check = {
                "x": bool(getattr(brain.scanner, "x_bearer_token", None)),
                "youtube": bool(getattr(brain.scanner, "youtube_api_key", None)),
                "reddit": bool(getattr(brain.scanner, "reddit_client_id", None) and getattr(brain.scanner, "reddit_client_secret", None)),
            }
            if not cred_check.get(platform, False):
                platform_status[platform] = "missing_credentials"
                continue
            queries = _autonomous._get_watch_queries(platform) if _autonomous else []
            platform_signals = 0
            for q in queries:
                try:
                    result = await method(q, max_results=10)
                    signals.extend(result)
                    platform_signals += len(result)
                except Exception as e:
                    platform_status[platform] = f"error: {str(e)[:100]}"
            if platform not in platform_status:
                platform_status[platform] = f"ok ({platform_signals} signals)"
        return {
            "status": "complete",
            "signals": len(signals),
            "platforms": platform_status,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ===========================================================================
# Intelligence Engine Endpoints
# ===========================================================================


@app.post("/intelligence/brief")
async def generate_intelligence_brief(
    brief_type: str = Query(default="daily", description="Brief type: daily, alert, strategic_review"),
    authorization: str = Header(default=""),
) -> dict:
    """Generate a fresh intelligence brief from all data sources."""
    _verify_strike_token(authorization)
    if not _intelligence:
        raise HTTPException(status_code=503, detail="Intelligence engine not initialized")
    try:
        brief = await _intelligence.generate_brief(brief_type=brief_type)
        result = {
            "status": "generated",
            "brief_id": brief.brief_id,
            "total_signals": brief.total_signals_processed,
            "sectors": len(brief.sectors),
            "predictions": len(brief.predictions),
            "risk_alerts": len(brief.risk_alerts),
            "text": brief.to_text(),
            "data": brief.model_dump(),
        }
        # Push to all connected dashboards via SSE
        await broadcast_event("new_brief", {
            "brief_id": brief.brief_id,
            "brief_type": brief_type,
            "total_signals": brief.total_signals_processed,
            "summary": brief.to_text()[:200],
        })
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/intelligence/latest")
async def get_latest_brief() -> dict:
    """Get the most recent intelligence brief."""
    if not _intelligence:
        raise HTTPException(status_code=503, detail="Intelligence engine not initialized")
    brief = await _intelligence.get_latest_brief()
    if not brief:
        return {"status": "no_brief", "message": "No brief generated yet. POST /intelligence/brief to generate one."}
    return {
        "brief_id": brief.brief_id,
        "timestamp": brief.timestamp.isoformat(),
        "brief_type": brief.brief_type,
        "total_signals": brief.total_signals_processed,
        "text": brief.to_text(),
        "data": brief.model_dump(),
    }


@app.get("/intelligence/stats")
async def intelligence_stats() -> dict:
    """Get intelligence engine statistics."""
    if not _intelligence:
        raise HTTPException(status_code=503, detail="Intelligence engine not initialized")
    return _intelligence.get_stats()


@app.post("/intelligence/collect")
async def collect_intelligence_signals(authorization: str = Header(default="")) -> dict:
    """Run a signal collection sweep without generating a full brief."""
    _verify_strike_token(authorization)
    if not _intelligence:
        raise HTTPException(status_code=503, detail="Intelligence engine not initialized")
    try:
        signals = await _intelligence.collect_all_signals()
        # Return summary, not raw signals (too large)
        source_counts = {}
        for sig in signals:
            source_counts[sig.source.value] = source_counts.get(sig.source.value, 0) + 1

        top_5 = sorted(signals, key=lambda s: s.importance_score(), reverse=True)[:5]
        result = {
            "status": "collected",
            "total_signals": len(signals),
            "source_counts": source_counts,
            "top_signals": [
                {
                    "source": s.source.value,
                    "title": s.title,
                    "importance": s.importance_score(),
                    "direction": s.direction.value,
                }
                for s in top_5
            ],
        }
        # Push update to all connected dashboards
        await broadcast_event("signals_collected", {
            "total": len(signals),
            "sources": source_counts,
        })
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/intelligence/briefs")
async def list_intelligence_briefs(limit: int = Query(default=20, ge=1, le=100)) -> dict:
    """List all historical intelligence briefs (newest first)."""
    if not _intelligence:
        raise HTTPException(status_code=503, detail="Intelligence engine not initialized")
    briefs_file = _intelligence._briefs_file
    if not briefs_file.exists():
        return {"total": 0, "briefs": []}
    try:
        entries = []
        async with aiofiles.open(briefs_file, "r") as f:
            async for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    entries.append({
                        "brief_id": d.get("brief_id", ""),
                        "brief_type": d.get("brief_type", "daily"),
                        "timestamp": d.get("timestamp", ""),
                        "total_signals": d.get("total_signals_processed", 0),
                        "sectors": len(d.get("sectors", [])),
                        "predictions": len(d.get("predictions", [])),
                        "risk_alerts": len(d.get("risk_alerts", [])),
                        "executive_summary": d.get("executive_summary", "")[:200],
                    })
                except json.JSONDecodeError:
                    continue
        entries.reverse()  # newest first
        return {"total": len(entries), "briefs": entries[:limit]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/intelligence/briefs/{brief_id}")
async def get_brief_by_id(brief_id: str) -> dict:
    """Get a specific historical brief by ID."""
    if not _intelligence:
        raise HTTPException(status_code=503, detail="Intelligence engine not initialized")
    briefs_file = _intelligence._briefs_file
    if not briefs_file.exists():
        raise HTTPException(status_code=404, detail="No briefs found")
    try:
        async with aiofiles.open(briefs_file, "r") as f:
            async for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    if d.get("brief_id") == brief_id:
                        from ..intelligence.models import IntelBrief
                        brief = IntelBrief(**d)
                        return {
                            "brief_id": brief.brief_id,
                            "timestamp": brief.timestamp.isoformat(),
                            "brief_type": brief.brief_type,
                            "total_signals": brief.total_signals_processed,
                            "text": brief.to_text(),
                            "data": brief.model_dump(),
                        }
                except json.JSONDecodeError:
                    continue
        raise HTTPException(status_code=404, detail=f"Brief {brief_id} not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ===========================================================================
# Intelligence → FirstStrike / STRIKE-POINT Integration
# ===========================================================================


@app.post("/intelligence/escalate")
async def escalate_intelligence_to_strike_point(
    brief_id: str = Query(default="", description="Brief ID to escalate (empty = latest)"),
    signal_ids: str = Query(default="", description="Comma-separated signal IDs to focus on"),
    authorization: str = Header(default=""),
) -> dict:
    """
    Escalate intelligence signals to STRIKE-POINT for deep council analysis.

    Takes the top signals from a brief (or specific signal IDs) and creates
    a pump prompt that feeds into the STRIKE-POINT mandate generation pipeline.
    This is the "expand and analyze" action from FirstStrike on iPhone.
    """
    _verify_strike_token(authorization)
    if not _intelligence:
        raise HTTPException(status_code=503, detail="Intelligence engine not initialized")

    # Get the brief to escalate
    if brief_id:
        brief = await _intelligence.get_latest_brief()
        if brief and brief.brief_id != brief_id:
            brief = None  # TODO: lookup by ID from history
    else:
        brief = await _intelligence.get_latest_brief()

    if not brief:
        raise HTTPException(status_code=404, detail="No intelligence brief found to escalate")

    # Extract signals to escalate
    escalation_signals = []
    if signal_ids:
        target_ids = set(signal_ids.split(","))
        for sig in brief.top_signals:
            if sig.signal_id in target_ids:
                escalation_signals.append(sig)
    else:
        # Default: top 5 signals by importance
        escalation_signals = sorted(
            brief.top_signals, key=lambda s: s.importance_score(), reverse=True
        )[:5]

    if not escalation_signals:
        return {"status": "no_signals", "message": "No signals to escalate"}

    # Build the STRIKE-POINT pump prompt from intelligence signals
    signal_summaries = []
    for sig in escalation_signals:
        direction_arrow = {
            "bullish": "▲", "bearish": "▼", "emerging": "★",
            "expanding": "↑", "contracting": "↓",
        }.get(sig.direction.value, "●")
        change_str = f" ({sig.change_pct:+.1f}%)" if sig.change_pct is not None else ""
        signal_summaries.append(
            f"  {direction_arrow} [{sig.source.value}] {sig.title}{change_str} "
            f"(confidence: {sig.confidence:.0%})"
        )

    # Compose the pump intent for STRIKE-POINT council
    pump_intent = (
        f"INTELLIGENCE ESCALATION — {brief.brief_type.upper()} BRIEF\n\n"
        f"Executive Summary:\n{brief.executive_summary[:500]}\n\n"
        f"Escalated Signals ({len(escalation_signals)}):\n"
        + "\n".join(signal_summaries) + "\n\n"
        f"Risk Alerts: {', '.join(brief.risk_alerts[:3]) if brief.risk_alerts else 'None'}\n\n"
        f"DIRECTIVE: Analyze these intelligence signals. Identify actionable opportunities, "
        f"assess risks, and generate strategic mandates. Consider cross-signal convergence "
        f"and second-order implications."
    )

    # Create the pump prompt
    import uuid as _uuid
    pump_id = f"INTEL-ESC-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"

    pump_prompt = {
        "pump_id": pump_id,
        "source": "intelligence-engine",
        "intent": pump_intent,
        "context": {
            "origin": "intelligence_escalation",
            "brief_id": brief.brief_id,
            "brief_type": brief.brief_type,
            "signal_count": len(escalation_signals),
            "signal_ids": [s.signal_id for s in escalation_signals],
        },
        "urgency": "high",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    # Submit to brain's pump intake (fire-and-forget to avoid blocking)
    if brain:
        async def _submit_pump():
            try:
                pump = PumpPrompt(
                    prompt_id=pump_id,
                    source="intelligence-engine",
                    intent=pump_intent,
                    urgency="high",
                )
                result = await brain.receive_pump_prompt(pump)
                mandates = len(result.get("mandates", [])) if isinstance(result, dict) else 0
                log.info(f"Escalation pump {pump_id} submitted — {mandates} mandates generated")
            except Exception as e:
                logging.getLogger("ncl.api").warning(f"Pump submission failed: {e}")
                # Fallback: write to file
                pump_file = Path(config.data_dir) / "intelligence" / "escalations" / f"{pump_id}.json"
                pump_file.parent.mkdir(parents=True, exist_ok=True)
                pump_file.write_text(json.dumps(pump_prompt, indent=2, default=str))

        task = asyncio.create_task(_submit_pump())
        task.add_done_callback(lambda t: log.error(f"Pump submit task died: {t.exception()!r}") if not t.cancelled() and t.exception() else None)
        mandates_generated = -1  # Pending — running in background
    else:
        mandates_generated = 0
        pump_file = Path(config.data_dir) / "intelligence" / "escalations" / f"{pump_id}.json"
        pump_file.parent.mkdir(parents=True, exist_ok=True)
        pump_file.write_text(json.dumps(pump_prompt, indent=2, default=str))

    # Notify NATRIX that escalation was sent
    from ..strike_point_orchestrator import notify_natrix

    async def _notify_escalation():
        try:
            await notify_natrix(
                "Intel Escalated to STRIKE-POINT",
                f"Brief: {brief.brief_type} | Signals: {len(escalation_signals)}\n"
                f"Pump: {pump_id}\n"
                f"Top: {escalation_signals[0].title if escalation_signals else 'N/A'}",
                priority=0,
            )
        except Exception as e:
            log.warning(f"Escalation notification failed: {e}")

    _esc_task = asyncio.create_task(_notify_escalation())
    _esc_task.add_done_callback(
        lambda t: log.error(f"escalation notify task died: {t.exception()!r}")
        if not t.cancelled() and t.exception() is not None
        else None
    )

    return {
        "status": "escalated",
        "pump_id": pump_id,
        "brief_id": brief.brief_id,
        "escalated_count": len(escalation_signals),
        "escalated_signals": [
            {"signal_id": s.signal_id, "title": s.title, "source": s.source.value}
            for s in escalation_signals
        ],
        "mandates_generated": mandates_generated,
    }


@app.post("/intelligence/escalate/{signal_id}")
async def escalate_single_signal(
    signal_id: str,
    authorization: str = Header(default=""),
) -> dict:
    """
    Escalate a single intelligence signal to STRIKE-POINT.

    Used from the FirstStrike "NCL Signal Action" shortcut when NATRIX
    picks a specific signal to expand on.
    """
    _verify_strike_token(authorization)
    if not _intelligence:
        raise HTTPException(status_code=503, detail="Intelligence engine not initialized")

    brief = await _intelligence.get_latest_brief()
    if not brief:
        raise HTTPException(status_code=404, detail="No brief available")

    # Find the signal
    target_signal = None
    for sig in brief.top_signals:
        if sig.signal_id == signal_id:
            target_signal = sig
            break

    if not target_signal:
        raise HTTPException(status_code=404, detail=f"Signal {signal_id} not found in current brief")

    # Build focused pump for this single signal
    pump_id = f"INTEL-SIG-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    change_str = f" ({target_signal.change_pct:+.1f}%)" if target_signal.change_pct is not None else ""

    pump_intent = (
        f"SIGNAL DEEP-DIVE REQUEST\n\n"
        f"Signal: {target_signal.title}{change_str}\n"
        f"Source: {target_signal.source.value}\n"
        f"Direction: {target_signal.direction.value}\n"
        f"Confidence: {target_signal.confidence:.0%}\n"
        f"Content: {target_signal.content[:500]}\n\n"
        f"DIRECTIVE: Deep-dive this signal. Assess implications for NARTIX operations, "
        f"identify related signals or trends, evaluate risk/reward, and recommend "
        f"specific actions or mandates."
    )

    pump_prompt = {
        "pump_id": pump_id,
        "source": "intelligence-engine",
        "intent": pump_intent,
        "context": {
            "origin": "signal_escalation",
            "signal_id": signal_id,
            "signal_source": target_signal.source.value,
        },
        "urgency": "high",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    # Write escalation
    pump_file = Path(config.data_dir) / "intelligence" / "escalations" / f"{pump_id}.json"
    pump_file.parent.mkdir(parents=True, exist_ok=True)
    pump_file.write_text(json.dumps(pump_prompt, indent=2, default=str))

    # Submit to brain if available
    if brain:
        try:
            pump = PumpPrompt(
                prompt_id=pump_id,
                source="intelligence-engine",
                intent=pump_intent,
                urgency="high",
            )
            await brain.receive_pump_prompt(pump)
        except Exception as e:
            logging.getLogger("ncl.api").warning("intelligence escalation failed: %s", e)

    from ..strike_point_orchestrator import notify_natrix

    async def _notify_signal():
        try:
            await notify_natrix(
                "Signal Escalated",
                f"{target_signal.title}\n→ STRIKE-POINT pump: {pump_id}",
            )
        except Exception as e:
            log.warning(f"Signal escalation notification failed: {e}")

    _sig_task = asyncio.create_task(_notify_signal())
    _sig_task.add_done_callback(
        lambda t: log.error(f"signal notify task died: {t.exception()!r}")
        if not t.cancelled() and t.exception() is not None
        else None
    )

    return {
        "status": "escalated",
        "pump_id": pump_id,
        "signal_id": signal_id,
        "signal_title": target_signal.title,
    }


@app.get("/intelligence/signals/top")
async def get_top_signals(limit: int = Query(default=10, ge=1, le=50)) -> dict:
    """Get top unacknowledged signals from the latest brief (for FirstStrike)."""
    if not _intelligence:
        raise HTTPException(status_code=503, detail="Intelligence engine not initialized")

    brief = await _intelligence.get_latest_brief()
    if not brief:
        return {"total": 0, "signals": []}

    top = sorted(brief.top_signals, key=lambda s: s.importance_score(), reverse=True)[:limit]
    return {
        "total": len(top),
        "brief_id": brief.brief_id,
        "brief_type": brief.brief_type,
        "signals": [
            {
                "signal_id": s.signal_id,
                "title": s.title,
                "content": s.content,
                "category": s.category,
                "source": s.source.value,
                "direction": s.direction.value,
                "importance": s.importance_score(),
                "value": s.value,
                "change_pct": s.change_pct,
                "volume": s.volume,
                "confidence": s.confidence,
                "tags": s.tags,
                "url": s.url,
                "metadata": s.metadata,
                "timestamp": s.timestamp.isoformat(),
            }
            for s in top
        ],
    }


@app.post("/intelligence/ack/{brief_id}")
async def acknowledge_brief(brief_id: str) -> dict:
    """Acknowledge an intelligence brief (marks it as read in FirstStrike)."""
    # Mark notification as acknowledged
    notif_dir = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL"))) / "notifications" / "intelligence"
    if notif_dir.exists():
        for nf in notif_dir.glob("intel-*.json"):
            try:
                data = json.loads(nf.read_text())
                if data.get("brief_id") == brief_id:
                    data["acknowledged"] = True
                    data["acknowledged_at"] = datetime.now(timezone.utc).isoformat()
                    nf.write_text(json.dumps(data, indent=2, default=str))
                    return {"status": "acknowledged", "brief_id": brief_id}
            except (json.JSONDecodeError, OSError):
                continue

    return {"status": "not_found", "brief_id": brief_id}


@app.get("/notifications/subscribe")
async def get_notification_subscribe_info():
    """
    Return the ntfy.sh subscription info.
    Open the subscribe URL on iPhone → instant push notifications, no account needed.
    """
    from ..strike_point_orchestrator import NTFY_TOPIC, NTFY_SERVER
    return {
        "provider": "ntfy.sh",
        "topic": NTFY_TOPIC,
        "subscribe_url": f"{NTFY_SERVER}/{NTFY_TOPIC}",
        "app_install_url": "https://apps.apple.com/app/ntfy/id1625396347",
        "instructions": f"Install ntfy app → open {NTFY_SERVER}/{NTFY_TOPIC} in Safari → tap Subscribe",
    }


@app.post("/notifications/test")
async def send_test_notification():
    """Fire a test push notification to verify iPhone delivery."""
    from ..strike_point_orchestrator import notify_natrix, NCL_BRAIN_URL
    now = datetime.now(timezone.utc).strftime("%H:%M UTC")
    success = await notify_natrix(
        "⚡ NCL Command Center Online",
        f"Push pipeline verified at {now}.\n\n"
        f"Your brain is scanning real-time signals across news, markets, "
        f"social, and prediction markets — and will push actionable "
        f"intelligence directly to this device.\n\n"
        f"📊 Open dashboard: {NCL_BRAIN_URL}/app",
        priority=0,
    )
    return {"delivered": success, "method": "ntfy.sh" if success else "file_fallback"}


@app.post("/intelligence/push-brief")
async def push_brief_to_phone(
    brief_type: str = Query(default="daily"),
    authorization: str = Header(default=""),
) -> dict:
    """
    Generate a fresh brief AND push it to iPhone via Pushover/FirstStrike.

    This is the endpoint the autonomous scheduler calls on its periodic loop.
    """
    _verify_strike_token(authorization)
    if not _intelligence:
        raise HTTPException(status_code=503, detail="Intelligence engine not initialized")

    try:
        brief = await _intelligence.generate_brief(brief_type=brief_type)

        # Push to phone
        from ..strike_point_orchestrator import notify_intelligence_brief
        pushed = await notify_intelligence_brief(brief.model_dump())

        return {
            "status": "generated_and_pushed",
            "brief_id": brief.brief_id,
            "total_signals": brief.total_signals_processed,
            "push_delivered": pushed,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ===========================================================================
# Reddit Intelligence — on-demand retail sentiment scanning
# ===========================================================================


@app.get("/intelligence/reddit")
async def reddit_intel(
    subreddit: str = Query(default="wallstreetbets", description="Subreddit to scan"),
    limit: int = Query(default=15, ge=1, le=50, description="Number of posts"),
) -> dict:
    """
    On-demand Reddit scan for retail sentiment intelligence.
    Returns top posts with sentiment, ticker mentions, and engagement metrics.
    """
    from ..intelligence.collectors import RedditCollector

    scanner = RedditCollector(subreddits=[subreddit])
    try:
        signals = await scanner._collect_listing(subreddit, "hot", limit=limit)
        tickers = await scanner.collect_ticker_mentions(subreddit, limit=limit)

        return {
            "subreddit": subreddit,
            "post_count": len(signals),
            "top_tickers": dict(list(tickers.items())[:10]),
            "posts": [
                {
                    "title": s.title,
                    "score": s.metadata.get("score", 0),
                    "comments": s.metadata.get("num_comments", 0),
                    "flair": s.metadata.get("flair", ""),
                    "sentiment": round(s.sentiment, 2),
                    "tickers": s.metadata.get("tickers", []),
                    "strength": s.metadata.get("strength", ""),
                    "confidence": round(s.confidence, 2),
                    "url": s.url,
                    "category": s.category,
                }
                for s in sorted(signals, key=lambda x: x.metadata.get("score", 0), reverse=True)
            ],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Reddit scan failed: {e}")
    finally:
        await scanner.close()


@app.get("/intelligence/reddit/tickers")
async def reddit_ticker_heat() -> dict:
    """
    Ticker heatmap across WSB and Superstonk.
    Shows which stocks retail is most focused on right now.
    """
    from ..intelligence.collectors import RedditCollector

    scanner = RedditCollector()
    try:
        wsb = await scanner.collect_ticker_mentions("wallstreetbets", limit=100)
        ss = await scanner.collect_ticker_mentions("Superstonk", limit=50)

        # Merge counts
        merged: dict[str, dict] = {}
        for ticker, count in wsb.items():
            merged[ticker] = {"wsb": count, "superstonk": 0, "total": count}
        for ticker, count in ss.items():
            if ticker in merged:
                merged[ticker]["superstonk"] = count
                merged[ticker]["total"] += count
            else:
                merged[ticker] = {"wsb": 0, "superstonk": count, "total": count}

        # Sort by total
        sorted_tickers = dict(
            sorted(merged.items(), key=lambda x: x[1]["total"], reverse=True)
        )

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "ticker_count": len(sorted_tickers),
            "tickers": dict(list(sorted_tickers.items())[:20]),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ticker scan failed: {e}")
    finally:
        await scanner.close()


# ===========================================================================
# Server-Sent Events — live push to browser/PWA (replaces ntfy for dashboard)
# ===========================================================================

_sse_clients: list[asyncio.Queue] = []


async def broadcast_event(event_type: str, data: dict) -> None:
    """Push an event to all connected SSE clients (browser dashboards)."""
    msg = json.dumps({"type": event_type, **data})
    dead = []
    for q in _sse_clients:
        try:
            q.put_nowait(msg)
        except asyncio.QueueFull:
            dead.append(q)
    for d in dead:
        _sse_clients.remove(d)


@app.get("/app/events")
async def sse_stream():
    """Server-Sent Events stream for real-time dashboard updates."""
    queue: asyncio.Queue = asyncio.Queue(maxsize=50)
    _sse_clients.append(queue)

    async def event_generator():
        try:
            # Send heartbeat every 30s to keep connection alive
            while True:
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"data: {msg}\n\n"
                except asyncio.TimeoutError:
                    yield f": heartbeat\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            if queue in _sse_clients:
                _sse_clients.remove(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


# ===========================================================================
# NCL Command Center PWA — unified dashboard for iPhone / iPad / Mac
# ===========================================================================


@app.get("/app")
async def command_center_pwa() -> HTMLResponse:
    """Serve the NCL Command Center dashboard."""
    html_path = Path(__file__).parent.parent.parent / "dashboard" / "command-center.html"
    if not html_path.exists():
        raise HTTPException(status_code=404, detail="Command Center not found")
    async with aiofiles.open(html_path, "r") as f:
        html = await f.read()
    return HTMLResponse(content=html)


@app.get("/app/manifest.json")
async def pwa_manifest() -> JSONResponse:
    """PWA web app manifest for Add-to-Home-Screen."""
    return JSONResponse(content={
        "name": "NCL Workstation",
        "short_name": "NCL",
        "description": "NATRIX Command & Intelligence Workstation",
        "start_url": "/app",
        "display": "standalone",
        "background_color": "#0a0a0f",
        "theme_color": "#0a0a0f",
        "icons": [
            {
                "src": "data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><rect fill='%230a0a0f' width='100' height='100' rx='20'/><text x='50' y='68' text-anchor='middle' font-size='50' fill='%2300ff88'>⚡</text></svg>",
                "sizes": "any",
                "type": "image/svg+xml",
            }
        ],
    })


@app.get("/app/sw.js")
async def pwa_service_worker() -> HTMLResponse:
    """Service worker for PWA — offline caching + notification support."""
    sw_code = """
const CACHE_NAME = 'ncl-command-v1';
const SHELL = ['/app', '/app/manifest.json'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE_NAME).then(c => c.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', e => {
  // Network-first for API calls, cache-first for shell
  if (e.request.url.includes('/app')) {
    e.respondWith(
      fetch(e.request).then(r => {
        const clone = r.clone();
        caches.open(CACHE_NAME).then(c => c.put(e.request, clone));
        return r;
      }).catch(() => caches.match(e.request))
    );
  } else {
    e.respondWith(fetch(e.request));
  }
});

self.addEventListener('notificationclick', e => {
  e.notification.close();
  e.waitUntil(clients.matchAll({type:'window'}).then(cls => {
    if (cls.length) { cls[0].focus(); return; }
    clients.openWindow('/app');
  }));
});
"""
    return HTMLResponse(content=sw_code, media_type="application/javascript")


# ===========================================================================
# Agent Swarm — Multi-LLM Task Execution
# ===========================================================================


@app.post("/swarm/tasks")
async def create_swarm_task(
    title: str = Query(...),
    objective: str = Query(...),
    priority: int = Query(default=5, ge=1, le=10),
    budget_cents: int = Query(default=5000),
    tags: str = Query(default=""),
    authorization: str = Header(default=""),
) -> dict:
    """Submit a task to the agent swarm for autonomous execution."""
    _verify_strike_token(authorization)
    if not brain or not brain.swarm:
        raise HTTPException(status_code=503, detail="Swarm not initialized")

    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    result = await brain.submit_swarm_task(
        title=title,
        objective=objective,
        priority=priority,
        budget_cents=budget_cents,
        tags=tag_list,
    )
    return result


@app.get("/swarm/tasks")
async def list_swarm_tasks(
    status: str = Query(default=""),
    limit: int = Query(default=50, le=200),
) -> dict:
    """List swarm tasks with optional status filter."""
    if not brain or not brain.swarm:
        raise HTTPException(status_code=503, detail="Swarm not initialized")

    from ..swarm.models import TaskStatus

    status_filter = None
    if status:
        try:
            status_filter = TaskStatus(status)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status '{status}'. Valid: {[s.value for s in TaskStatus]}",
            )

    tasks = brain.swarm.list_tasks(status_filter=status_filter, limit=limit)
    return {
        "count": len(tasks),
        "tasks": [
            {
                "task_id": t.task_id,
                "title": t.title,
                "status": t.status.value,
                "priority": t.priority,
                "budget_cents": t.budget_cents,
                "tags": t.tags,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "completed_at": t.completed_at.isoformat() if t.completed_at else None,
            }
            for t in tasks
        ],
    }


@app.get("/swarm/tasks/{task_id}")
async def get_swarm_task(task_id: str) -> dict:
    """Get details of a specific swarm task."""
    if not brain or not brain.swarm:
        raise HTTPException(status_code=503, detail="Swarm not initialized")

    task = brain.swarm.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")

    return {
        "task_id": task.task_id,
        "title": task.title,
        "objective": task.objective,
        "status": task.status.value,
        "priority": task.priority,
        "budget_cents": task.budget_cents,
        "assigned_agent": task.assigned_agent,
        "subtasks": task.subtasks,
        "results": task.results,
        "tags": task.tags,
        "metadata": task.metadata,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
    }


@app.post("/swarm/tasks/{task_id}/cancel")
async def cancel_swarm_task(
    task_id: str,
    authorization: str = Header(default=""),
) -> dict:
    """Cancel a running swarm task."""
    _verify_strike_token(authorization)
    if not brain or not brain.swarm:
        raise HTTPException(status_code=503, detail="Swarm not initialized")

    success = await brain.swarm.cancel_task(task_id)
    if not success:
        raise HTTPException(
            status_code=404,
            detail=f"Task '{task_id}' not found or already terminal",
        )

    return {"status": "cancelled", "task_id": task_id}


@app.get("/swarm/stats")
async def get_swarm_stats() -> dict:
    """Get aggregate swarm orchestrator statistics."""
    if not brain or not brain.swarm:
        raise HTTPException(status_code=503, detail="Swarm not initialized")

    return brain.swarm.get_stats()


@app.get("/swarm/agents")
async def list_swarm_agents() -> dict:
    """List available swarm agent types."""
    if not brain or not brain.swarm:
        raise HTTPException(status_code=503, detail="Swarm not initialized")

    from ..swarm.agents import list_agent_types, get_registry

    registry = get_registry()
    return {
        "agent_types": list_agent_types(),
        "agents": [
            {
                "type": agent_type,
                "class": cls.__name__,
                "doc": (cls.__doc__ or "").strip().split("\n")[0],
            }
            for agent_type, cls in registry.items()
        ],
    }


# ── API Versioning ─────────────────────────────────────────────────────────
# Mount current app under /v1 prefix while keeping root routes for backwards
# compatibility. Clients can migrate to /v1/... at their own pace.
#
# IMPORTANT: lifespan must be passed to versioned_app — FastAPI does NOT
# propagate lifespans into mounted sub-apps, so without this the inner `app`'s
# startup (which initializes the `brain` global) never runs and every request
# returns 503 Service Unavailable.
versioned_app = FastAPI(
    title=f"{config.service_name} (versioned)",
    version=config.service_version,
    description="NCL Brain API — versioned gateway",
    lifespan=lifespan,
)
versioned_app.mount("/v1", app)  # All routes available under /v1/...
versioned_app.mount("/", app)    # Backwards compat: root routes still work


def main() -> None:
    """Main entry point."""
    import uvicorn

    import signal
    import sys

    # Graceful shutdown handler — prevents stale sockets on Ctrl+C / SIGTERM
    def _shutdown(signum, frame):
        log_main = logging.getLogger("ncl.main")
        log_main.info(f"Received signal {signum} — shutting down gracefully")
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    uvicorn.run(
        versioned_app,
        host=config.host,
        port=config.port,
        log_level="info" if not config.debug else "debug",
    )


if __name__ == "__main__":
    main()
