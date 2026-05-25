"""
PortfolioAnalystAgent — nightly orchestrator.

Mandate (NATRIX, verbatim):
    maximize capital flow IN, limit capital flow OUT
    + research positions and watchlist
    + every position has entry, exit, goal/mandate, watch-for
    + defend or invalidate position theses with evidence
    + escalate broken theses to council

Run profile:
    - Wakes at 03:15 ET nightly inside Night Watch (after intel_cycle,
      before the existing analyst.py daily-briefing synthesis).
    - One Sonnet 4 call for the narrative + trim/add ranking.
    - Cost-gated against ``anthropic`` daily budget at $0.10/run.
    - On budget block or LLM failure: emits a deterministic-only report
      with ``llm_narrative=None``. The Morning Brief renders both shapes.

Output:
    data/portfolio/analyst/reports/portfolio-YYYY-MM-DD.json
    + MemoryUnit (BRAIN tier, importance 75, tags=portfolio,agent,nightly)
    + ntfy push for any high-severity immediate-action items
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .metrics import compute_concentration, compute_risk
from .schema import (
    NAV,
    CapitalFlow,
    DeterministicSection,
    ImmediateAction,
    NightlyReport,
    RiskAlert,
    TrimAddCandidate,
)
from .theses import (
    PositionThesis,
    ThesisEvaluationResult,
)
from .thesis_evaluator import (
    apply_evaluation,
    imminent_catalysts,
)
from .thesis_evaluator import (
    evaluate as evaluate_thesis,
)
from .thesis_store import ThesisStore


log = logging.getLogger("ncl.portfolio.analyst.agent")


# Policy thresholds — see round-2 research §9
DEFAULT_POLICY = {
    "max_single_name_pct": 0.10,
    "max_sector_pct": 0.25,
    "max_per_broker_pct": 0.40,
    "max_cex_pct": 0.15,
    "max_self_custody_pct": 0.25,
    "max_options_premium_pct": 0.05,
    "daily_loss_circuit_breaker_pct": -0.035,
    "drawdown_trim_trigger_pct": -0.12,
    "portfolio_var_ceiling_pct": 0.02,
    "thesis_broken_threshold": 0.30,
    "thesis_strong_threshold": 0.70,
}


class PortfolioAnalystAgent:
    """Nightly portfolio-analysis orchestrator.

    Inputs are passed in (dependency-injection-friendly so tests can
    stub the data sources). Caller (Night Watch) is responsible for
    wiring the real PortfolioManager / MemoryStore / cost_tracker.
    """

    def __init__(
        self,
        *,
        portfolio_manager: Any,
        memory_store: Optional[Any] = None,
        cost_tracker: Optional[Any] = None,
        data_dir: Path,
        policy: Optional[dict[str, float]] = None,
        brain: Optional[Any] = None,
    ) -> None:
        self.portfolio_manager = portfolio_manager
        self.memory_store = memory_store
        self.cost_tracker = cost_tracker
        self.data_dir = Path(data_dir).expanduser()
        self.brain = brain
        self.policy = {**DEFAULT_POLICY, **(policy or {})}
        self.thesis_store = ThesisStore(self.data_dir)
        self.reports_dir = self.data_dir / "portfolio" / "analyst" / "reports"
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    # ── Public entrypoint ─────────────────────────────────────────────

    async def run(self, *, dry_run: bool = False) -> NightlyReport:
        """Execute one nightly analysis cycle.

        Steps:
          1. Snapshot inputs (positions, signals, council briefs, calendar)
          2. Compute deterministic metrics (HHI, sector, VaR, drawdown)
          3. Re-evaluate each thesis against last-24h evidence
          4. Detect immediate actions (stops, expiries, news-hot,
             mandate-drift, broken-thesis, contract-missing)
          5. Compose policy-breach risk alerts
          6. LLM synthesis (Sonnet 4) — trim/add candidates + capital
             flow + narrative
          7. Persist report + ingest to memory + push high-severity alerts
        """
        start = datetime.now(timezone.utc)
        report_id = f"portfolio-{start.strftime('%Y-%m-%d')}"
        notes: list[str] = []
        log.info("[ANALYST] starting run %s", report_id)

        # 1) Snapshot
        positions = await self._fetch_positions()
        nav = self._compute_nav(positions)
        signals_24h = await self._fetch_signals_24h(positions)
        council_briefs_24h = await self._fetch_council_briefs_24h()
        notes.append(f"signals_24h={len(signals_24h)} council_briefs_24h={len(council_briefs_24h)}")

        # 2) Deterministic metrics
        deterministic = self._compute_deterministic(positions, nav)

        # 3) Thesis re-evaluation
        thesis_results, theses_by_iid = await self._evaluate_all_theses(
            positions, signals_24h, council_briefs_24h, dry_run=dry_run
        )

        # 4) Immediate actions
        immediate = self._detect_immediate_actions(
            positions, theses_by_iid, thesis_results, signals_24h
        )

        # 5) Risk alerts
        risk_alerts = self._policy_risk_alerts(nav, deterministic)

        # 6) LLM synthesis (lazy import to avoid hard dep at module load)
        trim_add: list[TrimAddCandidate] = []
        capital_flow: Optional[CapitalFlow] = None
        narrative: Optional[str] = None
        cost_usd = 0.0
        try:
            from .llm_synthesis import synthesize_narrative

            trim_add, capital_flow, narrative, cost_usd = await synthesize_narrative(
                cost_tracker=self.cost_tracker,
                nav=nav,
                deterministic=deterministic,
                immediate_actions=immediate,
                risk_alerts=risk_alerts,
                thesis_results=thesis_results,
                signals_24h=signals_24h,
                policy=self.policy,
            )
        except Exception as exc:
            log.warning("[ANALYST] LLM synthesis failed: %s: %r", type(exc).__name__, exc)
            notes.append(f"llm_synthesis_failed: {type(exc).__name__}")

        # 7) Persist + ingest + alert
        report = NightlyReport(
            report_id=report_id,
            generated_at=start,
            duration_seconds=(datetime.now(timezone.utc) - start).total_seconds(),
            cost_usd=cost_usd,
            nav=nav,
            deterministic=deterministic,
            immediate_actions=immediate,
            trim_add_candidates=trim_add,
            capital_flow=capital_flow,
            risk_alerts=risk_alerts,
            llm_narrative=narrative,
            positions_count=len(positions),
            signals_consumed=len(signals_24h),
            notes=notes,
        )

        if not dry_run:
            await self._persist_report(report)
            await self._ingest_to_memory(report, thesis_results)
            await self._dispatch_alerts(immediate, thesis_results)

        log.info(
            "[ANALYST] run %s done in %.1fs — positions=%d immediate=%d cost=$%.4f",
            report_id,
            report.duration_seconds,
            report.positions_count,
            len(immediate),
            cost_usd,
        )
        return report

    # ── Input collection ──────────────────────────────────────────────

    async def _fetch_positions(self) -> list[dict]:
        """Pull current positions from PortfolioManager.

        PortfolioManager exposes ``_positions`` (an in-memory cache from
        the latest broker sync) and ``get_summary`` for top-line numbers.
        Use the cache directly to avoid blocking on a live broker call —
        the manager already syncs on its own loop.
        """
        try:
            cached = getattr(self.portfolio_manager, "_positions", None)
            if not cached:
                return []
            out: list[dict] = []
            # PortfolioManager._positions is a flat list[dict] today; the
            # legacy dict[broker -> list] shape is still tolerated so older
            # snapshots don't crash the agent.
            if isinstance(cached, dict):
                for broker, positions in cached.items():
                    for p in positions:
                        d = p if isinstance(p, dict) else getattr(p, "to_dict", lambda: {})()
                        if not d:
                            continue
                        d = {**d, "broker": d.get("broker") or broker}
                        out.append(d)
                return out
            if isinstance(cached, list):
                for p in cached:
                    d = p if isinstance(p, dict) else getattr(p, "to_dict", lambda: {})()
                    if not d:
                        continue
                    out.append(d)
                return out
            log.warning(
                "[ANALYST] _fetch_positions: unexpected cache type %s",
                type(cached).__name__,
            )
        except Exception as exc:
            log.warning("[ANALYST] _fetch_positions cache read failed: %s", exc)
        return []

    def _compute_nav(self, positions: list[dict]) -> NAV:
        """Sum market value across all positions; convert CAD via cached FX."""
        usd_total = 0.0
        cad_total = 0.0
        fx_rate = None
        for p in positions:
            mv_usd = p.get("market_value_usd") or p.get("market_value") or 0.0
            try:
                usd_total += float(mv_usd)
            except (TypeError, ValueError):
                pass
            # Some brokers report CAD on Canadian accounts
            if p.get("currency") == "CAD":
                cad_total += float(p.get("market_value") or 0.0)

        # FX rate from manager if available
        try:
            summary = getattr(self.portfolio_manager, "_last_summary", None) or {}
            fx_rate = summary.get("fx_rate_usd_cad") or summary.get("fx_rate")
        except Exception:
            pass

        return NAV(usd=round(usd_total, 2), cad=round(cad_total, 2), fx_rate_usd_cad=fx_rate)

    async def _fetch_signals_24h(self, positions: list[dict]) -> list[dict]:
        """Pull recent awarebot signals filtered by held-ticker tags.

        Uses memory store's fused search if available; else returns [].
        The 24h window matches the awarebot retention horizon.
        """
        if not self.memory_store:
            return []
        tickers = sorted(
            {
                (p.get("symbol") or p.get("ticker") or "").upper()
                for p in positions
                if p.get("symbol") or p.get("ticker")
            }
        )
        tickers = [t for t in tickers if t and len(t) <= 6]
        if not tickers:
            return []

        # Query: search for the union of tickers — memory store will rank
        # by recency × authority and we filter to last 24h. We use the
        # unified ``search(query=...)`` entry-point (vector by default;
        # ``search_units`` is tag-based and not suitable here).
        try:
            search_fn = getattr(self.memory_store, "search", None)
            if not search_fn:
                semantic = getattr(self.memory_store, "semantic_search", None)
                if not semantic:
                    return []
                query = " ".join(f"${t}" for t in tickers[:20])
                result = await semantic(query=query, n_results=200)
            else:
                query = " ".join(f"${t}" for t in tickers[:20])
                if asyncio.iscoroutinefunction(search_fn):
                    result = await search_fn(query=query, top_k=200)
                else:
                    result = search_fn(query=query, top_k=200)
            now_ts = datetime.now(timezone.utc).timestamp()
            cutoff = now_ts - 24 * 3600
            recent: list[dict] = []
            for u in result or []:
                ts = getattr(u, "created_at", None) or getattr(u, "timestamp", None)
                if hasattr(ts, "timestamp"):
                    ts = ts.timestamp()
                if ts and ts < cutoff:
                    continue
                recent.append(
                    {
                        "title": getattr(u, "content", "")[:120],
                        "content": getattr(u, "content", ""),
                        "direction": (getattr(u, "metadata", {}) or {}).get("direction", "neutral"),
                        "confidence": (getattr(u, "metadata", {}) or {}).get("confidence", 0.5),
                        "source": getattr(u, "source", ""),
                        "signal_id": getattr(u, "unit_id", None),
                    }
                )
            return recent
        except Exception as exc:
            log.warning("[ANALYST] signals fetch failed: %s", exc)
            return []

    async def _fetch_council_briefs_24h(self) -> list[dict]:
        """Council briefs persisted on disk from the last 24h."""
        briefs: list[dict] = []
        council_dir = self.data_dir / "councils"
        if not council_dir.exists():
            return briefs

        def _scan() -> list[dict]:
            cutoff = datetime.now(timezone.utc).timestamp() - 24 * 3600
            out: list[dict] = []
            for p in council_dir.glob("*.json"):
                try:
                    if p.stat().st_mtime < cutoff:
                        continue
                    raw = json.loads(p.read_text(encoding="utf-8"))
                    if isinstance(raw, dict):
                        out.append(raw)
                except Exception:
                    continue
            return out

        try:
            briefs = await asyncio.to_thread(_scan)
        except Exception:
            pass
        return briefs

    # ── Deterministic metrics ─────────────────────────────────────────

    def _compute_deterministic(self, positions: list[dict], nav: NAV) -> DeterministicSection:
        """HHI + sector weights + VaR/CVaR + leverage. Pure metrics module."""
        det = DeterministicSection()
        try:
            det.concentration = compute_concentration(positions)
        except Exception as exc:
            log.warning("[ANALYST] concentration failed: %s", exc)
        try:
            det.risk = compute_risk(positions=positions, nav_usd=nav.usd)
        except Exception as exc:
            log.warning("[ANALYST] risk failed: %s", exc)
        return det

    # ── Thesis evaluation across the book ────────────────────────────

    async def _evaluate_all_theses(
        self,
        positions: list[dict],
        signals_24h: list[dict],
        council_briefs_24h: list[dict],
        *,
        dry_run: bool = False,
    ) -> tuple[list[ThesisEvaluationResult], dict[str, PositionThesis]]:
        """For each held position, load+evaluate its thesis.

        Positions without a thesis on file get a placeholder result with
        ``contract_complete=False`` so they appear in the brief's
        "Needs Contract" section. The agent does NOT auto-draft theses
        here — that's a separate LLM call (future v1.1).
        """
        results: list[ThesisEvaluationResult] = []
        theses_by_iid: dict[str, PositionThesis] = {}

        # Filter signals per ticker for efficiency (rough — the evaluator
        # also re-checks via token overlap)
        for p in positions:
            iid = self._instrument_id(p)
            if not iid:
                continue
            thesis = await self.thesis_store.load(iid)
            if thesis is None:
                # Placeholder result — surface as "needs contract"
                results.append(
                    ThesisEvaluationResult(
                        instrument_id=iid,
                        health_score=0.5,
                        health_score_delta=0.0,
                        trend="stable",
                        recommended_action="complete_contract",
                        rationale="No thesis on file for this position.",
                        contract_complete=False,
                        missing_contract_fields=[
                            "ENTIRE THESIS — entry, exit, mandate, watch-for, pillars",
                        ],
                    )
                )
                continue

            theses_by_iid[iid] = thesis
            result = evaluate_thesis(
                thesis=thesis,
                signals_24h=signals_24h,
                council_briefs_24h=council_briefs_24h,
            )
            results.append(result)

            # Persist updated thesis (apply evaluation = append evidence + update health)
            if not dry_run:
                updated = apply_evaluation(thesis, result)
                theses_by_iid[iid] = updated
                try:
                    await self.thesis_store.save(updated)
                except Exception as exc:
                    log.warning("[ANALYST] thesis save failed for %s: %s", iid, exc)

        return results, theses_by_iid

    # ── Immediate actions ─────────────────────────────────────────────

    def _detect_immediate_actions(
        self,
        positions: list[dict],
        theses_by_iid: dict[str, PositionThesis],
        thesis_results: list[ThesisEvaluationResult],
        signals_24h: list[dict],
    ) -> list[ImmediateAction]:
        """Walk positions × theses to surface what NATRIX must act on.

        Severity ladder:
          critical — broken thesis OR stop breached intraday OR option
                     expiring in next 24h (call expiring deep ITM)
          high     — health score <0.40 OR mandate drift >7d OR
                     concentration >1.5× policy
          medium   — thesis weakening trend OR contract incomplete OR
                     imminent catalyst (<3d) with no plan
          low      — informational forward catalysts (3-7d out)
        """
        actions: list[ImmediateAction] = []

        # Index results by iid for quick lookup
        results_by_iid = {r.instrument_id: r for r in thesis_results}

        for p in positions:
            iid = self._instrument_id(p)
            if not iid:
                continue
            ticker = p.get("symbol") or p.get("ticker") or iid
            thesis = theses_by_iid.get(iid)
            result = results_by_iid.get(iid)
            last_price = p.get("last_price") or p.get("current_price") or 0.0

            # 1) Broken thesis
            if result and result.health_score <= self.policy["thesis_broken_threshold"]:
                actions.append(
                    ImmediateAction(
                        ticker=ticker,
                        kind="thesis_broken",
                        detail=(
                            f"Thesis health {result.health_score:.2f} below broken threshold. "
                            f"{result.rationale}"
                        ),
                        severity="critical",
                        linked_signals=[
                            e.signal_id for e in result.new_invalidating_evidence if e.signal_id
                        ][:5],
                    )
                )

            # 2) Stop breach proximity
            if thesis and thesis.exit_plan.stop_price and last_price:
                stop = thesis.exit_plan.stop_price
                if last_price <= stop * 1.02 and last_price > stop:
                    actions.append(
                        ImmediateAction(
                            ticker=ticker,
                            kind="stop_breach_imminent",
                            detail=(
                                f"Close ${last_price:.2f} within "
                                f"{((last_price - stop) / stop * 100):.1f}% of "
                                f"{thesis.exit_plan.stop_kind or 'hard'} stop ${stop:.2f}."
                            ),
                            severity="high",
                        )
                    )
                elif last_price <= stop:
                    actions.append(
                        ImmediateAction(
                            ticker=ticker,
                            kind="stop_breached",
                            detail=(
                                f"Close ${last_price:.2f} BELOW stop ${stop:.2f}. "
                                f"Review exit decision."
                            ),
                            severity="critical",
                        )
                    )

            # 3) Mandate drift
            if result and result.mandate_drift:
                horizon = (
                    thesis.exit_plan.time_horizon_days
                    if thesis and thesis.exit_plan.time_horizon_days
                    else None
                )
                held_days = (result.days_past_horizon or 0) + (horizon or 0) if horizon else "?"
                mandate_label = thesis.mandate.value if thesis else "?"
                actions.append(
                    ImmediateAction(
                        ticker=ticker,
                        kind="mandate_drift",
                        detail=(
                            f"Held {held_days}d, "
                            f"{result.days_past_horizon}d past {mandate_label} horizon."
                        ),
                        severity="high" if (result.days_past_horizon or 0) > 7 else "medium",
                    )
                )

            # 4) Imminent catalyst (within 3d)
            if thesis:
                imminent = imminent_catalysts(thesis, days_ahead=3)
                for w in imminent:
                    if not w.get("imminent"):
                        continue
                    actions.append(
                        ImmediateAction(
                            ticker=ticker,
                            kind="catalyst_imminent",
                            detail=(
                                f"{w.get('label')} in {w.get('days_until', '?')}d "
                                f"({w.get('expected_impact')} impact). "
                                f"{w.get('notes', '')}".strip()
                            ),
                            severity="medium" if w.get("expected_impact") == "high" else "low",
                        )
                    )

            # 5) Contract incomplete
            if result and not result.contract_complete:
                actions.append(
                    ImmediateAction(
                        ticker=ticker,
                        kind="contract_incomplete",
                        detail=(f"Thesis missing: {', '.join(result.missing_contract_fields[:3])}"),
                        severity="medium",
                    )
                )

        # Sort: critical > high > medium > low
        severity_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        actions.sort(key=lambda a: severity_rank.get(a.severity, 9))
        return actions

    # ── Policy risk alerts ────────────────────────────────────────────

    def _policy_risk_alerts(self, nav: NAV, det: DeterministicSection) -> list[RiskAlert]:
        """Compare deterministic metrics against the policy thresholds."""
        alerts: list[RiskAlert] = []

        c = det.concentration
        alerts.append(
            RiskAlert(
                rule="max_single_name_pct",
                value=c.top1_weight,
                threshold=self.policy["max_single_name_pct"],
                tripped=c.top1_weight > self.policy["max_single_name_pct"],
            )
        )

        # Worst sector
        if c.by_sector:
            worst = c.by_sector[0]
            alerts.append(
                RiskAlert(
                    rule="max_sector_pct",
                    value=worst.weight,
                    threshold=self.policy["max_sector_pct"],
                    tripped=worst.weight > self.policy["max_sector_pct"],
                )
            )

        # Drawdown trim trigger
        if det.risk.max_drawdown_ytd_pct is not None:
            alerts.append(
                RiskAlert(
                    rule="drawdown_trim_trigger",
                    value=det.risk.max_drawdown_ytd_pct,
                    threshold=self.policy["drawdown_trim_trigger_pct"] * 100,
                    tripped=det.risk.max_drawdown_ytd_pct
                    <= self.policy["drawdown_trim_trigger_pct"] * 100,
                )
            )

        # Daily loss circuit breaker
        if nav.delta_24h_pct is not None:
            alerts.append(
                RiskAlert(
                    rule="daily_loss_circuit_breaker",
                    value=nav.delta_24h_pct,
                    threshold=self.policy["daily_loss_circuit_breaker_pct"] * 100,
                    tripped=nav.delta_24h_pct
                    <= self.policy["daily_loss_circuit_breaker_pct"] * 100,
                )
            )

        return alerts

    # ── Persistence ───────────────────────────────────────────────────

    async def _persist_report(self, report: NightlyReport) -> Path:
        """Write the nightly report JSON atomically."""
        path = self.reports_dir / f"{report.report_id}.json"
        tmp = path.with_suffix(".json.tmp")

        def _do_write() -> None:
            tmp.write_text(report.model_dump_json(indent=2), encoding="utf-8")
            with open(tmp, "rb+") as f:
                os.fsync(f.fileno())
            os.replace(str(tmp), str(path))

        await asyncio.to_thread(_do_write)
        # Also write a "latest" pointer for easy iOS / Morning Brief fetch
        latest = self.reports_dir / "latest.json"

        def _do_latest() -> None:
            tmp_l = latest.with_suffix(".json.tmp")
            tmp_l.write_text(report.model_dump_json(indent=2), encoding="utf-8")
            os.replace(str(tmp_l), str(latest))

        await asyncio.to_thread(_do_latest)
        return path

    async def _ingest_to_memory(
        self, report: NightlyReport, thesis_results: list[ThesisEvaluationResult]
    ) -> None:
        """Drop a summary MemoryUnit so tomorrow's agent can see today's call."""
        if not self.memory_store:
            return
        try:
            content = report.summary_for_analyst()
            create = getattr(self.memory_store, "create_unit", None) or getattr(
                self.memory_store, "store_unit", None
            )
            if create is None:
                return
            tags = ["portfolio", "agent", "nightly"]
            metadata = {
                "report_id": report.report_id,
                "positions_count": report.positions_count,
                "immediate_action_count": len(report.immediate_actions),
                "authority_tier": "BRAIN",
            }
            kwargs = {
                "content": content,
                "source": f"portfolio:analyst:{report.report_id}",
                "memory_type": "semantic",
                "importance": 75.0,
                "tags": tags,
                "metadata": metadata,
            }
            if asyncio.iscoroutinefunction(create):
                await create(**kwargs)
            else:
                create(**kwargs)
        except Exception as exc:
            log.warning("[ANALYST] memory ingest failed: %s", exc)

    async def _dispatch_alerts(
        self,
        immediate: list[ImmediateAction],
        thesis_results: list[ThesisEvaluationResult],
    ) -> None:
        """Fire ntfy push for any critical-severity action."""
        if not self.brain:
            return
        enqueue = getattr(self.brain, "enqueue_alert", None)
        if not enqueue:
            return
        critical = [a for a in immediate if a.severity == "critical"]
        if not critical:
            return
        title = f"Portfolio: {len(critical)} critical item{'s' if len(critical) != 1 else ''}"
        body_lines = []
        for a in critical[:5]:
            body_lines.append(f"[{a.kind}] {a.ticker}: {a.detail}")
        body = "\n".join(body_lines)
        try:
            if asyncio.iscoroutinefunction(enqueue):
                await enqueue(title=title, body=body, priority="high", tag="portfolio")
            else:
                enqueue(title=title, body=body, priority="high", tag="portfolio")
        except Exception as exc:
            log.warning("[ANALYST] alert dispatch failed: %s", exc)

    # ── Helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _instrument_id(p: dict) -> str:
        """Canonical id for a position. Matches ThesisStore key shape."""
        explicit = p.get("instrument_id")
        if explicit:
            return explicit
        sym = (p.get("symbol") or p.get("ticker") or "").upper()
        if not sym:
            return ""
        asset = (p.get("asset_type") or "").lower()
        if asset == "option":
            # Cheap option id — caller can refine if needed
            return f"OPT:{sym}"
        if asset == "crypto":
            return f"CRYPTO:{sym}"
        if asset == "future":
            return f"FUT:{sym}"
        return f"EQ:{sym}"
