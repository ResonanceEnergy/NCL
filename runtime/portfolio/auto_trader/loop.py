"""
Auto-Trader decision loop — Wave 14K Phase 2 (K1a + K1b + K1c)

Main scheduler task. Every 60s in market hours / 300s off-hours:

  1. Read state.is_active() — if False, sleep + continue
  2. Read drawdown_bucket.get_state() — if band == "halt", set
     state.set_drawdown_halt(True) and sleep
  3. Read trade_idea_tracker.list_by_strategy(None) filtered to:
       - outcome == "emitted"
       - issued_at_iso > state.last_seen_trade_idea_iso
  4. For each new idea (sorted oldest-first, capped at max_opens_per_tick):
       a. Compute hypothetical R_dollars and call
          risk_governor.check_proposed_trade()
       b. Call policy.auto_open_eligible(idea, governor_decision)
       c. If NOT eligible: log + bump rejected counter
       d. If eligible:
            - Compute qty = max(1, effective_R / R_per_share)
            - Convert idea to paper_trade payload (K1b: stash trade_idea_id
              in scanner_data so outcome attribution can stitch)
            - Call PaperTradingEngine.create_trade()
            - Link via observability.update_paper_trade_id()
            - Call trade_idea_tracker.update_outcome("taken")
            - K1c: emit portfolio:auto_trade_opened MemUnit at importance 75
            - Bump opened counter
            - Respect max_opens_per_tick / max_opens_per_day
  5. state.record_tick(...) — update counters + last_seen_iso

Idempotent: each trade idea is keyed by trade_idea_id and re-recording
is a no-op (trade_idea_tracker.update_outcome + observability.record_
reasoning_chain both dedup). Restart-safe: state.last_seen_trade_idea_id
persists to disk; the loop resumes from where it left off.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time as dtime, timezone
from typing import Optional

log = logging.getLogger("ncl.portfolio.auto_trader.loop")

# Cadences (seconds)
TICK_MARKET = 60
TICK_OFFHOURS = 300


def _is_market_open(now: Optional[datetime] = None) -> bool:
    """M-F 09:30-16:00 ET. Crude (no holiday calendar) but good enough
    for cadence selection. The drawdown_bucket + risk_governor are the
    real gates on what gets opened."""
    now = now or datetime.now(timezone.utc)
    # UTC -> ET. Approximate UTC-4 (EDT). Use proper TZ if needed.
    et_hour = (now.hour - 4) % 24
    if now.weekday() >= 5:
        return False
    return (et_hour, now.minute) >= (9, 30) and et_hour < 16


# ── Helpers ──────────────────────────────────────────────────────

def _idea_to_paper_payload(idea: dict, qty: float, *, slippage_profile: str = "conservative") -> dict:
    """Convert a trade_idea dict into PaperTradingEngine.create_trade()
    payload. K1b: stash the trade_idea_id in scanner_data so the
    outcome attributor (Phase 3) can stitch back on close."""
    direction = (idea.get("direction") or "long").lower()
    return {
        "symbol": (idea.get("ticker") or "").upper(),
        "direction": direction,
        "asset_type": (idea.get("type") or "stock").lower(),
        "strategy": (
            idea.get("strategy_tag") or idea.get("strategy") or "auto"
        ),
        # Entry
        "entry_price": float(idea["entry_price"]),
        "quantity": float(qty),
        # Exit plan
        "stop_loss": float(idea["stop_price"]),
        "target_1": float(idea["target_price"]),
        # Journal
        "notes": (idea.get("thesis") or "")[:500],
        "confidence": int(idea.get("confidence_pct") or 3),
        "tags": ["auto_trader"] + (
            [f"stance:{idea['rotation_stance']}"] if idea.get("rotation_stance") else []
        ),
        # K1b: trade_idea_id stashed for stitching
        "scanner_data": {
            "trade_idea_id": idea.get("trade_idea_id"),
            "source": (idea.get("source") or "brief"),
            "issued_at_iso": idea.get("issued_at_iso"),
            "sources": idea.get("sources") or [],
            "stop_type": idea.get("stop_type"),
            "stop_basis": idea.get("stop_basis"),
            "target_basis": idea.get("target_basis"),
            "R_per_share_at_emit": idea.get("R_per_share"),
            "rotation_quadrant": idea.get("rotation_quadrant"),
            "rotation_stance": idea.get("rotation_stance"),
            "slippage_profile": slippage_profile,
        },
    }


async def _emit_open_memory_unit(brain, *, idea: dict, paper_trade_id: str,
                                  governor_decision: dict, effective_R: float) -> None:
    """K1c: emit portfolio:auto_trade_opened MemUnit (importance 75).
    Fire-and-forget — never block the loop on memory write."""
    mem = getattr(brain, "memory_store", None)
    if mem is None or not hasattr(mem, "create_unit"):
        return
    ticker = (idea.get("ticker") or "?").upper()
    strat = (idea.get("strategy_tag") or idea.get("type") or "auto").lower()
    content = (
        f"Auto-trader opened paper position: {ticker} "
        f"{idea.get('direction', 'long')} qty={idea.get('planned_qty') or 0} "
        f"@ ${idea.get('entry_price')}; stop ${idea.get('stop_price')}; "
        f"target ${idea.get('target_price')}; effective_R ${effective_R:.2f}; "
        f"strategy={strat}; trade_idea_id={idea.get('trade_idea_id')}"
    )
    try:
        await mem.create_unit(
            content=content,
            source="portfolio:auto_trade_opened",
            importance=75.0,
            tags=[
                "portfolio", "auto_trader", "paper_open",
                f"strategy:{strat}", f"ticker:{ticker}",
            ],
            memory_type="episodic",
            metadata={
                "trade_idea_id": idea.get("trade_idea_id"),
                "paper_trade_id": paper_trade_id,
                "ticker": ticker,
                "strategy": strat,
                "effective_R_dollars": effective_R,
                "governor_decision": (governor_decision.get("decision")
                                       if governor_decision else None),
                "wave": "14K-K1c",
            },
        )
    except Exception as e:
        log.debug("[AT-LOOP] memory emission skipped: %s", e)


# ── Main loop ────────────────────────────────────────────────────

async def auto_trader_loop(brain) -> None:
    """Main scheduler-registered loop. Runs forever; respects asyncio
    cancellation. Tick cadence depends on market hours."""
    log.info("[AT-LOOP] starting auto-trader decision loop")
    # Late imports so the module is safe to import in tests without
    # initializing the whole portfolio subsystem.
    from .state import (
        get_state, is_active, record_tick, set_drawdown_halt,
    )
    from .policy import get_policy, auto_open_eligible
    from .observability import record_reasoning_chain, update_paper_trade_id
    from ..drawdown_bucket import get_drawdown_bucket
    from ..risk_governor import check_proposed_trade
    from ..trade_idea_tracker import get_trade_idea_tracker
    from ..paper_trading import PaperTradingEngine
    # Wave 14K Phase 8 K7a — circuit breakers around external deps so a
    # failing governor / tracker / quote feed doesn't crash the loop or
    # spam logs. Three-strike pattern: 3 consecutive failures opens the
    # breaker for 10 min, then auto-resets.
    from ..hygiene import get_circuit_breaker

    paper = PaperTradingEngine()
    cb_drawdown = await get_circuit_breaker("auto_trader:drawdown_bucket")
    cb_governor = await get_circuit_breaker("auto_trader:risk_governor")
    cb_tracker = await get_circuit_breaker("auto_trader:trade_idea_tracker")
    cb_paper = await get_circuit_breaker("auto_trader:paper_engine")

    while True:
        try:
            tick_secs = TICK_MARKET if _is_market_open() else TICK_OFFHOURS
            # 1) Check drawdown band first (sets state side-effect)
            #    K7a: circuit-breaker wrapped — if drawdown subsystem is
            #    failing, skip the check but continue the loop (safer to
            #    keep evaluating than to halt on a degraded sensor).
            if cb_drawdown.is_open():
                log.debug("[AT-LOOP] drawdown breaker OPEN, skipping band check")
                band = None
            else:
                try:
                    bucket = await get_drawdown_bucket()
                    dd_state = await bucket.get_state()
                    band = dd_state.get("band", "green")
                    # Wave 14K hardening: a NAV reading of $0 means the
                    # portfolio sync hasn't completed yet, not that the
                    # account is wiped. Treat as data-unavailable rather
                    # than 100% drawdown — preserves operator intent
                    # ("don't pause for an empty data point").
                    nav_cad = float(dd_state.get("current_nav_cad") or 0)
                    if band == "halt" and nav_cad < 100:
                        log.debug(
                            "[AT-LOOP] drawdown band=halt but NAV=$%.2f — "
                            "treating as data-unavailable, not halt", nav_cad,
                        )
                        band = "unknown"
                        await set_drawdown_halt(False, band="unknown")
                    else:
                        await set_drawdown_halt(band == "halt", band=band)
                    cb_drawdown.record_success()
                except Exception as e:
                    cb_drawdown.record_failure()
                    log.warning("[AT-LOOP] drawdown read failed (continuing): %s", e)
                    band = None

            # 2) Active check (state.is_active() ANDs together
            #    active + not paused + not drawdown_halt)
            if not await is_active():
                # Don't burn cycles when paused — light tick
                await asyncio.sleep(tick_secs)
                continue

            policy = await get_policy()
            state = await get_state()

            # 3) Day-cap check
            if state.ideas_opened_today >= policy.max_opens_per_day:
                log.debug("[AT-LOOP] day cap reached (%d), skipping",
                          policy.max_opens_per_day)
                await asyncio.sleep(tick_secs)
                continue

            # 4) Pull recently-emitted ideas
            #    K7a: tracker breaker — if the tracker is broken, we
            #    have nothing to do this tick; skip to next.
            if cb_tracker.is_open():
                log.debug("[AT-LOOP] tracker breaker OPEN, skipping tick")
                await asyncio.sleep(tick_secs)
                continue
            try:
                tracker = await get_trade_idea_tracker()
                all_ideas = await tracker.list_by_strategy(None)
                cb_tracker.record_success()
            except Exception as e:
                cb_tracker.record_failure()
                log.warning("[AT-LOOP] tracker read failed: %s", e)
                await asyncio.sleep(tick_secs)
                continue
            # Filter to outcome=="emitted" and issued AFTER last_seen
            last_seen_iso = state.last_seen_trade_idea_id or ""
            # `list_by_strategy` returns ideas sorted by issued_at_iso DESC;
            # we want oldest-first for FIFO processing.
            candidates = sorted(
                [
                    i for i in all_ideas
                    if (i.get("outcome") == "emitted")
                    and (i.get("issued_at_iso") or "") > last_seen_iso
                ],
                key=lambda i: i.get("issued_at_iso") or "",
            )
            if not candidates:
                await record_tick(evaluated=0, opened=0, rejected=0)
                await asyncio.sleep(tick_secs)
                continue

            opens_this_tick = 0
            evaluated = 0
            rejected = 0
            opened = 0
            newest_seen = last_seen_iso

            for idea in candidates:
                evaluated += 1
                newest_seen = max(newest_seen, idea.get("issued_at_iso") or "")

                # Enforce per-tick cap
                if opens_this_tick >= policy.max_opens_per_tick:
                    break
                # Re-check day-cap inside loop (multiple opens this tick)
                if state.ideas_opened_today + opened >= policy.max_opens_per_day:
                    break

                trade_idea_id = idea.get("trade_idea_id")
                ticker = (idea.get("ticker") or "").upper()
                strat = (
                    idea.get("strategy_tag") or idea.get("strategy")
                    or idea.get("type") or "auto"
                )

                # 5) Compute R_dollars + call governor
                rps = float(idea.get("R_per_share") or 0)
                planned_qty = float(idea.get("planned_qty") or 100)
                proposed_R = rps * planned_qty if rps > 0 else 0.0
                gov = None
                if proposed_R > 0:
                    # K7a: governor breaker — if the governor is failing,
                    # default to REJECT (safest: no sizing without a gate).
                    if cb_governor.is_open():
                        log.debug(
                            "[AT-LOOP] governor breaker OPEN, defaulting REJECT for %s",
                            ticker,
                        )
                        gov = {"approved": False,
                               "decision": "reject",
                               "reason": "governor circuit-breaker open"}
                    else:
                        try:
                            gov = await check_proposed_trade(
                                strategy_tag=str(strat),
                                R_dollars_proposed=proposed_R,
                                symbol=ticker,
                            )
                            cb_governor.record_success()
                        except Exception as e:
                            cb_governor.record_failure()
                            log.warning("[AT-LOOP] governor check failed: %s", e)

                # 6a) Calendar gate (Wave 14K hardening #1) — block opens
                #     when macro events (FOMC/OPEX/quad-witch/VIX) or per-
                #     ticker earnings are within configured day windows.
                #     Non-blocking on failure: degrade to "no calendar info"
                #     rather than crash the loop.
                try:
                    from .calendar_gate import check_calendar_block
                    cal_blocked, cal_reason = await check_calendar_block(ticker)
                except Exception as e:
                    log.warning("[AT-LOOP] calendar gate failed: %s", e)
                    cal_blocked, cal_reason = False, ""
                if cal_blocked:
                    log.info(
                        "[AT-LOOP] REJECT %s (%s) — calendar: %s",
                        trade_idea_id, ticker, cal_reason,
                    )
                    rejected += 1
                    await record_reasoning_chain(
                        trade_idea_id=trade_idea_id,
                        idea_snapshot=idea,
                        governor_decision=gov,
                        policy_check={
                            "eligible": False,
                            "reason": f"calendar: {cal_reason}",
                            "policy_rev": policy.revision,
                        },
                        source=idea.get("source") or "brief",
                        strategy=str(strat),
                        ticker=ticker,
                        effective_R_dollars=None,
                        planned_qty=planned_qty,
                    )
                    continue

                # 6b) Working-context gate (Wave 14K hardening #3) — read
                #     today's NATRIX-tier pinned items + check if the
                #     ticker is contradicted. Annotates the idea with
                #     alignment metadata regardless. Non-blocking on read
                #     failure.
                wc_info = {"aligned_with": [], "contradicted_by": []}
                try:
                    from .working_context_gate import check_working_context
                    wc_info = await check_working_context(ticker)
                except Exception as e:
                    log.warning("[AT-LOOP] working_context gate failed: %s", e)
                if wc_info.get("blocked"):
                    log.info(
                        "[AT-LOOP] REJECT %s (%s) — working_context: %s",
                        trade_idea_id, ticker, wc_info.get("block_reason", ""),
                    )
                    rejected += 1
                    await record_reasoning_chain(
                        trade_idea_id=trade_idea_id,
                        idea_snapshot=idea,
                        governor_decision=gov,
                        policy_check={
                            "eligible": False,
                            "reason": f"working_context: {wc_info.get('block_reason', '')}",
                            "policy_rev": policy.revision,
                        },
                        source=idea.get("source") or "brief",
                        strategy=str(strat),
                        ticker=ticker,
                        effective_R_dollars=None,
                        planned_qty=planned_qty,
                    )
                    continue

                # 6c) Apply auto-bar
                eligible, reason = await auto_open_eligible(idea, gov, policy=policy)
                if not eligible:
                    log.info(
                        "[AT-LOOP] REJECT %s (%s): %s",
                        trade_idea_id, ticker, reason,
                    )
                    rejected += 1
                    # Record policy_check on the reasoning chain even
                    # for rejects — useful for retrospective analysis
                    await record_reasoning_chain(
                        trade_idea_id=trade_idea_id,
                        idea_snapshot=idea,
                        governor_decision=gov,
                        policy_check={
                            "eligible": False,
                            "reason": reason,
                            "policy_rev": policy.revision,
                        },
                        source=idea.get("source") or "brief",
                        strategy=str(strat),
                        ticker=ticker,
                        effective_R_dollars=None,
                        planned_qty=planned_qty,
                    )
                    continue

                # 7) Open paper trade
                effective_R = (
                    gov.get("effective_R_dollars") if gov else proposed_R
                ) or proposed_R
                qty = max(1, int(effective_R / rps)) if rps > 0 else int(planned_qty)

                # 7a) Wave 14L M1 — tax-aware sizing: wash sale check + earnings
                #     proximity multiplier. Block if wash-sale conflict +
                #     NCL_AT_WASH_BLOCK=1.
                tax_result = None
                try:
                    from .tax_sizing import apply_tax_sizing
                    tax_result = await apply_tax_sizing(
                        idea=idea, proposed_qty=qty,
                        proposed_R_dollars=effective_R, brain=brain,
                    )
                    if not tax_result.get("approved"):
                        log.info(
                            "[AT-LOOP] REJECT %s (%s) — tax: %s",
                            trade_idea_id, ticker, tax_result.get("block_reason", ""),
                        )
                        rejected += 1
                        await record_reasoning_chain(
                            trade_idea_id=trade_idea_id,
                            idea_snapshot=idea,
                            governor_decision=gov,
                            policy_check={
                                "eligible": False,
                                "reason": f"tax: {tax_result.get('block_reason', '')}",
                                "policy_rev": policy.revision,
                                "tax_result": tax_result,
                            },
                            source=idea.get("source") or "brief",
                            strategy=str(strat),
                            ticker=ticker,
                            effective_R_dollars=effective_R,
                            planned_qty=qty,
                        )
                        continue
                    # Apply size multiplier
                    qty = int(tax_result.get("adjusted_qty", qty))
                    effective_R = tax_result.get("adjusted_R_dollars", effective_R)
                except Exception as e:
                    log.warning("[AT-LOOP] tax sizing skipped: %s", e)

                payload = _idea_to_paper_payload(idea, qty)
                # Wave 14K Phase 7 K6a: apply per-strategy friction
                # (slippage + partial-fill) before handing to the paper
                # engine. Non-blocking — if friction lookup fails, open
                # at the unfricted price.
                try:
                    from .friction_profile import (
                        get_profile, apply_friction_to_payload,
                    )
                    asset_type = str(payload.get("asset_type") or "stock")
                    profile = await get_profile(str(strat), asset_type=asset_type)
                    payload = apply_friction_to_payload(payload, profile)
                except Exception as e:
                    log.warning("[AT-LOOP] friction injection skipped: %s", e)
                # 8.5) High-R council quorum check (gap-close A) — for
                #     trades sized large enough, get a Sonnet+Haiku second
                #     opinion before committing. Veto returns the idea to
                #     emitted state. Non-blocking on failure (env tunable).
                council_result = None
                try:
                    from .council_check import check_high_r_open
                    council_result = await check_high_r_open(
                        idea=idea, gov=gov, effective_R=effective_R,
                    )
                    if council_result.get("veto"):
                        log.info(
                            "[AT-LOOP] REJECT %s (%s) — council quorum: %s",
                            trade_idea_id, ticker,
                            council_result.get("reason", ""),
                        )
                        rejected += 1
                        await record_reasoning_chain(
                            trade_idea_id=trade_idea_id,
                            idea_snapshot=idea,
                            governor_decision=gov,
                            policy_check={
                                "eligible": False,
                                "reason": (
                                    f"council_quorum: "
                                    f"{council_result.get('reason', '')}"
                                ),
                                "policy_rev": policy.revision,
                                "council_check": council_result,
                            },
                            source=idea.get("source") or "brief",
                            strategy=str(strat),
                            ticker=ticker,
                            effective_R_dollars=effective_R,
                            planned_qty=qty,
                        )
                        continue
                except Exception as e:
                    log.warning("[AT-LOOP] council quorum check failed: %s", e)

                # K7a: paper-engine breaker — if create_trade is failing
                # repeatedly we want to stop hammering it.
                if cb_paper.is_open():
                    log.debug("[AT-LOOP] paper breaker OPEN, skipping %s open", ticker)
                    rejected += 1
                    continue
                try:
                    pt = paper.create_trade(payload)
                    cb_paper.record_success()
                except Exception as e:
                    cb_paper.record_failure()
                    log.error(
                        "[AT-LOOP] create_trade FAILED for %s: %s", ticker, e,
                    )
                    rejected += 1
                    continue

                paper_trade_id = getattr(pt, "id", None) or getattr(pt, "trade_id", None)
                log.info(
                    "[AT-LOOP] OPENED %s qty=%d @ $%.2f (paper_trade_id=%s, "
                    "trade_idea_id=%s, effective_R=$%.2f)",
                    ticker, qty, payload["entry_price"], paper_trade_id,
                    trade_idea_id, effective_R,
                )

                # 8) Record reasoning chain + link paper_trade_id
                policy_check_meta = {
                    "eligible": True,
                    "reason": reason,
                    "policy_rev": policy.revision,
                }
                if council_result:
                    policy_check_meta["council_check"] = council_result
                await record_reasoning_chain(
                    trade_idea_id=trade_idea_id,
                    idea_snapshot=idea,
                    governor_decision=gov,
                    policy_check=policy_check_meta,
                    paper_trade_id=paper_trade_id,
                    source=idea.get("source") or "brief",
                    strategy=str(strat),
                    ticker=ticker,
                    confidence_pct=idea.get("confidence_pct"),
                    effective_R_dollars=effective_R,
                    planned_qty=qty,
                )
                await update_paper_trade_id(trade_idea_id, paper_trade_id)

                # 9) Mark idea as taken in tracker
                try:
                    await tracker.update_outcome(
                        trade_idea_id,
                        outcome="taken",
                        notes=f"auto-opened paper_trade_id={paper_trade_id}",
                    )
                except Exception as e:
                    log.warning("[AT-LOOP] tracker.update_outcome failed: %s", e)

                # 10) K1c: emit memory unit
                await _emit_open_memory_unit(
                    brain, idea=idea, paper_trade_id=paper_trade_id,
                    governor_decision=gov, effective_R=effective_R,
                )

                opened += 1
                opens_this_tick += 1
                if policy.cooldown_seconds_after_open > 0 and opens_this_tick < len(candidates):
                    await asyncio.sleep(policy.cooldown_seconds_after_open)

            # 11) Tick book-keeping
            await record_tick(
                evaluated=evaluated, opened=opened, rejected=rejected,
                last_seen_id=newest_seen or None,
            )
            log.info(
                "[AT-LOOP] tick done — evaluated=%d opened=%d rejected=%d "
                "(day: %d opened, %d rejected)",
                evaluated, opened, rejected,
                state.ideas_opened_today + opened,
                state.ideas_rejected_today + rejected,
            )

        except asyncio.CancelledError:
            log.info("[AT-LOOP] cancelled")
            raise
        except Exception as e:
            log.error("[AT-LOOP] tick error (will continue): %s", e, exc_info=True)

        await asyncio.sleep(tick_secs)
