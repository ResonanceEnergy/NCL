"""
ncl-night-watch Phase 5 analyst (carved from scheduler.py, W10B-14).

LLM-powered analysis phase for Night Watch. Runs AFTER the deterministic
health checks. Collects operational data from multiple subsystems, triages
with Sonnet, synthesizes with Opus, pushes a daily briefing via ntfy, and
saves to disk.

This is the extracted body of what used to be
`AutonomousScheduler._night_watch_analyst` defined inline in
`runtime/autonomous/scheduler.py`. The method on the scheduler is now a
thin shim that calls `run(self, ...)` here so external callers and
factories that reference the method name still resolve.

Scheduler attributes touched (passed in as `scheduler`):
- `scheduler.data_dir` — Path. Used to locate `costs/cost_ledger.jsonl`,
  `predictions/`, `councils/`, `council_sessions.json`, `intelligence/`,
  `night-watch/` output dir. Read-write (creates `night-watch/` if absent).
- `scheduler.brain` — Brain instance. Reads `scheduler.brain.memory_store`
  and awaits its async `stats()`. Tolerates `None` / missing attrs.
- `scheduler.awarebot` — Awarebot instance. Reads `awarebot.get_stats()`.
  Tolerates `None`.

NOTE on safety of state refs:
- `data_dir`, `brain`, `awarebot` are all set in `Scheduler.__init__` and
  are stable for the scheduler's lifetime. Reads only; no mutation. The
  one mutation is `(data_dir / "night-watch").mkdir(...)` which is the
  scheduler's owned output dir, and aiofiles writes the brief MD file
  inside it. Safe to call from the carved-out module.
- The inline LLM-prompt template stays put — intentionally NOT externalized
  to a .txt file (separate refactor per W10B-14 scope).

Other dependencies:
- `runtime.cost_tracker.get_tracker` — async budget tracker singleton.
- `runtime.notifications.enqueue_alert` — central ntfy dispatcher.
- httpx, aiofiles — same direct calls as before the carve.
"""

from __future__ import annotations  # noqa: I001

import json
import logging
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiofiles

from ...notifications import enqueue_alert

log = logging.getLogger("ncl.autonomous")


async def run(
    scheduler,
    deterministic_issues: list[str],
    has_warnings: bool,
    critical: bool,
    *,
    memory_report: dict | None = None,
    intel_report: dict | None = None,
    council_report: dict | None = None,
) -> None:
    """
    LLM-powered analysis phase for Night Watch.

    Runs AFTER the deterministic health checks. Collects operational data
    from multiple subsystems, triages with Sonnet, synthesizes with Opus,
    pushes a daily briefing via ntfy, and saves to disk.
    """
    import httpx

    from ...cost_tracker import get_tracker

    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        log.warning("[NIGHT-WATCH] No ANTHROPIC_API_KEY — skipping LLM analyst")
        return

    tracker = await get_tracker()

    # ── Budget guard: estimate max cost ──────────────────────────
    # 4 Sonnet calls ~2000 tok in + ~500 tok out each = ~$0.05
    # 1 Sonnet call ~4000 tok in + ~1000 tok out   = ~$0.027
    # Total estimate: ~$0.04
    estimated_total = 0.05  # conservative
    if not await tracker.can_spend("anthropic", estimated_total):
        log.warning("[NIGHT-WATCH] LLM analysis skipped — budget exceeded")
        return

    # ══════════════════════════════════════════════════════════════
    # DATA COLLECTION PHASE (all local, no LLM cost)
    # ══════════════════════════════════════════════════════════════

    collected: dict[str, str] = {}

    # ── 1. Cost ledger summary ────────────────────────────────────
    try:
        cost_lines: list[str] = []
        ledger_path = scheduler.data_dir / "costs" / "cost_ledger.jsonl"
        if ledger_path.exists():
            source_totals: dict[str, float] = defaultdict(float)
            category_totals: dict[str, float] = defaultdict(float)
            all_entries: list[dict] = []
            with open(ledger_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        if entry.get("date") == today_str:
                            src = entry.get("source", "unknown")
                            cat = entry.get("category", "unknown")
                            amt = entry.get("amount_usd", 0.0)
                            source_totals[src] += amt
                            category_totals[cat] += amt
                            all_entries.append(entry)
                    except json.JSONDecodeError:
                        continue

            grand_total = sum(source_totals.values())
            cost_lines.append(f"Total spend today: ${grand_total:.4f}")
            cost_lines.append(f"Calls today: {len(all_entries)}")
            cost_lines.append(
                "Per-source: "
                + ", ".join(
                    f"{s}=${v:.4f}"
                    for s, v in sorted(source_totals.items(), key=lambda x: -x[1])
                )
            )
            cost_lines.append(
                "Per-category: "
                + ", ".join(
                    f"{c}=${v:.4f}"
                    for c, v in sorted(category_totals.items(), key=lambda x: -x[1])[:8]
                )
            )
            # Top 5 most expensive individual calls
            top5 = sorted(all_entries, key=lambda e: -e.get("amount_usd", 0))[:5]
            if top5:
                cost_lines.append("Top 5 costliest calls:")
                for e in top5:
                    cost_lines.append(
                        f"  ${e.get('amount_usd', 0):.4f} — "
                        f"{e.get('source', '?')}/{e.get('category', '?')}: "
                        f"{e.get('detail', '')[:80]}"
                    )
        else:
            cost_lines.append("No cost ledger found.")

        collected["costs"] = "\n".join(cost_lines)
    except Exception as e:
        collected["costs"] = f"Error reading cost data: {e}"

    # ── 2. Prediction accuracy ────────────────────────────────────
    try:
        pred_lines: list[str] = []
        pred_dir = scheduler.data_dir / "predictions"
        if pred_dir.exists():
            pred_files = sorted(pred_dir.glob("pred-*.json"), reverse=True)[:20]
            total_preds = 0
            with_outcome = 0
            correct = 0
            topics: list[str] = []
            for pf in pred_files:
                try:
                    pdata = json.loads(pf.read_text())
                    preds_list = (
                        pdata if isinstance(pdata, list) else pdata.get("predictions", [pdata])
                    )
                    for p in preds_list if isinstance(preds_list, list) else [preds_list]:
                        total_preds += 1
                        topic = p.get("topic", p.get("title", ""))
                        if topic and len(topics) < 10:
                            topics.append(topic[:60])
                        outcome = p.get("outcome")
                        if outcome:
                            with_outcome += 1
                            if outcome in ("correct", "partial"):
                                correct += 1
                except Exception:
                    continue

            pred_lines.append(f"Recent prediction files: {len(pred_files)}")
            pred_lines.append(f"Total predictions parsed: {total_preds}")
            pred_lines.append(f"With recorded outcomes: {with_outcome}")
            if with_outcome > 0:
                acc = correct / with_outcome * 100
                pred_lines.append(f"Accuracy (correct+partial): {acc:.1f}%")
            if topics:
                pred_lines.append(f"Recent topics: {'; '.join(topics[:5])}")

            # Check accuracy.jsonl
            acc_file = pred_dir / "accuracy.jsonl"
            if acc_file.exists():
                acc_count = sum(1 for _ in open(acc_file))
                pred_lines.append(f"Accuracy JSONL entries: {acc_count}")
        else:
            pred_lines.append("No predictions directory found.")

        collected["predictions"] = "\n".join(pred_lines)
    except Exception as e:
        collected["predictions"] = f"Error reading predictions: {e}"

    # ── 3. Council session summary ────────────────────────────────
    try:
        council_lines: list[str] = []
        councils_dir = scheduler.data_dir / "councils"
        if councils_dir.exists():
            # Count report files from today
            report_files = list(councils_dir.glob("*.json"))
            today_reports: list[dict] = []
            for rf in report_files:
                try:
                    if (
                        rf.stat().st_mtime
                        > (datetime.now(timezone.utc) - timedelta(hours=24)).timestamp()
                    ):
                        rdata = json.loads(rf.read_text())
                        topic = rdata.get("topic", rdata.get("prompt", ""))[:80]
                        today_reports.append({"file": rf.name, "topic": topic})
                except Exception:
                    continue

            council_lines.append(f"Council reports (last 24h): {len(today_reports)}")
            for cr in today_reports[:5]:
                council_lines.append(f"  {cr['file']}: {cr['topic']}")

            # Also check council sessions file
            sessions_file = scheduler.data_dir / "council_sessions.json"
            if sessions_file.exists():
                try:
                    sdata = json.loads(sessions_file.read_text())
                    if isinstance(sdata, list):
                        council_lines.append(f"Total council sessions on record: {len(sdata)}")
                except Exception:
                    pass
        else:
            council_lines.append("No councils directory found.")

        collected["councils"] = "\n".join(council_lines)
    except Exception as e:
        collected["councils"] = f"Error reading council data: {e}"

    # ── 4. Memory stats ───────────────────────────────────────────
    try:
        mem_lines: list[str] = []
        if scheduler.brain and scheduler.brain.memory_store:
            try:
                stats = await scheduler.brain.memory_store.stats()
                if isinstance(stats, dict):
                    mem_lines.append(f"Memory units: {stats.get('total', 'unknown')}")
                    for k, v in stats.items():
                        if k != "total" and isinstance(v, (int, float)):
                            mem_lines.append(f"  {k}: {v}")
                else:
                    mem_lines.append(f"Memory stats: {stats}")
            except Exception as e:
                mem_lines.append(f"Memory store stats() failed: {e}")
        else:
            mem_lines.append("Memory store not available.")

        collected["memory"] = "\n".join(mem_lines)
    except Exception as e:
        collected["memory"] = f"Error reading memory stats: {e}"

    # ── 4b. Night Watch Memory Cycle report ──────────────────────
    if memory_report:
        try:
            mc_lines: list[str] = []
            if memory_report.get("error"):
                mc_lines.append(f"Memory cycle error: {memory_report['error']}")
            else:
                mc_lines.append(f"Duplicates found: {memory_report.get('duplicates_found', 0)}")
                mc_lines.append(f"Units re-scored: {memory_report.get('units_rescored', 0)}")
                mc_lines.append(
                    f"Entities extracted: {memory_report.get('entities_extracted', 0)}"
                )
                mc_lines.append(
                    f"Stale facts found: {memory_report.get('stale_facts_found', 0)}"
                )
                mc_lines.append(f"Normalizations: {memory_report.get('normalizations', 0)}")
                kg = memory_report.get("kg_stats", {})
                if kg:
                    mc_lines.append(
                        f"KG nodes: {kg.get('nodes', 0)}, edges: {kg.get('edges', 0)}, components: {kg.get('components', 0)}"  # noqa: E501
                    )
                mc_lines.append(
                    f"Memory cycle cost: ${memory_report.get('total_cost_usd', 0):.4f}"
                )
                mc_lines.append(
                    f"Memory cycle duration: {memory_report.get('duration_seconds', 0):.1f}s"
                )
                errors = memory_report.get("errors", [])
                if errors:
                    mc_lines.append(f"Errors ({len(errors)}): " + "; ".join(errors[:5]))
            collected["memory_cycle"] = "\n".join(mc_lines)
        except Exception as e:
            collected["memory_cycle"] = f"Error formatting memory cycle report: {e}"

    # ── 4c. Night Watch Intel Cycle report ────────────────────────
    if intel_report:
        try:
            ic_lines: list[str] = []
            if intel_report.get("error"):
                ic_lines.append(f"Intel cycle error: {intel_report['error']}")
            else:
                ic_lines.append(
                    f"Missed correlations: {intel_report.get('missed_correlations', 0)}"
                )
                blind_spots = intel_report.get("blind_spots", [])
                if blind_spots:
                    ic_lines.append(
                        f"Coverage blind spots ({len(blind_spots)}): {', '.join(blind_spots[:10])}"  # noqa: E501
                    )
                ic_lines.append(
                    f"Over-scored signals: {intel_report.get('over_scored_signals', 0)}"
                )
                ic_lines.append(
                    f"Under-scored signals: {intel_report.get('under_scored_signals', 0)}"
                )
                ic_lines.append(
                    f"Stale predictions: {intel_report.get('predictions_stale', 0)}"
                )
                pma = intel_report.get("per_model_accuracy", {})
                if pma:
                    ic_lines.append(
                        "Per-model accuracy: " + ", ".join(f"{m}={a}" for m, a in pma.items())
                    )
                suggestions = intel_report.get("council_suggestions", [])
                if suggestions:
                    ic_lines.append(
                        f"Council topic suggestions ({len(suggestions)}): {'; '.join(suggestions[:3])}"  # noqa: E501
                    )
                cost_opt = intel_report.get("cost_optimization", "")
                if cost_opt:
                    ic_lines.append(f"Cost optimization: {cost_opt[:200]}")
                ic_lines.append(
                    f"Intel cycle cost: ${intel_report.get('total_cost_usd', 0):.4f}"
                )
                ic_lines.append(
                    f"Intel cycle duration: {intel_report.get('duration_seconds', 0):.1f}s"
                )
                errors = intel_report.get("errors", [])
                if errors:
                    ic_lines.append(f"Errors ({len(errors)}): " + "; ".join(errors[:5]))
            collected["intel_cycle"] = "\n".join(ic_lines)
        except Exception as e:
            collected["intel_cycle"] = f"Error formatting intel cycle report: {e}"

    # ── 4d. Night Watch Council Cycle report ─────────────────────
    if council_report:
        try:
            cc_lines: list[str] = []
            if council_report.get("error"):
                cc_lines.append(f"Council cycle error: {council_report['error']}")
            else:
                cc_lines.append(f"Councils run: {council_report.get('councils_run', 0)}/4")
                for domain in ("memory", "intel", "portfolio", "journal"):
                    synthesis = council_report.get(f"{domain}_council")
                    if synthesis:
                        # Truncate each council output for the analyst prompt
                        cc_lines.append(f"\n--- {domain.upper()} COUNCIL ---")
                        cc_lines.append(synthesis[:500])
                cc_lines.append(
                    f"\nCouncil cycle cost: ${council_report.get('total_cost_usd', 0):.4f}"
                )
                cc_lines.append(
                    f"Council cycle duration: {council_report.get('duration_seconds', 0):.1f}s"
                )
                errors = council_report.get("errors", [])
                if errors:
                    cc_lines.append(f"Errors ({len(errors)}): " + "; ".join(errors[:5]))
            collected["council_cycle"] = "\n".join(cc_lines)
        except Exception as e:
            collected["council_cycle"] = f"Error formatting council cycle report: {e}"

    # ── 5. Awarebot scan results ──────────────────────────────────
    try:
        aware_lines: list[str] = []
        intel_dir = scheduler.data_dir / "intelligence"
        if intel_dir.exists():
            signals_file = intel_dir / "signals.jsonl"
            if signals_file.exists():
                recent_signals = 0
                tier_counts: dict[str, int] = defaultdict(int)
                cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
                with open(signals_file, "r") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            sig = json.loads(line)
                            ts = sig.get("timestamp", "")
                            if ts >= cutoff:
                                recent_signals += 1
                                tier = sig.get("tier", sig.get("importance_tier", "unknown"))
                                tier_counts[str(tier)] += 1
                        except json.JSONDecodeError:
                            continue
                aware_lines.append(f"Signals (last 24h): {recent_signals}")
                if tier_counts:
                    aware_lines.append(
                        "By tier: "
                        + ", ".join(f"{t}={c}" for t, c in sorted(tier_counts.items()))
                    )

            briefs_file = intel_dir / "briefs.jsonl"
            if briefs_file.exists():
                brief_count = 0
                with open(briefs_file, "r") as f:
                    for line in f:
                        if line.strip():
                            brief_count += 1
                aware_lines.append(f"Total intel briefs on record: {brief_count}")

        if scheduler.awarebot:
            ab_stats = scheduler.awarebot.get_stats()
            if isinstance(ab_stats, dict):
                aware_lines.append(
                    f"Awarebot scans completed: {ab_stats.get('scans_completed', '?')}"
                )
                aware_lines.append(
                    f"Awarebot predictions run: {ab_stats.get('predictions_run', '?')}"
                )

        if not aware_lines:
            aware_lines.append("No intelligence data found.")

        collected["intelligence"] = "\n".join(aware_lines)
    except Exception as e:
        collected["intelligence"] = f"Error reading intelligence data: {e}"

    # ── 6. Log analysis ───────────────────────────────────────────
    try:
        log_lines: list[str] = []
        log_candidates = [
            Path.home() / "NCL" / "logs" / "brain-stderr.log",
            Path.home() / "dev" / "NCL" / "logs" / "brain-stderr.log",
            scheduler.data_dir.parent / "logs" / "brain-stderr.log",
            scheduler.data_dir.parent / "logs" / "ncl-brain-stderr.log",
        ]
        log_file = None
        for lf in log_candidates:
            if lf.exists():
                log_file = lf
                break

        if log_file:
            # Read last 200 lines
            all_lines_raw = log_file.read_text(errors="replace").splitlines()
            tail = all_lines_raw[-200:]
            error_count = 0
            warning_count = 0
            unique_errors: set[str] = set()
            for ll in tail:
                if "ERROR" in ll:
                    error_count += 1
                    # Extract error message (after last colon or ERROR marker)
                    parts = ll.split("ERROR", 1)
                    err_msg = parts[1].strip()[:120] if len(parts) > 1 else ll[:120]
                    unique_errors.add(err_msg)
                elif "WARNING" in ll:
                    warning_count += 1

            log_lines.append(f"Log file: {log_file.name}")
            log_lines.append(f"Last 200 lines: {error_count} ERRORs, {warning_count} WARNINGs")
            if unique_errors:
                log_lines.append(f"Unique error patterns ({len(unique_errors)}):")
                for ue in list(unique_errors)[:10]:
                    log_lines.append(f"  {ue[:120]}")
        else:
            log_lines.append("No brain log file found.")

        collected["logs"] = "\n".join(log_lines)
    except Exception as e:
        collected["logs"] = f"Error reading logs: {e}"

    # ══════════════════════════════════════════════════════════════
    # LLM ANALYSIS PHASE
    # ══════════════════════════════════════════════════════════════

    api_headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    sonnet_model = "claude-sonnet-4"
    opus_model = "claude-opus-4-6"

    # Sonnet cost rates: $3.00/1M input, $15.00/1M output
    # Opus cost rates: $15.00/1M input, $75.00/1M output

    triage_outputs: dict[str, str] = {}
    total_llm_cost = 0.0

    async def _call_anthropic(
        model: str, prompt: str, max_tokens: int, label: str
    ) -> tuple[str, float]:
        """Make a single Anthropic API call, return (text, cost_usd)."""
        timeout = 120.0 if model == opus_model else 60.0
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers=api_headers,
                json={
                    "model": model,
                    "max_tokens": max_tokens,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            resp.raise_for_status()
            data = resp.json()
            text = data["content"][0]["text"]
            usage = data.get("usage", {})
            input_tokens = usage.get("input_tokens", 0)
            output_tokens = usage.get("output_tokens", 0)

            # Compute cost per model
            if model == opus_model:
                cost = (input_tokens * 15.00 + output_tokens * 75.00) / 1_000_000
            else:
                # Sonnet-class rates (default)
                cost = (input_tokens * 3.00 + output_tokens * 15.00) / 1_000_000

            log.info(
                "[NIGHT-WATCH] LLM call '%s': %d in / %d out tokens, $%.4f",
                label,
                input_tokens,
                output_tokens,
                cost,
            )
            return text, cost

    # ── Sonnet triage calls ───────────────────────────────────────

    triage_prompts = {
        "cost_analysis": (
            "You are an operations analyst for an autonomous AI brain system. "
            "Analyze this cost data from today. Flag anomalies, unusual spending "
            "patterns, projected budget issues, and sources burning money fastest. "
            "Be concise — 3-5 bullet points max.\n\n"
            f"COST DATA:\n{collected.get('costs', 'No data')}\n\n"
            f"DETERMINISTIC ISSUES FOUND:\n" + "\n".join(deterministic_issues[:10])
            if deterministic_issues
            else "None"
        ),
        "prediction_review": (
            "You are a prediction system analyst. Review this prediction data "
            "for an AI forecasting system. Note any accuracy drift, coverage gaps, "
            "or model performance issues. 3-5 bullet points.\n\n"
            f"PREDICTION DATA:\n{collected.get('predictions', 'No data')}\n\n"
            f"COUNCIL DATA:\n{collected.get('councils', 'No data')}"
        ),
        "log_analysis": (
            "You are a systems reliability engineer. Analyze these log extracts "
            "from an AI brain service. Categorize errors by severity, identify "
            "root causes, flag any patterns that suggest impending failures. "
            "3-5 bullet points.\n\n"
            f"LOG DATA:\n{collected.get('logs', 'No data')}"
        ),
        "system_health": (
            "You are an infrastructure analyst. Review this operational data for "
            "an autonomous AI system. Assess memory health, intelligence pipeline "
            "throughput, and scanner performance. Note any degradation or anomalies. "
            "3-5 bullet points.\n\n"
            f"MEMORY:\n{collected.get('memory', 'No data')}\n\n"
            f"INTELLIGENCE:\n{collected.get('intelligence', 'No data')}"
        ),
    }

    for label, prompt in triage_prompts.items():
        try:
            # Budget check before each call
            if not await tracker.can_spend("anthropic", 0.03):
                log.warning("[NIGHT-WATCH] Budget hit mid-analysis -- stopping Sonnet triage")
                break

            text, cost = await _call_anthropic(sonnet_model, prompt, 1024, label)
            triage_outputs[label] = text
            total_llm_cost += cost

            await tracker.record(
                "anthropic",
                cost,
                "night_watch",
                f"Night Watch Sonnet triage: {label}",
                {"model": sonnet_model, "phase": "triage", "label": label},
            )
        except Exception as e:
            log.error("[NIGHT-WATCH] Sonnet triage '%s' failed: %s", label, e)
            triage_outputs[label] = f"[Analysis failed: {type(e).__name__}: {e}]"

    # ── Opus synthesis call ───────────────────────────────────────
    synthesis_text = ""
    if triage_outputs:
        try:
            if not await tracker.can_spend("anthropic", 0.10):
                log.warning("[NIGHT-WATCH] Budget hit -- skipping Opus synthesis")
            else:
                subsystem_reports = "\n\n".join(
                    f"=== {label.upper()} ===\n{text}" for label, text in triage_outputs.items()
                )

                deterministic_summary = (
                    "\n".join(f"  - {i}" for i in deterministic_issues[:15])
                    if deterministic_issues
                    else "None — all deterministic checks passed."
                )

                synthesis_prompt = (
                    "You are the Night Watch analyst for NCL Brain, an autonomous AI "
                    "second brain system. Synthesize these subsystem triage reports into "
                    "a daily briefing for NATRIX (the human operator).\n\n"
                    "FORMAT YOUR RESPONSE EXACTLY AS:\n"
                    "STATUS: [GREEN/YELLOW/RED]\n\n"
                    "KEY FINDINGS:\n- [3-5 concise bullets about what matters most]\n\n"
                    "COST REPORT:\n- Today's spend, budget utilization, anomalies\n\n"
                    "SYSTEM HEALTH:\n- Component status, degraded services, pipeline throughput\n\n"  # noqa: E501
                    "RECOMMENDATIONS:\n- [2-3 actionable items for tomorrow]\n\n"
                    "Be concise and actionable. Focus on PATTERNS and CORRELATIONS "
                    "across subsystems, not just restating individual findings. "
                    "Highlight anything that could become a problem if ignored.\n\n"
                    f"DETERMINISTIC HEALTH CHECK ISSUES:\n{deterministic_summary}\n\n"
                    f"SUBSYSTEM TRIAGE REPORTS:\n{subsystem_reports}"
                )

                synthesis_text, cost = await _call_anthropic(
                    opus_model, synthesis_prompt, 2048, "synthesis"
                )
                total_llm_cost += cost

                await tracker.record(
                    "anthropic",
                    cost,
                    "night_watch",
                    "Night Watch Opus synthesis",
                    {"model": opus_model, "phase": "synthesis"},
                )
        except Exception as e:
            log.error("[NIGHT-WATCH] Opus synthesis failed: %s", e)
            synthesis_text = ""

    # ── Fallback: if no synthesis, use deterministic results ──────
    if not synthesis_text:
        synthesis_text = (
            "STATUS: UNKNOWN\n\n"
            "LLM analysis was unavailable. Deterministic check results:\n"
            + (
                "\n".join(f"  - {i}" for i in deterministic_issues)
                if deterministic_issues
                else "All deterministic checks passed."
            )
            + "\n\nSonnet triage outputs:\n"
            + "\n".join(f"  [{k}]: {v[:200]}" for k, v in triage_outputs.items())
        )

    # ══════════════════════════════════════════════════════════════
    # OUTPUT PHASE
    # ══════════════════════════════════════════════════════════════

    # ── 1. Save to disk ───────────────────────────────────────────
    try:
        nw_dir = scheduler.data_dir / "night-watch"
        nw_dir.mkdir(parents=True, exist_ok=True)
        brief_file = nw_dir / f"daily-{today_str}.md"

        brief_content = (
            f"# NCL Night Watch Daily Brief — {today_str}\n\n"
            f"Generated: {datetime.now(timezone.utc).isoformat()}\n"
            f"LLM cost: ${total_llm_cost:.4f}\n\n"
            f"---\n\n"
            f"{synthesis_text}\n\n"
            f"---\n\n"
            f"## Raw Data Collected\n\n"
        )
        for section, data in collected.items():
            brief_content += f"### {section.title()}\n```\n{data}\n```\n\n"

        async with aiofiles.open(brief_file, "w") as f:
            await f.write(brief_content)

        log.info("[NIGHT-WATCH] Daily brief saved to %s", brief_file)
    except Exception as e:
        log.error("[NIGHT-WATCH] Failed to save daily brief: %s", e)

    # ── 2. Determine status for push notification ─────────────────
    status_line = ""
    for line in synthesis_text.split("\n"):
        if line.strip().startswith("STATUS:"):
            status_line = line.strip().split(":", 1)[1].strip().upper()
            break

    if "RED" in status_line:
        nw_priority = "5"
        nw_tags = "brain,red_circle"
        nw_title = "NCL Night Watch Brief — RED"
    elif "YELLOW" in status_line:
        nw_priority = "4"
        nw_tags = "brain,yellow_circle"
        nw_title = "NCL Night Watch Brief — YELLOW"
    else:
        nw_priority = "3"
        nw_tags = "brain,green_circle"
        nw_title = "NCL Night Watch Daily Brief"

    # ── 3. Push via ntfy ──────────────────────────────────────────
    # Migrated 2026-05-21 to enqueue via central AlertDispatcher.
    try:
        push_body = synthesis_text
        if len(push_body) > 3800:
            push_body = push_body[:3800] + "\n\n... (truncated — full brief saved to disk)"
        push_body += f"\n\nLLM analysis cost: ${total_llm_cost:.4f}"

        try:
            enqueue_alert(
                title=nw_title,
                body=push_body,
                priority=nw_priority,
                tags=nw_tags,
                dedup_key=f"night-watch-analyst:{datetime.now(timezone.utc).date().isoformat()}",
                source="night_watch",
            )
            log.info("[NIGHT-WATCH] Analyst brief enqueued: %s", nw_title)
        except Exception as enq_err:
            log.warning(
                "[NIGHT-WATCH] dispatcher unavailable, direct POST fallback: %s", enq_err
            )
            async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
                resp = await client.post(
                    "https://ntfy.sh/ncl-natrix-intel-7x9k",
                    content=push_body.encode("utf-8"),
                    headers={
                        "Content-Type": "text/plain; charset=utf-8",
                        "Title": nw_title.encode("ascii", "replace").decode("ascii"),
                        "Priority": nw_priority,
                        "Tags": nw_tags,
                    },
                )
                resp.raise_for_status()
                log.info("[NIGHT-WATCH] Analyst brief pushed via ntfy (fallback): %s", nw_title)
    except Exception as e:
        log.error("[NIGHT-WATCH] Analyst ntfy push failed: %s", e)

    log.info(
        "[NIGHT-WATCH] Analyst phase complete — total LLM cost: $%.4f, "
        "triage calls: %d, synthesis: %s",
        total_llm_cost,
        len(triage_outputs),
        "yes" if "STATUS:" in synthesis_text else "fallback",
    )
