"""FastAPI routes for NCL brain service."""

import asyncio
import html as html_mod
import ipaddress
import json
import logging
import logging.config
import os
import re
import secrets
import sys
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse


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
            # W8-A9: include request_id so JSON logs can be filtered by trace.
            "format": "%(asctime)s %(name)s %(levelname)s %(request_id)s %(message)s",
            "rename_fields": {
                "asctime": "ts",
                "levelname": "level",
                "name": "logger",
                "request_id": "req_id",
            },
        }
    except ImportError:
        _log_formatter = {
            # W8-A9: include request_id even on the fallback format.
            "format": "%(asctime)s [%(name)s] %(levelname)s [req=%(request_id)s]: %(message)s",
        }
else:
    _log_formatter = {
        # W8-A9: include request_id in the human-readable text format.
        "format": "%(asctime)s [%(name)s] %(levelname)s [req=%(request_id)s]: %(message)s",
    }

# W8-A9: import the RequestIdFilter class BEFORE dictConfig — passing the
# callable directly via `()` sidesteps the dotted-path resolver, which fails
# because runtime/__init__.py has a strict __getattr__ that does not expose
# submodules until they have been imported as attributes.
from .middleware.correlation import RequestIdFilter as _RequestIdFilter


logging.config.dictConfig(
    {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "ncl": _log_formatter,
        },
        # W8-A9: attach the RequestIdFilter to every handler so `%(request_id)s`
        # is always populated — including for background tasks where the
        # contextvar default `-` is used.
        "filters": {
            "request_id": {
                "()": _RequestIdFilter,
            },
        },
        "handlers": {
            "stderr": {
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stderr",
                "formatter": "ncl",
                "filters": ["request_id"],
                "level": _NCL_LOG_LEVEL,
            },
        },
        "root": {
            "handlers": ["stderr"],
            "level": _NCL_LOG_LEVEL,
        },
    }
)

# W8-A9: also attach the filter directly to the `ncl` logger tree so any
# child logger using its own handler still gets request_id injected.
try:
    logging.getLogger("ncl").addFilter(_RequestIdFilter())
except Exception:
    # Filter is best-effort — never block boot on it.
    pass
# Uvicorn will (re)configure its own `uvicorn.*` loggers with its own
# handlers + formatters when uvicorn.run() executes. Its loggers default to
# propagate=False, so they won't double-emit through our root handler.

import urllib.request

import aiofiles
from fastapi import Body, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field


# Rate limiting
try:
    from slowapi import Limiter, _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded
    from slowapi.util import get_remote_address

    _limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])
    _has_slowapi = True
except ImportError:
    _limiter = None
    _has_slowapi = False

# Calendar
from ..calendar.calendar_routes import calendar_router

# Sprint 4 — Council Runner v1
# W5-06 (2026-05-23): the council_runner/ directory was archived to
# archive/strike-point-pre-merge/council_runner/. The persistence layer
# (store + replay) was relocated into runtime/council_pack/; the v1
# Planner/Skeptic/Risk agents live in council_pack.legacy as a
# deprecated back-compat shim. /council-runner/* endpoints moved to
# runtime/api/routers/council_runner.py.
from ..config import flags
from ..council_pack import (
    CouncilRunStore,
    ReplayEngine,
)
from ..evaluation.runner import GoldenTaskRunner
from ..feedback.feedback_routes import router as feedback_router
from ..feedback.feedback_routes import set_feedback_recorder
from ..feedback.recorder import FeedbackRecorder
from ..governance.action_router import ActionRouter
from ..governance.emergency_stop import EmergencyStop
from ..governance.policy_kernel import PolicyKernel
from ..ncl_brain.brain import NCLBrain
from ..ncl_brain.models import (
    MandateStatus,
)
from ..portfolio.paper_routes import router as paper_router
from ..portfolio.paper_routes import set_paper_engine
from ..portfolio.polymarket_strategies import router as polymarket_strategies_router

# Portfolio
from ..portfolio.portfolio_routes import router as portfolio_router
from ..portfolio.portfolio_routes import set_portfolio_manager

# Sprint 3 — Review Queue
from ..review_queue.manager import ReviewQueueManager
from ..search.indexer import SearchIndexer
from ..telemetry.availability import (
    AvailabilityTracker,
    make_ntfy_alert_callback,
)
from ..telemetry.collector import TelemetryCollector

# Sprint 2 — Telemetry, Governance, Evaluation
from ..telemetry.schema import TelemetryConfig, TelemetryLevel
from .config import create_config_file, load_config, validate_config


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

# Journal
_journal_store = None  # JournalStore — lazy import
_reflection_engine = None  # ReflectionEngine — lazy import
_context_tips = None  # ContextAwareTips — lazy import

# Module-level logger — used throughout this file as `log`
log = logging.getLogger(__name__)

# W10B-12 — once-per-hour rate-limit for swallowed-exception warnings on hot paths.
_log_warned_at: dict[str, float] = {}


def _warn_once_per_hour(key: str, msg: str, *args) -> None:
    """Emit log.warning at most once per 3600s per ``key``.

    Used on hot paths where a swallowed exception (e.g. cost-record drift)
    would otherwise either be silent (`pass`) or spam logs on each request.
    """
    import time as _t

    now = _t.time()
    last = _log_warned_at.get(key, 0.0)
    if now - last >= 3600.0:
        _log_warned_at[key] = now
        log.warning(msg, *args)


# Strike point authentication token — load from config (.env) FIRST, then env var,
# then .strike_token file, then auto-gen + persist to .strike_token.
_TOKEN_FILE = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL"))) / ".strike_token"
STRIKE_TOKEN = config.strike_auth_token or os.getenv("STRIKE_AUTH_TOKEN", "")
if not STRIKE_TOKEN:
    # Try .strike_token file
    if _TOKEN_FILE.exists():
        try:
            STRIKE_TOKEN = _TOKEN_FILE.read_text().strip()
        except Exception:
            STRIKE_TOKEN = ""
if not STRIKE_TOKEN:
    # Auto-generate and persist to .strike_token so it survives restarts
    STRIKE_TOKEN = secrets.token_urlsafe(32)
    try:
        _TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        _TOKEN_FILE.write_text(STRIKE_TOKEN)
        _TOKEN_FILE.chmod(0o600)
    except Exception as _write_err:
        logging.getLogger("ncl.strike").warning(
            f"Could not persist token to {_TOKEN_FILE}: {_write_err}"
        )
    _masked = f"...{STRIKE_TOKEN[-4:]}"
    logging.getLogger("ncl.strike").warning(
        f"No STRIKE_AUTH_TOKEN set. Auto-generated token ending in {_masked} — "
        f"Set this in .env or check {_TOKEN_FILE}"
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
    )
    # Boot-time hardening: bound brain.init() at 30s so a hung subsystem
    # cannot block port 8800 bind indefinitely. The Brain is the trunk —
    # if it can't init in 30s we crash loud rather than silently hang.
    try:
        await asyncio.wait_for(brain.init(), timeout=30.0)
    except asyncio.TimeoutError:
        log.error("[lifespan] brain.init() exceeded 30s timeout — aborting startup")
        raise

    # Initialize search indexer; .load() is a potentially heavy read from
    # units.jsonl + events.ndjson + mandates.json. Defer the actual load
    # to a background task scheduled before yield so the HTTP listener
    # can bind 8800 immediately. The first /search call will await the
    # indexer's internal _load_lock if the deferred load hasn't completed.
    global search_index
    search_index = SearchIndexer(data_dir=config.data_dir)

    async def _deferred_search_index_load():
        try:
            await asyncio.sleep(30.0)
            log.info("[lifespan] deferred: search_index.load() starting")
            await asyncio.wait_for(search_index.load(), timeout=120.0)
            log.info("[lifespan] deferred: search_index.load() complete")
        except asyncio.TimeoutError:
            log.warning(
                "[lifespan] deferred search_index.load() exceeded 120s — "
                "queries will retry the load lazily"
            )
        except Exception:
            log.exception("[lifespan] deferred search_index.load() failed")

    asyncio.create_task(_deferred_search_index_load())

    # W10B-4 PARALLEL LIFESPAN INITS — independent subsystems run in parallel
    # after brain.init(). Per Wave 9 A3 R4, these inits have no cross-deps:
    #   _telemetry.init / _availability.init / _emergency_stop.init /
    #   _policy_kernel.init / _review_queue.init / _intelligence.initialize
    # Each preserves its original per-subsystem timeout via asyncio.wait_for.
    # Wiring that depends on multiple subsystems runs AFTER the gather.
    global _telemetry, _availability
    global _policy_kernel, _action_router, _emergency_stop
    global _review_queue
    global _intelligence

    _telemetry = TelemetryCollector(data_dir=config.data_dir, config=TelemetryConfig())
    _availability = AvailabilityTracker(data_dir=config.data_dir)
    _emergency_stop = EmergencyStop(data_dir=config.data_dir)
    _policy_kernel = PolicyKernel(data_dir=config.data_dir)
    _review_queue = ReviewQueueManager(data_dir=str(Path(config.data_dir) / "review_queue"))
    _intelligence = IntelligenceEngine(config=config)

    async def _bounded_init(name: str, coro, timeout: float):
        try:
            await asyncio.wait_for(coro, timeout=timeout)
            return (name, "ok")
        except asyncio.TimeoutError:
            log.warning(f"[lifespan] {name} exceeded {timeout}s — continuing")
            return (name, "timeout")
        except Exception as _exc:
            log.warning(f"[lifespan] {name} failed: {_exc}")
            return (name, f"error:{_exc}")

    _parallel_results = await asyncio.gather(
        _bounded_init("_telemetry.init", _telemetry.init(), 15.0),
        _bounded_init("_availability.init", _availability.init(), 15.0),
        _bounded_init("_emergency_stop.init", _emergency_stop.init(), 15.0),
        _bounded_init("_policy_kernel.init", _policy_kernel.init(), 15.0),
        _bounded_init("_review_queue.init", _review_queue.init(), 15.0),
        _bounded_init("_intelligence.initialize", _intelligence.initialize(), 20.0),
        return_exceptions=True,
    )
    log.info(f"[lifespan] parallel init results: {_parallel_results}")

    # Post-gather wiring (depends on multiple subsystems being initialized)
    _availability.on_alert(make_ntfy_alert_callback())
    log.info("[init] ntfy push callback registered for availability alerts")
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

    # Sprint 3 — Review Queue (initialized in parallel block above)

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
        # Initialize knowledge graph and wire into memory store
        try:
            from ..memory.knowledge_graph import KnowledgeGraph

            _kg = KnowledgeGraph(data_dir=brain.memory_store.data_dir.parent)
            brain.memory_store.set_knowledge_graph(_kg)
            log.info("Knowledge graph initialized and wired into memory store")
        except Exception as e:
            log.warning(f"Knowledge graph initialization failed (non-fatal): {e}")

    # Pipeline Hardening — Deployment Monitor
    from ..deployment.manager import DeploymentManager
    from ..deployment.monitor import ServiceMonitor

    _dm = DeploymentManager()
    _deployment_monitor = ServiceMonitor(
        data_dir=config.data_dir,
        services=_dm.config.services,
    )

    # Intelligence Engine — initialized in parallel block above

    # Bridge: connect intelligence engine to brain's MemoryStore
    # so intelligence signals get written for the predictor to consume
    if hasattr(brain, "memory_store") and brain.memory_store is not None:
        _intelligence.set_memory_store(brain.memory_store)

    # Journal Store + Reflection Engine
    global _journal_store, _reflection_engine, _context_tips
    try:
        from ..journal.reflection_engine import ContextAwareTips, ReflectionEngine
        from ..journal.store import JournalStore

        _journal_store = JournalStore(
            data_dir=brain.data_dir
            if hasattr(brain, "data_dir")
            else os.getenv("NCL_DATA", str(Path.home() / "NCL" / "data")),
            memory_store=brain.memory_store if brain else None,
            working_context=None,
        )

        # Inline Anthropic client for reflection LLM synthesis.
        # Mirrors the Haiku call pattern used by night_watch (scheduler.py).
        # Falls back to template-based reflection if no API key.
        class _AnthropicReflectionClient:
            def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514"):
                self.api_key = api_key
                self.model = model

            async def generate(self, prompt: str, system: str = "") -> str:
                import httpx

                async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
                    resp = await client.post(
                        "https://api.anthropic.com/v1/messages",
                        headers={
                            "x-api-key": self.api_key,
                            "anthropic-version": "2023-06-01",
                            "content-type": "application/json",
                        },
                        json={
                            "model": self.model,
                            "max_tokens": 1200,
                            "system": system
                            or "You are a journaling synthesis assistant. Return valid JSON only.",
                            "messages": [{"role": "user", "content": prompt}],
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    # Record cost (Haiku 3.5: $0.80 in / $4.00 out per Mtok)
                    try:
                        from ..cost_tracker import record_cost

                        usage = data.get("usage", {}) or {}
                        i_t = usage.get("input_tokens", 0)
                        o_t = usage.get("output_tokens", 0)
                        cost = (i_t * 0.80 + o_t * 4.00) / 1_000_000
                        if cost > 0:
                            await record_cost("anthropic", cost, "journal_reflection")
                    except Exception:
                        pass
                    return data["content"][0]["text"]

        _anth_key = os.environ.get("ANTHROPIC_API_KEY", "")
        _llm_client = _AnthropicReflectionClient(_anth_key) if _anth_key else None
        if _llm_client:
            log.info("[lifespan] ReflectionEngine wired with Anthropic Haiku LLM client")
        else:
            log.warning("[lifespan] No ANTHROPIC_API_KEY — reflections will use template fallback")

        _reflection_engine = ReflectionEngine(_journal_store, llm_client=_llm_client)
        _context_tips = ContextAwareTips(_journal_store)
        log.info("[lifespan] Journal subsystem initialised")
    except Exception as _exc:
        log.warning(f"[lifespan] Journal subsystem unavailable: {_exc}")

    # Autonomous Scheduler — makes NCL a true second brain
    global _autonomous
    _autonomous = AutonomousScheduler(brain=brain, config=config, intelligence_engine=_intelligence)
    _autonomous.council_trigger_threshold = config.council_trigger_threshold
    _autonomous.council_min_signals = config.council_min_signals
    if config.autonomous_enabled:
        try:
            await asyncio.wait_for(_autonomous.start(), timeout=20.0)
        except asyncio.TimeoutError:
            log.warning(
                "[lifespan] _autonomous.start() exceeded 20s — "
                "scheduler tasks may still be spawning in background"
            )
    else:
        import logging

        logging.getLogger("ncl.autonomous").info(
            "Autonomous scheduler DISABLED (set autonomous_enabled: true to enable)"
        )

    # Rotate old prediction files (keep 30 days, archive older)
    try:
        from runtime.awarebot.predictor import FuturePredictor

        rotated = FuturePredictor.rotate_prediction_files(
            data_dir=os.getenv("NCL_DATA_DIR", "data"),
            keep_days=30,
        )
        if any(rotated.values()):
            log.info(f"[lifespan] Prediction file rotation: {rotated}")
    except Exception as _exc:
        log.warning(f"[lifespan] Prediction rotation failed: {_exc}")

    # Portfolio manager — fail-open at 20s.
    # The IBKR adapter previously did a sequential 15s × N-attempt retry per
    # broker, stalling lifespan by ~10 minutes on a degraded TWS. Adapters
    # now connect in parallel (portfolio_manager.start) and IBKR has its own
    # circuit breaker + bounded retry. The 20s cap is a final safety net —
    # the background sync loop will reconnect failed adapters later.
    from runtime.portfolio.portfolio_manager import PortfolioManager

    _portfolio_mgr = PortfolioManager()
    try:
        await asyncio.wait_for(_portfolio_mgr.start(), timeout=20.0)
        log.info("Portfolio manager started")
    except asyncio.TimeoutError:
        log.warning(
            "[lifespan] _portfolio_mgr.start() exceeded 20s — "
            "broker sync will run in background; partial data only"
        )
    set_portfolio_manager(_portfolio_mgr)

    # Paper trading engine
    from runtime.portfolio.paper_trading import PaperTradingEngine

    _data_dir = os.getenv("NCL_DATA_DIR", "data")
    _paper_engine = PaperTradingEngine(data_dir=_data_dir)
    set_paper_engine(_paper_engine)
    log.info("Paper trading engine started (%d existing trades)", len(_paper_engine.trades))

    yield

    # Shutdown
    await _portfolio_mgr.stop()
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

app.include_router(portfolio_router)
app.include_router(paper_router)
app.include_router(polymarket_strategies_router)
app.include_router(calendar_router)
app.include_router(feedback_router)

# Extracted sub-routers (W4-12 onward) — /system/* lives in routers/system.py.
# Other prefixes follow in subsequent waves. See runtime/api/routers/__init__.py
# for the registry; routes.py is being incrementally drained into focused modules.
from .routers import register_routers  # noqa: E402


register_routers(app)

# Wire feedback recorder singleton (P1-11)
try:
    _fb_dir = Path(os.path.expanduser("~/dev/NCL/data"))
    set_feedback_recorder(FeedbackRecorder(_fb_dir))
    log.info("[FEEDBACK] recorder wired at ~/dev/NCL/data/feedback/")
except Exception as _fb_err:
    log.warning(f"[FEEDBACK] init failed: {_fb_err}")

# Rate limiting middleware
if _has_slowapi and _limiter:
    app.state.limiter = _limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
else:
    log.warning(
        "[AUTH] slowapi not available — per-route @_limiter decorators will be no-ops; "
        "falling back to homegrown _check_rate_limit only"
    )


def _maybe_limit(rule: str):
    """Apply slowapi @_limiter.limit(rule) if slowapi is wired, else no-op decorator.

    Defined here (early) so per-route decorators (`/pump`, `/chat`, etc.)
    can reference it at module-load time.
    """
    if _has_slowapi and _limiter:
        return _limiter.limit(rule)

    def _noop(fn):
        return fn

    return _noop


# CORS middleware — tight allow-list by default; honor ALLOWED_ORIGINS env override.
# Previous behavior allowed localhost:3000/8000/8800 + 127.0.0.1 variants by default,
# which is too permissive for production. Now defaults to a single dev origin.
_allowed_origins_env = os.getenv("ALLOWED_ORIGINS", os.getenv("CORS_ALLOWED_ORIGINS", ""))
if _allowed_origins_env:
    allowed_origins = [o.strip() for o in _allowed_origins_env.split(",") if o.strip()]
else:
    allowed_origins = ["http://localhost:3000"]
log.info(f"[AUTH] CORS allow-list: {allowed_origins}")
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
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
_RATE_LIMIT_MAX = 30  # requests per window


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

# W8-A9: correlation IDs — stamp every request with a request_id, accept
# inbound X-Request-Id, echo it back on the response. The contextvar this
# middleware sets is read by RequestIdFilter (installed above) so every
# log line emitted while handling the request is tagged with the id.
from .middleware.correlation import CorrelationMiddleware as _CorrelationMiddleware


app.add_middleware(_CorrelationMiddleware)

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
                        detail="URL resolves to a blocked private IP range.",
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


# Health check — bare liveness probe (unauthenticated, no service detail leaked).
# Detailed payload (mandates, councils, memory units, warnings) moved to
# /health/detailed which requires the Strike token. Existing service-monitors
# (matrix-config.json, MONITORED_SERVICES, smoke-test.sh, restart-all.command,
# reload-services.command) only check HTTP status<400 and remain compatible.
@app.get("/health")
async def health_check() -> dict:
    """Bare liveness probe — returns 200 OK if the process is up."""
    return {"status": "ok"}


@app.get("/health/detailed")
async def health_check_detailed(authorization: str = Header(default="")) -> dict:
    """Detailed health: uptime, mandate counts, council sessions, memory units, warnings."""
    _verify_strike_token(authorization)
    if not brain:
        raise HTTPException(status_code=503, detail="Service not initialized")
    return await brain.health_check()


# ── Service Health Proxy (server-side checks, avoids browser CORS) ──

# Pillar services retired 2026-05-23:
#   - AAC Monitor (8080), BRS Dashboard (8000): pillars retired
#   - NCC Relay (8787), NCC Master (8765): NCC repo removed from this machine
MONITORED_SERVICES = [
    {"name": "NCL Brain", "port": 8800, "path": "/health"},
    {"name": "One-Drop", "port": 8123, "path": "/health"},
    {"name": "Paperclip", "port": 3100, "path": "/health"},
    {"name": "Ollama", "port": 11434, "path": "/api/tags"},
]


@app.get("/services/status")
async def services_status(authorization: str = Header(default="")) -> dict:
    """Check all monitored services server-side and return status."""
    _verify_strike_token(authorization)
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
async def network_info(authorization: str = Header(default="")):
    """Return the server's LAN IP for iPhone shortcut configuration."""
    _verify_strike_token(authorization)
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
    token = authorization.removeprefix("Bearer ").strip()
    if not secrets.compare_digest(token, STRIKE_TOKEN):
        raise HTTPException(status_code=403, detail="Invalid strike token")


# Pump endpoints (/pump/*) moved to routers/pump.py (W5-05).
# _PUMP_QUALITY counters + _pump_count helper stay here at module scope
# so the router can reach them via the lazy ``from .. import routes as
# _routes`` pattern (and so any future internal caller can mutate the
# per-process telemetry without touching the router).
# In-process pump quality counters. Lives at module scope so the simple
# /pump/health monitor can read them without poking at brain internals.
_PUMP_QUALITY = {
    "submitted_total": 0,
    "submitted_today": 0,
    "rejected_total": 0,
    "rejected_today": 0,
    "last_submission_at": None,
    "last_submission_id": None,
    "_today_date": None,
}


def _pump_count(kind: str, pump_id: str | None = None) -> None:
    """Increment pump counters with daily-rollover semantics."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if _PUMP_QUALITY["_today_date"] != today:
        _PUMP_QUALITY["_today_date"] = today
        _PUMP_QUALITY["submitted_today"] = 0
        _PUMP_QUALITY["rejected_today"] = 0
    if kind == "submitted":
        _PUMP_QUALITY["submitted_total"] += 1
        _PUMP_QUALITY["submitted_today"] += 1
        _PUMP_QUALITY["last_submission_at"] = datetime.now(timezone.utc).isoformat()
        _PUMP_QUALITY["last_submission_id"] = pump_id
    elif kind == "rejected":
        _PUMP_QUALITY["rejected_total"] += 1
        _PUMP_QUALITY["rejected_today"] += 1


# Council endpoints — /council/* and /council/youtube/* moved to routers/council.py (W5-03).
# Only `/youtube/reports/recent` remains here (not a /council path).
# `/council-runner/*` endpoints moved to routers/council_runner.py (W5-06).


# /youtube/reports/recent moved to runtime/api/routers/intel.py (W5-04)


# /council/youtube/reports/{filename}, /council/youtube/run,
# /council/youtube/status/{id} — moved to routers/council.py (W5-03)


# ═══════════════════════════════════════════════════════════════════════════
# X OAUTH + LIKED-VIDEO ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════


@app.get("/x/oauth/status")
async def x_oauth_status(authorization: str = Header(default="")) -> dict:
    """Check X OAuth authentication status."""
    _verify_strike_token(authorization)
    from ..councils.xai.x_oauth import get_auth_status

    return get_auth_status()


@app.post("/x/oauth/authorize")
async def x_oauth_authorize(authorization: str = Header(default="")) -> dict:
    """Generate OAuth 2.0 authorization URL for X user context."""
    _verify_strike_token(authorization)
    from ..councils.xai.x_oauth import get_authorization_url

    return get_authorization_url()


# NOTE: No auth check — this is an OAuth callback URL that X redirects to.
# CSRF protection via state parameter.
@app.get("/x/oauth/callback")
async def x_oauth_callback(
    code: str = Query(...),
    state: str = Query(...),
) -> dict:
    """OAuth 2.0 callback — exchange authorization code for tokens."""
    from ..councils.xai.x_oauth import exchange_code

    result = await exchange_code(code, state)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.post("/x/oauth/refresh")
async def x_oauth_refresh(authorization: str = Header(default="")) -> dict:
    """Refresh the X OAuth access token."""
    _verify_strike_token(authorization)
    from ..councils.xai.x_oauth import refresh_access_token

    result = await refresh_access_token()
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.post("/x/liked-videos/scan")
async def x_liked_video_scan(
    authorization: str = Header(default=""),
) -> dict:
    """Trigger a liked-video scan — fetch, download, transcribe, analyze."""
    _verify_strike_token(authorization)
    from ..councils.xai.liked_scanner import run_liked_video_scan

    session_id = f"xliked-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"

    async def _run():
        try:
            reports = await run_liked_video_scan(session_id=session_id)
            log.info(f"[X-Liked] Scan complete: {len(reports)} reports")
        except Exception as e:
            log.exception(f"[X-Liked] Scan failed: {e}")

    asyncio.create_task(_run())
    return {
        "session_id": session_id,
        "status": "running",
        "message": "X liked-video scan started. Reports will appear in /x/liked-videos/reports.",
    }


@app.get("/x/liked-videos/reports")
async def list_x_liked_video_reports(
    limit: int = Query(default=50, ge=1, le=200),
    authorization: str = Header(default=""),
) -> dict:
    """List X liked-video reports."""
    _verify_strike_token(authorization)

    ncl_base = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
    reports_dir = ncl_base / "intelligence-scan" / "x-liked-videos"

    reports: list[dict] = []
    if reports_dir.exists():
        for rpt_path in sorted(
            reports_dir.glob("xliked-*.json"), key=lambda p: p.stat().st_mtime, reverse=True
        ):
            try:
                data = json.loads(rpt_path.read_text())
                videos = data.get("videos", [])
                first_video = videos[0] if videos else {}
                reports.append(
                    {
                        "filename": rpt_path.name,
                        "session_id": data.get("session_id", rpt_path.stem),
                        "title": first_video.get("title", data.get("title", rpt_path.stem)),
                        "channel": first_video.get("channel", "Unknown"),
                        "tweet_id": data.get("tweet_id", ""),
                        "tweet_text": data.get("tweet_text", "")[:200],
                        "video_url": first_video.get("url", ""),
                        "date": data.get("completed_at", ""),
                        "summary": data.get("summary", ""),
                        "insights_count": len(data.get("insights", [])),
                        "duration_hours": data.get("total_duration_hours", 0),
                        "status": data.get("status", "complete"),
                    }
                )
            except Exception as e:
                log.warning(f"Failed to read X liked-video report {rpt_path}: {e}")
            if len(reports) >= limit:
                break

    return {"reports": reports, "count": len(reports)}


@app.get("/x/liked-videos/reports/{filename}")
async def get_x_liked_video_report(
    filename: str,
    authorization: str = Header(default=""),
) -> dict:
    """Get a specific X liked-video report."""
    _verify_strike_token(authorization)

    ncl_base = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
    report_path = ncl_base / "intelligence-scan" / "x-liked-videos" / filename

    if not report_path.exists():
        raise HTTPException(status_code=404, detail=f"Report not found: {filename}")

    try:
        data = json.loads(report_path.read_text())
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read report: {e}")


# Mandate endpoints (/mandates/*) moved to routers/mandate.py (W5-05).
# /mandate/{id}/requeue (singular) was retired with the strike-point
# pipeline 2026-05-23; the FAILED → DRAFT escape impl lives at
# archive/strike-point-pre-merge/PILLAR_DISPATCH.md if it ever needs to
# come back.


# Memory endpoints
# /memory/query moved to runtime/api/routers/memory.py (W5-04)


# Feedback pipeline endpoints (/feedback POST, /feedback/synthesis,
# /feedback/scan-now) moved to routers/feedback.py (W5-05). The iOS
# feedback event stream (/feedback/event, /feedback/events, /feedback/
# stats) is owned by runtime/feedback/feedback_routes.py and registered
# separately via app.include_router(feedback_router).


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
# /prediction (POST) moved to runtime/api/routers/intel.py (W5-04)


# Strike Point Orchestrator endpoints — DELETED W10C-13 (2026-05-24).
# Three handlers (POST /orchestrator/dispatch/{mandate_id}, GET /orchestrator/status,
# POST /orchestrator/feedback/{pump_id}) were 410-gone stubs after the pillar dispatch
# pipeline was retired 2026-05-23 (see archive/strike-point-pre-merge/). Fully removed.
# Do not re-introduce — see CLAUDE.md DO NOT TOUCH rule #6.


# Root endpoint — minimal service shell, no version/description leak.
# Previously exposed config.service_name + service_version + docs URL to
# unauthenticated callers, which is a fingerprinting aid for attackers.
@app.get("/")
async def root() -> dict:
    """Root endpoint — minimal service marker."""
    return {"service": "ncl-brain"}


# ────────────────────────────────────────────────────────────────────────────
# DASHBOARD API ENDPOINTS
# ────────────────────────────────────────────────────────────────────────────


# ── SQLite units-index fast path (W5-07) ─────────────────────────────────
#
# Used by the /dashboard handler below to surface ``recent_units`` without
# full-scanning the 200MB units.jsonl on every iOS Dashboard poll. Falls
# back to the canonical search_units path on flag-off or ANY failure —
# flag-off behavior is bit-identical to before this retrofit.
async def _maybe_indexed_search(memory_store, **kwargs):
    """Drop-in replacement for ``memory_store.search_units(**kwargs)``."""
    if flags.units_index_sqlite():
        try:
            unit_ids = await memory_store._search_units_via_sqlite_index(**kwargs)
            if unit_ids:
                units_by_id = await memory_store._load_units_batch(set(unit_ids))
                return [units_by_id[uid] for uid in unit_ids if uid in units_by_id]
        except Exception as e:
            logging.getLogger("ncl.api").debug(
                "dashboard sqlite index search failed (%s) — falling back", e
            )
    return await memory_store.search_units(**kwargs)


@app.get("/dashboard/ui")
async def dashboard_ui(authorization: str = Header(default="")) -> HTMLResponse:
    """Serve the main NCL Pipeline Dashboard HTML."""
    _verify_strike_token(authorization)
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

    pipeline_status = {  # noqa: F841
        "pending_pumps": pending_count,
        "active_mandates": active_mandates,
        "completed_mandates": completed_mandates,
        "council_sessions": council_count,
    }

    # ── Services ───────────────────────────────────────────────────────────
    # Pillar services retired 2026-05-23:
    #   - AAC Monitor (8080), BRS Dashboard (8000): pillars retired
    #   - NCC Relay (8787), NCC Master (8765): NCC repo removed from this machine
    services = [
        {"name": "NCL Brain", "port": 8800, "status": "running"},
        {"name": "One-Drop", "port": 8123, "status": "unknown"},
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

    councils_data = {  # noqa: F841
        "total_sessions": council_count,
        "latest_session": latest_council,
    }

    # ── Memory Stats ───────────────────────────────────────────────────────
    memory_stats = {
        "total_units": len(brain.memory_store.memory_units)
        if hasattr(brain.memory_store, "memory_units")
        else 0,
        "recent_units": [],
    }

    # Try to get recent memory units
    try:
        recent_units = await _maybe_indexed_search(brain.memory_store, days_back=1)
        memory_stats["recent_units"] = [
            {
                "content": (u.content if hasattr(u, "content") else u.get("content", ""))[:200],
                "importance": u.importance if hasattr(u, "importance") else u.get("importance", 0),
                "created_at": (
                    u.created_at.isoformat()
                    if hasattr(u, "created_at") and u.created_at
                    else u.get("created_at", "")
                    if isinstance(u, dict)
                    else ""
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
            "created_at": m.created_at.isoformat()
            if hasattr(m, "created_at") and m.created_at
            else None,
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
        "pipeline_status": "online"
        if active_mandates > 0 or has_pumps
        else "degraded"
        if has_mandates
        else "offline",
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
        "mandates": [{**m, "id": m["mandate_id"]} for m in mandates_data],
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
# /councils/* endpoints — moved to routers/council.py (W5-03)
# ────────────────────────────────────────────────────────────────────────────


# /councils/reports, /councils/rag, /councils/knowledge-base/stats,
# /councils/vector-store/stats, /councils/vector-store/backfill,
# /councils/multi-agent — moved to routers/council.py (W5-03).

# ── Living Doctrine Engine (LDE) Endpoints ────────────────────────────────

# Global LDE engine instance + persistent results store
_lde_engine = None
_lde_results_file = Path(config.data_dir).expanduser() / "lde_results.jsonl"
_lde_results_lock = asyncio.Lock()  # Guards concurrent appends to lde_results.jsonl


def _sync_save_lde_result(session_id: str, result: dict) -> None:
    """Synchronous file-write helper for LDE results (run via asyncio.to_thread)."""
    import json as _json

    entry = {
        "session_id": session_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "result": result,
    }
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


_lde_init_lock: asyncio.Lock | None = None


def _get_lde_lock() -> asyncio.Lock:
    global _lde_init_lock
    if _lde_init_lock is None:
        _lde_init_lock = asyncio.Lock()
    return _lde_init_lock


async def _get_lde():
    """Lazy-initialize the LDE engine (thread-safe with async lock)."""
    global _lde_engine
    if _lde_engine is not None:
        return _lde_engine
    async with _get_lde_lock():
        # Double-check after acquiring lock
        if _lde_engine is None:
            from ..lde.engine import LivingDoctrineEngine

            _lde_engine = LivingDoctrineEngine()
            await _lde_engine.init()
    return _lde_engine


class LDEProcessRequest(BaseModel):
    """Request to process a URL through the Living Doctrine Engine."""

    url: str = Field(..., min_length=5, description="URL to process (YouTube, article, etc.)")
    source_type: str | None = Field(
        default=None, description="Override: youtube, article, video, audio"
    )


class LDESearchRequest(BaseModel):
    """Search the LDE sandbox for prior insights."""

    query: str = Field(..., min_length=1)
    top_k: int = Field(default=10, ge=1, le=100)


@app.post("/lde/process")
async def lde_process_url(
    request: Request,
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
    _check_rate_limit(request)
    if not brain:
        raise HTTPException(status_code=503, detail="Service not initialized")

    # SSRF prevention: validate URL scheme and block private IPs
    _validate_url(req.url)

    lde = await _get_lde()
    session_id = (
        f"lde-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{str(uuid.uuid4())[:8]}"
    )

    async def run_lde_background():
        try:
            result = await lde.process_url(req.url, source_type=req.source_type)
            async with _lde_results_lock:
                await _save_lde_result(session_id, result)

            await brain._log_event(
                "lde_pipeline_complete",
                f"LDE processed {req.url}: {result.get('stages', {}).get('extract', {}).get('insights_count', 0)} insights, "  # noqa: E501
                f"{result.get('total_elapsed_seconds', 0)}s",
                metadata={
                    "session_id": session_id,
                    "url": req.url,
                    "insights_count": result.get("stages", {})
                    .get("extract", {})
                    .get("insights_count", 0),
                    "market_bias": result.get("stages", {})
                    .get("analyze", {})
                    .get("market_bias_shift", "unknown"),
                    "doctrine_changes": result.get("stages", {})
                    .get("doctrine_update", {})
                    .get("changes_summary", ""),
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
    task.add_done_callback(
        lambda t: log.error(f"LDE task died: {t.exception()!r}")
        if not t.cancelled() and t.exception()
        else None
    )

    return {
        "session_id": session_id,
        "url": req.url,
        "source_type": req.source_type or "auto-detect",
        "status": "queued",
        "pipeline": ["ingest", "extract", "analyze", "doctrine_update"],
    }


@app.get("/lde/doctrine")
async def get_living_doctrine(authorization: str = Header(default="")):
    """Return the current Living Trading Doctrine."""
    _verify_strike_token(authorization)
    lde = await _get_lde()
    return lde.get_doctrine()


@app.get("/lde/stats")
async def lde_stats(authorization: str = Header(default="")):
    """Return LDE engine statistics."""
    _verify_strike_token(authorization)
    lde = await _get_lde()
    return lde.get_stats()


@app.get("/lde/doctrine/rules")
async def get_doctrine_rules(authorization: str = Header(default="")):
    """Return just the active rules from the doctrine."""
    _verify_strike_token(authorization)
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
async def get_doctrine_signals(authorization: str = Header(default="")):
    """Return active signals from the doctrine."""
    _verify_strike_token(authorization)
    lde = await _get_lde()
    doctrine = lde.get_doctrine()
    return {
        "total_signals": len(doctrine.get("active_signals", [])),
        "signals": doctrine.get("active_signals", []),
        "market_bias": doctrine.get("market_bias", "neutral"),
    }


@app.get("/lde/doctrine/trends")
async def get_doctrine_trends(authorization: str = Header(default="")):
    """Return monitored trends from the doctrine."""
    _verify_strike_token(authorization)
    lde = await _get_lde()
    doctrine = lde.get_doctrine()
    return {
        "total_trends": len(doctrine.get("monitored_trends", [])),
        "trends": doctrine.get("monitored_trends", []),
    }


class AddDoctrineRuleRequest(BaseModel):
    """Request to add a doctrine rule."""

    title: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    category: str = Field(
        ...,
        description="macro, company, sentiment, risk, opportunity, geopolitical, sector, tech, technical, regulatory, correlation",  # noqa: E501
    )
    strength: float = Field(default=5.0, ge=0.0, le=10.0)
    tickers: list[str] = Field(default_factory=list)
    action: str = Field(default="")


@app.post("/lde/doctrine/rules")
async def add_doctrine_rule(req: AddDoctrineRuleRequest, authorization: str = Header(default="")):
    """Add a new rule to the Living Doctrine."""
    _verify_strike_token(authorization)
    lde = await _get_lde()

    from ..lde.models import DoctrineRule, InsightCategory

    rule = DoctrineRule(
        title=req.title,
        description=req.description,
        category=InsightCategory(req.category),
        strength=req.strength,
        tickers=req.tickers,
        action=req.action,
    )
    lde.sandbox.doctrine.core_rules.append(rule)
    lde.sandbox._save_doctrine(lde.sandbox.doctrine)

    return {
        "status": "added",
        "rule_id": rule.rule_id,
        "title": rule.title,
        "total_rules": len(lde.sandbox.doctrine.core_rules),
    }


@app.post("/lde/doctrine/seed")
async def seed_doctrine(authorization: str = Header(default="")):
    """
    Seed the Living Doctrine with foundational rules for the NATRIX ecosystem.
    Only seeds if the doctrine is empty (0 rules).
    """
    _verify_strike_token(authorization)
    lde = await _get_lde()

    if len(lde.sandbox.doctrine.core_rules) > 0:
        return {
            "status": "already_seeded",
            "existing_rules": len(lde.sandbox.doctrine.core_rules),
        }

    from ..lde.models import DoctrineRule, DoctrineSignal, InsightCategory, TrendMonitor

    seed_rules = [
        DoctrineRule(
            title="Macro Regime Awareness",
            description="Monitor Federal Reserve policy signals, Treasury yields, and inflation data. Rate decisions and forward guidance shift risk appetite across all asset classes. Track 10Y/2Y spread for recession signals.",  # noqa: E501
            category=InsightCategory.MACRO,
            strength=8.0,
            tickers=["TLT", "SPY", "QQQ"],
            action="Adjust position sizing based on rate environment. Risk-off when yield curve inverts.",  # noqa: E501
        ),
        DoctrineRule(
            title="Geopolitical Risk Premium",
            description="Track geopolitical flashpoints (trade wars, military conflicts, sanctions) that create supply chain disruption and energy price shocks. Middle East tensions directly impact oil and shipping costs.",  # noqa: E501
            category=InsightCategory.GEOPOLITICAL,
            strength=7.0,
            tickers=["USO", "XLE", "GLD"],
            action="Increase gold and energy exposure during geopolitical escalation. Reduce tech on supply chain risks.",  # noqa: E501
        ),
        DoctrineRule(
            title="Sentiment Divergence Alpha",
            description="When retail sentiment (Reddit, X) diverges significantly from institutional positioning (13F, dark pool data), mean reversion creates trading opportunities. Extreme fear = buy signal, extreme greed = reduce exposure.",  # noqa: E501
            category=InsightCategory.SENTIMENT,
            strength=7.5,
            action="Track sentiment indicators. Enter contrarian positions when divergence exceeds 2 standard deviations.",  # noqa: E501
        ),
        DoctrineRule(
            title="AI Infrastructure Secular Trend",
            description="AI/ML infrastructure buildout is a multi-year capex cycle. Track hyperscaler spending, chip demand, data center construction, and energy requirements. Companies enabling AI infrastructure have structural tailwinds.",  # noqa: E501
            category=InsightCategory.TECH,
            strength=8.5,
            tickers=["NVDA", "AVGO", "MSFT", "GOOGL"],
            action="Maintain long-term core position in AI infrastructure leaders. Add on pullbacks of >15%.",  # noqa: E501
        ),
        DoctrineRule(
            title="Crypto Correlation Regime",
            description="Monitor Bitcoin correlation with risk assets. In risk-on regimes, BTC trades as a high-beta tech proxy. In liquidity crises, it correlates with equities. Track BTC dominance for altcoin rotation signals.",  # noqa: E501
            category=InsightCategory.CORRELATION,
            strength=6.5,
            tickers=["BTC", "ETH"],
            action="Size crypto exposure relative to overall portfolio risk. Reduce when BTC/SPX correlation exceeds 0.7.",  # noqa: E501
        ),
        DoctrineRule(
            title="Earnings Revision Momentum",
            description="Companies with positive earnings revision trends (analysts raising estimates) outperform. Track earnings surprise patterns and forward guidance changes for sector rotation signals.",  # noqa: E501
            category=InsightCategory.COMPANY,
            strength=6.0,
            action="Overweight sectors with positive revision breadth. Avoid stocks with 3+ consecutive estimate cuts.",  # noqa: E501
        ),
        DoctrineRule(
            title="Regulatory Disruption Watch",
            description="Monitor regulatory actions (antitrust, data privacy, financial regulation) that can rapidly repruce sector valuations. Track legislative calendars and enforcement actions.",  # noqa: E501
            category=InsightCategory.REGULATORY,
            strength=5.5,
            tickers=["META", "GOOGL", "AMZN"],
            action="Reduce position sizing in companies facing active regulatory proceedings. Hedge with sector puts.",  # noqa: E501
        ),
        DoctrineRule(
            title="Sector Rotation via Relative Strength",
            description="Track sector ETF relative strength vs SPY on 20/50/200 day moving averages. Leading sectors in rate-cutting cycles: growth, tech, small caps. Leading in tightening: value, energy, utilities.",  # noqa: E501
            category=InsightCategory.SECTOR,
            strength=6.5,
            tickers=["XLK", "XLF", "XLE", "XLU", "XLV"],
            action="Rotate into sectors showing rising relative strength. Exit sectors breaking below 200-day RS line.",  # noqa: E501
        ),
    ]

    seed_signals = [
        DoctrineSignal(
            name="Treasury Yield Curve",
            description="Monitor 10Y-2Y spread for recession/expansion signals",
            category=InsightCategory.MACRO,
            direction="neutral",
            strength=7.0,
            tickers=["TLT", "SHY"],
        ),
        DoctrineSignal(
            name="VIX Regime",
            description="Track VIX levels and term structure for volatility regime changes",
            category=InsightCategory.TECHNICAL,
            direction="neutral",
            strength=6.0,
            tickers=["VIX", "UVXY"],
        ),
        DoctrineSignal(
            name="USD Strength Index",
            description="Dollar strength impacts emerging markets, commodities, and multinational earnings",  # noqa: E501
            category=InsightCategory.MACRO,
            direction="neutral",
            strength=5.5,
            tickers=["UUP", "DXY"],
        ),
    ]

    seed_trends = [
        TrendMonitor(
            name="AI Infrastructure Buildout",
            description="Multi-year capex cycle in data centers, chips, and energy for AI workloads",  # noqa: E501
            category=InsightCategory.TECH,
            direction="accelerating",
            confidence=8.0,
            tickers=["NVDA", "AVGO", "MSFT"],
            sectors=["semiconductors", "cloud", "data-centers"],
            data_points=50,
        ),
        TrendMonitor(
            name="De-globalization Supply Chain Shift",
            description="Nearshoring and friend-shoring trends creating new winners in manufacturing and logistics",  # noqa: E501
            category=InsightCategory.GEOPOLITICAL,
            direction="emerging",
            confidence=6.5,
            sectors=["industrials", "logistics", "manufacturing"],
            data_points=15,
        ),
    ]

    lde.sandbox.doctrine.core_rules.extend(seed_rules)
    lde.sandbox.doctrine.active_signals.extend(seed_signals)
    lde.sandbox.doctrine.monitored_trends.extend(seed_trends)
    lde.sandbox._save_doctrine(lde.sandbox.doctrine)

    return {
        "status": "seeded",
        "rules_added": len(seed_rules),
        "signals_added": len(seed_signals),
        "trends_added": len(seed_trends),
        "total_rules": len(lde.sandbox.doctrine.core_rules),
        "total_signals": len(lde.sandbox.doctrine.active_signals),
        "total_trends": len(lde.sandbox.doctrine.monitored_trends),
    }


@app.post("/lde/search")
async def lde_search(req: LDESearchRequest, authorization: str = Header(default="")):
    """Search the LDE sandbox for prior insights."""
    _verify_strike_token(authorization)
    lde = await _get_lde()
    results = await lde.sandbox.search_insights(req.query, top_k=req.top_k)
    return {
        "query": req.query,
        "total": len(results),
        "results": results,
    }


@app.get("/lde/dashboard")
async def lde_dashboard_page(authorization: str = Header(default="")):
    """Serve the LDE dashboard HTML."""
    _verify_strike_token(authorization)
    from fastapi.responses import FileResponse

    dashboard_path = Path(__file__).parent.parent.parent / "dashboard" / "lde.html"
    if not dashboard_path.exists():
        raise HTTPException(status_code=404, detail="LDE dashboard not found")
    return FileResponse(dashboard_path, media_type="text/html")


@app.get("/lde/history")
async def lde_history(
    limit: int = Query(default=20, ge=1, le=100), authorization: str = Header(default="")
):
    """Return recent LDE processing history."""
    _verify_strike_token(authorization)
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
    authorization: str = Header(default=""),
):
    """
    Return all iOS Shortcut definitions with auth tokens baked in.

    Call from your Mac to get the JSON, then import into Shortcuts app.
    Optionally pass ?host=your-tailscale-ip to override localhost.
    """
    _verify_strike_token(authorization)
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
async def test_shortcut(shortcut_id: str, authorization: str = Header(default="")):
    """Test a shortcut endpoint by simulating what the iOS Shortcut would call."""
    _verify_strike_token(authorization)
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
            example = (
                _json.dumps(body)
                .replace("{{intent}}", "Test pump from shortcuts")
                .replace("{{urgency}}", "normal")
                .replace("{{council_type}}", "both")
                .replace("{{query}}", "test search")
                .replace("{{UUID}}", "shortcut-test-001")
            )
            parts.append(f"-d '{example}'")
    parts.append(shortcut["endpoint"])
    return " \\\n  ".join(parts)


@app.get("/shortcuts/setup", response_class=HTMLResponse)
async def shortcuts_setup_page(
    host: str = Query(default=None, description="Override NCL host IP"),
    authorization: str = Header(default=""),
):
    _verify_strike_token(authorization)
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
        auth = html_mod.escape(
            f"Authorization: {_masked_auth}" if _masked_auth else "None required"
        )
        # Escape all user-controllable fields for XSS prevention
        s_name = html_mod.escape(s.get("name", ""))
        s_color = html_mod.escape(s.get("color", "#888"))
        s_icon = html_mod.escape(s.get("icon", "⚡"))
        s_siri = html_mod.escape(s.get("siri_phrase", ""))
        s_desc = html_mod.escape(s.get("description", ""))
        s_trigger = html_mod.escape(s.get("trigger_phrase", ""))

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

    # Strike-point orchestrator archived 2026-05-23 — pipeline merged into Brain auto_flow. See CLAUDE.md DO NOT TOUCH rule #6.  # noqa: E501
    # ntfy constants used to live in strike_point_orchestrator.py; inlined here from the same env-var contract.  # noqa: E501
    NTFY_TOPIC = os.getenv("NTFY_TOPIC", "ncl-natrix-intel-7x9k")  # noqa: N806
    NTFY_SERVER = os.getenv("NTFY_SERVER", "https://ntfy.sh")  # noqa: N806
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
    """  # noqa: E501

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
    days_back: int | None = Field(
        default=None, ge=1, description="Only return results from past N days"
    )


class EventSearchRequest(BaseModel):
    """Structured event search request."""

    event_type: str | None = None
    correlation_id: str | None = None
    pump_id: str | None = None
    mandate_id: str | None = None
    days_back: int | None = Field(default=None, ge=1)
    limit: int = Field(default=50, ge=1, le=500)


@app.post("/search")
async def full_text_search(req: SearchRequest, authorization: str = Header(default="")):
    """Full-text search across events, memory, and mandates."""
    _verify_strike_token(authorization)
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
async def search_events(req: EventSearchRequest, authorization: str = Header(default="")):
    """Structured search across events by type, correlation, pump, or mandate."""
    _verify_strike_token(authorization)
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
async def get_causality_chain(correlation_id: str, authorization: str = Header(default="")):
    """Retrieve the full causality chain for a correlation ID (chronological)."""
    _verify_strike_token(authorization)
    if not search_index:
        raise HTTPException(status_code=503, detail="Search index not initialized")

    results = await search_index.get_chain(correlation_id)
    return {
        "correlation_id": correlation_id,
        "chain_length": len(results),
        "events": [r.to_dict() for r in results],
    }


@app.get("/search/stats")
async def search_stats(authorization: str = Header(default="")):
    """Return search index statistics."""
    _verify_strike_token(authorization)
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
async def get_telemetry_config(authorization: str = Header(default="")) -> dict:
    """Get current telemetry configuration."""
    _verify_strike_token(authorization)
    if not _telemetry:
        raise HTTPException(status_code=503, detail="Telemetry not initialized")
    return _telemetry.config.model_dump()


@app.post("/telemetry/config")
async def update_telemetry_config(
    level: str = Query(default="standard"), authorization: str = Header(default="")
) -> dict:
    """Update telemetry level (off/minimal/standard/verbose)."""
    _verify_strike_token(authorization)
    if not _telemetry:
        raise HTTPException(status_code=503, detail="Telemetry not initialized")
    try:
        _telemetry.config.level = TelemetryLevel(level)
    except ValueError:
        raise HTTPException(
            status_code=400, detail=f"Invalid level: {level}. Use: off, minimal, standard, verbose"
        )
    return {"status": "updated", "level": _telemetry.config.level.value}


@app.get("/telemetry/stats")
async def get_telemetry_stats(
    hours_back: int = Query(default=24, ge=1, le=8760), authorization: str = Header(default="")
) -> dict:
    """Get aggregated telemetry stats per workflow."""
    _verify_strike_token(authorization)
    if not _telemetry:
        raise HTTPException(status_code=503, detail="Telemetry not initialized")
    stats = _telemetry.get_all_workflow_stats(hours_back=hours_back)
    return {"workflows": [s.model_dump() for s in stats], "hours_back": hours_back}


@app.get("/telemetry/recent")
async def get_recent_telemetry(
    n: int = Query(default=100, le=1000), authorization: str = Header(default="")
) -> dict:
    """Get recent telemetry records."""
    _verify_strike_token(authorization)
    if not _telemetry:
        raise HTTPException(status_code=503, detail="Telemetry not initialized")
    records = _telemetry.get_recent(n=n)
    return {"records": [r.model_dump() for r in records], "count": len(records)}


@app.post("/telemetry/flush")
async def flush_telemetry(authorization: str = Header(default="")) -> dict:
    """Force-flush telemetry buffer to disk."""
    _verify_strike_token(authorization)
    if not _telemetry:
        raise HTTPException(status_code=503, detail="Telemetry not initialized")
    await _telemetry.flush()
    return {"status": "flushed"}


# ===========================================================================
# Sprint 2 — Availability Tracker Endpoints
# ===========================================================================


@app.get("/availability/dashboard")
async def availability_dashboard(authorization: str = Header(default="")) -> dict:
    """Dashboard-ready availability summary for all workflows."""
    _verify_strike_token(authorization)
    if not _availability:
        raise HTTPException(status_code=503, detail="Availability tracker not initialized")
    return _availability.get_dashboard_summary()


@app.get("/availability/workflow/{workflow}")
async def get_workflow_availability(workflow: str, authorization: str = Header(default="")) -> dict:
    """Get availability health for a specific workflow."""
    _verify_strike_token(authorization)
    if not _availability:
        raise HTTPException(status_code=503, detail="Availability tracker not initialized")
    health = _availability.get_workflow_health(workflow)
    return health.model_dump()


@app.get("/availability/alerts")
async def get_availability_alerts(
    acknowledged: bool = Query(default=None), authorization: str = Header(default="")
) -> dict:
    """Get availability alerts."""
    _verify_strike_token(authorization)
    if not _availability:
        raise HTTPException(status_code=503, detail="Availability tracker not initialized")
    alerts = _availability.get_alerts(acknowledged=acknowledged)
    return {"alerts": [a.model_dump() for a in alerts], "count": len(alerts)}


@app.post("/availability/alerts/{alert_id}/acknowledge")
async def acknowledge_availability_alert(
    alert_id: str, authorization: str = Header(default="")
) -> dict:
    """Acknowledge an availability alert."""
    _verify_strike_token(authorization)
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
        name=name,
        source_agent=source_agent,
        description=description,
        pump_id=pump_id,
        mandate_id=mandate_id,
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


@app.get("/governance/status")
async def get_governance_status(authorization: str = Header(default="")) -> dict:
    """Composite governance status — emergency stop, pending actions, policy rules."""
    _verify_strike_token(authorization)
    result: dict = {"status": "active"}
    # Emergency stop state
    if _emergency_stop:
        try:
            e_stats = await _emergency_stop.get_stats()
            halted = e_stats.get("halted", False) or e_stats.get("active", False)
            result["emergency_halt"] = halted
            if halted:
                result["status"] = "halted"
        except Exception:
            result["emergency_halt"] = False
    else:
        result["emergency_halt"] = False
    # Pending actions count
    if _action_router:
        try:
            pending = _action_router.get_pending()
            result["pending_actions"] = len(pending) if pending else 0
        except Exception:
            result["pending_actions"] = 0
    else:
        result["pending_actions"] = 0
    # Policy rules count
    if _policy_kernel:
        try:
            rules = _policy_kernel.get_rules()
            result["policy_rules"] = len(rules) if rules else 0
        except Exception:
            result["policy_rules"] = 0
    else:
        result["policy_rules"] = 0
    return result


@app.get("/governance/emergency-stop")
async def get_emergency_stop_status(authorization: str = Header(default="")) -> dict:
    """Get current emergency stop status."""
    _verify_strike_token(authorization)
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
    request: Request,
    authorization: str = Header(default=""),
) -> dict:
    """Run the full Golden Task Suite (50 deterministic tasks)."""
    _verify_strike_token(authorization)
    _check_rate_limit(request)
    if not _eval_runner:
        raise HTTPException(status_code=503, detail="EvalRunner not initialized")

    async def _run():
        try:
            result = await _eval_runner.run_suite()
            _eval_runner.save_results(result)
        except Exception as e:
            log.exception(f"[/evaluation/run] Golden Task Suite failed: {e}")

    task = asyncio.create_task(_run())
    task.add_done_callback(
        lambda t: log.error(f"Eval task died: {t.exception()!r}")
        if not t.cancelled() and t.exception()
        else None
    )
    return {
        "status": "started",
        "message": "Golden Task Suite running in background. Check /evaluation/results for output.",
    }


@app.get("/evaluation/results")
async def get_evaluation_results(authorization: str = Header(default="")) -> dict:
    """Get the most recent Golden Task Suite results."""
    _verify_strike_token(authorization)
    if not _eval_runner:
        raise HTTPException(status_code=503, detail="EvalRunner not initialized")
    result = _eval_runner.load_previous_results()
    if not result:
        return {
            "status": "no_results",
            "message": "No evaluation results found. Run POST /evaluation/run first.",
        }
    return result.model_dump()


@app.get("/evaluation/summary")
async def get_evaluation_summary(authorization: str = Header(default="")) -> dict:
    """Quick summary of last evaluation run."""
    _verify_strike_token(authorization)
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
    authorization: str = Header(default=""),
) -> dict:
    """Get all review queue items with optional filters."""
    _verify_strike_token(authorization)
    if not _review_queue:
        raise HTTPException(status_code=503, detail="ReviewQueue not initialized")
    items = _review_queue.get_items(
        type_filter=type_filter,
        urgency_filter=urgency_filter,
        tag_filter=tag_filter,
        archived=archived,
    )
    return {"items": [i.model_dump() for i in items], "count": len(items)}


@app.get("/review-queue/items/{item_id}")
async def get_review_queue_item(item_id: str, authorization: str = Header(default="")) -> dict:
    """Get a single review queue item by ID."""
    _verify_strike_token(authorization)
    if not _review_queue:
        raise HTTPException(status_code=503, detail="ReviewQueue not initialized")
    item = _review_queue.get_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail=f"Item {item_id} not found")
    return item.model_dump()


@app.post("/review-queue/refresh")
async def refresh_review_queue(authorization: str = Header(default="")) -> dict:
    """Refresh the review queue — pull latest items, deduplicate, regenerate suggestions."""
    _verify_strike_token(authorization)
    if not _review_queue:
        raise HTTPException(status_code=503, detail="ReviewQueue not initialized")
    items = await _review_queue.refresh()
    return {"items": [i.model_dump() for i in items], "count": len(items)}


@app.post("/review-queue/ingest/pump")
async def ingest_pump_to_queue(pump_data: dict, authorization: str = Header(default="")) -> dict:
    """Ingest a pending pump prompt into the review queue."""
    _verify_strike_token(authorization)
    if not _review_queue:
        raise HTTPException(status_code=503, detail="ReviewQueue not initialized")
    item = await _review_queue.ingest_pump(pump_data)
    return {"status": "ingested", "item": item.model_dump()}


@app.post("/review-queue/ingest/action")
async def ingest_action_to_queue(
    action_data: dict, authorization: str = Header(default="")
) -> dict:
    """Ingest a pending governance action into the review queue."""
    _verify_strike_token(authorization)
    if not _review_queue:
        raise HTTPException(status_code=503, detail="ReviewQueue not initialized")
    item = await _review_queue.ingest_action(action_data)
    return {"status": "ingested", "item": item.model_dump()}


@app.post("/review-queue/ingest/council")
async def ingest_council_to_queue(
    session_data: dict, authorization: str = Header(default="")
) -> dict:
    """Ingest a council session into the review queue."""
    _verify_strike_token(authorization)
    if not _review_queue:
        raise HTTPException(status_code=503, detail="ReviewQueue not initialized")
    item = await _review_queue.ingest_council(session_data)
    return {"status": "ingested", "item": item.model_dump()}


@app.post("/review-queue/tag")
async def batch_tag_items(
    item_ids: list[str], tags: list[str], authorization: str = Header(default="")
) -> dict:
    """Tag multiple items in the review queue."""
    _verify_strike_token(authorization)
    if not _review_queue:
        raise HTTPException(status_code=503, detail="ReviewQueue not initialized")
    items = await _review_queue.batch_tag(item_ids, tags)
    return {"status": "tagged", "items": [i.model_dump() for i in items], "count": len(items)}


@app.post("/review-queue/link")
async def batch_link_items(item_ids: list[str], authorization: str = Header(default="")) -> dict:
    """Link/associate multiple review queue items together."""
    _verify_strike_token(authorization)
    if not _review_queue:
        raise HTTPException(status_code=503, detail="ReviewQueue not initialized")
    items = await _review_queue.batch_link(item_ids)
    return {"status": "linked", "items": [i.model_dump() for i in items], "count": len(items)}


@app.post("/review-queue/archive")
async def batch_archive_items(item_ids: list[str], authorization: str = Header(default="")) -> dict:
    """Archive multiple items from the review queue."""
    _verify_strike_token(authorization)
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
async def get_review_queue_stats(authorization: str = Header(default="")) -> dict:
    """Get review queue statistics."""
    _verify_strike_token(authorization)
    if not _review_queue:
        raise HTTPException(status_code=503, detail="ReviewQueue not initialized")
    return _review_queue.get_stats()


@app.get("/review-queue/dashboard")
async def review_queue_dashboard(authorization: str = Header(default="")) -> HTMLResponse:
    """Serve the Review Queue UI dashboard.

    W6-E (2026-05-24): ``review-queue.html`` used to ship a hardcoded
    placeholder ``'Bearer nartix-token'`` Authorization header. That was
    a stub (the real STRIKE_AUTH_TOKEN would have rejected it), but it
    still teaches the dashboard wrong, and review-queue actions silently
    no-op against an authed Brain. Same injection treatment as /app.
    """
    _verify_strike_token(authorization)
    token = authorization.replace("Bearer ", "").strip()
    dashboard_path = Path(__file__).parent.parent.parent / "dashboard" / "review-queue.html"
    if not dashboard_path.exists():
        raise HTTPException(status_code=404, detail="Review Queue dashboard not found")
    async with aiofiles.open(dashboard_path, "r") as f:
        html = await f.read()
    safe_token = token.replace("\\", "\\\\").replace("'", "\\'")
    html = html.replace("__AUTH_TOKEN__", safe_token)
    return HTMLResponse(content=html)


# ===========================================================================
# Sprint 4 — Council Runner v1 Endpoints
# ===========================================================================
# Extracted to ``runtime/api/routers/council_runner.py`` in W5-06 (2026-05-23).
# Globals (``_council_store``, ``_replay_engine``) and the
# ``CouncilRunRecord`` / ``ReplayConfig`` / ``run_parallel_council``
# imports above still live in this module — the router accesses them
# via ``from .. import routes as _routes`` inside each handler.

# (legacy handlers removed — they live in
# ``runtime/api/routers/council_runner.py`` now)

# ===========================================================================
# Pipeline Hardening — UNI Research Cortex Endpoints
# ===========================================================================


@app.post("/uni/research")
async def run_research(
    request: Request,
    query: str,
    depth: str = Query(default="standard"),
    priority: int = Query(default=5, ge=1, le=10),
    authorization: str = Header(default=""),
) -> dict:
    """Run a deep research task via the UNI Research Cortex."""
    _verify_strike_token(authorization)
    _check_rate_limit(request)
    if not _research_cortex:
        raise HTTPException(status_code=503, detail="ResearchCortex not initialized")
    from ..uni.models import ResearchDepth

    try:
        rd = ResearchDepth(depth)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid depth: {depth}. Use: quick, standard, deep, exhaustive",
        )

    task_id = str(uuid.uuid4())

    async def _run():
        try:
            await _research_cortex.research(query=query, depth=rd, priority=priority)
        except Exception as e:
            log.exception(f"[/uni/research] research task failed: {e}")

    bg_task = asyncio.create_task(_run())
    bg_task.add_done_callback(
        lambda t: log.error(f"Research task died: {t.exception()!r}")
        if not t.cancelled() and t.exception()
        else None
    )
    return {"status": "started", "task_id": task_id, "query": query, "depth": depth}


@app.get("/uni/results")
async def list_research_results(
    limit: int = Query(default=50, le=200), authorization: str = Header(default="")
) -> dict:
    """List recent research results."""
    _verify_strike_token(authorization)
    if not _research_cortex:
        raise HTTPException(status_code=503, detail="ResearchCortex not initialized")
    results = await _research_cortex.list_results(limit=limit)
    return {"results": results, "count": len(results)}


@app.get("/uni/results/{task_id}")
async def get_research_result(task_id: str, authorization: str = Header(default="")) -> dict:
    """Get a specific research result."""
    _verify_strike_token(authorization)
    if not _research_cortex:
        raise HTTPException(status_code=503, detail="ResearchCortex not initialized")
    result = await _research_cortex.get_result(task_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"Research {task_id} not found")
    return result.model_dump()


@app.get("/uni/stats")
async def get_research_stats(authorization: str = Header(default="")) -> dict:
    """Get UNI Research Cortex statistics."""
    _verify_strike_token(authorization)
    if not _research_cortex:
        raise HTTPException(status_code=503, detail="ResearchCortex not initialized")
    return await _research_cortex.get_stats()


# ===========================================================================
# Pipeline Hardening — Memory Dashboard Endpoints
# ===========================================================================


# /memory/* endpoints moved to runtime/api/routers/memory.py (W5-04)


# ===========================================================================
# Pipeline Hardening — Deployment & Monitoring Endpoints
# ===========================================================================


@app.get("/deployment/status")
async def get_deployment_status(authorization: str = Header(default="")) -> dict:
    """Get status of all NCL daemon services."""
    _verify_strike_token(authorization)
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
async def get_service_status(service_name: str, authorization: str = Header(default="")) -> dict:
    """Get status of a specific service."""
    _verify_strike_token(authorization)
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
async def get_uptime_report(authorization: str = Header(default="")) -> dict:
    """Get uptime report for all services."""
    _verify_strike_token(authorization)
    if not _deployment_monitor:
        raise HTTPException(status_code=503, detail="DeploymentMonitor not initialized")
    return await _deployment_monitor.get_uptime_report()


@app.get("/deployment/logs/{service_name}")
async def get_service_logs(
    service_name: str,
    lines: int = Query(default=50, le=500),
    authorization: str = Header(default=""),
) -> dict:
    """Get recent log lines for a service."""
    _verify_strike_token(authorization)
    if not _deployment_monitor:
        raise HTTPException(status_code=503, detail="DeploymentMonitor not initialized")
    from ..deployment.models import ServiceName

    try:
        sn = ServiceName(service_name)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown service: {service_name}")
    return await _deployment_monitor.get_log_tail(sn, lines=lines)


@app.get("/deployment/dashboard")
async def deployment_dashboard(authorization: str = Header(default="")) -> dict:
    """Dashboard-ready deployment summary."""
    _verify_strike_token(authorization)
    if not _deployment_monitor:
        raise HTTPException(status_code=503, detail="DeploymentMonitor not initialized")
    return await _deployment_monitor.get_dashboard_data()


# ─── Autonomous Scheduler Endpoints ────────────────────────────────


@app.get("/autonomous/status")
async def autonomous_status(authorization: str = Header(default="")) -> dict:
    """Get autonomous scheduler status and statistics."""
    _verify_strike_token(authorization)
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
async def autonomous_signals(
    limit: int = Query(50, ge=1, le=500), authorization: str = Header(default="")
) -> dict:
    """Get recent autonomous signals and events."""
    _verify_strike_token(authorization)
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
async def autonomous_council_flags(authorization: str = Header(default="")) -> dict:
    """Get pending council trigger flags."""
    _verify_strike_token(authorization)
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
    """Trigger an immediate intelligence scan via Awarebot agent."""
    _verify_strike_token(authorization)
    if not _autonomous:
        raise HTTPException(status_code=503, detail="Autonomous scheduler not initialized")
    if not _autonomous.awarebot:
        raise HTTPException(status_code=503, detail="Awarebot agent not initialized")
    try:
        result = await _autonomous.awarebot.on_demand_scan()
        return {"status": "complete", **result}
    except Exception as e:
        log.exception("Endpoint error: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/autonomous/loops")
async def autonomous_loops(authorization: str = Header(default="")) -> dict:
    """Get configuration and status of all autonomous scheduler loops."""
    _verify_strike_token(authorization)
    if not _autonomous:
        return {"loops": [], "count": 0, "status": "scheduler_not_initialized"}

    # --- Scheduler-level tasks (spawned in scheduler.py start()) ---
    loop_definitions = [
        {
            "name": "Heartbeat",
            "id": "ncl-heartbeat",
            "interval": 60,
            "enabled": True,
            "description": "Health heartbeat and uptime tracking",
        },
        {
            "name": "Council Auto-Spawn",
            "id": "ncl-council-auto",
            "interval": 120,
            "enabled": True,
            "description": "Monitors triggers for autonomous council sessions",
        },
        {
            "name": "Memory Consolidation",
            "id": "ncl-memory",
            "interval": getattr(_autonomous.config, "memory_consolidation_interval", 7200),
            "enabled": True,
            "description": "Consolidates and prunes memory store",
        },
        {
            "name": "Workspace Health",
            "id": "ncl-workspace",
            "interval": 1800,
            "enabled": True,
            "description": "Monitors workspace health and connectivity",
        },
        {
            "name": "Working Context",
            "id": "ncl-working-ctx",
            "interval": 0,
            "enabled": True,
            "description": "Daily context window: 6am assembly, noon refresh, 11pm EOD cycle",
        },
        {
            "name": "Journal Reflection",
            "id": "ncl-journal-reflection",
            "interval": 0,
            "enabled": True,
            "description": "Daily 10pm ET journal synthesis with intel patterns",
        },
        {
            "name": "Night Watch",
            "id": "ncl-night-watch",
            "interval": 0,
            "enabled": True,
            "description": "Nightly 2am ET health audit — deterministic checks (services, loops, staleness, costs, connectivity, disk) + LLM analyst phase (Haiku triage + Sonnet synthesis → daily brief pushed via ntfy)",  # noqa: E501
        },
        {
            "name": "Mandate Purge",
            "id": "ncl-mandate-purge",
            "interval": 21600,
            "enabled": True,
            "description": "Purges stale mandates every 6 hours to prevent state explosion",
        },
        {
            "name": "Feedback Synthesis",
            "id": "ncl-feedback-synth",
            "interval": 300,
            "enabled": True,
            "description": "Consumes pillar feedback reports and produces synthesis notes",
        },
        {
            "name": "Supervisor",
            "id": "ncl-supervisor",
            "interval": 30,
            "enabled": True,
            "description": "Supervisor loop — monitors and restarts crashed scheduler tasks",
        },
        # ── New 2026-05-21 loops ──────────────────────────────
        {
            "name": "Health Rollup",
            "id": "ncl-health-rollup",
            "interval": 60,
            "enabled": True,
            "description": "60s aggregated component health → data/health/current.json (iOS dashboard one-call status)",  # noqa: E501
        },
        {
            "name": "Cost Rollover",
            "id": "ncl-cost-rollover",
            "interval": 60,
            "enabled": True,
            "description": "Polls UTC date every 60s; explicit midnight close of cost ledger + counter reset",  # noqa: E501
        },
        {
            "name": "Cache Warmer",
            "id": "ncl-cache-warmer",
            "interval": 300,
            "enabled": True,
            "description": "Pre-touches calendar compile_events + working-context to amortize cold-start latency",  # noqa: E501
        },
        {
            "name": "Alert Dispatch",
            "id": "ncl-alert-dispatch",
            "interval": 10,
            "enabled": True,
            "description": "Centralized rate-limited + deduped ntfy dispatcher (consumes from all alert producers)",  # noqa: E501
        },
        {
            "name": "YTC Dedicated",
            "id": "ncl-ytc-dedicated",
            "interval": 3600,
            "enabled": True,
            "description": "Dedicated YouTube Council loop (split from Awarebot) with its own $3/day budget",  # noqa: E501
        },
        # ── New 2026-05-22 memory loops (Loops 2/4/5/6/9/11 from memory swarm) ──
        {
            "name": "BM25 Index Rebuild",
            "id": "ncl-bm25-rebuild",
            "interval": 1800,
            "enabled": True,
            "description": "Rebuilds BM25 keyword index (30m) — backs FusedRetriever for multi-signal RRF",  # noqa: E501
        },
        {
            "name": "Memory Eval Harness",
            "id": "ncl-memory-eval",
            "interval": 604800,
            "enabled": True,
            "description": "Weekly memory eval (Sunday 3am ET): hit@5/MRR/recall@10, regression alerts",  # noqa: E501
        },
        {
            "name": "ChromaDB GC",
            "id": "ncl-chroma-gc",
            "interval": 3600,
            "enabled": True,
            "description": "Hourly ghost-embedding purge (was 3x bloat: 29K vectors for 10K units)",
        },
        {
            "name": "Conflict Arbitration",
            "id": "ncl-conflict-arb",
            "interval": 900,
            "enabled": True,
            "description": "15m scan for contradictory units, link via KG, queue critical to council",  # noqa: E501
        },
        {
            "name": "Staleness Detector",
            "id": "ncl-staleness",
            "interval": 21600,
            "enabled": True,
            "description": "6h: re-verify high-importance facts (≥70) against current signals; mark/revive",  # noqa: E501
        },
        {
            "name": "Narrative Threads",
            "id": "ncl-narrative-threads",
            "interval": 21600,
            "enabled": True,
            "description": "6h cross-session narrative threading: link episodes by entity overlap",
        },
        {
            "name": "Dedup Scan",
            "id": "ncl-dedup-scan",
            "interval": 21600,
            "enabled": True,
            "description": "Sliding-window dedup of 500 newest units, every 6h (replaces Night Watch M1 — 200-merge cap per cycle)",  # noqa: E501
        },
        # ── 2026-05-22 batch 2 (async writer + budget telemetry) ──
        {
            "name": "Async Memory Writer",
            "id": "ncl-async-writer",
            "interval": 0,
            "enabled": True,
            "description": "Fire-and-forget memory write queue (4 drainers, Sonnet 4.6 enrichment in background)",  # noqa: E501
        },
        {
            "name": "Memory Budget Telemetry",
            "id": "ncl-memory-budget",
            "interval": 900,
            "enabled": True,
            "description": "15m per-tier token-spend rollup on context injection; ntfy on cap exceed",  # noqa: E501
        },
        # ── 2026-05-22 EOD: stocks scanner agent ──
        {
            "name": "Stocks Scanner",
            "id": "ncl-stocks-scan",
            "interval": 14400,
            "enabled": True,
            "description": "4h GOAT + BRAVO scan during NYSE hours — portfolio dedup, liquidity gate, earnings filter (next 7d), IVR gate, options-flow confirmation, dark-pool support refinement. Hits persist to data/scanners/*.jsonl + MemoryStore (importance 70 GOAT / 55 BRAVO).",  # noqa: E501
        },
    ]

    # --- Awarebot sub-tasks (spawned inside awarebot agent) ---
    if _autonomous.awarebot:
        _ab = _autonomous.awarebot
        loop_definitions.extend(
            [
                {
                    "name": "Awarebot Agent",
                    "id": "ncl-awarebot-agent",
                    "interval": 0,
                    "enabled": True,
                    "description": "Unified intelligence pipeline supervisor",
                },
                {
                    "name": "Intelligence Scanner",
                    "id": "awarebot-scan",
                    "interval": getattr(_ab, "_scan_interval", 300),
                    "enabled": True,
                    "description": "Scans all sources for signals (X, YouTube, Reddit, news, markets)",  # noqa: E501
                },
                {
                    "name": "Future Prediction",
                    "id": "awarebot-predict",
                    "interval": getattr(_ab, "_prediction_interval", 1800),
                    "enabled": True,
                    "description": "Runs prediction models on accumulated signals",
                },
                {
                    "name": "Intel Brief",
                    "id": "awarebot-brief",
                    "interval": getattr(_ab, "_brief_interval", 14400),
                    "enabled": True,
                    "description": "Generates periodic intelligence briefs",
                },
                {
                    "name": "Context Maintenance",
                    "id": "awarebot-context",
                    "interval": getattr(_ab, "_context_interval", 600),
                    "enabled": True,
                    "description": "Maintains context window and signal buffers",
                },
                {
                    "name": "Journal Processing",
                    "id": "awarebot-journal",
                    "interval": getattr(_ab, "_journal_interval", 3600),
                    "enabled": True,
                    "description": "Processes journal entries and generates tips",
                },
                {
                    "name": "YouTube Council (legacy)",
                    "id": "awarebot-ytc",
                    "interval": 1800,
                    "enabled": False,
                    "description": "DISABLED 2026-05-21 — superseded by scheduler-level 'ncl-ytc-dedicated' (own $3/day budget)",  # noqa: E501
                },
                {
                    "name": "X Liked Posts",
                    "id": "awarebot-x-liked",
                    "interval": 3600,
                    "enabled": True,
                    "description": "Processes liked posts from X for signal extraction",
                },
            ]
        )

    # Enrich with live task status from scheduler + awarebot sub-tasks
    active_task_names = set()
    for t in _autonomous._tasks:
        if not t.done():
            active_task_names.add(t.get_name())
    # Check supervisor task (not in self._tasks)
    if _autonomous._supervisor_task and not _autonomous._supervisor_task.done():
        active_task_names.add("ncl-supervisor")
    # Also check Awarebot internal tasks
    if _autonomous.awarebot and hasattr(_autonomous.awarebot, "_tasks"):
        for t in _autonomous.awarebot._tasks:
            if not t.done():
                active_task_names.add(t.get_name())

    # Explicit timestamp source map — avoids the brittle string-mangling
    # that left every awarebot-* loop showing last_run=null even when firing
    # on cadence. Pulls scheduler shadow stats first, then live awarebot stats.
    aware_stats = {}
    if _autonomous.awarebot and hasattr(_autonomous.awarebot, "get_stats"):
        try:
            aware_stats = _autonomous.awarebot.get_stats() or {}
        except Exception:
            aware_stats = {}
    elif _autonomous.awarebot and hasattr(_autonomous.awarebot, "_stats"):
        aware_stats = getattr(_autonomous.awarebot, "_stats", {}) or {}

    timestamp_map = {
        # scheduler-level
        "ncl-heartbeat": _autonomous._stats.get("last_heartbeat_at"),
        "ncl-council-auto": _autonomous._stats.get("last_council"),
        "ncl-memory": _autonomous._stats.get("last_consolidation"),
        "ncl-workspace": _autonomous._stats.get("last_workspace_check"),
        "ncl-working-ctx": _autonomous._stats.get("last_working_ctx"),
        "ncl-journal-reflection": _autonomous._stats.get("last_journal_reflection"),
        "ncl-night-watch": _autonomous._stats.get("last_night_watch"),
        "ncl-mandate-purge": _autonomous._stats.get("last_mandate_purge"),
        "ncl-feedback-synth": _autonomous._stats.get("last_feedback_synth"),
        "ncl-supervisor": _autonomous._stats.get("last_supervisor_tick"),
        "ncl-calendar-agent": _autonomous._stats.get("last_calendar_scan"),
        "ncl-calendar-alerts": _autonomous._stats.get("last_calendar_alert_check"),
        # New 2026-05-21 loops
        "ncl-health-rollup": _autonomous._stats.get("last_health_rollup"),
        "ncl-cost-rollover": _autonomous._stats.get("last_cost_rollover"),
        "ncl-cache-warmer": _autonomous._stats.get("last_cache_warm"),
        "ncl-alert-dispatch": _autonomous._stats.get("last_alert_dispatch_tick"),
        "ncl-ytc-dedicated": _autonomous._stats.get("last_ytc_dedicated"),
        # New 2026-05-22 memory loops
        "ncl-bm25-rebuild": _autonomous._stats.get("last_bm25_build"),
        "ncl-memory-eval": _autonomous._stats.get("last_memory_eval_at"),
        "ncl-chroma-gc": _autonomous._stats.get("last_chroma_gc"),
        "ncl-conflict-arb": _autonomous._stats.get("last_conflict_arbitration"),
        "ncl-staleness": _autonomous._stats.get("last_staleness_check"),
        "ncl-narrative-threads": _autonomous._stats.get("last_narrative_threading"),
        "ncl-dedup-scan": _autonomous._stats.get("last_dedup_scan"),
        "ncl-async-writer": _autonomous._stats.get("last_async_writer_tick")
        or (
            _autonomous._async_writer.get_stats().get("last_drain_at")
            if getattr(_autonomous, "_async_writer", None)
            else None
        ),
        "ncl-memory-budget": _autonomous._stats.get("last_memory_budget_check"),
        "ncl-stocks-scan": _autonomous._stats.get("last_stocks_scan"),
        # awarebot sub-tasks — read directly from awarebot stats
        "ncl-awarebot-agent": aware_stats.get("last_scan_at"),
        "awarebot-scan": aware_stats.get("last_scan_at"),
        "awarebot-predict": aware_stats.get("last_prediction_at"),
        "awarebot-brief": aware_stats.get("last_brief_at"),
        "awarebot-context": aware_stats.get("last_context_at"),
        "awarebot-journal": aware_stats.get("last_journal_at"),
        "awarebot-ytc": aware_stats.get("last_ytc_at"),
        "awarebot-x-liked": aware_stats.get("last_x_liked_at"),
    }

    for loop in loop_definitions:
        loop["active"] = loop["id"] in active_task_names
        loop["last_run"] = timestamp_map.get(loop["id"])

    return {"loops": loop_definitions, "count": len(loop_definitions)}


@app.get("/autonomous/processor")
async def autonomous_processor_stats(authorization: str = Header(default="")) -> dict:
    """Get unified signal processor statistics — routing metrics across all loops."""
    _verify_strike_token(authorization)
    if not _autonomous:
        return {"status": "scheduler_not_initialized"}
    return _autonomous.signal_processor.get_stats()


@app.get("/autonomous/history")
async def autonomous_history(
    limit: int = Query(50, ge=1, le=500), authorization: str = Header(default="")
) -> dict:
    """Get recent autonomous execution history from event log."""
    _verify_strike_token(authorization)
    if not _autonomous:
        return {"history": [], "total": 0, "status": "scheduler_not_initialized"}

    events_file = _autonomous.signals_dir / "events.ndjson"
    entries = []
    if events_file.exists():
        try:
            async with aiofiles.open(events_file, "r") as f:
                content = await f.read()
                for line in content.strip().split("\n"):
                    if not line.strip():
                        continue
                    try:
                        event = json.loads(line)
                        entries.append(
                            {
                                "task": event.get("event_type", event.get("type", "unknown")),
                                "name": event.get("event_type", event.get("type", "unknown")),
                                "status": event.get("status", "complete"),
                                "result": event.get("summary", event.get("detail", "")),
                                "timestamp": event.get("timestamp", event.get("ts", "")),
                                "completed_at": event.get("timestamp", event.get("ts", "")),
                                "duration": event.get("duration", 0),
                                "elapsed": event.get("duration", 0),
                            }
                        )
                    except json.JSONDecodeError:
                        pass
        except Exception as _hist_err:
            log.warning("Failed to read autonomous history: %s", _hist_err)

    # Most recent first
    entries.reverse()
    return {"history": entries[:limit], "total": len(entries)}


# ===========================================================================
# Awarebot Context Windows — live signal context for iOS app
# ===========================================================================


@app.get("/context/top10")
async def context_top10(authorization: str = Header(default="")) -> dict:
    """Get the top 10 highest-scoring signals right now."""
    _verify_strike_token(authorization)
    if not _autonomous or not _autonomous.awarebot:
        raise HTTPException(status_code=503, detail="Awarebot agent not initialized")
    agent = _autonomous.awarebot
    signals = sorted(agent._context_top10, key=lambda s: s.composite_score, reverse=True)[:10]
    return {
        "signals": [s.to_dict() for s in signals],
        "count": len(signals),
        "window": "top10",
        "updated_at": agent._stats.get("last_scan_at"),
    }


def _score_signals_against_context(signals: list, wctx) -> list[dict]:
    """Score signals against working context themes and return enriched dicts."""
    from ..memory.working_context import DailyContextWindow

    themes = []
    if wctx and wctx._current:
        themes = wctx._current.themes or []

    scored = []
    for s in signals:
        d = s.to_dict()
        # Compute context relevance
        text = f"{d.get('title', '')} {d.get('summary', '')} {d.get('content', '')}"
        if themes:
            d["context_relevance"] = round(DailyContextWindow.compute_relevance(text, themes), 3)
        else:
            d["context_relevance"] = round(d.get("composite_score", 0.5), 3)
        # Blended score: 60% context relevance + 40% composite score
        composite = d.get("composite_score", 0.5)
        d["hot_score"] = round(0.6 * d["context_relevance"] + 0.4 * composite, 3)
        scored.append(d)

    scored.sort(key=lambda x: x["hot_score"], reverse=True)
    return scored


@app.get("/context/24h")
async def context_24h(
    limit: int = Query(default=50, ge=1, le=200),
    authorization: str = Header(default=""),
) -> dict:
    """Get signals from the last 24 hours, ranked by context relevance."""
    _verify_strike_token(authorization)
    if not _autonomous or not _autonomous.awarebot:
        raise HTTPException(status_code=503, detail="Awarebot agent not initialized")
    agent = _autonomous.awarebot
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    signals = [s for s in agent._context_24h if s.timestamp >= cutoff]

    # Get working context for theme scoring
    wctx = getattr(_autonomous, "_working_context", None)
    scored = _score_signals_against_context(signals, wctx)

    return {
        "signals": scored[:limit],
        "count": len(scored),
        "window": "24h",
        "updated_at": agent._stats.get("last_scan_at"),
    }


@app.get("/context/7d")
async def context_7d(
    limit: int = Query(default=100, ge=1, le=500),
    authorization: str = Header(default=""),
) -> dict:
    """Get signals from the last 7 days, ranked by context relevance."""
    _verify_strike_token(authorization)
    if not _autonomous or not _autonomous.awarebot:
        raise HTTPException(status_code=503, detail="Awarebot agent not initialized")
    agent = _autonomous.awarebot
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    signals = [s for s in agent._context_7d if s.timestamp >= cutoff]

    wctx = getattr(_autonomous, "_working_context", None)
    scored = _score_signals_against_context(signals, wctx)

    return {
        "signals": scored[:limit],
        "count": len(scored),
        "window": "7d",
        "updated_at": agent._stats.get("last_scan_at"),
    }


@app.get("/context/brief")
async def context_brief(
    refresh: bool = False,
    authorization: str = Header(default=""),
) -> dict:
    """Get the latest Awarebot consolidation brief.

    Returns cached brief if < 4h old. Pass ?refresh=true to force regeneration.
    """
    _verify_strike_token(authorization)
    if not _autonomous or not _autonomous.awarebot:
        raise HTTPException(status_code=503, detail="Awarebot agent not initialized")
    try:
        brief = await _autonomous.awarebot.on_demand_brief(force_refresh=refresh)
        return brief
    except Exception as e:
        log.exception("Endpoint error: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/context/scan")
async def context_scan_now(authorization: str = Header(default="")) -> dict:
    """Trigger an immediate Awarebot scan + score + route cycle."""
    _verify_strike_token(authorization)
    if not _autonomous or not _autonomous.awarebot:
        raise HTTPException(status_code=503, detail="Awarebot agent not initialized")
    try:
        result = await _autonomous.awarebot.on_demand_scan()
        return {"status": "complete", **result}
    except Exception as e:
        log.exception("Endpoint error: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/context/source/{source}")
async def context_source_report(
    source: str,
    authorization: str = Header(default=""),
) -> dict:
    """Get per-source report (x, youtube, reddit, crypto, etc)."""
    _verify_strike_token(authorization)
    if not _autonomous or not _autonomous.awarebot:
        raise HTTPException(status_code=503, detail="Awarebot agent not initialized")
    try:
        report = await _autonomous.awarebot.generate_source_report(source)
        return report
    except Exception as e:
        log.exception("Endpoint error: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/context/health")
async def context_health(authorization: str = Header(default="")) -> dict:
    """Get Awarebot source health status."""
    _verify_strike_token(authorization)
    if not _autonomous or not _autonomous.awarebot:
        raise HTTPException(status_code=503, detail="Awarebot agent not initialized")
    return _autonomous.awarebot.get_source_health()


# ---------------------------------------------------------------------------
# 3-Tier Context Endpoints — Awarebot Single Scorer + Tier Router
# ---------------------------------------------------------------------------
# Awarebot scores on ingest (6-factor composite) and route_to_tiers()
# handles Focused/Micro/Macro assignment in one pass.
# ---------------------------------------------------------------------------


def _get_awarebot_tiers() -> dict:
    """Get tier-routed signals directly from Awarebot's single scorer."""
    if not _autonomous or not _autonomous.awarebot:
        return {
            "focused": {"signals": [], "count": 0, "tier": "focused"},
            "micro": {"signals": [], "count": 0, "tier": "micro"},
            "macro": {"signals": [], "count": 0, "tier": "macro"},
        }
    return _autonomous.awarebot.route_to_tiers()


@app.get("/context/focused")
async def context_focused(authorization: str = Header(default="")) -> dict:
    """
    FOCUSED tier (green) — Top 10 highest-priority, actionable, fresh signals.
    Score ≥ 0.75, < 4 hours old, multi-source preferred.
    """
    _verify_strike_token(authorization)
    tiers = _get_awarebot_tiers()
    result = tiers["focused"]
    result["updated_at"] = datetime.now(timezone.utc).isoformat()
    return result


@app.get("/context/micro")
async def context_micro(
    window: str = Query(default="24h", regex="^(24h|7d)$"),
    authorization: str = Header(default=""),
) -> dict:
    """
    MICRO tier (orange) — Top 10 trending signals within 24h/7d window.
    Score ≥ 0.50, sector clusters, momentum.
    """
    _verify_strike_token(authorization)
    tiers = _get_awarebot_tiers()

    # For 7d window, include Macro items too (broader view)
    signals = tiers["micro"]["signals"]
    if window == "7d":
        signals = tiers["micro"]["signals"] + tiers["macro"]["signals"]

    return {
        "signals": signals,
        "count": len(signals),
        "tier": "micro",
        "window": window,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/context/macro")
async def context_macro(authorization: str = Header(default="")) -> dict:
    """
    MACRO tier (blue) — Top 10 persistent narrative-level signals.
    Score ≥ 0.30, 7d+ persistence, council/journal/mandate sources.
    """
    _verify_strike_token(authorization)
    tiers = _get_awarebot_tiers()
    result = tiers["macro"]
    result["updated_at"] = datetime.now(timezone.utc).isoformat()
    return result


@app.get("/context/tiers")
async def context_all_tiers(authorization: str = Header(default="")) -> dict:
    """
    All 3 tiers in one call — Focused + Micro + Macro.
    Single request for the iOS Intel tab to populate all sections.
    """
    _verify_strike_token(authorization)
    tiers = _get_awarebot_tiers()

    return {
        "focused": tiers["focused"],
        "micro": tiers["micro"],
        "macro": tiers["macro"],
        "counts": {
            "focused": tiers["focused"]["count"],
            "micro": tiers["micro"]["count"],
            "macro": tiers["macro"]["count"],
        },
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


# /focus/* endpoints + helpers moved to runtime/api/routers/intel.py (W5-04)

# ---------------------------------------------------------------------------
# Chat Endpoint — Synchronous AI response for FirstStrike chatbot
# ---------------------------------------------------------------------------

# Maximum length of a single chat message (bytes-of-text, not tokens).
# Anything larger is rejected with 413; the iOS app should chunk or summarize.
MAX_CHAT_MESSAGE_CHARS = 8000

# Control characters that should never appear in chat input — null byte,
# bell, backspace, form-feed, vertical-tab, and other C0 controls. Tab (\t),
# LF (\n), and CR (\r) are kept intact. Used to scrub prompt-injection
# tricks that hide payloads behind invisible characters.
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _sanitize_chat_message(raw: str) -> str:
    """Strip control characters and enforce max length. Raise 413 if too long."""
    if not isinstance(raw, str):
        raise HTTPException(status_code=400, detail="'message' must be a string")
    cleaned = _CONTROL_CHAR_RE.sub("", raw)
    if len(cleaned) > MAX_CHAT_MESSAGE_CHARS:
        raise HTTPException(
            status_code=413,
            detail=f"Message exceeds {MAX_CHAT_MESSAGE_CHARS} characters",
        )
    return cleaned


# W4-02 / W8-A1 Q16 (2026-05-24): sanitize the chat_context_block before it
# gets f-strung into the system prompt. The block can contain user-controlled
# memory content (e.g. pinned working-context items), so we strip control
# chars, collapse runs of blank lines, scan for prompt-injection directives
# ANYWHERE in the block (not just at line-start — "BTW system: …" used to slip
# past the old anchored regex), and cap total length as a safety net.
#
# Match policy: if ANY injection pattern is found anywhere in the block, the
# ENTIRE context block is dropped. Per-line [REDACTED] is too soft — a single
# crafted line carrying jailbreak text can poison the prompt even after the
# surrounding lines are kept.
_CHAT_CTX_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_CHAT_CTX_NEWLINE_RUN_RE = re.compile(r"\n{3,}")
_CHAT_CTX_INJECTION_RE = re.compile(
    r"(?:"
    r"ignore\s+previous"
    r"|you\s+are\s+now"
    r"|\bsystem\s*:"
    r"|<\|system\|>"
    r"|###\s*(?:system|override|new\s+instructions)"
    r"|forget\s+(?:everything|previous|all)"
    r"|\bdisregard\b"
    r"|\boverride\b"
    r"|\bnew\s+instructions\b"
    r"|\bact\s+as\b"
    r"|\bpretend\b"
    r")",
    re.IGNORECASE,
)
_CHAT_CTX_MAX_CHARS = 16000


def _sanitize_chat_context(text: str) -> str:
    """Sanitize a chat_context_block before it lands in the system prompt.

    Returns the cleaned string. If any injection pattern is detected ANYWHERE
    in the block, the entire block is dropped (returns "") and an INFO line
    is logged. Never raises — falls back to "" on unexpected input.
    """
    if not text:
        return ""
    try:
        # 1) strip control characters (keep \t \n \r)
        cleaned = _CHAT_CTX_CONTROL_RE.sub("", text)

        # 2) full-block scan for prompt-injection directives. Unanchored
        # `re.search` so patterns like "BTW system:" or "...please act as..."
        # are caught regardless of where they sit on the line. On any hit,
        # drop the whole block — soft per-line redaction is bypassable.
        if _CHAT_CTX_INJECTION_RE.search(cleaned):
            log.info("[chat] injection pattern detected in context block — dropping entire block")
            return ""

        # 3) collapse 3+ consecutive newlines to 2
        cleaned = _CHAT_CTX_NEWLINE_RUN_RE.sub("\n\n", cleaned)

        # 4) hard length cap
        if len(cleaned) > _CHAT_CTX_MAX_CHARS:
            cleaned = cleaned[:_CHAT_CTX_MAX_CHARS]

        return cleaned
    except Exception as _sanitize_err:
        log.warning(f"[chat] _sanitize_chat_context failed, dropping context: {_sanitize_err}")
        return ""


@app.post("/chat")
@_maybe_limit("30/minute")
async def chat_endpoint(
    request: Request,
    body: dict = Body(...),
    authorization: str = Header(default=""),
) -> dict:
    """
    Synchronous chat endpoint for FirstStrike iOS chatbot.

    Unlike /pump (which fires the full council pipeline in background),
    this endpoint returns a direct AI response for conversational use.

    Accepts: { "message": "...", "session_id": "...", "pillar": "NCL" }
    Returns: { "text": "...", "source": "NCL Brain", "conversation_id": "..." }

    Hardening (2026-05-23): user message is never f-strung into the system
    prompt. It is passed as a separate {role:"user"} message to the LLM,
    so any 'ignore previous instructions' payload sits in the user role
    where the model treats it as content, not as a system override. Control
    characters are stripped; messages > MAX_CHAT_MESSAGE_CHARS are rejected.
    """
    _verify_strike_token(authorization)
    _check_rate_limit(request)

    if not brain:
        raise HTTPException(status_code=503, detail="Brain not initialized")

    raw_message = (
        body.get("message") or body.get("intent") or body.get("raw_intent") or body.get("prompt")
    )
    if not raw_message:
        raise HTTPException(status_code=400, detail="Missing required field: 'message'")

    message = _sanitize_chat_message(raw_message)
    # Log only the first 100 chars — never log the full message (PII / injection payload).
    log.info(f"[/chat] inbound msg len={len(message)} preview={message[:100]!r}")

    session_id = body.get("session_id") or body.get("conversation_id") or ""

    # Build session tag so /chat history can be recalled per-conversation.
    # MemUnit has no first-class session field, so we encode it on tags.
    chat_tags = ["chat", "first-strike"]
    if session_id:
        chat_tags.append(f"session:{session_id}")

    # Store in memory
    await brain.memory_store.create_unit(
        content=f"Chat from FirstStrike: {message}",
        source="first-strike-chat",
        importance=30.0,
        tags=chat_tags,
    )

    # Loop 1: chat context injector. Pulls top-N working context, last 5
    # same-session turns, and top-3 semantically-relevant memories. Pure
    # retrieval — no LLM calls. Returns "" on any failure so chat keeps working.
    chat_context_block = ""
    try:
        from ..memory.chat_context import build_chat_context

        chat_context_block = await build_chat_context(
            message=message,
            session_id=session_id,
            brain=brain,
            autonomous=_autonomous,
        )
    except Exception as ctx_err:
        log.warning(f"[/chat] context injector failed (proceeding without): {ctx_err}")
        chat_context_block = ""

    # Memory budget telemetry — count the prompt context we're about to
    # inject (chars/4 ≈ tokens). Inbound side only; cost_tracker handles $$
    # on the response. Never block the chat path on a tracker failure.
    if chat_context_block:
        try:
            from ..memory.budget_tracker import estimate_tokens as _bt_est
            from ..memory.budget_tracker import record as _bt_record

            await _bt_record(
                "chat_injection",
                _bt_est(chat_context_block),
                source=f"chat:{session_id or 'anon'}",
            )
        except Exception as bt_err:
            log.debug(f"[/chat] memory budget record failed: {bt_err}")

    # Build system prompt for NATRIX context
    system_prompt = (
        "You are the NCL Brain — NATRIX's strategic intelligence AI. "
        "You operate the autonomous infrastructure for the NATRIX ecosystem. "
        "You have access to intelligence from social media scanning, prediction models, "
        "multi-AI council deliberation, and mandate governance. "
        "Respond concisely and directly. Use markdown formatting. "
        "You are speaking with NATRIX, your operator, via the FirstStrike iPhone app."
    )

    # Prepend the recalled context block (if any) before the static prompt so
    # the model sees conversation state first, then identity instructions.
    # W4-02: sanitize the block first — it can contain user-controlled
    # memory content (pinned working-context items) and must not be allowed
    # to inject directives into the system prompt.
    if chat_context_block:
        chat_context_block = _sanitize_chat_context(chat_context_block)
    if chat_context_block:
        full_system_prompt = f"{chat_context_block}\n{system_prompt}"
    else:
        full_system_prompt = system_prompt

    # Pre-flight cost gate — block the LLM call if anthropic budget exhausted.
    try:
        from ..cost_tracker import check_budget

        if not await check_budget("anthropic", 0.01):
            log.warning("[/chat] anthropic budget exhausted — returning soft fallback")
            return {
                "text": (
                    "I've hit my Anthropic daily budget cap. Try again after midnight UTC, "
                    "or raise NCL_BUDGET_ANTHROPIC in .env."
                ),
                "message": (
                    "I've hit my Anthropic daily budget cap. Try again after midnight UTC, "
                    "or raise NCL_BUDGET_ANTHROPIC in .env."
                ),
                "source": "NCL Brain",
                "conversation_id": session_id,
                "status": "budget_exhausted",
            }
    except Exception as budget_err:
        log.debug(f"[/chat] budget precheck skipped: {budget_err}")

    # Call Claude for a direct response — STRUCTURED messages, no f-string fusion.
    # The user's literal message rides in {role:"user"} and the system prompt
    # (identity + retrieved context) rides in `system`. This is the Anthropic-
    # SDK-correct way to fence off prompt-injection: any 'ignore previous
    # instructions' the user types stays in user-content, where the model
    # treats it as data, not as a higher-priority directive.
    council_engine = brain.council_engine
    response_text = None
    try:
        resp = await council_engine.http_client.post(
            f"{council_engine.anthropic_base_url}/v1/messages",
            headers={
                "x-api-key": council_engine.claude_api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 2048,
                "system": full_system_prompt,
                "messages": [{"role": "user", "content": message}],
            },
            timeout=council_engine._api_timeout,
        )
        resp.raise_for_status()
        _data = resp.json()
        _content = _data.get("content", [])
        if _content and isinstance(_content, list):
            response_text = _content[0].get("text", "")
        # Record cost (no double-counting — _call_claude did NOT run here)
        try:
            from ..cost_tracker import record_cost

            _usage = _data.get("usage", {}) or {}
            _in = int(_usage.get("input_tokens", 0))
            _out = int(_usage.get("output_tokens", 0))
            _cost = (_in / 1000 * 0.003) + (_out / 1000 * 0.015)
            await record_cost(
                "anthropic",
                _cost,
                "user_chat",
                f"chat msg preview={message[:80]!r}",
                model="claude-sonnet-4-20250514",
                input_tokens=_in,
                output_tokens=_out,
            )
        except Exception as _cost_err:
            _warn_once_per_hour(
                "chat_cost_record",
                "[/chat] cost record swallowed (drift risk): %s",
                _cost_err,
            )
    except Exception as claude_err:
        log.warning(f"[/chat] Claude failed: {claude_err}, trying Grok fallback")
        try:
            resp = await council_engine.http_client.post(
                "https://api.x.ai/v1/chat/completions",
                headers={"Authorization": f"Bearer {council_engine.xai_api_key}"},
                json={
                    "model": "grok-3",
                    "messages": [
                        {"role": "system", "content": full_system_prompt},
                        {"role": "user", "content": message},
                    ],
                    "temperature": 0.8,
                    "max_tokens": 2048,
                },
                timeout=council_engine._api_timeout,
            )
            resp.raise_for_status()
            _data = resp.json()
            _choices = _data.get("choices", []) or []
            if _choices:
                response_text = _choices[0].get("message", {}).get("content", "")
            try:
                from ..cost_tracker import record_cost

                _usage = _data.get("usage", {}) or {}
                _in = int(_usage.get("prompt_tokens", 0))
                _out = int(_usage.get("completion_tokens", 0))
                _cost = (_in / 1000 * 0.005) + (_out / 1000 * 0.015)
                await record_cost(
                    "xai",
                    _cost,
                    "user_chat",
                    f"chat fallback preview={message[:80]!r}",
                    model="grok-3",
                    input_tokens=_in,
                    output_tokens=_out,
                )
            except Exception:
                pass
        except Exception as grok_err:
            log.error(f"[/chat] All LLM calls failed: Claude={claude_err}, Grok={grok_err}")
            response_text = (
                "I'm having trouble reaching my AI backends right now. "
                "Both Claude and Grok APIs returned errors. "
                "Check that API keys are configured in .env and try again."
            )

    if not response_text:
        response_text = (
            "I received an empty response from the LLM backend. "
            "This is usually a transient API hiccup — please retry."
        )

    # Store response in memory — tag with session so future turns can recall it
    response_tags = ["chat", "response"]
    if session_id:
        response_tags.append(f"session:{session_id}")
    await brain.memory_store.create_unit(
        content=f"Brain response: {response_text[:200]}",
        source="brain-chat-response",
        importance=20.0,
        tags=response_tags,
    )

    return {
        "text": response_text,
        "message": response_text,
        "source": "NCL Brain",
        "conversation_id": session_id,
        "status": "ok",
    }


# /intelligence/* (brief, latest, stats, escalate, signals, ack, etc.) — moved to runtime/api/routers/intel.py (W5-04)  # noqa: E501


@app.get("/notifications/subscribe")
async def get_notification_subscribe_info(authorization: str = Header(default="")):
    """
    Return the ntfy.sh subscription info.
    Open the subscribe URL on iPhone → instant push notifications, no account needed.
    """
    _verify_strike_token(authorization)
    # Strike-point orchestrator archived 2026-05-23 — pipeline merged into Brain auto_flow. See CLAUDE.md DO NOT TOUCH rule #6.  # noqa: E501
    # ntfy constants used to live in strike_point_orchestrator.py; inlined here from the same env-var contract.  # noqa: E501
    NTFY_TOPIC = os.getenv("NTFY_TOPIC", "ncl-natrix-intel-7x9k")  # noqa: N806
    NTFY_SERVER = os.getenv("NTFY_SERVER", "https://ntfy.sh")  # noqa: N806
    return {
        "provider": "ntfy.sh",
        "topic": NTFY_TOPIC,
        "subscribe_url": f"{NTFY_SERVER}/{NTFY_TOPIC}",
        "app_install_url": "https://apps.apple.com/app/ntfy/id1625396347",
        "instructions": f"Install ntfy app → open {NTFY_SERVER}/{NTFY_TOPIC} in Safari → tap Subscribe",  # noqa: E501
    }


@app.post("/notifications/test")
async def send_test_notification(authorization: str = Header(default="")):
    """Fire a test push notification to verify iPhone delivery."""
    _verify_strike_token(authorization)
    # Strike-point orchestrator archived 2026-05-23 — pipeline merged into Brain auto_flow. See CLAUDE.md DO NOT TOUCH rule #6.  # noqa: E501
    # Was: notify_natrix() pushed an ntfy alert via the orchestrator's httpx client. The helper is gone with the  # noqa: E501
    # orchestrator; this endpoint returns a 410 until a fresh ntfy client is wired (no other caller depends on it).  # noqa: E501
    raise HTTPException(
        status_code=410,
        detail="push helper retired with strike-point orchestrator; ntfy client needs to be re-wired before this endpoint returns",  # noqa: E501
    )


# /intelligence/push-brief, /intelligence/reddit/*, /intelligence/x/* — moved to runtime/api/routers/intel.py (W5-04)  # noqa: E501

# Journal endpoints (/journal/*) moved to routers/journal.py (W5-05).
# Request schemas (_JournalEntryRequest, _JournalTipRequest) live there too.


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
async def sse_stream(authorization: str = Header(default="")):
    """Server-Sent Events stream for real-time dashboard updates."""
    _verify_strike_token(authorization)
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
                    yield ": heartbeat\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            if queue in _sse_clients:
                _sse_clients.remove(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ===========================================================================
# NCL Command Center PWA — unified dashboard for iPhone / iPad / Mac
# ===========================================================================


@app.get("/app")
async def command_center_pwa(authorization: str = Header(default="")) -> HTMLResponse:
    """Serve the NCL Command Center dashboard.

    GATED in W5-01 (2026-05-23): the HTML used to embed the strike Bearer
    token as a hardcoded string in inline JavaScript, so this endpoint MUST
    require auth or it leaked credentials to anyone with the URL.

    HARDENED in W6-E (2026-05-24): the token is no longer in the file at
    rest. ``dashboard/command-center.html`` now contains the placeholder
    ``__AUTH_TOKEN__`` which we substitute with the requester's already-
    verified Bearer token before serving. The page is auth-gated, so the
    token that comes back out is the same one the client already has.
    Source on disk + in VCS contains zero secrets.

    Manifest + service worker remain unauth (they're static install
    assets with no secrets).
    """
    _verify_strike_token(authorization)
    token = authorization.removeprefix("Bearer ").strip()
    html_path = Path(__file__).parent.parent.parent / "dashboard" / "command-center.html"
    if not html_path.exists():
        raise HTTPException(status_code=404, detail="Command Center not found")
    async with aiofiles.open(html_path, "r") as f:
        html = await f.read()
    # JS-string-safe substitution. Token is base64url-ish (A-Za-z0-9_-),
    # which has no JS string-escape concerns, but we still guard the
    # replace to belt-and-braces against any future token format change.
    safe_token = token.replace("\\", "\\\\").replace("'", "\\'")
    html = html.replace("__AUTH_TOKEN__", safe_token)
    return HTMLResponse(content=html)


@app.get("/app/manifest.json")
async def pwa_manifest() -> JSONResponse:
    """PWA web app manifest for Add-to-Home-Screen."""
    return JSONResponse(
        content={
            "name": "NCL Workstation",
            "short_name": "NCL",
            "description": "NATRIX Command & Intelligence Workstation",
            "start_url": "/app",
            "display": "standalone",
            "background_color": "#0a0a0f",
            "theme_color": "#0a0a0f",
            "icons": [
                {
                    "src": "data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><rect fill='%230a0a0f' width='100' height='100' rx='20'/><text x='50' y='68' text-anchor='middle' font-size='50' fill='%2300ff88'>⚡</text></svg>",  # noqa: E501
                    "sizes": "any",
                    "type": "image/svg+xml",
                }
            ],
        }
    )


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
    authorization: str = Header(default=""),
) -> dict:
    """List swarm tasks with optional status filter."""
    _verify_strike_token(authorization)
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
async def get_swarm_task(task_id: str, authorization: str = Header(default="")) -> dict:
    """Get details of a specific swarm task."""
    _verify_strike_token(authorization)
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
async def get_swarm_stats(authorization: str = Header(default="")) -> dict:
    """Get aggregate swarm orchestrator statistics."""
    _verify_strike_token(authorization)
    if not brain or not brain.swarm:
        raise HTTPException(status_code=503, detail="Swarm not initialized")

    return brain.swarm.get_stats()


@app.get("/swarm/agents")
async def list_swarm_agents(authorization: str = Header(default="")) -> dict:
    """List available swarm agent types."""
    _verify_strike_token(authorization)
    if not brain or not brain.swarm:
        raise HTTPException(status_code=503, detail="Swarm not initialized")

    from ..swarm.agents import get_registry, list_agent_types

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


# ── Missing Endpoints (FirstStrike iOS app) ────────────────────────────────
# /predictions, /prediction/* endpoints + helpers moved to runtime/api/routers/intel.py (W5-04)

# /councils/status — moved to routers/council.py (W5-03)


# /intelligence/signals, /intelligence/signals/{id}, /intelligence/reddit/posts — aliases moved to runtime/api/routers/intel.py (W5-04)  # noqa: E501


# ── Stock Scanner Endpoints (FirstStrike Stocks Tab) ──────────────────────
# GOAT Academy strategy + Johnny Bravo swing scanner — powered by yfinance
# with numpy-based technical indicators (SMA, EMA, RSI, Bollinger, VWAP).
# No paid API key required. Optional Alpaca upgrade path.

from runtime.stocks.scanner import StockScanner
from runtime.stocks.watchlist import (
    DEFAULT_WATCHLIST,
    DISPLAY_MAP,
    WATCHLIST_MAP,
    WATCHLIST_TICKERS,
    display_ticker,
)


# Module-level scanner instance (5-min cache for data)
_stock_scanner = StockScanner()


@app.get("/stocks/watchlist", tags=["stocks"])
async def stocks_watchlist(sector: str = None, authorization: str = Header(default="")):
    """Fetch current quotes for the full NATRIX watchlist.
    Optional ?sector= filter (e.g. Semis/AI, Energy, Tech).
    """
    _verify_strike_token(authorization)
    tickers = WATCHLIST_TICKERS
    if sector:
        tickers = [t.ticker for t in DEFAULT_WATCHLIST if t.sector.lower() == sector.lower()]
        if not tickers:
            return {"stocks": [], "error": f"Unknown sector: {sector}"}

    try:
        quotes = await _stock_scanner.fetch_quotes(tickers)

        # Merge watchlist metadata into quotes, strip exchange suffixes
        stocks = []
        for q in quotes:
            raw_ticker = q["ticker"]
            disp = display_ticker(raw_ticker)
            q["ticker"] = disp  # iOS expects WCP not WCP.TO
            meta = WATCHLIST_MAP.get(raw_ticker) or DISPLAY_MAP.get(disp)
            if meta:
                q["name"] = meta.name
                q["sector"] = meta.sector
                q["currency"] = meta.currency
                q["is_position"] = meta.is_position
            stocks.append(q)

        return {
            "stocks": stocks,
            "count": len(stocks),
            "total_watchlist": len(WATCHLIST_TICKERS),
        }
    except Exception as e:
        log.error("Watchlist fetch failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Watchlist fetch failed: {e}")


# ──────────────────────────────────────────────────────────────────────────
# Watchlist source-of-truth endpoints (W14 — 2026-05-25)
#
# Pre-W14 the watchlist lived in TWO places: runtime/stocks/watchlist.py
# (Python module constant) AND Sources/Models/StockModels.swift mirror.
# They had to be hand-edited in two repos to add/remove tickers.
#
# Now the Brain owns it via WatchlistStore (data/watchlist/watchlist.json).
# iOS fetches via /stocks/watchlist/items, can add/remove/import via the
# endpoints below. The Python DEFAULT_WATCHLIST becomes a one-time seed
# that populates the JSON on first boot.
# ──────────────────────────────────────────────────────────────────────────


def _get_watchlist_store():
    """Lazy-init the watchlist store. Idempotent."""
    from runtime.stocks.watchlist_store import init_store

    return init_store(Path(config.data_dir))


class _WatchlistAddBody(BaseModel):
    ticker: str
    name: str = ""
    sector: str = "Other"
    currency: str = "USD"
    is_position: bool = False
    notes: str = ""
    source: str = "manual"


class _WatchlistPatchBody(BaseModel):
    name: str | None = None
    sector: str | None = None
    currency: str | None = None
    is_position: bool | None = None
    notes: str | None = None


class _WatchlistImportBody(BaseModel):
    """TradingView .txt export contents (one symbol per line, EXCHANGE:TICKER)."""

    text: str
    replace: bool = False


@app.get("/stocks/watchlist/items", tags=["stocks"])
async def stocks_watchlist_items(authorization: str = Header(default="")):
    """Return the persistent watchlist (no quote fetch). Source of truth."""
    _verify_strike_token(authorization)
    store = _get_watchlist_store()
    tickers = await store.get_all()
    return {"count": len(tickers), "tickers": tickers}


@app.post("/stocks/watchlist/items", tags=["stocks"])
async def stocks_watchlist_add(body: _WatchlistAddBody, authorization: str = Header(default="")):
    """Add or upsert a single ticker to the watchlist."""
    _verify_strike_token(authorization)
    store = _get_watchlist_store()
    try:
        entry = await store.add(
            ticker=body.ticker,
            name=body.name,
            sector=body.sector,
            currency=body.currency,
            is_position=body.is_position,
            notes=body.notes,
            source=body.source,
        )
        return {"status": "ok", "entry": entry}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.patch("/stocks/watchlist/items/{ticker}", tags=["stocks"])
async def stocks_watchlist_patch(
    ticker: str, body: _WatchlistPatchBody, authorization: str = Header(default="")
):
    """Partial update of a ticker entry."""
    _verify_strike_token(authorization)
    store = _get_watchlist_store()
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    entry = await store.patch(ticker, **updates)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Ticker {ticker} not found")
    return {"status": "ok", "entry": entry}


@app.delete("/stocks/watchlist/items/{ticker}", tags=["stocks"])
async def stocks_watchlist_remove(ticker: str, authorization: str = Header(default="")):
    """Remove a ticker from the watchlist."""
    _verify_strike_token(authorization)
    store = _get_watchlist_store()
    removed = await store.remove(ticker)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Ticker {ticker} not found")
    return {"status": "ok", "removed": ticker}


# ──────────────────────────────────────────────────────────────────────────
# Portfolio Analyst Agent endpoints (W14 — 2026-05-25)
# ──────────────────────────────────────────────────────────────────────────


@app.get("/portfolio/analyst/report/latest", tags=["portfolio"])
async def portfolio_analyst_report_latest(authorization: str = Header(default="")):
    """Most recent nightly portfolio-agent report.

    Returns the JSON written by ``PortfolioAnalystAgent`` during the
    Night Watch Phase 6 run. iOS Portfolio "AGENT" sub-tab consumes
    this. Morning Brief also pulls from here when present.
    """
    _verify_strike_token(authorization)
    path = Path(config.data_dir) / "portfolio" / "analyst" / "reports" / "latest.json"
    if not path.exists():
        return {"status": "not_found", "message": "No portfolio analyst report yet"}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        log.warning("portfolio analyst latest read failed: %s", exc)
        raise HTTPException(status_code=500, detail="latest report read failed")


@app.get("/portfolio/analyst/report/{date}", tags=["portfolio"])
async def portfolio_analyst_report_by_date(date: str, authorization: str = Header(default="")):
    """Historical report by date (YYYY-MM-DD)."""
    _verify_strike_token(authorization)
    safe_date = "".join(c for c in date if c.isdigit() or c == "-")
    if not safe_date:
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")
    path = (
        Path(config.data_dir) / "portfolio" / "analyst" / "reports" / f"portfolio-{safe_date}.json"
    )
    if not path.exists():
        return {"status": "not_found", "date": safe_date}
    return json.loads(path.read_text(encoding="utf-8"))


@app.get("/portfolio/analyst/theses", tags=["portfolio"])
async def portfolio_analyst_theses_list(authorization: str = Header(default="")):
    """List every active position thesis."""
    _verify_strike_token(authorization)
    from runtime.portfolio.analyst.thesis_store import ThesisStore

    store = ThesisStore(Path(config.data_dir))
    theses = await store.list_active()
    return {
        "count": len(theses),
        "theses": [t.model_dump(mode="json") for t in theses],
    }


@app.get("/portfolio/analyst/theses/{instrument_id}", tags=["portfolio"])
async def portfolio_analyst_thesis_get(instrument_id: str, authorization: str = Header(default="")):
    """Fetch one thesis by instrument_id."""
    _verify_strike_token(authorization)
    from runtime.portfolio.analyst.thesis_store import ThesisStore

    store = ThesisStore(Path(config.data_dir))
    thesis = await store.load(instrument_id)
    if thesis is None:
        raise HTTPException(status_code=404, detail=f"No thesis for {instrument_id}")
    return thesis.model_dump(mode="json")


@app.post("/portfolio/analyst/theses/{instrument_id}", tags=["portfolio"])
async def portfolio_analyst_thesis_upsert(
    instrument_id: str,
    body: dict,
    authorization: str = Header(default=""),
):
    """Create or update a thesis. Body is a full PositionThesis dict."""
    _verify_strike_token(authorization)
    from runtime.portfolio.analyst.theses import PositionThesis
    from runtime.portfolio.analyst.thesis_store import ThesisStore

    body["instrument_id"] = instrument_id  # enforce path match
    try:
        thesis = PositionThesis.model_validate(body)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid thesis: {exc}")

    store = ThesisStore(Path(config.data_dir))
    await store.save(thesis)
    return {"status": "ok", "thesis": thesis.model_dump(mode="json")}


@app.post("/portfolio/analyst/run", tags=["portfolio"])
async def portfolio_analyst_run_now(dry_run: bool = False, authorization: str = Header(default="")):
    """Manual trigger — run the agent once and return the report.

    Useful for testing. The scheduled run still fires nightly inside
    Night Watch Phase 6.
    """
    _verify_strike_token(authorization)
    from runtime.portfolio import portfolio_routes as _pr
    from runtime.portfolio.analyst.agent import PortfolioAnalystAgent

    portfolio_manager = getattr(brain, "portfolio_manager", None) if brain else None
    if portfolio_manager is None:
        portfolio_manager = _pr._portfolio_manager
    if portfolio_manager is None:
        raise HTTPException(
            status_code=503,
            detail="portfolio_manager not initialized",
        )
    agent = PortfolioAnalystAgent(
        portfolio_manager=portfolio_manager,
        memory_store=getattr(brain, "memory_store", None),
        cost_tracker=None,
        data_dir=Path(config.data_dir),
        brain=brain,
    )
    report = await agent.run(dry_run=dry_run)
    return report.model_dump(mode="json")


@app.post("/stocks/watchlist/import/tradingview", tags=["stocks"])
async def stocks_watchlist_import_tradingview(
    body: _WatchlistImportBody, authorization: str = Header(default="")
):
    """Import a TradingView watchlist export (.txt format).

    The TV web app's "Export Watchlist" menu produces a text file with
    one symbol per line in EXCHANGE:TICKER form (e.g. NASDAQ:NVDA,
    NYSE:F, TSX:WCP, BATS:SPY). Comma-separated single-line exports
    are also accepted.

    Body:
        text:    the raw .txt contents
        replace: if true, wipe existing entries; else merge (skip dupes)

    Returns:
        {added, skipped, total, parsed, tickers}
    """
    _verify_strike_token(authorization)
    if not body.text or not body.text.strip():
        raise HTTPException(status_code=400, detail="text body required")
    store = _get_watchlist_store()
    result = await store.import_tradingview_txt(body.text, replace=body.replace)
    return {"status": "ok", **result}


@app.get("/stocks/scanner/goat", tags=["stocks"])
async def stocks_scanner_goat(
    sector: str = None,
    min_score: int = 0,
    include_held: bool = False,
    include_earnings_risk: bool = False,
    authorization: str = Header(default=""),
):
    """Run GOAT Academy strategy scanner on the watchlist.

    6 Rules: Price > 50 SMA, Price > 150 SMA, 50 SMA rising,
    RSI 40-70, Volume > 1.5x avg, Price > 20-day high.

    Filters:
    - ?sector= — scan only one sector
    - ?min_score= — only return results >= this GOAT score
    - ?include_held=true — include symbols already in portfolio (default false)
    - ?include_earnings_risk=true — include symbols with earnings in next 7d (default false)

    Enrichments applied: liquidity gate (ADV 500K, mcap $1B, option OI 1K),
    IVR gate (reject >70), options-flow confirmation, dark-pool support refinement.
    Persists to data/scanners/goat-YYYY-MM-DD.jsonl + MemoryStore (importance 70).
    """
    _verify_strike_token(authorization)
    tickers = WATCHLIST_TICKERS
    if sector:
        tickers = [t.ticker for t in DEFAULT_WATCHLIST if t.sector.lower() == sector.lower()]

    try:
        # Late-bind portfolio_manager into the scanner if not already attached
        if _stock_scanner.portfolio_manager is None:
            try:
                from runtime.portfolio.portfolio_routes import _portfolio_manager as _pm

                if _pm is not None:
                    _stock_scanner.attach_portfolio_manager(_pm)
            except Exception:
                pass
        # Late-bind async_writer (set after Brain scheduler starts)
        if _stock_scanner.async_writer is None and _autonomous is not None:
            aw = getattr(_autonomous, "_async_writer", None)
            if aw is not None:
                _stock_scanner.attach_async_writer(aw)

        import time as _t
        scan_start = _t.time()
        results, scan_meta = await _stock_scanner.run_goat_scan_enriched(
            tickers,
            include_held=include_held,
            include_earnings_risk=include_earnings_risk,
        )
        scan_end = _t.time()
        from datetime import datetime as _dt, timezone as _tz
        scan_meta["scan_started_at"] = _dt.fromtimestamp(scan_start, _tz.utc).isoformat()
        scan_meta["scan_completed_at"] = _dt.fromtimestamp(scan_end, _tz.utc).isoformat()
        scan_meta["scan_duration_s"] = round(scan_end - scan_start, 1)

        # P19-B — drop score=0 entries. They passed liquidity but failed
        # every alpha gate. Pure noise to the user.
        results = [r for r in results if r.get("goat_score", 0) > 0]

        if min_score > 0:
            results = [r for r in results if r["goat_score"] >= min_score]

        # Merge names + sector from watchlist, strip exchange suffixes
        for r in results:
            raw = r["ticker"]
            disp = display_ticker(raw)
            r["ticker"] = disp
            meta = WATCHLIST_MAP.get(raw) or DISPLAY_MAP.get(disp)
            if meta:
                r["name"] = meta.name
                # P19-B — sector was unpopulated in P18 audit; join from watchlist.
                if getattr(meta, "sector", None):
                    r["sector"] = meta.sector

        # Wave 14I — rotation_aligned tag (Leading quadrant check)
        try:
            from runtime.intelligence.rotation_tracker import load_latest_rotation
            _rot = load_latest_rotation()
            _leading = set(((_rot or {}).get("by_quadrant") or {}).get("Leading") or [])
        except Exception:
            _leading = set()
        _SECTOR_TO_ETF_GOAT = {
            "Technology": "XLK", "Information Technology": "XLK",
            "Financials": "XLF", "Financial Services": "XLF",
            "Energy": "XLE", "Health Care": "XLV", "Healthcare": "XLV",
            "Industrials": "XLI", "Consumer Staples": "XLP",
            "Consumer Defensive": "XLP", "Consumer Discretionary": "XLY",
            "Consumer Cyclical": "XLY", "Materials": "XLB",
            "Basic Materials": "XLB", "Utilities": "XLU",
            "Communication Services": "XLC", "Real Estate": "XLRE",
        }
        if _leading:
            for r in results:
                etf = _SECTOR_TO_ETF_GOAT.get(r.get("sector") or "")
                r["rotation_aligned"] = bool(etf and etf in _leading)
                if etf:
                    r["sector_etf"] = etf
            scan_meta["rotation_leading_sectors"] = sorted(_leading)

        # Wave 14J J1a+J1b — risk governor tagging. For each scanner result,
        # estimate a hypothetical R (1% of price as a rough stop distance ×
        # 100 share unit), submit to the governor, and attach the decision
        # so iOS / brief can show whether the trade FITS in the current
        # heat + drawdown envelope. Soft-tag — does NOT filter out results.
        try:
            from runtime.portfolio.risk_governor import check_proposed_trade, heat_summary
            _gov_heat = await heat_summary()
            scan_meta["risk_governor"] = {
                "band": _gov_heat.get("band"),
                "sizing_multiplier": _gov_heat.get("sizing_multiplier"),
                "remaining_strategy_R": (_gov_heat.get("by_strategy") or {}).get("goat", {}).get("remaining_R"),
            }
            for r in results:
                px = float(r.get("price") or r.get("last_price") or 0)
                if px <= 0:
                    r["governor_decision"] = None
                    continue
                # Rough R proxy: 1 share unit × 5% stop distance.
                # The brief/scanner doesn't yet ship operator-set stops
                # (that's J1c next). This is a sanity check, not a sizing.
                hypo_R = px * 0.05
                dec = await check_proposed_trade(
                    strategy_tag="goat",
                    R_dollars_proposed=hypo_R,
                    symbol=r.get("symbol") or r.get("ticker"),
                    broker=None,
                )
                r["governor_decision"] = {
                    "decision": dec.get("decision"),
                    "approved": dec.get("approved"),
                    "effective_R_dollars": dec.get("effective_R_dollars"),
                    "proposed_R_dollars": dec.get("proposed_R_dollars"),
                }
        except Exception as e:
            log.debug("[goat] governor tagging failed (non-fatal): %s", e)

        return {
            "results": results,
            "count": len(results),
            "scanned": len(tickers),
            "scanner": "goat",
            "rules": [
                "Price > 50-day SMA",
                "Price > 150-day SMA",
                "50-day SMA rising",
                "RSI 40-70",
                "Volume > 1.5x 20-day avg",
                "Price > 20-day high (breakout)",
            ],
            "_meta": scan_meta,
        }
    except Exception as e:
        log.error("GOAT scan failed: %s", e)
        raise HTTPException(status_code=500, detail=f"GOAT scan failed: {e}")


@app.get("/stocks/scanner/bravo", tags=["stocks"])
async def stocks_scanner_bravo(
    sector: str = None,
    min_score: int = 0,
    gogo_only: bool = False,
    include_held: bool = False,
    include_earnings_risk: bool = False,
    authorization: str = Header(default=""),
):
    """Run Johnny Bravo / Bill Stenzel swing scanner on the watchlist.

    Core: SMA 9 > EMA 20 > SMA 180 alignment, all MAs sloping up,
    entry above SMA 9, exit below EMA 20, GoGo Juice, Bollinger Squeeze.

    Filters:
    - ?sector= — scan only one sector
    - ?min_score= — only return results >= this Bravo score
    - ?gogo_only=true — only show stocks with GoGo Juice active
    - ?include_held=true — include symbols already in portfolio (default false)
    - ?include_earnings_risk=true — include symbols with earnings in next 7d (default false)

    Enrichments applied: liquidity gate (ADV 250K, mcap $1B, option OI 1K),
    IVR gate (reject <20 — no juice for swing), options-flow confirmation
    (high-put + bullish-tech = squeeze candidate), dark-pool support refinement.
    Persists to data/scanners/bravo-YYYY-MM-DD.jsonl + MemoryStore (importance 55).
    """
    _verify_strike_token(authorization)
    tickers = WATCHLIST_TICKERS
    if sector:
        tickers = [t.ticker for t in DEFAULT_WATCHLIST if t.sector.lower() == sector.lower()]

    try:
        if _stock_scanner.portfolio_manager is None:
            try:
                from runtime.portfolio.portfolio_routes import _portfolio_manager as _pm

                if _pm is not None:
                    _stock_scanner.attach_portfolio_manager(_pm)
            except Exception:
                pass
        if _stock_scanner.async_writer is None and _autonomous is not None:
            aw = getattr(_autonomous, "_async_writer", None)
            if aw is not None:
                _stock_scanner.attach_async_writer(aw)

        results, scan_meta = await _stock_scanner.run_bravo_scan_enriched(
            tickers,
            include_held=include_held,
            include_earnings_risk=include_earnings_risk,
        )

        scan_end = _tb.time()
        from datetime import datetime as _dtb, timezone as _tzb
        scan_meta["scan_started_at"] = _dtb.fromtimestamp(scan_start, _tzb.utc).isoformat()
        scan_meta["scan_completed_at"] = _dtb.fromtimestamp(scan_end, _tzb.utc).isoformat()
        scan_meta["scan_duration_s"] = round(scan_end - scan_start, 1)

        # P19-B — drop score=0 entries
        results = [r for r in results if r.get("bravo_score", 0) > 0]

        if min_score > 0:
            results = [r for r in results if r["bravo_score"] >= min_score]
        if gogo_only:
            results = [r for r in results if r.get("gogo_juice")]

        # Merge names + sector from watchlist
        for r in results:
            raw = r["ticker"]
            disp = display_ticker(raw)
            r["ticker"] = disp
            meta = WATCHLIST_MAP.get(raw) or DISPLAY_MAP.get(disp)
            if meta:
                r["name"] = meta.name
                if getattr(meta, "sector", None):
                    r["sector"] = meta.sector

        # Wave 14I — rotation_aligned tag (Leading quadrant check)
        try:
            from runtime.intelligence.rotation_tracker import load_latest_rotation
            _rot = load_latest_rotation()
            _leading_b = set(((_rot or {}).get("by_quadrant") or {}).get("Leading") or [])
        except Exception:
            _leading_b = set()
        _SECTOR_TO_ETF_BRAVO = {
            "Technology": "XLK", "Information Technology": "XLK",
            "Financials": "XLF", "Financial Services": "XLF",
            "Energy": "XLE", "Health Care": "XLV", "Healthcare": "XLV",
            "Industrials": "XLI", "Consumer Staples": "XLP",
            "Consumer Defensive": "XLP", "Consumer Discretionary": "XLY",
            "Consumer Cyclical": "XLY", "Materials": "XLB",
            "Basic Materials": "XLB", "Utilities": "XLU",
            "Communication Services": "XLC", "Real Estate": "XLRE",
        }
        if _leading_b:
            for r in results:
                etf = _SECTOR_TO_ETF_BRAVO.get(r.get("sector") or "")
                r["rotation_aligned"] = bool(etf and etf in _leading_b)
                if etf:
                    r["sector_etf"] = etf
            scan_meta["rotation_leading_sectors"] = sorted(_leading_b)

        # Wave 14J J1a+J1b — risk governor tagging (same shape as GOAT).
        try:
            from runtime.portfolio.risk_governor import check_proposed_trade, heat_summary
            _gov_heat_b = await heat_summary()
            scan_meta["risk_governor"] = {
                "band": _gov_heat_b.get("band"),
                "sizing_multiplier": _gov_heat_b.get("sizing_multiplier"),
                "remaining_strategy_R": (_gov_heat_b.get("by_strategy") or {}).get("bravo", {}).get("remaining_R"),
            }
            for r in results:
                px = float(r.get("price") or r.get("last_price") or 0)
                if px <= 0:
                    r["governor_decision"] = None
                    continue
                hypo_R = px * 0.05
                dec = await check_proposed_trade(
                    strategy_tag="bravo",
                    R_dollars_proposed=hypo_R,
                    symbol=r.get("symbol") or r.get("ticker"),
                    broker=None,
                )
                r["governor_decision"] = {
                    "decision": dec.get("decision"),
                    "approved": dec.get("approved"),
                    "effective_R_dollars": dec.get("effective_R_dollars"),
                    "proposed_R_dollars": dec.get("proposed_R_dollars"),
                }
        except Exception as e:
            log.debug("[bravo] governor tagging failed (non-fatal): %s", e)

        return {
            "results": results,
            "count": len(results),
            "scanned": len(tickers),
            "scanner": "bravo",
            "_meta": scan_meta,
        }
    except Exception as e:
        log.error("Bravo scan failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Bravo scan failed: {e}")


@app.get("/stocks/quote/{ticker}", tags=["stocks"])
async def stocks_quote(ticker: str, authorization: str = Header(default="")):
    """Fetch a single stock quote with basic technical data."""
    _verify_strike_token(authorization)
    ticker = ticker.upper()
    try:
        quotes = await _stock_scanner.fetch_quotes([ticker])
        if not quotes:
            raise HTTPException(status_code=404, detail=f"No data for {ticker}")

        quote = quotes[0]
        meta = WATCHLIST_MAP.get(ticker)
        if meta:
            quote["name"] = meta.name
            quote["sector"] = meta.sector
            quote["currency"] = meta.currency
            quote["is_position"] = meta.is_position
            quote["in_watchlist"] = True
        else:
            quote["in_watchlist"] = False

        return quote
    except HTTPException:
        raise
    except Exception as e:
        log.error("Quote fetch failed for %s: %s", ticker, e)
        raise HTTPException(status_code=500, detail=f"Quote fetch failed: {e}")


# ── /system/* endpoints moved to runtime/api/routers/system.py (W4-12) ─────
# Eight handlers extracted: /system/costs[, /today, /history, /ledger, /record, /reset]
# and /system/health/rollup + /system/memory-profile.
# Auth (_verify_strike_token) + behavior preserved verbatim. The two POST
# cost-mutator endpoints (/system/costs/record + /system/costs/reset) remain
# UNAUTH'd to match the previous monolith behavior; tightening their auth is
# tracked separately as W4-EXTRA.
# TODO: W4-13's new /system endpoints should join routers/system.py after
# their PR lands (currently expected to land first in this file).


# ── W4-13 — Status / observability endpoints ────────────────────────────────
# Three new endpoints exposing previously-invisible backend state:
#   1. /system/persistence/status      — SQLite double-write flags + JSONL state
#   2. /feedback/source-authority      — Beta-Bernoulli learner snapshot
#   3. /feedback/source-authority/{source}/history — per-source audit trail
#   4. /system/cold-start-ready        — single smoke endpoint ("is NCL up?")
# Endpoints 1-3 require the Strike token. #4 is intentionally unauthenticated
# so external monitors (uptime probes, ntfy heartbeats) can poll it cheaply
# without credential rotation. The two /system endpoints live here rather than
# in routers/system.py per W4-12's note above — they'll get lifted by a later
# pass.


def _file_stat_block(p: Path) -> dict:
    """Return a small dict with size + mtime for a JSONL/JSON file. Never
    raises — missing/unreadable files map to all-None."""
    try:
        if not p.exists():
            return {
                "jsonl_path": str(p),
                "jsonl_size_bytes": 0,
                "jsonl_last_modified": None,
            }
        st = p.stat()
        mtime = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat()
        return {
            "jsonl_path": str(p),
            "jsonl_size_bytes": int(st.st_size),
            "jsonl_last_modified": mtime,
        }
    except Exception as e:
        return {
            "jsonl_path": str(p),
            "jsonl_size_bytes": 0,
            "jsonl_last_modified": None,
            "error": str(e),
        }


@app.get("/system/persistence/status", tags=["system"])
async def system_persistence_status(authorization: str = Header(default="")) -> dict:
    """Report SQLite double-write status for the cost ledger and mandates store.

    Each section returns ``enabled`` (driven by env flag), ``db_path``,
    ``last_write_ts``, plus the JSONL source-of-truth file's path, size,
    and mtime. Each section is wrapped in try/except so a missing flag or
    path doesn't crash the endpoint — degraded fields surface as
    ``{enabled: false, error: ...}``.
    """
    _verify_strike_token(authorization)

    ncl_base = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
    default_db = str(ncl_base / "data" / "persistence" / "ncl.db")

    # ── cost_ledger section ─────────────────────────────────────────────
    cost_ledger: dict = {"enabled": False}
    try:
        cost_ledger["enabled"] = flags.cost_ledger_sqlite()
        cost_ledger["db_path"] = os.getenv("NCL_SQLITE_PATH") or default_db

        last_write_ts = None
        if cost_ledger["enabled"]:
            try:
                from ..persistence import get_store

                store = await get_store()
                async with store.acquire("read") as conn:
                    cur = conn.execute("SELECT ts FROM cost_ledger ORDER BY ts DESC LIMIT 1")
                    row = cur.fetchone()
                    if row is not None:
                        last_write_ts = row[0]
            except Exception as e:
                cost_ledger["sqlite_error"] = str(e)
        cost_ledger["last_write_ts"] = last_write_ts

        # JSONL source-of-truth
        jsonl_path = ncl_base / "data" / "costs" / "cost_ledger.jsonl"
        cost_ledger.update(_file_stat_block(jsonl_path))
    except Exception as e:
        cost_ledger = {"enabled": False, "error": str(e)}

    # ── mandates section ────────────────────────────────────────────────
    mandates: dict = {"enabled": False}
    try:
        mandates["enabled"] = flags.mandates_sqlite()
        mandates["db_path"] = os.getenv("NCL_SQLITE_PATH") or default_db

        last_write_ts = None
        if mandates["enabled"]:
            try:
                from ..persistence import get_store

                store = await get_store()
                async with store.acquire("read") as conn:
                    cur = conn.execute(
                        "SELECT updated_at FROM mandates ORDER BY updated_at DESC LIMIT 1"
                    )
                    row = cur.fetchone()
                    if row is not None:
                        last_write_ts = row[0]
            except Exception as e:
                mandates["sqlite_error"] = str(e)
        mandates["last_write_ts"] = last_write_ts

        # JSON source-of-truth (brain stores at data/mandates.json)
        json_path = ncl_base / "data" / "mandates.json"
        mandates.update(_file_stat_block(json_path))
    except Exception as e:
        mandates = {"enabled": False, "error": str(e)}

    # ── applied migrations (best-effort, doesn't gate on either flag) ───
    applied_migrations: list = []
    try:
        from ..persistence import get_store

        store = await get_store()
        applied_set = await store.applied_migrations()
        applied_migrations = sorted(applied_set)
    except Exception:
        # Don't surface as error — `applied_migrations: []` already says it.
        applied_migrations = []

    return {
        "cost_ledger": cost_ledger,
        "mandates": mandates,
        "applied_migrations": applied_migrations,
    }


# /feedback/source-authority and /feedback/source-authority/{source}/history
# moved to routers/feedback.py (W5-05) — joined the pipeline-side
# feedback router that owns POST /feedback, /feedback/synthesis, and
# /feedback/scan-now.


@app.get("/system/cold-start-ready", tags=["system"])
async def system_cold_start_ready() -> dict:
    """Unauthenticated smoke endpoint — is NCL operational right now?

    Runs a handful of sanity probes (memory units, cost-ledger replay,
    awarebot, working context, ChromaDB collections). Returns
    ``{ready: bool, checks: {...}, warnings: [...]}``. ``ready`` is True
    only when every individual check passes.

    Intentionally no auth: external monitors (ntfy heartbeats, uptime
    probes) need to poll this cheaply without credential rotation. The
    payload reveals only counts + booleans, no PII.
    """
    checks: dict = {}
    warnings: list[str] = []

    # 1. memory_units_count — from MemoryStore stats
    memory_units_count = 0
    try:
        if brain is not None and brain.memory_store is not None:
            stats = await brain.memory_store.get_stats()
            memory_units_count = int(stats.get("total_units", 0) or 0)
        else:
            warnings.append("brain or memory_store not initialized")
    except Exception as e:
        warnings.append(f"memory_store.get_stats failed: {e}")
    checks["memory_units_count"] = memory_units_count

    # 2. cost_ledger_replayed — has the tracker replayed today's spend?
    cost_ledger_replayed = False
    try:
        from ..cost_tracker import get_tracker

        tracker = await get_tracker()
        cost_ledger_replayed = bool(getattr(tracker, "_initialized", False))
        if not cost_ledger_replayed:
            warnings.append("cost tracker not yet initialized")
    except Exception as e:
        warnings.append(f"cost tracker init failed: {e}")
    checks["cost_ledger_replayed"] = cost_ledger_replayed

    # 3. awarebot_active — scheduler has an awarebot reference
    awarebot_active = False
    try:
        if _autonomous is not None:
            aw = getattr(_autonomous, "awarebot", None)
            awarebot_active = aw is not None
            if not awarebot_active:
                warnings.append("awarebot not initialized in scheduler")
        else:
            warnings.append("autonomous scheduler not initialized")
    except Exception as e:
        warnings.append(f"awarebot probe failed: {e}")
    checks["awarebot_active"] = awarebot_active

    # 4. working_context_loaded — the 6am/noon/11pm assembly has produced
    # a snapshot since boot. Yellow during the first few minutes after a
    # restart, before the loop ticks.
    working_context_loaded = False
    try:
        if _autonomous is not None:
            wc_window = getattr(_autonomous, "_working_context", None)
            if wc_window is not None:
                ctx = wc_window.get_current()
                working_context_loaded = (
                    ctx is not None and len(getattr(ctx, "items", []) or []) > 0
                )
        if not working_context_loaded:
            warnings.append("working context not assembled yet")
    except Exception as e:
        warnings.append(f"working context probe failed: {e}")
    checks["working_context_loaded"] = working_context_loaded

    # 5. chromadb_collections — typed ChromaDB collections live in the
    # MemoryStore. The store creates 6 typed + 1 legacy default; anything
    # < 1 indicates ChromaDB never initialized.
    chromadb_collections = 0
    try:
        if brain is not None and brain.memory_store is not None:
            ms = brain.memory_store
            cols = getattr(ms, "_chroma_collections", None)
            if isinstance(cols, dict):
                chromadb_collections = len(cols)
    except Exception as e:
        warnings.append(f"chromadb probe failed: {e}")
    checks["chromadb_collections"] = chromadb_collections

    ready = (
        memory_units_count > 0
        and cost_ledger_replayed
        and awarebot_active
        and working_context_loaded
        and chromadb_collections > 0
    )

    return {
        "ready": ready,
        "checks": checks,
        "warnings": warnings,
        "timestamp": datetime.now(timezone.utc).isoformat(),
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
# W8-A9: also stamp correlation IDs on the outer gateway so the contextvar
# is set before the request reaches the mounted inner `app`. Mounting does
# not propagate middleware in Starlette, so both layers need their own.
versioned_app.add_middleware(_CorrelationMiddleware)
versioned_app.mount("/v1", app)  # All routes available under /v1/...
versioned_app.mount("/", app)  # Backwards compat: root routes still work


def main() -> None:
    """Main entry point."""
    import signal

    import uvicorn

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


# ─── Dependency-injection factories (W8-A8 DI proof) ───────────────────
# These let routers use FastAPI Depends() instead of the legacy
# `from .. import routes as _routes` lazy-import pattern. Each factory
# returns the live singleton from the routes module's global namespace.
# First adopted by routers/feedback.py (W8-A8). Other routers continue to
# use the lazy-import shim until they are individually converted.
#
# W10B-3 (2026-05-24): canonical home moved to runtime.api.deps; the
# factories below are kept for back-compat with any external caller doing
# ``from runtime.api.routes import get_brain``. New routers should import
# from ``..deps`` directly. See ``runtime/api/deps.py`` for the source.
from . import deps as _deps  # noqa: F401,E402  (W10B-3 back-compat re-export marker)


def get_brain():
    """DI factory: returns the live NCLBrain singleton (may be None pre-lifespan)."""
    return brain


def get_intelligence():
    """DI factory: returns the live IntelligenceEngine singleton.

    Note: the module-level global is ``_intelligence`` (underscore-prefixed)
    but the public DI accessor drops the underscore for FastAPI ergonomics.
    May be None before the lifespan handler completes.
    """
    return _intelligence


def get_autonomous():
    """DI factory: returns the live AutonomousScheduler singleton (may be None pre-lifespan)."""
    return _autonomous


def verify_strike_token_dep(authorization: str = Header(default="")):
    """DI factory: verifies the strike-point auth token.

    Wraps :func:`_verify_strike_token` so handlers can simply add
    ``_: None = Depends(verify_strike_token_dep)`` to their signature instead
    of pulling the Authorization header and calling the verifier inline.
    Raises 401 (missing header) or 403 (invalid token) on failure.
    """
    _verify_strike_token(authorization)


if __name__ == "__main__":
    main()
