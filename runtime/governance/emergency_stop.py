"""Emergency Stop (Kill Switch) — one-tap STOP for Execute-tier actions.

One-tap STOP disables all Execute-tier actions immediately.
Persists across restarts via flag file.
All activations/deactivations logged in AuditLedger.
"""
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Any
import json
import logging
import uuid as _uuid

import aiofiles
from pydantic import BaseModel, Field

log = logging.getLogger("ncl.emergency_stop")


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

    One-tap STOP disables ALL Execute-tier actions.
    State persists across restarts via file system.
    All operations logged to AuditLedger.
    """

    FLAG_FILE = "emergency_stop.flag"
    STATE_FILE = "emergency_stop_state.json"
    LEDGER_FILE = "emergency_stop_ledger.jsonl"

    def __init__(self, data_dir):
        self.data_dir = Path(data_dir) if not isinstance(data_dir, Path) else data_dir
        self.gov_dir = self.data_dir / "governance"
        self._state = EmergencyStopState()
        self._callbacks = []  # Notify on activate/deactivate

    async def init(self):
        """Initialize — load persisted state."""
        self.gov_dir.mkdir(parents=True, exist_ok=True)

        # Load state from file
        state_path = self.gov_dir / self.STATE_FILE
        if state_path.exists():
            async with aiofiles.open(state_path, 'r') as f:
                data = json.loads(await f.read())
                self._state = EmergencyStopState(**data)

        # Also check flag file (belt + suspenders)
        flag_path = self.gov_dir / self.FLAG_FILE
        if flag_path.exists() and not self._state.active:
            self._state.active = True
            log.warning("Emergency stop flag file detected — STOP is ACTIVE")

        if self._state.active:
            log.warning(f"Emergency stop is ACTIVE (activated by {self._state.activated_by} at {self._state.activated_at})")

    @property
    def is_active(self) -> bool:
        return self._state.active

    @property
    def state(self) -> EmergencyStopState:
        return self._state

    def on_change(self, callback):
        """Register callback for state changes."""
        self._callbacks.append(callback)

    async def activate(self, actor: str = "NATRIX", reason: str = "Manual emergency stop") -> EmergencyStopState:
        """ONE-TAP STOP — immediately disable all Execute-tier actions."""
        if self._state.active:
            log.warning(f"Emergency stop already active (activated by {self._state.activated_by})")
            return self._state

        self._state.active = True
        self._state.activated_at = datetime.now(timezone.utc)
        self._state.activated_by = actor
        self._state.reason = reason
        self._state.deactivated_at = None
        self._state.deactivated_by = None
        self._state.activation_count += 1

        # Persist state
        await self._persist_state()

        # Write flag file (persists across restarts)
        flag_path = self.gov_dir / self.FLAG_FILE
        async with aiofiles.open(flag_path, 'w') as f:
            await f.write(json.dumps({
                "active": True,
                "activated_at": self._state.activated_at.isoformat(),
                "activated_by": actor,
                "reason": reason,
            }))

        # Log to audit ledger
        await self._log_ledger(AuditLedgerEntry(
            action="activated",
            actor=actor,
            reason=reason,
            metadata={"activation_count": self._state.activation_count},
        ))

        log.critical(f"EMERGENCY STOP ACTIVATED by {actor}: {reason}")

        # Notify callbacks
        for cb in self._callbacks:
            try:
                cb("activated", self._state)
            except Exception as e:
                log.error(f"Emergency stop callback error: {e}")

        return self._state

    async def deactivate(self, actor: str = "NATRIX", reason: str = "Manual deactivation") -> EmergencyStopState:
        """Deactivate emergency stop — re-enable Execute-tier actions."""
        if not self._state.active:
            log.info("Emergency stop already inactive")
            return self._state

        self._state.active = False
        self._state.deactivated_at = datetime.now(timezone.utc)
        self._state.deactivated_by = actor

        # Persist state
        await self._persist_state()

        # Remove flag file
        flag_path = self.gov_dir / self.FLAG_FILE
        if flag_path.exists():
            flag_path.unlink()

        # Log to audit ledger
        await self._log_ledger(AuditLedgerEntry(
            action="deactivated",
            actor=actor,
            reason=reason,
            metadata={
                "was_active_since": self._state.activated_at.isoformat() if self._state.activated_at else None,
            },
        ))

        log.info(f"Emergency stop DEACTIVATED by {actor}: {reason}")

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

        # Log the blocked action
        await self._log_ledger(AuditLedgerEntry(
            action="blocked_action",
            actor="emergency_stop",
            reason=f"Execute-tier action blocked: {action_name}",
            blocked_action_name=action_name,
            blocked_action_id=action_id,
        ))

        log.warning(f"BLOCKED by emergency stop: {action_name} (id={action_id})")
        return True  # Blocked

    async def get_ledger(self, n: int = 100) -> list[AuditLedgerEntry]:
        """Read recent audit ledger entries."""
        ledger_path = self.gov_dir / self.LEDGER_FILE
        if not ledger_path.exists():
            return []

        entries = []
        async with aiofiles.open(ledger_path, 'r') as f:
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
            "activated_at": self._state.activated_at.isoformat() if self._state.activated_at else None,
            "activated_by": self._state.activated_by,
            "reason": self._state.reason,
            "activation_count": activation_count,
            "total_blocked_actions": blocked_count,
            "deactivated_at": self._state.deactivated_at.isoformat() if self._state.deactivated_at else None,
        }

    async def _persist_state(self):
        state_path = self.gov_dir / self.STATE_FILE
        async with aiofiles.open(state_path, 'w') as f:
            await f.write(self._state.model_dump_json(indent=2))

    async def _log_ledger(self, entry: AuditLedgerEntry):
        ledger_path = self.gov_dir / self.LEDGER_FILE
        async with aiofiles.open(ledger_path, 'a') as f:
            await f.write(entry.model_dump_json() + "\n")
