"""
Staleness detector — Loop 6.

High-importance memory units (importance >= 70) accumulate over time, but the
world they describe keeps moving. A "decision" recorded a month ago may already
have been reversed; a "signal" from three days ago may have been disproved by
fresher data; a "preference" from two months ago may no longer hold.

Mem0's authors call this the #1 unsolved production problem for long-running
agents: stale-but-still-high-confidence facts hijack retrieval and the agent
acts on outdated knowledge.

This module:
  1. Walks high-importance units and computes age vs a per-memory-type
     threshold.
  2. Where Awarebot is available, cross-checks each stale candidate against
     the agent's recent signal window — supporting signals revive freshness,
     contradicting signals confirm staleness.
  3. Marks confirmed stale units (sidecar JSONL ledger, plus a 25% importance
     downweight persisted into the live store) so they still exist but sit
     below truly current facts in retrieval.
  4. Revives previously-stale units when current signals support them again,
     restoring the original importance.

Design notes — read before changing thresholds:
  - We do NOT extend the MemUnit pydantic model. Staleness is purely a
    sidecar concern, written to ``data/memory/staleness.jsonl`` and to a live
    state file ``data/memory/staleness_state.json``. The live store sees only
    the importance downweight, which it can decay/process normally.
  - The boundary between "fresh" and "stale" is the age ratio
    ``(now - last_accessed) / STALENESS_THRESHOLDS[memory_type]``. Anything
    over 1.0 is a candidate; only candidates with EITHER >= 2 contradicting
    signals OR (no signal evidence at all AND age_ratio > 1.5) get marked.
    The 1.5x buffer is intentional false-positive insurance — a recently
    aged-out unit gets a 50% grace window before we touch it.
  - The 24h cooldown on re-marking prevents thrashing when the same unit
    keeps coming up as a candidate every cycle.
  - The per-cycle cap of 500 units is so the first cycle on a large store
    doesn't burn an hour. Backlog spans multiple cycles.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import aiofiles

log = logging.getLogger("ncl.memory.staleness")

# ── Tunables (all overridable via env) ───────────────────────────────────────

_DEFAULT_THRESHOLDS = {
    "semantic":   30 * 86400,  # 30 days — facts evolve slowly
    "procedural": 14 * 86400,  # 14 days — workflows shift quarterly-ish
    "preference": 60 * 86400,  # 60 days — preferences are the stickiest
    "decision":    7 * 86400,  # 7 days  — decisions can be reversed quickly
    "signal":      3 * 86400,  # 3 days  — signals decay fastest by design
    "episodic":    7 * 86400,  # 7 days  — episodes lose actionability fast
}


def _env_threshold(memory_type: str, default_seconds: int) -> int:
    env_var = f"NCL_STALENESS_{memory_type.upper()}_SECONDS"
    raw = os.getenv(env_var)
    if not raw:
        return default_seconds
    try:
        return max(60, int(raw))
    except ValueError:
        log.warning("Invalid %s=%r — keeping default %ds", env_var, raw, default_seconds)
        return default_seconds


_MIN_IMPORTANCE = float(os.getenv("NCL_STALENESS_MIN_IMPORTANCE", "70"))
_PER_CYCLE_CAP = int(os.getenv("NCL_STALENESS_PER_CYCLE_CAP", "500"))
_REMARK_COOLDOWN_SECONDS = int(os.getenv("NCL_STALENESS_REMARK_COOLDOWN", str(24 * 3600)))
_AGE_RATIO_HARD_STALE = float(os.getenv("NCL_STALENESS_AGE_RATIO_STALE", "1.5"))
_SUPPORTING_REQUIRED = int(os.getenv("NCL_STALENESS_SUPPORT_REQUIRED", "2"))
_CONTRADICTING_REQUIRED = int(os.getenv("NCL_STALENESS_CONTRADICT_REQUIRED", "2"))
_IMPORTANCE_DOWNWEIGHT = float(os.getenv("NCL_STALENESS_DOWNWEIGHT", "0.75"))  # multiply by

# Words that, if they show up alongside overlapping content tokens, suggest
# the live signal CONTRADICTS the stored unit rather than supports it.
_CONTRADICTION_MARKERS = {
    "no", "not", "never", "false", "wrong", "reversed", "cancelled",
    "canceled", "denied", "rejected", "fail", "failed", "down", "dump",
    "drop", "drops", "decline", "declines", "miss", "missed", "lost",
    "lose", "loses", "bear", "bearish", "crashes", "crashed", "broke",
    "broken", "halted", "paused", "delayed", "withdrawn",
}

# Tokens to drop when extracting keywords from content (high-noise stopwords)
_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "is", "are", "was", "were",
    "be", "been", "being", "to", "of", "in", "on", "at", "for", "with",
    "as", "by", "from", "this", "that", "these", "those", "it", "its",
    "i", "you", "he", "she", "we", "they", "him", "her", "them", "my",
    "your", "his", "their", "our", "me", "us",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "can", "just", "than", "then", "so", "too",
    "very", "any", "some", "all", "more", "most", "other", "into", "over",
    "about", "up", "down", "out", "off", "if", "no", "not", "only",
    "consolidation", "consolidated", "scan",
}

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9$_]{2,}")


def _tokens(text: str) -> set[str]:
    """Cheap keyword extraction — lowercase, alpha-ish, length >= 3, no stopwords."""
    if not text:
        return set()
    out: set[str] = set()
    for tok in _WORD_RE.findall(text):
        low = tok.lower()
        if low in _STOPWORDS:
            continue
        out.add(low)
    return out


def _to_aware(dt_or_str) -> Optional[datetime]:
    """Coerce a value to a timezone-aware datetime (or None)."""
    if dt_or_str is None:
        return None
    if isinstance(dt_or_str, datetime):
        return dt_or_str if dt_or_str.tzinfo else dt_or_str.replace(tzinfo=timezone.utc)
    if isinstance(dt_or_str, str):
        try:
            d = datetime.fromisoformat(dt_or_str.replace("Z", "+00:00"))
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


# ─────────────────────────────────────────────────────────────────────────────


class StalenessDetector:
    """
    Per-cycle stale-unit detector for the autonomous scheduler.

    Args:
        memory_store: An instance of ``MemoryStore`` (runtime/memory/store.py).
        awarebot: Optional running Awarebot agent. If present, the detector
            cross-checks stale candidates against the agent's
            ``_context_7d`` deque (the last week of routed signals).

    Construct once at scheduler startup; call ``run_cycle()`` from the loop.
    """

    STALENESS_THRESHOLDS = {
        mt: _env_threshold(mt, secs) for mt, secs in _DEFAULT_THRESHOLDS.items()
    }

    def __init__(self, memory_store: Any, awarebot: Any = None) -> None:
        self.memory_store = memory_store
        self.awarebot = awarebot

        # Sidecar paths under data/memory/ (same dir the store uses).
        data_dir = Path(memory_store.data_dir)
        data_dir.mkdir(parents=True, exist_ok=True)
        self._ledger_path = data_dir / "staleness.jsonl"
        self._state_path = data_dir / "staleness_state.json"

        # In-memory state mirror.
        # state[unit_id] = {
        #   "marked_at": iso str, "reason": str,
        #   "original_importance": float,
        #   "supporting": int, "contradicting": int,
        # }
        self._state: dict[str, dict] = {}
        self._state_loaded = False

    # ── Public API ──────────────────────────────────────────────────────

    async def find_stale(self) -> list[dict]:
        """
        Walk all units with importance >= _MIN_IMPORTANCE, score age vs
        per-type threshold, return everything where ``age_ratio > 1.0``.
        Results are pre-sorted by age_ratio descending (worst offenders first)
        so the per-cycle cap chops cleanly.
        """
        try:
            units = await self.memory_store._load_all_units()
        except Exception as e:
            log.error("[STALENESS] find_stale: failed to load units: %s", e)
            return []

        now = datetime.now(timezone.utc)
        out: list[dict] = []

        for unit in units:
            try:
                importance = getattr(unit, "importance", 0.0) or 0.0
                if importance < _MIN_IMPORTANCE:
                    continue

                mem_type = getattr(unit, "memory_type", "episodic") or "episodic"
                threshold = self.STALENESS_THRESHOLDS.get(
                    mem_type, self.STALENESS_THRESHOLDS["episodic"]
                )
                last_accessed = _to_aware(getattr(unit, "last_accessed", None))
                if last_accessed is None:
                    last_accessed = _to_aware(getattr(unit, "created_at", None))
                if last_accessed is None:
                    continue

                age_seconds = (now - last_accessed).total_seconds()
                if age_seconds <= threshold:
                    continue

                content = getattr(unit, "content", "") or ""
                preview = content.strip().replace("\n", " ")[:160]

                out.append({
                    "unit_id": unit.unit_id,
                    "memory_type": mem_type,
                    "importance": importance,
                    "age_seconds": int(age_seconds),
                    "threshold_seconds": int(threshold),
                    "age_ratio": round(age_seconds / threshold, 3) if threshold else 0.0,
                    "content_preview": preview,
                })
            except Exception as e:
                log.debug("[STALENESS] skipped one unit: %s", e)

        out.sort(key=lambda d: d["age_ratio"], reverse=True)
        return out

    async def verify_against_signals(self, unit: Any) -> dict:
        """
        If awarebot is available, score the unit against the live signal
        window. Returns:
            {
              "verified": bool,        # supporting >= _SUPPORTING_REQUIRED
              "supporting_signal_count": int,
              "contradicting_signal_count": int,
              "checked": bool,         # False if we had nothing to check against
            }
        """
        result = {
            "verified": False,
            "supporting_signal_count": 0,
            "contradicting_signal_count": 0,
            "checked": False,
        }

        if not self.awarebot:
            return result

        # Pull the agent's recent signal context — _context_7d is the broadest.
        signals = None
        for attr in ("_context_7d", "_context_24h", "_context_top10"):
            sigs = getattr(self.awarebot, attr, None)
            if sigs is None:
                continue
            try:
                signals = list(sigs)
                break
            except Exception:
                continue

        if not signals:
            return result

        try:
            unit_tokens = _tokens(getattr(unit, "content", "") or "")
            for ent in getattr(unit, "entities", []) or []:
                unit_tokens.update(_tokens(str(ent)))
            for tag in getattr(unit, "tags", []) or []:
                unit_tokens.update(_tokens(str(tag)))

            if len(unit_tokens) < 2:
                # Too thin a fingerprint to compare reliably — skip cross-check.
                return result

            supporting = 0
            contradicting = 0

            for sig in signals:
                try:
                    sig_text = " ".join([
                        getattr(sig, "title", "") or "",
                        getattr(sig, "content", "") or "",
                    ])
                    sig_tokens = _tokens(sig_text)
                    overlap = unit_tokens & sig_tokens
                    # Require at least 2 overlapping content tokens for the
                    # signal to count for or against the unit at all.
                    if len(overlap) < 2:
                        continue
                    # A signal "contradicts" if it overlaps AND uses
                    # negation/reversal vocabulary.
                    sig_low = sig_text.lower()
                    if any(w in sig_low for w in _CONTRADICTION_MARKERS):
                        contradicting += 1
                    else:
                        supporting += 1
                except Exception:
                    continue

            result["supporting_signal_count"] = supporting
            result["contradicting_signal_count"] = contradicting
            result["verified"] = supporting >= _SUPPORTING_REQUIRED
            result["checked"] = True
        except Exception as e:
            log.debug("[STALENESS] verify_against_signals: %s", e)

        return result

    async def mark_stale(self, unit_id: str, reason: str) -> bool:
        """
        Mark a unit stale: record in sidecar state + append-only ledger,
        and apply a 25% importance downweight to the live unit so retrieval
        ranking de-emphasizes it (without deleting it).
        """
        await self._ensure_state_loaded()
        try:
            unit = await self.memory_store._load_unit(unit_id)
            if unit is None:
                log.debug("[STALENESS] mark_stale: unit %s not found", unit_id)
                return False

            original = float(getattr(unit, "importance", 0.0) or 0.0)
            new_importance = max(0.0, min(100.0, original * _IMPORTANCE_DOWNWEIGHT))

            now_iso = datetime.now(timezone.utc).isoformat()
            self._state[unit_id] = {
                "marked_at": now_iso,
                "reason": reason,
                "original_importance": original,
                "downweighted_to": new_importance,
            }

            # Apply downweight by going through the store's persistence path.
            unit.importance = new_importance
            try:
                await self.memory_store._persist_reinforcement(unit)
            except Exception as e:
                log.warning("[STALENESS] persist downweight failed for %s: %s", unit_id, e)
                # State is still recorded; re-index next cycle.

            await self._append_ledger({
                "event": "marked_stale",
                "unit_id": unit_id,
                "reason": reason,
                "original_importance": original,
                "new_importance": new_importance,
                "at": now_iso,
            })
            await self._persist_state()
            return True
        except Exception as e:
            log.error("[STALENESS] mark_stale failed for %s: %s", unit_id, e)
            return False

    async def revive_stale(self, unit_id: str) -> bool:
        """
        Clear stale state and restore original importance.
        """
        await self._ensure_state_loaded()
        if unit_id not in self._state:
            return False
        try:
            unit = await self.memory_store._load_unit(unit_id)
            if unit is None:
                # Lost the underlying unit (probably pruned); drop the state row.
                self._state.pop(unit_id, None)
                await self._persist_state()
                return False

            restore_to = float(self._state[unit_id].get(
                "original_importance", getattr(unit, "importance", 0.0)
            ))
            unit.importance = max(0.0, min(100.0, restore_to))
            unit.last_accessed = datetime.now(timezone.utc)
            try:
                await self.memory_store._persist_reinforcement(unit)
            except Exception as e:
                log.warning("[STALENESS] persist revive failed for %s: %s", unit_id, e)

            await self._append_ledger({
                "event": "revived",
                "unit_id": unit_id,
                "restored_importance": restore_to,
                "at": datetime.now(timezone.utc).isoformat(),
            })
            self._state.pop(unit_id, None)
            await self._persist_state()
            return True
        except Exception as e:
            log.error("[STALENESS] revive_stale failed for %s: %s", unit_id, e)
            return False

    async def run_cycle(self) -> dict:
        """
        One full cycle. Called by the scheduler loop. Returns counters.

        Order of operations:
          1. ``find_stale()`` over the whole store (cap at PER_CYCLE_CAP).
          2. For each candidate not in 24h cooldown:
             - verify_against_signals (if awarebot present)
             - supporting >= N → bump last_accessed (treat as fresh)
             - contradicting >= N → mark_stale(reason="contradicted")
             - else, age_ratio > 1.5 → mark_stale(reason="aged out")
          3. Walk previously-stale units; if current signals now support
             them, revive_stale().
        """
        await self._ensure_state_loaded()

        checked = 0
        marked = 0
        revived = 0
        refreshed = 0

        # ── Phase 1+2 — find stale candidates, decide ────────────────────
        candidates = await self.find_stale()
        candidates = candidates[:_PER_CYCLE_CAP]
        log.info("[STALENESS] checking %d candidates (cap %d)",
                 len(candidates), _PER_CYCLE_CAP)

        now = datetime.now(timezone.utc)

        for cand in candidates:
            uid = cand["unit_id"]
            checked += 1

            # Cooldown — don't re-mark within REMARK_COOLDOWN.
            prior = self._state.get(uid)
            if prior:
                marked_at = _to_aware(prior.get("marked_at"))
                if marked_at and (now - marked_at).total_seconds() < _REMARK_COOLDOWN_SECONDS:
                    continue

            try:
                unit = await self.memory_store._load_unit(uid)
                if unit is None:
                    continue

                verify = await self.verify_against_signals(unit)

                supporting = verify["supporting_signal_count"]
                contradicting = verify["contradicting_signal_count"]

                if supporting >= _SUPPORTING_REQUIRED:
                    # Fresh after all — bump last_accessed.
                    try:
                        unit.last_accessed = now
                        await self.memory_store._persist_reinforcement(unit)
                        refreshed += 1
                    except Exception as e:
                        log.debug("[STALENESS] refresh persist failed %s: %s", uid, e)
                    continue

                if contradicting >= _CONTRADICTING_REQUIRED:
                    if await self.mark_stale(uid, reason="contradicted"):
                        marked += 1
                    continue

                if cand["age_ratio"] > _AGE_RATIO_HARD_STALE:
                    if await self.mark_stale(uid, reason="aged out"):
                        marked += 1
                    continue

            except Exception as e:
                log.debug("[STALENESS] per-candidate error %s: %s", uid, e)

        # ── Phase 3 — revive previously-stale units now backed by signals ─
        for uid in list(self._state.keys()):
            try:
                unit = await self.memory_store._load_unit(uid)
                if unit is None:
                    # Drop ghost state for pruned units.
                    self._state.pop(uid, None)
                    continue
                verify = await self.verify_against_signals(unit)
                if verify["supporting_signal_count"] >= _SUPPORTING_REQUIRED:
                    if await self.revive_stale(uid):
                        revived += 1
            except Exception as e:
                log.debug("[STALENESS] per-state error %s: %s", uid, e)

        try:
            await self._persist_state()
        except Exception as e:
            log.warning("[STALENESS] state persist at end-of-cycle failed: %s", e)

        return {
            "candidates_found": len(candidates),
            "checked": checked,
            "marked": marked,
            "revived": revived,
            "refreshed": refreshed,
            "stale_total": len(self._state),
        }

    # ── Inspection helpers (for /memory/staleness route, if added) ───────

    async def get_state(self) -> dict[str, dict]:
        await self._ensure_state_loaded()
        return dict(self._state)

    # ── Sidecar persistence ─────────────────────────────────────────────

    async def _ensure_state_loaded(self) -> None:
        if self._state_loaded:
            return
        if not self._state_path.exists():
            self._state_loaded = True
            return
        try:
            async with aiofiles.open(self._state_path, "r") as f:
                raw = await f.read()
            if raw.strip():
                self._state = json.loads(raw)
        except Exception as e:
            log.warning("[STALENESS] failed to load state %s: %s",
                        self._state_path, e)
        finally:
            self._state_loaded = True

    async def _persist_state(self) -> None:
        tmp = str(self._state_path) + ".tmp"
        try:
            async with aiofiles.open(tmp, "w") as f:
                await f.write(json.dumps(self._state, default=str))
                await f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, str(self._state_path))
        except Exception as e:
            log.warning("[STALENESS] state write failed: %s", e)
            try:
                os.unlink(tmp)
            except OSError:
                pass

    async def _append_ledger(self, entry: dict) -> None:
        """Append a single JSONL row to the audit ledger."""
        try:
            async with aiofiles.open(self._ledger_path, "a") as f:
                await f.write(json.dumps(entry, default=str) + "\n")
                await f.flush()
                os.fsync(f.fileno())
        except Exception as e:
            log.warning("[STALENESS] ledger append failed: %s", e)


# ─────────────────────────────────────────────────────────────────────────────
# Scheduler-side loop helper
#
# Placed in this module (not in scheduler.py) so the scheduler integration is
# a single import + a one-line `asyncio.create_task` call. See the integration
# spec for the exact wiring.
# ─────────────────────────────────────────────────────────────────────────────


# Default cadence: 21600s = 6h. Override per-instance if needed.
STALENESS_LOOP_INTERVAL_SECONDS = int(
    os.getenv("NCL_STALENESS_LOOP_INTERVAL", "21600")
)


async def staleness_detector_loop(
    scheduler: Any,
    detector: StalenessDetector,
    interval_seconds: int = STALENESS_LOOP_INTERVAL_SECONDS,
) -> None:
    """
    Long-running staleness detection loop.

    Args:
        scheduler: The autonomous scheduler instance. Used for
            ``_running`` / emergency-stop checks and to update
            ``_stats["last_staleness_check"]`` / ``_stats["stale_units_total"]``.
        detector: A constructed ``StalenessDetector``.
        interval_seconds: Cycle cadence (default 6h).

    Designed so the scheduler integration is one wiring change only.
    """
    # Brief startup delay so we don't race the brain's first consolidation.
    await asyncio.sleep(120)

    # Lazy import to avoid a hard dependency at module-import time.
    try:
        from ..autonomous.scheduler import EMERGENCY_STOP_EVENT  # type: ignore
    except Exception:  # pragma: no cover
        EMERGENCY_STOP_EVENT = None

    while getattr(scheduler, "_running", True):
        if EMERGENCY_STOP_EVENT is not None and EMERGENCY_STOP_EVENT.is_set():
            log.critical("[STALENESS] Emergency stop active — halting loop")
            break

        try:
            result = await detector.run_cycle()
            log.info(
                "[STALENESS] checked %d high-importance, marked %d stale, "
                "revived %d, refreshed %d (stale total: %d)",
                result["checked"], result["marked"], result["revived"],
                result["refreshed"], result["stale_total"],
            )

            # Stats updates — gracefully no-op if scheduler doesn't carry them.
            try:
                scheduler._stats["last_staleness_check"] = (
                    datetime.now(timezone.utc).isoformat()
                )
                scheduler._stats["stale_units_total"] = result["stale_total"]
                scheduler._stats["staleness_marked_total"] = (
                    scheduler._stats.get("staleness_marked_total", 0)
                    + result["marked"]
                )
                scheduler._stats["staleness_revived_total"] = (
                    scheduler._stats.get("staleness_revived_total", 0)
                    + result["revived"]
                )
            except Exception:
                pass

            # Optional autonomous_event log (mirrors other loops).
            try:
                if hasattr(scheduler, "_log_autonomous_event"):
                    await scheduler._log_autonomous_event(
                        "staleness_cycle", result
                    )
            except Exception:
                pass

        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.error("[STALENESS] cycle error: %s", e, exc_info=True)

        await asyncio.sleep(interval_seconds)
