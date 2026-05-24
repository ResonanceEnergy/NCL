"""Emergency Stop (Kill Switch) — one-tap STOP for Execute-tier actions.

One-tap STOP disables all Execute-tier actions immediately.
Persists across restarts via flag file.
All activations/deactivations logged in AuditLedger.

Global EMERGENCY_STOP_EVENT (threading.Event) is set on activation so that
all subsystem loops can check `if EMERGENCY_STOP_EVENT.is_set(): break`.
"""

import asyncio
import json
import logging
import os
import threading
import uuid as _uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import aiofiles
from pydantic import BaseModel, Field


log = logging.getLogger("ncl.emergency_stop")

# ─── Global emergency stop event ─────────────────────────────────────────────
# All subsystem loops MUST check `if EMERGENCY_STOP_EVENT.is_set(): break`
# at the top of each iteration.  Set on activation; cleared on deactivation
# so that loops can resume without a process restart.
EMERGENCY_STOP_EVENT: threading.Event = threading.Event()


class EmergencyStopState(BaseModel):
    """Persistent state of the emergency stop."""

    active: bool = False
    activated_at: Optional[datetime] = None
    activated_by: str = ""
    reason: str = ""
    deactivated_at: Optional[datetime] = None
    deactivated_by: Optional[str] = None
    activation_count: int = 0


class AuditLedgerEntry(BaseModel):
    """Audit ledger entry for emergency stop actions."""

    entry_id: str = Field(default_factory=lambda: str(_uuid.uuid4()))
    action: str  # "activated", "deactivated", "blocked_action"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    actor: str  # Who performed the action
    reason: str = ""
    blocked_action_name: Optional[str] = None
    blocked_action_id: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class EmergencyStop:
    """
    Emergency Stop Controller.

    One-tap STOP disables ALL Execute-tier actions AND signals all subsystems
    to halt via the global EMERGENCY_STOP_EVENT (threading.Event).

    State persists across restarts via file system.
    All operations logged to AuditLedger.

    Usage in subsystem loops::

        from runtime.governance.emergency_stop import EMERGENCY_STOP_EVENT

        while running:
            if EMERGENCY_STOP_EVENT.is_set():
                log.critical("Emergency stop active — halting loop")
                break
            ...
    """

    FLAG_FILE = "emergency_stop.flag"
    STATE_FILE = "emergency_stop_state.json"
    LEDGER_FILE = "emergency_stop_ledger.jsonl"

    NOTIFICATIONS_FILE = "emergency_stop_notifications.jsonl"

    def __init__(
        self,
        data_dir,
        policy_kernel=None,
        scheduler=None,
        swarm_orchestrator=None,
        intelligence_engine=None,
    ):
        self.data_dir = Path(data_dir) if not isinstance(data_dir, Path) else data_dir
        self.gov_dir = self.data_dir / "governance"
        self._state = EmergencyStopState()
        self._callbacks = []  # Notify on activate/deactivate
        self._init_lock = asyncio.Lock()
        self._initialized = False

        # Optional subsystem references for direct halt
        self._policy_kernel = policy_kernel
        self._scheduler = scheduler
        self._swarm_orchestrator = swarm_orchestrator
        self._intelligence_engine = intelligence_engine

    def register_subsystems(
        self,
        policy_kernel=None,
        scheduler=None,
        swarm_orchestrator=None,
        intelligence_engine=None,
    ) -> None:
        """Register subsystem references so stop() can halt them directly."""
        if policy_kernel is not None:
            self._policy_kernel = policy_kernel
        if scheduler is not None:
            self._scheduler = scheduler
        if swarm_orchestrator is not None:
            self._swarm_orchestrator = swarm_orchestrator
        if intelligence_engine is not None:
            self._intelligence_engine = intelligence_engine

    async def init(self):
        """Initialize — load persisted state. Safe to call multiple times (idempotent)."""
        async with self._init_lock:
            if self._initialized:
                return
            await self._do_init()
            self._initialized = True

    async def _do_init(self):
        """Internal init logic — called exactly once."""
        self.gov_dir.mkdir(parents=True, exist_ok=True)

        # Load state from file
        state_path = self.gov_dir / self.STATE_FILE
        if state_path.exists():
            async with aiofiles.open(state_path, "r") as f:
                data = json.loads(await f.read())
                self._state = EmergencyStopState(**data)

        # Also check flag file (belt + suspenders)
        flag_path = self.gov_dir / self.FLAG_FILE
        if flag_path.exists() and not self._state.active:
            self._state.active = True
            log.warning("Emergency stop flag file detected — STOP is ACTIVE")

        if self._state.active:
            log.warning(
                f"Emergency stop is ACTIVE (activated by {self._state.activated_by} "
                f"at {self._state.activated_at})"
            )
            # Re-arm the global event so loops that started after restart also stop
            EMERGENCY_STOP_EVENT.set()

    @property
    def is_active(self) -> bool:
        return self._state.active

    @property
    def state(self) -> EmergencyStopState:
        return self._state

    def on_change(self, callback):
        """Register callback for state changes."""
        self._callbacks.append(callback)

    async def activate(
        self, actor: str = "NATRIX", reason: str = "Manual emergency stop"
    ) -> EmergencyStopState:
        """ONE-TAP STOP — immediately halt ALL subsystems.

        Actions taken in order:
        1. Set global EMERGENCY_STOP_EVENT (all loops break on next iteration)
        2. Freeze PolicyKernel (no more policy evaluations)
        3. Cancel scheduler tasks
        4. Cancel swarm orchestrator tasks
        5. Cancel intelligence engine tasks
        6. Persist state + flag file
        7. Notify callbacks
        """
        if self._state.active:
            log.warning(f"Emergency stop already active (activated by {self._state.activated_by})")
            return self._state

        # ── 1. Signal all loops to halt immediately ────────────────────────
        EMERGENCY_STOP_EVENT.set()
        log.critical("EMERGENCY_STOP_EVENT SET — all subsystem loops signaled to halt")

        self._state.active = True
        self._state.activated_at = datetime.now(timezone.utc)
        self._state.activated_by = actor
        self._state.reason = reason
        self._state.deactivated_at = None
        self._state.deactivated_by = None
        self._state.activation_count += 1

        # ── 2. Freeze PolicyKernel ─────────────────────────────────────────
        if self._policy_kernel is not None:
            try:
                self._policy_kernel.set_emergency_stop(enabled=True)
                log.critical("PolicyKernel: emergency stop engaged — policy evaluation frozen")
            except Exception as e:
                log.error(f"Failed to freeze PolicyKernel: {e}")

        # ── 3. Cancel scheduler ────────────────────────────────────────────
        if self._scheduler is not None:
            try:
                await self._scheduler.stop()
                log.critical("Scheduler: stopped")
            except Exception as e:
                log.error(f"Failed to stop scheduler: {e}")

        # ── 4. Cancel swarm orchestrator ───────────────────────────────────
        if self._swarm_orchestrator is not None:
            try:
                if hasattr(self._swarm_orchestrator, "stop"):
                    await self._swarm_orchestrator.stop()
                elif hasattr(self._swarm_orchestrator, "shutdown"):
                    await self._swarm_orchestrator.shutdown()
                log.critical("SwarmOrchestrator: stopped")
            except Exception as e:
                log.error(f"Failed to stop swarm orchestrator: {e}")

        # ── 5. Cancel intelligence engine ──────────────────────────────────
        if self._intelligence_engine is not None:
            try:
                if hasattr(self._intelligence_engine, "stop"):
                    await self._intelligence_engine.stop()
                elif hasattr(self._intelligence_engine, "shutdown"):
                    await self._intelligence_engine.shutdown()
                log.critical("IntelligenceEngine: stopped")
            except Exception as e:
                log.error(f"Failed to stop intelligence engine: {e}")

        # ── 6. Persist state + flag file ───────────────────────────────────
        await self._persist_state()

        flag_path = self.gov_dir / self.FLAG_FILE
        async with aiofiles.open(flag_path, "w") as f:
            await f.write(
                json.dumps(
                    {
                        "active": True,
                        "activated_at": self._state.activated_at.isoformat(),
                        "activated_by": actor,
                        "reason": reason,
                    }
                )
            )

        await self._log_ledger(
            AuditLedgerEntry(
                action="activated",
                actor=actor,
                reason=reason,
                metadata={"activation_count": self._state.activation_count},
            )
        )

        log.critical(f"EMERGENCY STOP FULLY ACTIVATED by {actor}: {reason}")

        # ── 7. Emit notification ───────────────────────────────────────────
        await self._emit_notification("activated", actor, reason)

        # ── 8. Notify callbacks ────────────────────────────────────────────
        for cb in self._callbacks:
            try:
                cb("activated", self._state)
            except Exception as e:
                log.error(f"Emergency stop callback error: {e}")

        return self._state

    async def deactivate(
        self, actor: str = "NATRIX", reason: str = "Manual deactivation"
    ) -> EmergencyStopState:
        """Deactivate emergency stop — re-enable Execute-tier actions.

        Clears the global EMERGENCY_STOP_EVENT so scheduler loops can resume
        on the next iteration without requiring a full process restart.
        PolicyKernel flag is also cleared so new actions can be evaluated.
        """
        if not self._state.active:
            log.info("Emergency stop already inactive")
            return self._state

        self._state.active = False
        self._state.deactivated_at = datetime.now(timezone.utc)
        self._state.deactivated_by = actor

        # Clear the global event so all scheduler loops resume on next iteration
        EMERGENCY_STOP_EVENT.clear()
        log.info("EMERGENCY_STOP_EVENT cleared — scheduler loops will resume")

        # Unfreeze PolicyKernel so new requests can be evaluated
        if self._policy_kernel is not None:
            try:
                self._policy_kernel.set_emergency_stop(enabled=False)
                log.info("PolicyKernel: emergency stop cleared — policy evaluation resumed")
            except Exception as e:
                log.error(f"Failed to unfreeze PolicyKernel: {e}")

        # Persist state
        await self._persist_state()

        # Remove flag file
        flag_path = self.gov_dir / self.FLAG_FILE
        if flag_path.exists():
            flag_path.unlink()

        await self._log_ledger(
            AuditLedgerEntry(
                action="deactivated",
                actor=actor,
                reason=reason,
                metadata={
                    "was_active_since": self._state.activated_at.isoformat()
                    if self._state.activated_at
                    else None,
                },
            )
        )

        log.info(f"Emergency stop DEACTIVATED by {actor}: {reason}. Operations may resume.")

        # Emit notification
        await self._emit_notification("deactivated", actor, reason)

        for cb in self._callbacks:
            try:
                cb("deactivated", self._state)
            except Exception as e:
                log.error(f"Emergency stop callback error: {e}")

        return self._state

    async def check_action(self, action_name: str, action_id: str = None) -> bool:
        """Check if an Execute-tier action is allowed. Returns True if BLOCKED."""
        if not self._state.active:
            return False  # Not blocked

        await self._log_ledger(
            AuditLedgerEntry(
                action="blocked_action",
                actor="emergency_stop",
                reason=f"Execute-tier action blocked: {action_name}",
                blocked_action_name=action_name,
                blocked_action_id=action_id,
            )
        )

        log.warning(f"BLOCKED by emergency stop: {action_name} (id={action_id})")
        return True  # Blocked

    async def get_ledger(self, n: int = 100) -> list[AuditLedgerEntry]:
        """Read recent audit ledger entries."""
        ledger_path = self.gov_dir / self.LEDGER_FILE
        if not ledger_path.exists():
            return []

        entries = []
        async with aiofiles.open(ledger_path, "r") as f:
            async for line in f:
                line = line.strip()
                if line:
                    entries.append(AuditLedgerEntry(**json.loads(line)))

        return entries[-n:]

    async def get_stats(self) -> dict:
        """Get emergency stop statistics."""
        ledger = await self.get_ledger(1000)
        blocked_count = sum(1 for e in ledger if e.action == "blocked_action")
        activation_count = sum(1 for e in ledger if e.action == "activated")

        return {
            "active": self._state.active,
            "global_event_set": EMERGENCY_STOP_EVENT.is_set(),
            "activated_at": self._state.activated_at.isoformat()
            if self._state.activated_at
            else None,
            "activated_by": self._state.activated_by,
            "reason": self._state.reason,
            "activation_count": activation_count,
            "total_blocked_actions": blocked_count,
            "deactivated_at": self._state.deactivated_at.isoformat()
            if self._state.deactivated_at
            else None,
        }

    async def _persist_state(self):
        """Persist state using atomic write-to-temp-then-rename pattern."""
        self.gov_dir.mkdir(parents=True, exist_ok=True)
        state_path = self.gov_dir / self.STATE_FILE
        tmp_path = state_path.with_suffix(".tmp")
        async with aiofiles.open(tmp_path, "w") as f:
            await f.write(self._state.model_dump_json(indent=2))
            await f.flush()
            os.fsync(f.fileno())
        os.replace(str(tmp_path), str(state_path))

    async def _log_ledger(self, entry: AuditLedgerEntry):
        self.gov_dir.mkdir(parents=True, exist_ok=True)
        ledger_path = self.gov_dir / self.LEDGER_FILE
        async with aiofiles.open(ledger_path, "a") as f:
            await f.write(entry.model_dump_json() + "\n")
            await f.flush()
            os.fsync(f.fileno())

    async def _emit_notification(self, event: str, actor: str, reason: str) -> None:
        """Write a notification entry so external consumers can detect state changes."""
        notif_path = self.gov_dir / self.NOTIFICATIONS_FILE
        notification = {
            "id": str(_uuid.uuid4()),
            "event": f"emergency_stop.{event}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "actor": actor,
            "reason": reason,
            "active": self._state.active,
        }
        async with aiofiles.open(notif_path, "a") as f:
            await f.write(json.dumps(notification) + "\n")
