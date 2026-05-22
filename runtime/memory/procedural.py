"""
Procedural distillation — Loop 7.

Mines successful workflows from completed council→mandate→outcome chains and
scanner→paper-trade→graduation chains, abstracts them into reusable procedural
skills, and writes them back into the `ncl_procedural` memory collection.

Pipeline:
    mine_*_chains   →   distill_skill   →   upsert_to_procedural_memory

Each distilled skill is stored as a `MemUnit` with:
    memory_type="procedural"   (auto-routes to LML / DECAY_RATE_LML)
    source="procedural_distiller"
    tags=["procedural_skill", "skill:<slug>", "domain:<...>"]
    content=<JSON-encoded skill blob>

Idempotency:
    - skill_id is the deterministic sha256 of (kind, normalised_trigger)
    - on upsert, an existing unit with the same skill_id is reinforced
      (evidence + success_rate recomputed, last_reinforced bumped) rather
      than duplicated. Evidence chain_ids are deduped via set semantics.

Budget:
    - LLM (Sonnet) abstraction step is guarded by cost_tracker.check_budget
      with a $0.50 nightly cap. If exceeded, fall back to a rule-based
      template (just stuff the chain into the skill blob, no LLM polish).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import aiofiles

log = logging.getLogger("ncl.memory.procedural")

# ── Tunables ──────────────────────────────────────────────────────────
LLM_NIGHTLY_CAP_USD = 0.50
LLM_MODEL = "claude-sonnet-4-6-20250514"
LLM_MAX_TOKENS = 600
LLM_TIMEOUT_S = 20.0

# Lookback windows
COUNCIL_DOWNSTREAM_WINDOW_H = 24    # mandate must be created within 24h of council
TRADE_DOWNSTREAM_WINDOW_H = 6       # trade must be entered within 6h of alert

# Skill reinforcement
MIN_EVIDENCE_FOR_SKILL = 1          # 1 chain = candidate skill; more = stronger
HIGH_IMPORTANCE_BOOST = 5.0


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────

def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(s: Any) -> Optional[datetime]:
    """Tolerant ISO-8601 parser."""
    if s is None:
        return None
    if isinstance(s, datetime):
        return s if s.tzinfo else s.replace(tzinfo=timezone.utc)
    if not isinstance(s, str) or not s.strip():
        return None
    txt = s.strip().replace("Z", "+00:00")
    # Handle "2026-05-17 19:03:21.541466+00:00"
    if "T" not in txt and " " in txt:
        txt = txt.replace(" ", "T", 1)
    try:
        dt = datetime.fromisoformat(txt)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _slugify(text: str, max_len: int = 60) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text[:max_len] or "untitled"


def _stable_skill_id(kind: str, trigger: str) -> str:
    """Deterministic id derived from (kind, normalised_trigger)."""
    norm = re.sub(r"\s+", " ", (trigger or "").lower().strip())
    h = hashlib.sha256(f"{kind}::{norm}".encode("utf-8")).hexdigest()
    return f"skill_{kind}_{h[:16]}"


# ─────────────────────────────────────────────────────────────────────
# Main class
# ─────────────────────────────────────────────────────────────────────

class ProceduralDistiller:
    """
    Distills successful workflow chains into reusable procedural skills.

    Sources mined:
        1. Council → Mandate → Outcome chains
        2. Scanner alert → Paper trade → Outcome chains
    """

    def __init__(
        self,
        memory_store: Any,
        council_store: Any = None,
        paper_trading: Any = None,
        data_dir: Optional[str | Path] = None,
    ) -> None:
        self.memory_store = memory_store
        self.council_store = council_store
        self.paper_trading = paper_trading
        # data_dir is used for the raw council_sessions.json / mandates.json
        # fallback when no in-memory brain handle was provided.
        self.data_dir = Path(data_dir).expanduser() if data_dir else None
        # Cached lookup of existing procedural skills by skill_id
        self._existing_skills_cache: Optional[dict[str, Any]] = None

    # ──────────────────────────────────────────────────────────────────
    # Mining: council → mandate → outcome
    # ──────────────────────────────────────────────────────────────────

    async def mine_council_chains(self, days_back: int = 30) -> list[dict]:
        """
        Build chains of council session → downstream mandate(s) → outcome.

        A chain is considered useful for distillation when:
            - council has consensus OR is COMPLETE
            - at least one mandate was created within COUNCIL_DOWNSTREAM_WINDOW_H
              of the council's completion (or creation if no completion)
            - the mandate has a non-DRAFT terminal-ish status to score

        Returns a list of dicts with shape:
            {
                "kind": "council",
                "chain_id": str,
                "council_topic": str,
                "council_id": str,
                "consensus": str,
                "completed_at": iso,
                "mandates": [{mandate_id, title, status, pillar, ...}],
                "outcome": "completed" | "in_progress" | "failed" | "active" | "abandoned",
                "success_score": float (0..1),
            }
        """
        cutoff = _utc_now() - timedelta(days=days_back)
        sessions = await self._load_council_sessions()
        mandates = await self._load_mandates()

        chains: list[dict] = []

        for sess in sessions:
            created = _parse_iso(sess.get("created_at"))
            if not created or created < cutoff:
                continue

            # Consider sessions with any signal of progress: consensus, completed,
            # or any synthesis output. Don't require strict status to avoid
            # mis-counting older live sessions stuck in "debating".
            consensus = (sess.get("consensus") or "").strip()
            synthesis = (sess.get("synthesis") or "").strip()
            status = (sess.get("status") or "").lower()
            has_signal = bool(consensus) or bool(synthesis) or status in (
                "complete", "completed", "synthesizing"
            )
            if not has_signal:
                # No usable output yet — skip.
                continue

            anchor = _parse_iso(sess.get("completed_at")) or created
            window_end = anchor + timedelta(hours=COUNCIL_DOWNSTREAM_WINDOW_H)

            # Find downstream mandates whose source_pump_id matches or
            # whose created_at falls inside the window. Many mandates have
            # no source_pump_id wired through, so we fall back to time-window.
            downstream: list[dict] = []
            for m in mandates:
                m_created = _parse_iso(m.get("created_at"))
                if not m_created:
                    continue
                if anchor <= m_created <= window_end:
                    downstream.append(m)

            if not downstream:
                continue

            # Score the chain by aggregate mandate outcomes.
            outcome, success = self._score_mandate_outcomes(downstream)

            chain_id = f"council:{sess.get('session_id', 'unknown')}"
            chains.append({
                "kind": "council",
                "chain_id": chain_id,
                "council_id": sess.get("session_id"),
                "council_topic": sess.get("topic", ""),
                "consensus": consensus or synthesis[:500],
                "chair": sess.get("chair"),
                "members": sess.get("members", []),
                "completed_at": (
                    _parse_iso(sess.get("completed_at")) or created
                ).isoformat(),
                "mandates": [
                    {
                        "mandate_id": m.get("mandate_id"),
                        "title": m.get("title"),
                        "objective": m.get("objective", "")[:300],
                        "status": m.get("status"),
                        "pillar": m.get("pillar"),
                        "priority": m.get("priority"),
                    }
                    for m in downstream
                ],
                "outcome": outcome,
                "success_score": success,
            })

        return chains

    def _score_mandate_outcomes(
        self, mandates: list[dict]
    ) -> tuple[str, float]:
        """Aggregate downstream mandate status into outcome + success score."""
        if not mandates:
            return "abandoned", 0.0

        weights = {
            "completed": 1.0,
            "in_progress": 0.6,
            "active": 0.5,
            "pending_approval": 0.4,
            "draft": 0.3,
            "superseded": 0.3,
            "cancelled": 0.1,
            "failed": 0.0,
        }
        scores = [weights.get(str(m.get("status", "")).lower(), 0.3) for m in mandates]
        success = sum(scores) / len(scores)

        # Outcome label by majority semantics
        if any(str(m.get("status", "")).lower() == "completed" for m in mandates):
            outcome = "completed"
        elif any(str(m.get("status", "")).lower() == "failed" for m in mandates):
            outcome = "failed"
        elif any(str(m.get("status", "")).lower() in ("active", "in_progress") for m in mandates):
            outcome = "in_progress"
        else:
            outcome = "abandoned"

        return outcome, round(success, 3)

    # ──────────────────────────────────────────────────────────────────
    # Mining: scanner alert → paper trade → outcome
    # ──────────────────────────────────────────────────────────────────

    async def mine_trade_chains(self, days_back: int = 30) -> list[dict]:
        """
        Build chains of scanner alert → paper trade → outcome.

        Each closed paper trade with `scanner_data` populated counts as
        one chain. The "alert signal" is reconstructed from `scanner_data`
        + `strategy` rather than re-fetched from agent_signals.jsonl (the
        scanner data on the trade IS the signal snapshot at entry time).

        Returns chains shaped:
            {
                "kind": "trade",
                "chain_id": str,
                "alert_signal": {strategy, scanner_data, symbol, ...},
                "trade": {id, symbol, direction, entry, stop, target_1, ...},
                "outcome": "win" | "loss" | "breakeven" | "open",
                "r_multiple": float,
                "exit_reason": str,
            }
        """
        cutoff = _utc_now() - timedelta(days=days_back)
        trades = await self._load_paper_trades()

        chains: list[dict] = []
        for t in trades:
            created = _parse_iso(t.get("created_at") or t.get("entry_date"))
            if not created or created < cutoff:
                continue

            scanner_data = t.get("scanner_data") or {}
            strategy = (t.get("strategy") or "manual").upper()
            # We want *signal-linked* trades; manual trades aren't a procedural pattern.
            if strategy not in ("GOAT", "BRAVO") and not scanner_data:
                continue

            status = (t.get("status") or "").lower()
            r_mult = float(t.get("r_multiple") or 0)
            realized = float(t.get("realized_pl") or 0)
            exit_reason = (t.get("exit_reason") or "").lower()

            if status == "open":
                outcome = "open"
            elif realized > 0 and r_mult > 0:
                outcome = "win"
            elif realized < 0 or exit_reason == "stop_hit":
                outcome = "loss"
            else:
                outcome = "breakeven"

            chain_id = f"trade:{t.get('id', 'unknown')}"
            chains.append({
                "kind": "trade",
                "chain_id": chain_id,
                "alert_signal": {
                    "strategy": strategy,
                    "symbol": t.get("symbol"),
                    "direction": t.get("direction", "long"),
                    "asset_type": t.get("asset_type", "stock"),
                    "scanner_data": scanner_data,
                },
                "trade": {
                    "id": t.get("id"),
                    "symbol": t.get("symbol"),
                    "direction": t.get("direction"),
                    "entry_price": t.get("entry_price"),
                    "stop_loss": t.get("stop_loss"),
                    "target_1": t.get("target_1"),
                    "risk_reward_ratio": t.get("risk_reward_ratio"),
                    "days_held": t.get("days_held"),
                    "entry_date": t.get("entry_date"),
                    "exit_date": t.get("exit_date"),
                },
                "outcome": outcome,
                "r_multiple": r_mult,
                "exit_reason": exit_reason or None,
            })

        return chains

    # ──────────────────────────────────────────────────────────────────
    # Distillation
    # ──────────────────────────────────────────────────────────────────

    async def distill_skill(self, chain: dict) -> dict:
        """
        Abstract one chain into a procedural skill blob.

        Tries Sonnet (if budget allows); otherwise falls back to
        rule-based templating.
        """
        kind = chain.get("kind", "unknown")

        if kind == "council":
            trigger_seed = chain.get("council_topic", "")[:160]
            domain = "governance"
        elif kind == "trade":
            sig = chain.get("alert_signal", {})
            trigger_seed = f"{sig.get('strategy', 'SCANNER')} {sig.get('direction', '')} {sig.get('symbol', '')}".strip()
            domain = "trading"
        else:
            trigger_seed = chain.get("chain_id", "unknown")
            domain = "general"

        # ── LLM abstraction (budget-gated) ────────────────────────────
        abstract: Optional[dict] = None
        if await self._llm_budget_ok():
            abstract = await self._llm_abstract_chain(chain)

        if abstract is None:
            abstract = self._rule_based_abstract(chain)

        # Final skill blob
        name = abstract.get("name") or f"{domain.title()} pattern: {trigger_seed}"
        trigger = abstract.get("trigger") or trigger_seed
        procedure = abstract.get("procedure") or "(no procedure synthesised)"

        skill_id = _stable_skill_id(kind, trigger)

        # Initial success_rate from this single chain.
        # Open / in_progress chains carry sr=0.5 but DO NOT count as a success
        # (we only count once the chain has reached a terminal outcome).
        terminal = True
        if kind == "council":
            sr = float(chain.get("success_score", 0.5))
            terminal = chain.get("outcome") in ("completed", "failed", "abandoned")
        else:
            outcome = chain.get("outcome")
            if outcome == "win":
                sr = 1.0
            elif outcome == "loss":
                sr = 0.0
            elif outcome == "breakeven":
                sr = 0.5
            else:  # "open"
                sr = 0.5
                terminal = False

        success_count = 1 if (terminal and sr >= 0.5) else 0

        skill = {
            "skill_id": skill_id,
            "kind": kind,
            "domain": domain,
            "name": name,
            "trigger": trigger,
            "procedure": procedure,
            "evidence": [chain.get("chain_id")],
            "evidence_count": 1,
            "success_count": success_count,
            "success_rate": round(sr, 3),
            "first_observed": _utc_now().isoformat(),
            "last_reinforced": _utc_now().isoformat(),
            "distilled_by": "llm" if abstract.get("_via") == "llm" else "rule",
        }
        return skill

    async def _llm_budget_ok(self) -> bool:
        """Check the anthropic daily budget for this distillation pass."""
        try:
            from ..cost_tracker import check_budget
            return await check_budget("anthropic", LLM_NIGHTLY_CAP_USD)
        except Exception as e:
            log.debug(f"Budget check failed (treating as DENY): {e}")
            return False

    async def _llm_abstract_chain(self, chain: dict) -> Optional[dict]:
        """
        Ask Sonnet to abstract a chain into {name, trigger, procedure}.

        Returns None if the LLM call fails for any reason — caller falls
        back to rule-based templating.
        """
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            return None

        # Compact summary of the chain to keep tokens small
        if chain.get("kind") == "council":
            payload = {
                "topic": chain.get("council_topic", "")[:300],
                "consensus": (chain.get("consensus") or "")[:1200],
                "outcome": chain.get("outcome"),
                "success_score": chain.get("success_score"),
                "mandate_titles": [
                    (m.get("title") or "")[:120] for m in chain.get("mandates", [])
                ][:5],
            }
            sys_hint = (
                "You distill governance workflows (council debate -> mandate -> outcome) "
                "into reusable procedural skills."
            )
        else:
            payload = {
                "strategy": chain.get("alert_signal", {}).get("strategy"),
                "symbol": chain.get("alert_signal", {}).get("symbol"),
                "direction": chain.get("alert_signal", {}).get("direction"),
                "scanner_data": chain.get("alert_signal", {}).get("scanner_data", {}),
                "trade": chain.get("trade", {}),
                "outcome": chain.get("outcome"),
                "r_multiple": chain.get("r_multiple"),
                "exit_reason": chain.get("exit_reason"),
            }
            sys_hint = (
                "You distill scanner-driven trade chains (alert -> entry -> exit) into "
                "reusable procedural skills traders can follow."
            )

        prompt = (
            f"{sys_hint}\n\n"
            "Given the following chain (JSON), produce a procedural skill as JSON ONLY "
            "(no markdown fences) with exactly these keys:\n"
            '{ "name": "<short skill title, <=80 chars>", '
            '"trigger": "<one-sentence condition that triggers this skill>", '
            '"procedure": "<numbered step-by-step (3-6 steps), <=600 chars>" }\n\n'
            f"Chain:\n{json.dumps(payload, default=str)}"
        )

        try:
            import httpx
            async with httpx.AsyncClient(timeout=LLM_TIMEOUT_S) as client:
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": LLM_MODEL,
                        "max_tokens": LLM_MAX_TOKENS,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                )
            if resp.status_code != 200:
                log.debug(f"LLM distill HTTP {resp.status_code}: {resp.text[:200]}")
                return None
            data = resp.json()

            # Cost tracking (Sonnet 4 pricing)
            try:
                from ..cost_tracker import record_cost
                usage = data.get("usage", {})
                in_t = usage.get("input_tokens", 0)
                out_t = usage.get("output_tokens", 0)
                cost = (in_t * 3.00 + out_t * 15.00) / 1_000_000
                await record_cost(
                    "anthropic", cost, "procedural_distill",
                    f"distill {chain.get('kind')} in={in_t} out={out_t}",
                )
            except Exception:
                pass

            text = data.get("content", [{}])[0].get("text", "").strip()
            # Strip any code fences just in case
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                log.debug(f"LLM distill returned non-JSON: {text[:200]}")
                return None
            parsed["_via"] = "llm"
            return parsed
        except Exception as e:
            log.debug(f"LLM distill failed: {e}")
            return None

    def _rule_based_abstract(self, chain: dict) -> dict:
        """Deterministic fallback when the LLM is unavailable / over budget."""
        kind = chain.get("kind")
        if kind == "council":
            topic = (chain.get("council_topic") or "untitled council")[:120]
            mandate_titles = [
                (m.get("title") or "?")[:80] for m in chain.get("mandates", [])[:3]
            ]
            return {
                "name": f"Council pattern: {topic[:60]}",
                "trigger": f"Pump or topic resembling: {topic}",
                "procedure": (
                    "1. Spawn council on the matched topic.\n"
                    "2. Wait for consensus or synthesis.\n"
                    f"3. Issue downstream mandates similar to: {' | '.join(mandate_titles) or 'n/a'}.\n"
                    "4. Track each mandate to terminal status."
                ),
                "_via": "rule",
            }
        if kind == "trade":
            sig = chain.get("alert_signal", {})
            trade = chain.get("trade", {})
            strat = sig.get("strategy", "SCANNER")
            sym = sig.get("symbol", "?")
            dirn = sig.get("direction", "long")
            return {
                "name": f"{strat} {dirn} setup on {sym}",
                "trigger": (
                    f"{strat} scanner alert: {sym} {dirn}, "
                    f"scanner_data={json.dumps(sig.get('scanner_data', {}), default=str)[:160]}"
                ),
                "procedure": (
                    f"1. Confirm {strat} entry criteria on {sym}.\n"
                    f"2. Enter {dirn} at ~{trade.get('entry_price')} with stop {trade.get('stop_loss')}.\n"
                    f"3. First target {trade.get('target_1')} (R:R {trade.get('risk_reward_ratio')}).\n"
                    "4. Trail or scale per strategy rules; close on stop or target."
                ),
                "_via": "rule",
            }
        return {
            "name": f"Pattern: {chain.get('chain_id', 'unknown')}",
            "trigger": chain.get("chain_id", "unknown"),
            "procedure": "(no rule template for this chain kind)",
            "_via": "rule",
        }

    # ──────────────────────────────────────────────────────────────────
    # Upsert into procedural memory
    # ──────────────────────────────────────────────────────────────────

    async def upsert_to_procedural_memory(self, skill: dict) -> str:
        """
        Persist (or reinforce) the skill as a procedural-typed memory unit.

        Returns the skill_id (also stable across reinforcement calls).
        """
        skill_id = skill["skill_id"]
        await self._refresh_skills_cache()

        existing_unit = self._existing_skills_cache.get(skill_id) if self._existing_skills_cache else None

        if existing_unit is not None:
            # Reinforce: merge evidence, bump counts, recompute success_rate,
            # rewrite content + bump last_reinforced. We mutate via the same
            # MemoryStore API used elsewhere (no schema changes).
            try:
                prior_blob = json.loads(existing_unit.content)
            except Exception:
                prior_blob = {}

            evidence = set(prior_blob.get("evidence", []))
            evidence.update(skill.get("evidence", []))
            new_evidence = sorted(evidence)
            success_prev = int(prior_blob.get("success_count", 0))
            sr_new = float(skill.get("success_rate", 0.0))
            success_count = success_prev + (1 if sr_new >= 0.5 else 0)
            ev_count = len(new_evidence)
            success_rate = round(success_count / ev_count, 3) if ev_count else 0.0

            merged = dict(prior_blob)
            merged.update({
                "evidence": new_evidence,
                "evidence_count": ev_count,
                "success_count": success_count,
                "success_rate": success_rate,
                "last_reinforced": _utc_now().isoformat(),
                # Refresh procedure/name/trigger only if the new distill ran
                # via LLM and the prior was rule-based.
                "name": (
                    skill["name"]
                    if skill.get("distilled_by") == "llm" and prior_blob.get("distilled_by") != "llm"
                    else prior_blob.get("name", skill["name"])
                ),
                "procedure": (
                    skill["procedure"]
                    if skill.get("distilled_by") == "llm" and prior_blob.get("distilled_by") != "llm"
                    else prior_blob.get("procedure", skill["procedure"])
                ),
                "trigger": prior_blob.get("trigger", skill["trigger"]),
                "skill_id": skill_id,
                "kind": prior_blob.get("kind", skill.get("kind")),
                "domain": prior_blob.get("domain", skill.get("domain")),
                "distilled_by": (
                    "llm" if "llm" in (skill.get("distilled_by", ""), prior_blob.get("distilled_by", "")) else "rule"
                ),
                "first_observed": prior_blob.get("first_observed", skill["first_observed"]),
            })

            # Reinforce via API: read unit (which boosts importance), then
            # rewrite content + tags via _persist_reinforcement-equivalent.
            existing_unit.content = json.dumps(merged)
            existing_unit.last_accessed = _utc_now()
            existing_unit.reinforcement_count = int(existing_unit.reinforcement_count or 0) + 1
            existing_unit.importance = min(
                100.0,
                float(existing_unit.importance or 50.0) + HIGH_IMPORTANCE_BOOST,
            )
            # Tags: ensure procedural_skill + skill:<id> tags
            tag_set = set(existing_unit.tags or [])
            tag_set.update([
                "procedural_skill",
                f"skill:{skill_id}",
                f"domain:{merged.get('domain', 'general')}",
                f"kind:{merged.get('kind', 'unknown')}",
            ])
            existing_unit.tags = sorted(tag_set)

            # Use the store's internal persist_reinforcement if available;
            # else write a fresh unit and let consolidation reconcile.
            persisted = await self._persist_reinforced(existing_unit)
            if not persisted:
                # Fall back to creating a fresh unit — consolidation will dedup
                # by fingerprint over time. This path should be rare.
                await self._create_skill_unit(skill_id, merged)
            return skill_id

        # Brand new skill
        await self._create_skill_unit(skill_id, skill)
        return skill_id

    async def _create_skill_unit(self, skill_id: str, blob: dict) -> None:
        """Create a fresh procedural MemUnit for this skill."""
        tags = sorted({
            "procedural_skill",
            f"skill:{skill_id}",
            f"domain:{blob.get('domain', 'general')}",
            f"kind:{blob.get('kind', 'unknown')}",
        })
        # Importance starts at 60 (above LML default thresholds for
        # promotion/preservation) but not so high that low-evidence skills
        # crowd out high-evidence semantic facts.
        importance = 60.0 if blob.get("distilled_by") == "llm" else 55.0
        await self.memory_store.create_unit(
            content=json.dumps(blob),
            source="procedural_distiller",
            importance=importance,
            tags=tags,
            memory_type="procedural",
        )
        # Cache invalidated — re-fetch next call
        self._existing_skills_cache = None

    async def _persist_reinforced(self, unit: Any) -> bool:
        """
        Persist a mutated MemUnit via MemoryStore's internal rewrite path.

        Returns True if persistence succeeded.
        """
        store = self.memory_store
        # MemoryStore has a private _persist_reinforcement that does atomic
        # JSONL rewrite of a single unit (the same path used by get_unit
        # reinforcement). It exists on the current codebase; if it ever
        # disappears we fall back gracefully.
        persist = getattr(store, "_persist_reinforcement", None)
        if not callable(persist):
            return False
        try:
            await persist(unit)
            # Also re-index in vector DB if available
            indexer = getattr(store, "index_unit", None)
            if callable(indexer):
                try:
                    await indexer(unit)
                except Exception as e:
                    log.debug(f"Re-index after reinforcement failed: {e}")
            return True
        except Exception as e:
            log.warning(f"Persist reinforced unit failed: {e}")
            return False

    async def _refresh_skills_cache(self) -> None:
        """Load all existing procedural units indexed by their skill_id."""
        if self._existing_skills_cache is not None:
            return
        cache: dict[str, Any] = {}
        try:
            units = await self.memory_store.search_units(
                tags=["procedural_skill"], importance_threshold=0.0, days_back=365
            )
        except Exception as e:
            log.debug(f"Skills cache load failed: {e}")
            self._existing_skills_cache = cache
            return

        for u in units:
            sid = None
            # Prefer explicit skill:<id> tag (cheap lookup)
            for t in (u.tags or []):
                if t.startswith("skill:"):
                    sid = t.split(":", 1)[1]
                    break
            # Fall back to parsing content
            if not sid:
                try:
                    blob = json.loads(u.content)
                    sid = blob.get("skill_id")
                except Exception:
                    sid = None
            if sid and sid not in cache:
                cache[sid] = u
        self._existing_skills_cache = cache

    # ──────────────────────────────────────────────────────────────────
    # Raw data loaders (council_sessions.json / mandates.json / trades)
    # ──────────────────────────────────────────────────────────────────

    async def _load_council_sessions(self) -> list[dict]:
        """Load council sessions from disk (idempotent, read-only)."""
        path = self._resolve_data_path("council_sessions.json")
        if not path or not path.exists():
            return []
        try:
            async with aiofiles.open(path, "r") as f:
                raw = await f.read()
            data = json.loads(raw or "{}")
            if isinstance(data, dict):
                return list(data.values())
            if isinstance(data, list):
                return data
        except Exception as e:
            log.warning(f"Failed to load council_sessions.json: {e}")
        return []

    async def _load_mandates(self) -> list[dict]:
        """Load mandates from disk."""
        path = self._resolve_data_path("mandates.json")
        if not path or not path.exists():
            return []
        try:
            async with aiofiles.open(path, "r") as f:
                raw = await f.read()
            data = json.loads(raw or "[]")
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                return list(data.values())
        except Exception as e:
            log.warning(f"Failed to load mandates.json: {e}")
        return []

    async def _load_paper_trades(self) -> list[dict]:
        """
        Load paper trades.

        Prefer the live PaperTradingEngine handle (if provided) — its
        in-memory dict is the freshest source. Otherwise read JSONL.
        """
        if self.paper_trading is not None:
            try:
                # PaperTradingEngine.trades is a dict[id, PaperTrade]
                trades_dict = getattr(self.paper_trading, "trades", None)
                if trades_dict:
                    out = []
                    for t in trades_dict.values():
                        to_dict = getattr(t, "to_dict", None)
                        if callable(to_dict):
                            out.append(to_dict())
                        elif isinstance(t, dict):
                            out.append(t)
                    if out:
                        return out
            except Exception as e:
                log.debug(f"Live paper_trading read failed, falling back to JSONL: {e}")

        path = self._resolve_data_path("paper_trading/trades.jsonl")
        if not path or not path.exists():
            return []
        out: list[dict] = []
        try:
            async with aiofiles.open(path, "r") as f:
                async for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        out.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            log.warning(f"Failed to load paper trades: {e}")
        return out

    def _resolve_data_path(self, relative: str) -> Optional[Path]:
        """Resolve a path relative to the project data dir."""
        candidates = []
        if self.data_dir:
            candidates.append(self.data_dir / relative)
        # Memory store data_dir is .../data/memory — its parent is data root.
        try:
            mem_dir = getattr(self.memory_store, "data_dir", None)
            if mem_dir is not None:
                candidates.append(Path(mem_dir).parent / relative)
        except Exception:
            pass
        # Last resort: env-driven dir
        env_dir = os.getenv("NCL_DATA_DIR")
        if env_dir:
            candidates.append(Path(env_dir).expanduser() / relative)
        # Repo default
        candidates.append(
            Path(__file__).resolve().parents[2] / "data" / relative
        )
        for c in candidates:
            try:
                if c and c.exists():
                    return c
            except Exception:
                continue
        # Return the first candidate even if it doesn't exist so callers can
        # log a single canonical missing-path.
        return candidates[0] if candidates else None


# ─────────────────────────────────────────────────────────────────────
# Night Watch Phase 2.5 entry point
# ─────────────────────────────────────────────────────────────────────

async def run_procedural_distillation(brain: Any) -> dict:
    """
    Night Watch Phase 2.5 — procedural distillation.

    Mines successful chains from the last 30 days, distills each into a
    procedural skill, and upserts into the `ncl_procedural` collection.

    Returns:
        {
            "chains_mined": int,        # total chains across both sources
            "skills_distilled": int,    # number of distill_skill() calls
            "new_skills": int,          # number of brand-new skill_ids
            "reinforced": int,          # number of existing skill_ids reinforced
            "errors": int,
            "council_chains": int,
            "trade_chains": int,
            "via_llm": int,
            "via_rule": int,
        }
    """
    report = {
        "chains_mined": 0,
        "skills_distilled": 0,
        "new_skills": 0,
        "reinforced": 0,
        "errors": 0,
        "council_chains": 0,
        "trade_chains": 0,
        "via_llm": 0,
        "via_rule": 0,
    }

    # Wire dependencies from the brain handle (all optional, all defensive).
    memory_store = getattr(brain, "memory_store", None)
    if memory_store is None:
        log.warning("[PROCEDURAL] brain.memory_store missing — aborting")
        return report

    # Pull the live PaperTradingEngine if available
    paper_engine = None
    try:
        from ..portfolio.paper_routes import _engine as _paper_engine
        paper_engine = _paper_engine
    except Exception:
        paper_engine = None

    distiller = ProceduralDistiller(
        memory_store=memory_store,
        council_store=getattr(brain, "council_store", None),
        paper_trading=paper_engine,
        data_dir=getattr(brain, "data_dir", None),
    )

    # ── Mine ───────────────────────────────────────────────────────────
    try:
        council_chains = await distiller.mine_council_chains(days_back=30)
    except Exception as e:
        log.warning(f"[PROCEDURAL] mine_council_chains failed: {e}")
        council_chains = []
        report["errors"] += 1

    try:
        trade_chains = await distiller.mine_trade_chains(days_back=30)
    except Exception as e:
        log.warning(f"[PROCEDURAL] mine_trade_chains failed: {e}")
        trade_chains = []
        report["errors"] += 1

    report["council_chains"] = len(council_chains)
    report["trade_chains"] = len(trade_chains)
    report["chains_mined"] = len(council_chains) + len(trade_chains)

    # ── Distill + upsert ──────────────────────────────────────────────
    # Process trade chains first (cheap signal), then council chains.
    for chain in trade_chains + council_chains:
        try:
            skill = await distiller.distill_skill(chain)
            report["skills_distilled"] += 1
            if skill.get("distilled_by") == "llm":
                report["via_llm"] += 1
            else:
                report["via_rule"] += 1

            # Check existing BEFORE upsert to classify new vs reinforced
            await distiller._refresh_skills_cache()
            was_existing = skill["skill_id"] in (distiller._existing_skills_cache or {})

            await distiller.upsert_to_procedural_memory(skill)
            if was_existing:
                report["reinforced"] += 1
            else:
                report["new_skills"] += 1
        except Exception as e:
            log.warning(f"[PROCEDURAL] distill+upsert failed for {chain.get('chain_id')}: {e}")
            report["errors"] += 1

    log.info(
        "[PROCEDURAL] Phase 2.5 done: %d chains -> %d skills (%d new, %d reinforced); LLM=%d rule=%d",
        report["chains_mined"], report["skills_distilled"],
        report["new_skills"], report["reinforced"],
        report["via_llm"], report["via_rule"],
    )
    return report
