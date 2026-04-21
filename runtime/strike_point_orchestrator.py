"""
Strike Point Orchestrator — NCL ↔ NCC Interface with AAC/BRS Data Coordination

The central nervous system bridge between NCL (brain) and NCC (execution).
Handles the full lifecycle:

1. Receives approved mandates from NCL brain
2. Dispatches to NCC with validation against ncl-ncc-contract
3. Triggers execution_loop.py for coding tasks
4. Coordinates AAC market signals and BRS revenue data into execution context
5. Receives execution feedback and routes back to NCL + FirstStrike (iPhone)
6. Sends push notifications to NATRIX at key lifecycle points

This is the missing orchestration layer between NCL's approval gate
and NCC's execution infrastructure.

Usage:
    # As a service (run alongside NCL brain):
    python3 -m runtime.strike_point_orchestrator

    # Dispatch a single mandate:
    python3 -m runtime.strike_point_orchestrator --dispatch MANDATE-2026-009

    # Check pipeline status:
    python3 -m runtime.strike_point_orchestrator --status
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import logging.handlers
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ── Config ────────────────────────────────────────────────────────────────

NCL_BASE = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
NCC_BASE = Path.home() / "Projects" / "ncc-server"
AAC_BASE = Path.home() / "Projects" / "AAC-v2"
BRS_BASE = Path.home() / "Projects" / "BRS-v2"
FIRST_STRIKE_BASE = Path.home() / "Projects" / "FirstStrike"

# Pipeline paths
MANDATE_INPUT = NCL_BASE / "mandate-generation" / "input"
MANDATE_OUTPUT = NCL_BASE / "mandate-generation" / "output"
EXEC_PIPELINE = NCL_BASE / "workspaces" / "execution-pipeline"
FEEDBACK_DIR = NCL_BASE / "feedback-synthesis" / "ncc-reports"
AAC_INTELLIGENCE = AAC_BASE / "war-room" / "intelligence"
BRS_SIGNALS = NCL_BASE / "feedback-synthesis" / "brs-reports"
AAC_SIGNALS = NCL_BASE / "feedback-synthesis" / "aac-reports"
WORKING_FILES = EXEC_PIPELINE / "03-Execution" / "working-files"


def _ensure_directories() -> None:
    """Create all required pipeline directories on startup."""
    dirs = [
        MANDATE_INPUT,
        MANDATE_OUTPUT,
        EXEC_PIPELINE / "01-Input",
        EXEC_PIPELINE / "02-Planning",
        EXEC_PIPELINE / "03-Execution" / "working-files",
        EXEC_PIPELINE / "04-Review",
        EXEC_PIPELINE / "05-Output",
        FEEDBACK_DIR,
        AAC_INTELLIGENCE,
        NCL_BASE / "notifications",
        NCC_BASE / "mandate-intake",
        NCL_BASE / "logs",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)


# Auto-create all directories on import
_ensure_directories()

# Service endpoints
NCL_BRAIN_URL = os.getenv("NCL_BRAIN_URL", "http://localhost:8800")
NCC_SERVER_URL = os.getenv("NCC_SERVER_URL", "http://localhost:8765")
RELAY_URL = os.getenv("RELAY_URL", "https://localhost:8443")
STRIKE_TOKEN = os.getenv("STRIKE_AUTH_TOKEN", "")

# Pushover notification (iPhone push alerts)
PUSHOVER_TOKEN = os.getenv("PUSHOVER_APP_TOKEN", "")
PUSHOVER_USER = os.getenv("PUSHOVER_USER_KEY", "")

# ntfy.sh — free push notifications, no account needed
# Install ntfy app on iPhone → subscribe to this topic → done
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "ncl-natrix-intel-7x9k")
NTFY_SERVER = os.getenv("NTFY_SERVER", "https://ntfy.sh")

# ── Logging ───────────────────────────────────────────────────────────────

LOG_DIR = NCL_BASE / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.handlers.RotatingFileHandler(
            LOG_DIR / "strike-point-orchestrator.log",
            maxBytes=5 * 1024 * 1024,
            backupCount=5,
        ),
    ],
)
log = logging.getLogger("ncl.strike-point")


# ── Notification System ───────────────────────────────────────────────────

async def notify_natrix(title: str, message: str, priority: int = 0) -> bool:
    """
    Send push notification to NATRIX's iPhone.

    Tries ntfy.sh first (free, no account needed), then Pushover fallback.

    Priority levels:
      -2 = no notification
      -1 = quiet
       0 = normal
       1 = high priority (bypasses quiet hours)
       2 = emergency (repeats until acknowledged)
    """
    sent = False

    # 1. Try ntfy.sh (free, no config needed)
    if NTFY_TOPIC:
        try:
            import httpx
            ntfy_priority = {-2: 1, -1: 2, 0: 3, 1: 4, 2: 5}.get(priority, 3)
            # Strip non-ASCII for ntfy compatibility
            safe_title = title.encode("ascii", "replace").decode("ascii")
            safe_message = message.encode("utf-8")
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{NTFY_SERVER}/{NTFY_TOPIC}",
                    content=safe_message,
                    headers={
                        "Content-Type": "text/plain; charset=utf-8",
                        "Title": safe_title,
                        "Priority": str(ntfy_priority),
                        "Tags": "brain,zap" if priority >= 1 else "brain",
                        "Click": f"{NCL_BRAIN_URL}/app",
                    },
                )
                resp.raise_for_status()
                log.info(f"ntfy.sh notification sent: {title}")
                sent = True
        except Exception as e:
            log.warning(f"ntfy.sh notification failed: {e}")

    # 2. Try Pushover if configured
    if not sent and PUSHOVER_TOKEN and PUSHOVER_USER:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    "https://api.pushover.net/1/messages.json",
                    data={
                        "token": PUSHOVER_TOKEN,
                        "user": PUSHOVER_USER,
                        "title": f"NARTIX: {title}",
                        "message": message,
                        "priority": priority,
                        "sound": "cosmic" if priority >= 1 else "pushover",
                    },
                )
                resp.raise_for_status()
                log.info(f"Pushover notification sent: {title}")
                sent = True
        except Exception as e:
            log.warning(f"Pushover notification failed: {e}")

    # 3. File fallback
    if not sent:
        log.info(f"[NOTIFY] (file fallback) {title}: {message}")
        _write_notification_file(title, message, priority)

    return sent


def _write_notification_file(title: str, message: str, priority: int) -> None:
    """Fallback: write notification to file for polling by iPhone/relay."""
    notif_dir = NCL_BASE / "notifications"
    notif_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    notif = {
        "id": f"notif-{ts}",
        "title": title,
        "message": message,
        "priority": priority,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "acknowledged": False,
    }
    path = notif_dir / f"notif-{ts}.json"
    path.write_text(json.dumps(notif, indent=2))
    log.info(f"Notification saved to file → {path.name}")


async def notify_intelligence_brief(brief: dict, top_n: int = 3) -> bool:
    """
    Push a structured intelligence "tweet" to NATRIX's iPhone.

    This is the primary delivery mechanism for intelligence briefs.
    Sends a compact push notification with the executive summary headline,
    top signals as one-liners, and a URL link back to the full report.

    Args:
        brief: IntelBrief dict (from brief.model_dump() or raw dict)
        top_n: Number of top signals to include in the push
    """
    brief_id = brief.get("brief_id", "unknown")
    brief_type = brief.get("brief_type", "daily").upper()
    total_signals = brief.get("total_signals_processed", 0)
    exec_summary = brief.get("executive_summary", "")

    # Build a punchy executive summary — lead with the "so what"
    headline = exec_summary[:200] if exec_summary else f"{brief_type} brief — {total_signals} signals processed"

    # Extract predictions / key takeaways for context
    predictions = brief.get("predictions", [])
    sectors = brief.get("sectors", [])
    prediction_line = ""
    if predictions:
        top_pred = predictions[0] if isinstance(predictions[0], str) else predictions[0].get("text", str(predictions[0]))
        prediction_line = f"\n\n🔮 {str(top_pred)[:120]}"

    # Top signal one-liners — include brief context snippet
    top_signals = brief.get("top_signals", [])[:top_n]
    signal_lines = []
    for sig in top_signals:
        title = sig.get("title", "")[:50]
        direction = sig.get("direction", "neutral")
        source = sig.get("source", "")
        content = sig.get("content", "") or sig.get("description", "")
        snippet = f" — {content[:60]}" if content else ""
        arrow = {"bullish": "▲", "bearish": "▼", "emerging": "★", "expanding": "↑", "contracting": "↓"}.get(direction, "●")
        signal_lines.append(f"{arrow} {title}{snippet}")

    # Risk alerts — include the first alert's actual text
    risk_alerts = brief.get("risk_alerts", [])
    risk_line = ""
    if risk_alerts:
        first_risk = risk_alerts[0] if isinstance(risk_alerts[0], str) else risk_alerts[0].get("text", str(risk_alerts[0]))
        risk_line = f"\n\n⚠ RISK: {str(first_risk)[:100]}"
        if len(risk_alerts) > 1:
            risk_line += f" (+{len(risk_alerts)-1} more)"

    # Compose push message
    message = headline
    if signal_lines:
        message += "\n\n" + "\n".join(signal_lines)
    message += prediction_line
    message += risk_line
    message += f"\n\n📊 {NCL_BRAIN_URL}/app"

    # Determine priority based on brief type and risk alerts
    if brief_type == "ALERT" or len(risk_alerts) >= 3:
        priority = 1  # high — bypasses quiet hours
    elif brief_type == "STRATEGIC_REVIEW":
        priority = 0  # normal
    else:
        priority = 0  # daily = normal

    # Always write for FirstStrike polling
    _write_intel_notification(brief_id, brief_type, message, brief)

    sent = False

    # 1. Try ntfy.sh (free, no config)
    if NTFY_TOPIC:
        try:
            import httpx
            ntfy_priority = 4 if priority >= 1 else 3
            safe_title = f"NCL INTEL - {brief_type}"
            safe_message = message.encode("utf-8")
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{NTFY_SERVER}/{NTFY_TOPIC}",
                    content=safe_message,
                    headers={
                        "Content-Type": "text/plain; charset=utf-8",
                        "Title": safe_title,
                        "Priority": str(ntfy_priority),
                        "Tags": "rotating_light,chart_with_upwards_trend" if priority >= 1 else "brain,chart_with_upwards_trend",
                        "Click": f"{NCL_BRAIN_URL}/app",
                    },
                )
                resp.raise_for_status()
                log.info(f"ntfy.sh intel brief push sent: {brief_type} ({brief_id})")
                sent = True
        except Exception as e:
            log.warning(f"ntfy.sh intel push failed: {e}")

    # 2. Try Pushover if configured
    if not sent and PUSHOVER_TOKEN and PUSHOVER_USER:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    "https://api.pushover.net/1/messages.json",
                    data={
                        "token": PUSHOVER_TOKEN,
                        "user": PUSHOVER_USER,
                        "title": f"NCL INTEL — {brief_type}",
                        "message": message,
                        "priority": priority,
                        "sound": "cosmic" if priority >= 1 else "magic",
                        "url": f"{NCL_BRAIN_URL}/app",
                        "url_title": "View Full Report",
                        "html": 1,
                    },
                )
                resp.raise_for_status()
                log.info(f"Pushover intel brief push sent: {brief_type} ({brief_id})")
                sent = True
        except Exception as e:
            log.warning(f"Pushover intel push failed: {e}")

    if not sent:
        _write_notification_file(f"Intel {brief_type}", message, priority)

    return sent


async def notify_intel_signal_alert(signal: dict) -> bool:
    """
    Push a single high-importance signal as an immediate alert.

    Used when a signal exceeds the alert threshold (importance > 80)
    and needs NATRIX's attention before the next scheduled brief.

    Args:
        signal: IntelSignal dict
    """
    title = signal.get("title", "Unknown signal")
    source = signal.get("source", "")
    direction = signal.get("direction", "neutral")
    change_pct = signal.get("change_pct")
    confidence = signal.get("confidence", 0)

    arrow = {"bullish": "▲", "bearish": "▼", "emerging": "★"}.get(direction, "●")
    change_str = f" ({'+' if change_pct > 0 else ''}{change_pct:.1f}%)" if change_pct is not None else ""

    # Build a human-readable punchline from signal content
    content = signal.get("content", "") or signal.get("description", "") or signal.get("summary", "")
    punchline = content[:200].strip() if content else ""
    # If no content blob, synthesize a readable sentence from metadata
    if not punchline:
        if direction == "bullish":
            punchline = f"{title} is showing strong upward momentum{change_str}."
        elif direction == "bearish":
            punchline = f"{title} is trending down{change_str} — monitor for risk exposure."
        elif direction == "emerging":
            punchline = f"New trend detected: {title}. Early signal, confidence {confidence:.0%}."
        else:
            punchline = f"{title}{change_str} flagged by {source} — review recommended."

    message = (
        f"{arrow} {title}{change_str}\n\n"
        f"{punchline}\n\n"
        f"Source: {source} | Confidence: {confidence:.0%} | Direction: {direction}\n"
        f"📊 {NCL_BRAIN_URL}/app"
    )

    return await notify_natrix(
        f"🚨 {title[:60]}",
        message,
        priority=1,
    )


def _write_intel_notification(
    brief_id: str,
    brief_type: str,
    message: str,
    brief_data: dict,
) -> None:
    """
    Write structured intelligence notification for FirstStrike relay polling.

    FirstStrike can poll /notifications/intel-*.json to pick up briefs
    and present them with action buttons on iPhone.
    """
    notif_dir = NCL_BASE / "notifications" / "intelligence"
    notif_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

    # Extract actionable signal IDs for FirstStrike action buttons
    top_signal_ids = [
        sig.get("signal_id", "") for sig in brief_data.get("top_signals", [])[:5]
    ]

    notif = {
        "id": f"intel-{ts}",
        "brief_id": brief_id,
        "brief_type": brief_type,
        "message": message,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "acknowledged": False,
        # FirstStrike action options
        "actions": [
            {
                "id": "view_report",
                "label": "View Full Report",
                "type": "url",
                "url": f"{NCL_BRAIN_URL}/app",
            },
            {
                "id": "escalate_to_strike_point",
                "label": "Send to STRIKE-POINT",
                "type": "api_call",
                "endpoint": f"{NCL_BRAIN_URL}/intelligence/escalate",
                "method": "POST",
                "body": {"brief_id": brief_id, "signal_ids": top_signal_ids},
            },
            {
                "id": "acknowledge",
                "label": "Acknowledge",
                "type": "api_call",
                "endpoint": f"{NCL_BRAIN_URL}/intelligence/ack/{brief_id}",
                "method": "POST",
            },
        ],
        # Compact brief data for inline display
        "brief_summary": {
            "executive_summary": brief_data.get("executive_summary", "")[:280],
            "total_signals": brief_data.get("total_signals_processed", 0),
            "risk_alerts": brief_data.get("risk_alerts", []),
            "source_counts": brief_data.get("source_counts", {}),
        },
    }

    path = notif_dir / f"intel-{ts}.json"
    path.write_text(json.dumps(notif, indent=2, default=str))
    log.info(f"Intel notification saved → {path.name} (actions: view/escalate/ack)")


async def notify_relay_completion(pump_id: str, feedback: dict) -> bool:
    """
    Send completion notification back to FirstStrike relay for iPhone delivery.
    """
    try:
        import httpx
        async with httpx.AsyncClient(timeout=15.0, verify=False) as client:
            resp = await client.post(
                f"{RELAY_URL}/responses",
                headers={"Authorization": f"Bearer {STRIKE_TOKEN}"},
                json={
                    "pump_id": pump_id,
                    "status": feedback.get("status", "complete"),
                    "summary": feedback.get("summary", ""),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )
            resp.raise_for_status()
            log.info(f"Completion relayed to FirstStrike for pump {pump_id}")
            return True
    except Exception as e:
        log.warning(f"Relay notification failed for {pump_id}: {e}")
        return False


# ── AAC/BRS Data Coordination ────────────────────────────────────────────

def gather_aac_context() -> dict:
    """
    Pull latest AAC War Room intelligence for execution context.
    Provides market signals and risk assessments to the coding pipeline.
    """
    context = {"market_signals": [], "risk_level": "NORMAL", "positions": []}

    # Check AAC intelligence directory
    if AAC_INTELLIGENCE.exists():
        intel_files = sorted(AAC_INTELLIGENCE.glob("council-intel-*.json"), reverse=True)
        if intel_files:
            try:
                latest = json.loads(intel_files[0].read_text())
                context["market_signals"] = latest.get("signals", [])
                log.info(f"Loaded {len(context['market_signals'])} AAC signals from {intel_files[0].name}")
            except (json.JSONDecodeError, OSError) as e:
                log.warning(f"Failed to load AAC intelligence: {e}")

    # Check AAC feedback reports
    if AAC_SIGNALS.exists():
        reports = sorted(AAC_SIGNALS.glob("*.yaml"), reverse=True)
        if reports:
            log.info(f"Found {len(reports)} AAC feedback reports")

    return context


def gather_brs_context() -> dict:
    """
    Pull latest BRS revenue signals for execution context.
    Provides economic data to inform priority decisions.
    """
    context = {"revenue_signals": [], "active_leads": 0, "monthly_revenue": 0}

    if BRS_SIGNALS.exists():
        reports = sorted(BRS_SIGNALS.glob("*.yaml"), reverse=True)
        if reports:
            log.info(f"Found {len(reports)} BRS feedback reports")

    return context


def build_execution_context(mandate: dict) -> dict:
    """
    Build rich execution context by combining mandate data with
    AAC market intelligence and BRS revenue signals.
    """
    aac = gather_aac_context()
    brs = gather_brs_context()

    return {
        "mandate": mandate,
        "aac_context": aac,
        "brs_context": brs,
        "environment": {
            "machine": "Mac Mini M4 Pro, 64GB",
            "python": "3.12+",
            "services": {
                "ncl_brain": NCL_BRAIN_URL,
                "ncc_server": NCC_SERVER_URL,
                "paperclip": "http://localhost:3100",
                "ollama": "http://localhost:11434",
            },
        },
        "gathered_at": datetime.now(timezone.utc).isoformat(),
    }


# ── Mandate Dispatch ─────────────────────────────────────────────────────

async def dispatch_mandate(mandate: dict) -> dict:
    """
    Dispatch an approved mandate from NCL to NCC.

    1. Validates mandate against ncl-ncc-contract schema
    2. Gathers AAC/BRS context for enrichment
    3. Sends to NCC server (creates /mandate/intake if needed)
    4. Triggers execution_loop.py for coding mandates
    5. Notifies NATRIX that execution has started
    """
    mandate_id = mandate.get("mandate_id", "unknown")
    pump_id = mandate.get("pump_id", "")
    pillar = mandate.get("pillar", "NCC")
    title = mandate.get("title", "Untitled mandate")

    log.info(f"Dispatching mandate {mandate_id} to {pillar}")

    # Step 1: Validate
    validation = _validate_mandate(mandate)
    if not validation["valid"]:
        log.error(f"Mandate validation failed: {validation['errors']}")
        await notify_natrix(
            f"❌ Mandate Rejected — {title[:40]}",
            f"{title}\n\n"
            f"Validation failed: {', '.join(validation['errors'])}\n\n"
            f"Fix and resubmit via pump.",
            priority=1,
        )
        return {"status": "rejected", "errors": validation["errors"]}

    # Step 2: Enrich with AAC/BRS context
    execution_context = build_execution_context(mandate)

    # Step 3: Write enriched mandate to NCC intake
    ncc_intake_dir = NCC_BASE / "mandate-intake"
    ncc_intake_dir.mkdir(parents=True, exist_ok=True)
    intake_file = ncc_intake_dir / f"{mandate_id}.json"
    intake_file.write_text(json.dumps(execution_context, indent=2, default=str))
    log.info(f"Mandate written to NCC intake → {intake_file.name}")

    # Step 4: Also try HTTP dispatch to NCC (if endpoint exists)
    http_result = await _try_ncc_http_dispatch(mandate)

    # Step 5: Write to execution pipeline input
    exec_input = EXEC_PIPELINE / "01-Input"
    exec_input.mkdir(parents=True, exist_ok=True)
    exec_pump = exec_input / f"pump-{mandate_id}.json"
    exec_pump.write_text(json.dumps({
        "pump_id": pump_id or mandate_id,
        "mandate_id": mandate_id,
        "raw_intent": mandate.get("objective", title),
        "target_pillar": pillar,
        "priority": mandate.get("priority_level", "P2"),
        "aac_context": execution_context.get("aac_context", {}),
        "brs_context": execution_context.get("brs_context", {}),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }, indent=2, default=str))

    # Step 6: Auto-trigger execution loop for coding mandates
    if _is_coding_mandate(mandate):
        log.info(f"Coding mandate detected — launching execution loop")
        _trigger_execution_loop(pump_id or mandate_id)

    # Step 7: Notify NATRIX — include objective context so the push has substance
    objective = mandate.get("objective", "") or title
    priority_lvl = mandate.get("priority_level", "P2")
    await notify_natrix(
        f"⚡ {title[:60]}",
        f"Mandate dispatched to {pillar} ({priority_lvl})\n\n"
        f"{objective[:200]}\n\n"
        f"📋 {NCL_BRAIN_URL}/app",
    )

    return {
        "status": "dispatched",
        "mandate_id": mandate_id,
        "ncc_intake_file": str(intake_file),
        "http_dispatch": http_result,
        "execution_triggered": _is_coding_mandate(mandate),
    }


def _validate_mandate(mandate: dict) -> dict:
    """Validate mandate against ncl-ncc-contract schema."""
    errors = []

    mandate_id = mandate.get("mandate_id", "")
    if not mandate_id or not mandate_id.startswith("MANDATE-"):
        errors.append(f"Invalid mandate_id format: '{mandate_id}' (expected MANDATE-YYYY-NNN)")

    priority = mandate.get("priority_level", "")
    if priority not in ("P1", "P2", "P3", "P4"):
        errors.append(f"Invalid priority: '{priority}' (expected P1-P4)")

    pillar = mandate.get("pillar", "")
    if pillar.upper() not in ("NCL", "NCC", "BRS", "AAC"):
        errors.append(f"Invalid pillar: '{pillar}' (expected NCL/NCC/BRS/AAC)")

    if not mandate.get("title") and not mandate.get("objective"):
        errors.append("Missing title or objective")

    return {"valid": len(errors) == 0, "errors": errors}


def _is_coding_mandate(mandate: dict) -> bool:
    """Check if this mandate involves coding work (should trigger execution loop)."""
    title = (mandate.get("title", "") + " " + mandate.get("objective", "")).lower()
    coding_keywords = [
        "build", "ship", "code", "implement", "deploy", "fix", "create",
        "develop", "script", "module", "service", "api", "endpoint",
        "pipeline", "automation", "dashboard",
    ]
    return any(kw in title for kw in coding_keywords)


async def _try_ncc_http_dispatch(mandate: dict) -> dict:
    """Try to dispatch via NCC server HTTP API. Returns status."""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=15.0) as client:
            # Try the event endpoint (NCC's actual ingestion point)
            resp = await client.post(
                f"{NCC_SERVER_URL}/event",
                json={
                    "type": "mandate_dispatch",
                    "mandate_id": mandate.get("mandate_id"),
                    "pillar": mandate.get("pillar"),
                    "title": mandate.get("title"),
                    "priority": mandate.get("priority_level", "P2"),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )
            resp.raise_for_status()
            log.info("NCC HTTP dispatch succeeded via /event")
            return {"method": "http", "status": "delivered", "endpoint": "/event"}
    except Exception as e:
        log.warning(f"NCC HTTP dispatch failed: {e} — using file-based intake")
        return {"method": "file", "status": "file_only", "reason": str(e)}


def _trigger_execution_loop(pump_id: str) -> None:
    """Launch execution_loop.py as a background process."""
    try:
        cmd = [
            sys.executable, "-m", "runtime.execution_loop", pump_id,
        ]
        proc = subprocess.Popen(
            cmd,
            cwd=str(NCL_BASE),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        log.info(f"Execution loop launched for {pump_id} (PID: {proc.pid})")
    except Exception as e:
        log.error(f"Failed to launch execution loop: {e}")


# ── Feedback Processing ──────────────────────────────────────────────────

async def process_execution_feedback(pump_id: str) -> dict:
    """
    Process completed execution feedback and route it:
    1. Read feedback from 05-Output/
    2. POST to NCL brain API
    3. Save to feedback-synthesis/ncc-reports/
    4. Notify NATRIX via Pushover
    5. Send completion to FirstStrike relay for iPhone
    """
    feedback_file = EXEC_PIPELINE / "05-Output" / f"feedback-{pump_id}.json"
    if not feedback_file.exists():
        log.warning(f"No feedback file found for {pump_id}")
        return {"status": "not_found"}

    feedback = json.loads(feedback_file.read_text())
    status = feedback.get("status", "unknown")
    summary = feedback.get("summary", "")

    log.info(f"Processing feedback for {pump_id}: {status}")

    # 1. POST to NCL brain API
    brain_result = await _post_feedback_to_brain(pump_id, feedback)

    # 2. Save to feedback-synthesis
    FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)
    report_file = FEEDBACK_DIR / f"exec-report-{pump_id}-{datetime.now(timezone.utc).strftime('%Y%m%d')}.json"
    report_file.write_text(json.dumps({
        "report_id": f"NCC-EXEC-{pump_id}",
        "source": "NCC",
        "pump_id": pump_id,
        "status": status,
        "summary": summary,
        "artifacts": feedback.get("artifacts", []),
        "metrics": feedback.get("metrics", {}),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }, indent=2))
    log.info(f"Feedback saved to {report_file.name}")

    # 3. Notify NATRIX — include the actual summary so the push tells you what happened
    emoji = "✅" if status == "complete" else "⚠️" if status == "escalated" else "📋"
    artifacts = feedback.get("artifacts", [])
    artifact_line = f"\n\nArtifacts: {', '.join(str(a) for a in artifacts[:3])}" if artifacts else ""
    await notify_natrix(
        f"{emoji} {status.title()}: {summary[:50]}",
        f"{summary[:300]}{artifact_line}\n\n"
        f"📊 {NCL_BRAIN_URL}/app",
        priority=1 if status == "escalated" else 0,
    )

    # 4. Send to FirstStrike relay
    await notify_relay_completion(pump_id, feedback)

    return {
        "status": "processed",
        "pump_id": pump_id,
        "brain_notified": brain_result,
        "natrix_notified": True,
        "relay_notified": True,
    }


async def _post_feedback_to_brain(pump_id: str, feedback: dict) -> bool:
    """POST execution feedback to NCL brain API."""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{NCL_BRAIN_URL}/feedback",
                headers={"Authorization": f"Bearer {STRIKE_TOKEN}"},
                json={
                    "pump_id": pump_id,
                    "source": "NCC",
                    "status": feedback.get("status"),
                    "summary": feedback.get("summary"),
                    "metrics": feedback.get("metrics", {}),
                },
            )
            resp.raise_for_status()
            log.info("Feedback posted to NCL brain API")
            return True
    except Exception as e:
        log.warning(f"Brain API feedback POST failed: {e}")
        return False


# ── Pipeline Status ───────────────────────────────────────────────────────

def get_pipeline_status() -> dict:
    """Get current status of the full First Strike → NCL → NCC pipeline."""
    status = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "stages": {},
    }

    # Stage 1: Pending pump prompts
    pending_pumps = list(MANDATE_INPUT.glob("pump-*.json")) + list(MANDATE_INPUT.glob("RLY-*.json"))
    status["stages"]["1_first_strike_input"] = {
        "pending_pumps": len(pending_pumps),
        "latest": sorted(pending_pumps, reverse=True)[0].name if pending_pumps else None,
    }

    # Stage 2: Active mandates
    mandate_files = list(MANDATE_OUTPUT.glob("mandate-*.json"))
    status["stages"]["2_mandate_output"] = {
        "total_mandates": len(mandate_files),
    }

    # Stage 3: Execution pipeline
    exec_input = list((EXEC_PIPELINE / "01-Input").glob("pump-*.json")) if (EXEC_PIPELINE / "01-Input").exists() else []
    working = list(WORKING_FILES.glob("*")) if WORKING_FILES.exists() else []
    status["stages"]["3_execution"] = {
        "queued": len(exec_input),
        "working_files": len(working),
        "signed_off": (EXEC_PIPELINE / "03-Execution" / "signed-off.md").exists(),
    }

    # Stage 4: Feedback
    feedback_files = list((EXEC_PIPELINE / "05-Output").glob("feedback-*.json")) if (EXEC_PIPELINE / "05-Output").exists() else []
    status["stages"]["4_feedback"] = {
        "completed_feedbacks": len(feedback_files),
    }

    # Stage 5: Notifications
    notif_dir = NCL_BASE / "notifications"
    notifs = list(notif_dir.glob("notif-*.json")) if notif_dir.exists() else []
    unacked = sum(1 for n in notifs if not json.loads(n.read_text()).get("acknowledged", False))
    status["stages"]["5_notifications"] = {
        "total": len(notifs),
        "unacknowledged": unacked,
    }

    # AAC/BRS data availability
    status["data_sources"] = {
        "aac_intelligence": AAC_INTELLIGENCE.exists() and any(AAC_INTELLIGENCE.glob("*.json")),
        "brs_signals": BRS_SIGNALS.exists() and any(BRS_SIGNALS.glob("*.yaml")),
        "aac_reports": AAC_SIGNALS.exists(),
    }

    return status


# ── Mandate Watcher (Service Mode) ───────────────────────────────────────

async def watch_mandates(poll_interval: int = 30) -> None:
    """
    Watch for newly approved mandates and auto-dispatch them.
    Runs as a long-lived service alongside NCL brain.
    """
    log.info(f"Strike Point Orchestrator watching for mandates (poll every {poll_interval}s)")
    processed: set[str] = set()

    while True:
        try:
            # Check for new mandate files
            for mf in sorted(MANDATE_OUTPUT.glob("mandate-*.json")):
                if mf.name in processed:
                    continue

                try:
                    mandate = json.loads(mf.read_text())
                    status = mandate.get("status", "")

                    if status == "APPROVED":
                        log.info(f"New approved mandate: {mf.name}")
                        result = await dispatch_mandate(mandate)
                        log.info(f"Dispatch result: {result.get('status')}")
                        processed.add(mf.name)

                except (json.JSONDecodeError, OSError) as e:
                    log.error(f"Failed to process {mf.name}: {e}")

            # Check for completed executions needing feedback processing
            output_dir = EXEC_PIPELINE / "05-Output"
            if output_dir.exists():
                for fb in output_dir.glob("feedback-*.json"):
                    pump_id = fb.stem.replace("feedback-", "")
                    report_key = f"feedback-{pump_id}"
                    if report_key not in processed:
                        result = await process_execution_feedback(pump_id)
                        if result.get("status") == "processed":
                            processed.add(report_key)

        except Exception as e:
            log.error(f"Watch loop error: {e}")

        await asyncio.sleep(poll_interval)


# ── CLI ───────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Strike Point Orchestrator — NCL ↔ NCC Interface",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--watch", action="store_true", help="Run as mandate watcher service (default)")
    group.add_argument("--dispatch", type=str, metavar="MANDATE_ID", help="Dispatch a specific mandate")
    group.add_argument("--feedback", type=str, metavar="PUMP_ID", help="Process feedback for a pump")
    group.add_argument("--status", action="store_true", help="Show pipeline status")
    group.add_argument("--notify", type=str, metavar="MESSAGE", help="Send test notification to NATRIX")
    parser.add_argument("--poll", type=int, default=30, help="Poll interval for watch mode (seconds)")

    args = parser.parse_args()

    if args.dispatch:
        # Find and dispatch a specific mandate
        mandate_file = MANDATE_OUTPUT / f"mandate-{args.dispatch}.json"
        if not mandate_file.exists():
            # Try without prefix
            matches = list(MANDATE_OUTPUT.glob(f"*{args.dispatch}*"))
            if matches:
                mandate_file = matches[0]
            else:
                print(f"Mandate not found: {args.dispatch}")
                sys.exit(1)
        mandate = json.loads(mandate_file.read_text())
        result = asyncio.run(dispatch_mandate(mandate))
        print(json.dumps(result, indent=2))

    elif args.feedback:
        result = asyncio.run(process_execution_feedback(args.feedback))
        print(json.dumps(result, indent=2))

    elif args.status:
        status = get_pipeline_status()
        print(json.dumps(status, indent=2))

    elif args.notify:
        asyncio.run(notify_natrix("Test Notification", args.notify))
        print("Notification sent (check Pushover or notifications/ folder)")

    else:
        # Default: run as watcher service
        asyncio.run(watch_mandates(poll_interval=args.poll))


if __name__ == "__main__":
    main()
