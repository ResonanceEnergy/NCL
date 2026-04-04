"""FastAPI routes for NCL brain service."""

import asyncio
import os
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, BackgroundTasks, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import load_config, create_config_file
from ..ncl_brain.brain import NCLBrain
from ..ncl_brain.models import (
    PumpPrompt,
    Mandate,
    CouncilSession,
    FeedbackReport,
    PillarType,
    MandateStatus,
)

# Global brain instance
brain: NCLBrain | None = None
config = load_config()

# Strike point authentication token — load from config (.env) FIRST, then env var, then auto-gen
STRIKE_TOKEN = config.strike_auth_token or os.getenv("STRIKE_AUTH_TOKEN", "")
if not STRIKE_TOKEN:
    # Auto-generate and log so NATRIX can copy it into the iOS Shortcut
    STRIKE_TOKEN = secrets.token_urlsafe(32)
    import logging
    logging.getLogger("ncl.strike").warning(
        f"No STRIKE_AUTH_TOKEN set. Auto-generated: {STRIKE_TOKEN} — "
        f"Set this in .env and in the iOS Shortcut."
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan context manager for startup/shutdown."""
    global brain

    # Startup
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

    yield

    # Shutdown
    if brain:
        await brain.shutdown()


app = FastAPI(
    title=config.service_name,
    version=config.service_version,
    description="NCL Brain - Think, Research, Plan, Decide",
    lifespan=lifespan,
)

# CORS middleware
allowed_origins = os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:8000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Health check
@app.get("/health")
async def health_check() -> dict:
    """Health check endpoint."""
    if not brain:
        raise HTTPException(status_code=503, detail="Service not initialized")
    return await brain.health_check()


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
    prompt: PumpPrompt,
    auto_flow: bool = Query(default=True, description="Run council→mandate pipeline (stops before NCC dispatch)"),
    authorization: str = Header(default=""),
) -> dict:
    """
    Receive pump prompt from iPhone via Grok.

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

    Args:
        prompt: PumpPrompt from Grok
        auto_flow: If True, runs pipeline up to approval gate; if False, just stores
        authorization: Bearer token for authentication

    Returns:
        Dict with council output, consensus, and proposed mandates awaiting approval
    """
    _verify_strike_token(authorization)

    if not brain:
        raise HTTPException(status_code=503, detail="Service not initialized")

    result = await brain.receive_pump_prompt(prompt, auto_flow=auto_flow)
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
    for pump_id, data in brain._pending_dispatches.items():
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


from pydantic import BaseModel


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


# Council endpoints
@app.post("/council/spawn")
async def spawn_council_session(
    topic: str, prompt: str, members: list[str] | None = None
) -> dict:
    """
    Spawn a new council debate session.

    Args:
        topic: Debate topic
        prompt: Chair's prompt to members
        members: Optional list of member names

    Returns:
        Dict with session details
    """
    if not brain:
        raise HTTPException(status_code=503, detail="Service not initialized")

    session = await brain.spawn_council_session(topic, prompt, members)
    return {
        "session_id": session.session_id,
        "topic": session.topic,
        "status": session.status.value,
        "consensus": session.consensus,
        "recommendations": session.recommendations,
    }


@app.get("/council/session/{session_id}")
async def get_council_session(session_id: str) -> dict:
    """
    Get council session details.

    Args:
        session_id: Council session ID

    Returns:
        Session details
    """
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
) -> dict:
    """
    Create a new mandate.

    Args:
        pillar: Target pillar (ncl, ncc, brs, aac)
        priority: Priority 1-10
        title: Mandate title
        objective: Strategic objective
        success_criteria: List of success criteria
        deadline: Optional ISO8601 deadline
        source_pump_id: Optional source pump ID

    Returns:
        Created mandate dict
    """
    if not brain:
        raise HTTPException(status_code=503, detail="Service not initialized")

    try:
        pillar_enum = PillarType(pillar)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid pillar: {pillar}")

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
async def list_mandates(pillar: str | None = None, status: str | None = None) -> dict:
    """
    List mandates with optional filters.

    Args:
        pillar: Filter by pillar
        status: Filter by status

    Returns:
        Dict with mandates list
    """
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
async def get_mandate(mandate_id: str) -> dict:
    """
    Get mandate details.

    Args:
        mandate_id: Mandate ID

    Returns:
        Mandate details
    """
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
async def complete_mandate(mandate_id: str, notes: str | None = None) -> dict:
    """
    Mark mandate as completed.

    Args:
        mandate_id: Mandate ID
        notes: Optional completion notes

    Returns:
        Status dict
    """
    if not brain:
        raise HTTPException(status_code=503, detail="Service not initialized")

    await brain.complete_mandate(mandate_id, notes)
    return {"mandate_id": mandate_id, "status": "completed"}


# Memory endpoints
@app.get("/memory/query")
async def query_memory(
    tags: list[str] | None = None,
    importance_threshold: float = 0.0,
    days_back: int | None = None,
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
    if not brain:
        raise HTTPException(status_code=503, detail="Service not initialized")

    return await brain.query_memory(
        tags=tags,
        importance_threshold=importance_threshold,
        days_back=days_back,
    )


# Feedback endpoint
@app.post("/feedback")
async def receive_feedback(feedback: FeedbackReport) -> dict:
    """
    Receive feedback report from downstream pillar.

    Args:
        feedback: FeedbackReport

    Returns:
        Dict with report_id
    """
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
async def receive_synthesis(synthesis: dict) -> dict:
    """
    Receive Claude-validated synthesis from feedback loop server.

    This is the ONLY path for interpreted feedback to enter NCL.
    Raw data never reaches here — only synthesized insights.

    Args:
        synthesis: Synthesis result dict from feedback-loop server

    Returns:
        Acceptance status
    """
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

    return {
        "status": "accepted",
        "synthesis_id": synthesis_id,
        "contradictions_flagged": len(contradictions),
        "adjustments_queued": len(mandate_adjustments),
    }


# Awarebot endpoints
@app.post("/awarebot/scan")
async def run_awarebot_scan(queries: list[str]) -> dict:
    """
    Run Awarebot intelligence scan.

    Args:
        queries: List of search queries

    Returns:
        Scan results
    """
    if not brain:
        raise HTTPException(status_code=503, detail="Service not initialized")

    return await brain.run_awarebot_scan(queries)


# Prediction endpoint
@app.post("/prediction")
async def run_prediction(topic: str) -> dict:
    """
    Run Future Predictor ensemble forecast.

    Args:
        topic: Prediction topic

    Returns:
        Prediction results
    """
    if not brain:
        raise HTTPException(status_code=503, detail="Service not initialized")

    return await brain.run_prediction(topic)


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


# Error handlers
@app.exception_handler(Exception)
async def exception_handler(request, exc: Exception):
    """Global exception handler."""
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "detail": str(exc) if config.debug else "An error occurred",
        },
    )


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
        app,
        host=config.host,
        port=config.port,
        log_level="info" if not config.debug else "debug",
    )


if __name__ == "__main__":
    main()
