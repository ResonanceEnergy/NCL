"""System-tier endpoints (/system/*) extracted from routes.py.

Owns the FirstStrike Settings tab surface:
    GET  /system/costs                 — today's cost summary (legacy shape) [AUTH]
    GET  /system/costs/today           — detailed today breakdown            [AUTH]
    GET  /system/costs/history         — N-day historical summaries          [AUTH]
    GET  /system/costs/ledger          — raw ledger entries                  [AUTH]
    POST /system/costs/record          — record a cost entry                 [AUTH]
    POST /system/costs/reset           — reset in-memory totals              [AUTH]
    GET  /system/health/rollup         — single-call health snapshot         [AUTH]
    GET  /system/memory-profile        — gc + buffers + disk profile         [AUTH]

Note on auth: all endpoints in this module are gated by the strike token,
exposed via the ``verify_strike_token_dep`` DI factory in
:mod:`runtime.api.deps`.

W10B-3 (2026-05-24): Converted from the legacy ``from .. import routes as
_routes`` lazy-import pattern to FastAPI ``Depends()`` injection. Mirrors
the W8-A8 conversion of routers/feedback.py. Singletons (brain,
autonomous) now arrive via DI rather than module-attribute lookup.
"""

from __future__ import annotations  # noqa: I001

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, PlainTextResponse

from ..deps import get_autonomous, get_brain, verify_strike_token_dep

log = logging.getLogger(__name__)

router = APIRouter(tags=["system"])


# ── System Cost Tracker (FirstStrike Settings Tab) ────────────────────────
# Real, file-backed cost tracking with per-source daily budgets.
# Backed by runtime/cost_tracker.py — JSONL ledger + daily summaries.


@router.get("/system/costs")
async def system_costs(_: None = Depends(verify_strike_token_dep)):
    """Return today's cost summary by source with budget enforcement status.
    The iOS Settings > Costs tab reads from this endpoint.
    """
    from ...cost_tracker import get_tracker

    tracker = await get_tracker()
    summary = await tracker.get_daily_summary()

    # Also format for legacy iOS compatibility
    services = []
    for source, info in summary.get("sources", {}).items():
        if info["spent_usd"] > 0 or info["budget_usd"] > 0:
            services.append(
                {
                    "name": source,
                    "cost": info["spent_usd"],
                    "detail": f"Budget: ${info['budget_usd']:.2f}/day | {info['pct_used']:.0f}% used | {info['calls']} calls",  # noqa: E501
                    "budget": info["budget_usd"],
                    "calls": info["calls"],
                    "blocked": info["blocked"],
                }
            )

    return {
        "services": sorted(services, key=lambda s: s["cost"], reverse=True),
        "total_cost": summary["total_spent_usd"],
        "total_calls": summary["total_calls"],
        "date": summary["date"],
        "period": f"Today ({summary['date']})",
        "daily": [],  # Legacy field — use /system/costs/history for historical
    }


@router.get("/system/costs/today")
async def system_costs_today(_: None = Depends(verify_strike_token_dep)):
    """Detailed today's cost breakdown — per source, per category."""
    from ...cost_tracker import get_tracker

    tracker = await get_tracker()
    return await tracker.get_daily_summary()


@router.get("/system/costs/history")
async def system_costs_history(days: int = 30, _: None = Depends(verify_strike_token_dep)):
    """Historical daily cost summaries."""
    from ...cost_tracker import get_tracker

    tracker = await get_tracker()
    return await tracker.get_historical(days)


@router.get("/system/costs/ledger")
async def system_costs_ledger(days: int = 7, _: None = Depends(verify_strike_token_dep)):
    """Raw cost ledger entries for the last N days."""
    from ...cost_tracker import get_tracker

    tracker = await get_tracker()
    entries = await tracker.get_full_ledger(days)
    return {"entries": entries, "count": len(entries)}


def _compute_spend_dashboard_data(days: int = 14) -> dict:
    """Wave 14BE helper — pure compute, no auth, no DI. Both the JSON
    endpoint and the HTML endpoint call this."""
    import collections
    import json
    import os
    from datetime import datetime, timedelta, timezone
    from pathlib import Path

    ledger_path = Path(os.environ.get("NCL_BASE", str(Path.home() / "dev" / "NCL"))) / (
        "data/costs/cost_ledger.jsonl"
    )
    if not ledger_path.exists():
        return {
            "error": f"ledger missing at {ledger_path}",
            "days_window": days,
            "by_day": {},
            "by_source": {},
            "by_source_model": {},
            "top_ops": [],
            "totals": {"window": 0.0, "today": 0.0},
        }

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    today_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    by_day: dict[str, float] = collections.defaultdict(float)
    by_source: dict[str, float] = collections.defaultdict(float)
    by_source_model: dict[str, float] = collections.defaultdict(float)
    by_op: dict[str, float] = collections.defaultdict(float)
    op_calls: dict[str, int] = collections.defaultdict(int)
    rows_seen = 0
    rows_in_window = 0

    with ledger_path.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            rows_seen += 1
            ts = d.get("timestamp") or d.get("ts") or ""
            try:
                dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            except Exception:
                continue
            if dt < cutoff:
                continue
            rows_in_window += 1
            day = dt.strftime("%Y-%m-%d")
            src = str(d.get("source") or "?")
            model = str((d.get("metadata") or {}).get("model") or "?")
            amt = float(
                d.get("amount_usd") or d.get("amount") or d.get("cost") or 0
            )
            # Wave 14BO: ledger rows use "category" (set by record_cost),
            # not "operation"/"feature"/"call" — those defaults left every
            # row in the "?" op bucket. Fall through to the legacy keys so
            # we don't regress callers that DO write operation.
            op = str(
                d.get("category")
                or d.get("operation")
                or d.get("feature")
                or d.get("call")
                or "?"
            )
            by_day[day] += amt
            by_source[src] += amt
            by_source_model[f"{src}/{model}"] += amt
            by_op[f"{src}/{op}"] += amt
            op_calls[f"{src}/{op}"] += 1

    top_ops = sorted(
        [
            {
                "key": k,
                "spend_usd": round(v, 4),
                "calls": op_calls[k],
            }
            for k, v in by_op.items()
        ],
        key=lambda r: r["spend_usd"],
        reverse=True,
    )[:15]

    return {
        "days_window": days,
        "ledger_path": str(ledger_path),
        "rows_seen": rows_seen,
        "rows_in_window": rows_in_window,
        "by_day": {k: round(v, 4) for k, v in sorted(by_day.items())},
        "by_source": {k: round(v, 4) for k, v in sorted(
            by_source.items(), key=lambda x: -x[1]
        )},
        "by_source_model": {k: round(v, 4) for k, v in sorted(
            by_source_model.items(), key=lambda x: -x[1]
        )[:25]},
        "top_ops": top_ops,
        "totals": {
            "window": round(sum(by_day.values()), 4),
            "today": round(by_day.get(today_iso, 0.0), 4),
        },
    }


@router.get("/system/costs/dashboard.json")
async def system_costs_dashboard_json(
    days: int = 14,
    _: None = Depends(verify_strike_token_dep),
):
    """Wave 14BE: spend dashboard data as JSON."""
    return _compute_spend_dashboard_data(days=days)


@router.get("/system/costs/dashboard", response_class=HTMLResponse)
async def system_costs_dashboard_html(
    authorization: str = Header(default=""),
    days: int = 14,
):
    """Wave 14BE: HTML spend dashboard. NATRIX visits this in any browser
    to see the same data the cost-audit ran against, live.
    """
    from .. import routes as _routes
    _routes._verify_strike_token(authorization)
    safe_token = (
        authorization.removeprefix("Bearer ").strip() if authorization else ""
    )
    data = _compute_spend_dashboard_data(days=days)
    import html as _html
    import json as _json

    by_day = data.get("by_day", {})
    by_source = data.get("by_source", {})
    by_source_model = data.get("by_source_model", {})
    top_ops = data.get("top_ops", [])
    totals = data.get("totals", {})

    def _bar_row(label: str, amount: float, max_amount: float, color: str) -> str:
        pct = (amount / max_amount * 100.0) if max_amount > 0 else 0.0
        return (
            f'<div class="bar-row">'
            f'<span class="bar-label">{_html.escape(label)}</span>'
            f'<div class="bar-track"><div class="bar-fill" style="width:{pct:.1f}%;background:{color}"></div></div>'
            f'<span class="bar-value">${amount:.4f}</span>'
            f'</div>'
        )

    max_day = max(by_day.values()) if by_day else 0.0
    day_bars = "\n".join(
        _bar_row(k, v, max_day, "#4ecdc4") for k, v in sorted(by_day.items())
    ) or '<p style="color:#888">No spend in window.</p>'

    max_src = max(by_source.values()) if by_source else 0.0
    source_bars = "\n".join(
        _bar_row(k, v, max_src, "#ff6b6b") for k, v in by_source.items()
    ) or '<p style="color:#888">No source data.</p>'

    max_sm = max(by_source_model.values()) if by_source_model else 0.0
    model_bars = "\n".join(
        _bar_row(k, v, max_sm, "#ffd700") for k, v in by_source_model.items()
    ) or '<p style="color:#888">No model attribution.</p>'

    op_rows = "\n".join(
        f'<tr><td>{_html.escape(o["key"])}</td>'
        f'<td style="text-align:right">${o["spend_usd"]:.4f}</td>'
        f'<td style="text-align:right">{o["calls"]:,}</td></tr>'
        for o in top_ops
    ) or '<tr><td colspan="3">no rows</td></tr>'

    html_doc = f"""<!DOCTYPE html><html><head><meta charset="utf-8"/>
<title>NCL Spend Dashboard</title>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<style>
  body {{ font-family: -apple-system, system-ui, sans-serif; background: #0a0e1a;
          color: #e8e8e8; margin: 0; padding: 16px; }}
  h1 {{ font-weight: 900; letter-spacing: 0.04em; }}
  h2 {{ font-size: 13px; letter-spacing: 0.18em; color: #888; margin-top: 28px; }}
  .totals {{ display: flex; gap: 12px; flex-wrap: wrap; }}
  .totals .tile {{ background: #16213e; padding: 14px 18px; border-radius: 10px;
                    border: 1px solid #1f2a4a; min-width: 130px; }}
  .totals .label {{ font-size: 10px; letter-spacing: 0.18em; color: #888; }}
  .totals .value {{ font-size: 22px; font-weight: 900; color: #4ecdc4; }}
  .bar-row {{ display: grid; grid-template-columns: 200px 1fr 100px; align-items: center;
              gap: 10px; padding: 4px 0; font-size: 12px; }}
  .bar-label {{ font-family: monospace; color: #ccc; overflow: hidden;
                text-overflow: ellipsis; white-space: nowrap; }}
  .bar-track {{ background: #1a1f3a; height: 14px; border-radius: 7px; overflow: hidden; }}
  .bar-fill {{ height: 100%; transition: width 0.4s; }}
  .bar-value {{ text-align: right; font-family: monospace; color: #4ecdc4; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
  th, td {{ padding: 6px 10px; border-bottom: 1px solid #1f2a4a; }}
  th {{ text-align: left; color: #888; font-weight: 600; letter-spacing: 0.1em;
        font-size: 10px; }}
  td {{ font-family: monospace; color: #ccc; }}
  .footer {{ margin-top: 36px; color: #555; font-size: 11px; }}
</style></head><body>
<h1>NCL Spend Dashboard</h1>
<p style="color:#888">Window: last {data.get('days_window', 14)} days · {data.get('rows_in_window', 0):,} ledger rows</p>
<div class="totals">
  <div class="tile"><div class="label">TODAY</div><div class="value">${totals.get('today', 0):.2f}</div></div>
  <div class="tile"><div class="label">WINDOW</div><div class="value">${totals.get('window', 0):.2f}</div></div>
  <div class="tile"><div class="label">DAILY AVG</div>
    <div class="value">${(totals.get('window', 0) / max(data.get('days_window', 14), 1)):.2f}</div>
  </div>
</div>
<h2>BY DAY</h2>{day_bars}
<h2>BY SOURCE</h2>{source_bars}
<h2>BY (SOURCE / MODEL)</h2>{model_bars}
<h2>TOP 15 (SOURCE / OPERATION)</h2>
<table>
  <thead><tr><th>KEY</th><th style="text-align:right">SPEND</th><th style="text-align:right">CALLS</th></tr></thead>
  <tbody>{op_rows}</tbody>
</table>
<p class="footer">NCL Cost Audit · live ledger at {_html.escape(str(data.get('ledger_path', '')))}</p>
</body></html>"""
    return HTMLResponse(content=html_doc.replace("__AUTH_TOKEN__", safe_token))


@router.post("/system/costs/record")
async def system_costs_record(
    service: str = Body(...),
    cost: float = Body(...),
    category: str = Body("api_calls"),
    detail: str = Body(""),
    _: None = Depends(verify_strike_token_dep),
):
    """Record a cost entry. Called by NCL services after API calls."""
    from ...cost_tracker import record_cost

    await record_cost(service, cost, category, detail)
    return {"status": "recorded"}


# Wave 14BF (2026-05-30) — Operator-toggleable env flags.
_MANAGED_FLAGS = (
    "NCL_FUSION_BGE_RERANK_ENABLED",
    "NCL_MINHASH_DEDUP_ENABLED",
    "NCL_CROSS_REF_BERTOPIC_ENABLED",
    "NCL_MEMORY_EMBED_MODEL",
    # Wave 14BM — local Ollama A/B for Brief Pro council members.
    "NCL_BRIEF_COUNCIL_LOCAL_AB",
)


@router.get("/system/env")
async def system_env_flags(_: None = Depends(verify_strike_token_dep)) -> dict:
    """Return current values of operator-toggleable env flags."""
    import os as _os

    return {
        "flags": {name: _os.environ.get(name, "") for name in _MANAGED_FLAGS},
        "managed": list(_MANAGED_FLAGS),
        "note": (
            "POST /system/env writes the .env.flags file (sourced by "
            "scripts/launch-brain.sh on next bounce). In-process os.environ "
            "is also updated so API-layer endpoints see the new values."
        ),
    }


@router.post("/system/env")
async def system_env_flags_set(
    request: Request,
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Update one or more managed env flags."""
    import os as _os
    from pathlib import Path as _Path

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON body")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="body must be a flag dict")

    rejected: list[str] = []
    accepted: dict[str, str] = {}
    for k, v in body.items():
        if k not in _MANAGED_FLAGS:
            rejected.append(k)
            continue
        accepted[k] = "" if v is None else str(v)

    flags_path = _Path(
        _os.environ.get("NCL_BASE", str(_Path.home() / "dev" / "NCL"))
    ) / ".env.flags"
    existing: dict[str, str] = {}
    if flags_path.exists():
        for line in flags_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            existing[key.strip()] = val.strip()
    for k, v in accepted.items():
        if v == "":
            existing.pop(k, None)
        else:
            existing[k] = v
    new_text = "# NCL managed env flags — written by /system/env (Wave 14BF)\n"
    for k in sorted(existing):
        new_text += f"{k}={existing[k]}\n"
    tmp = flags_path.with_suffix(".tmp")
    tmp.write_text(new_text)
    tmp.replace(flags_path)
    for k, v in accepted.items():
        if v == "":
            _os.environ.pop(k, None)
        else:
            _os.environ[k] = v
    return {
        "saved": accepted,
        "rejected": rejected,
        "flags_file": str(flags_path),
        "note": "Brain bounce required for autonomous loops to pick up new values.",
    }


# Wave 14BK (2026-05-30) — Manual BERTopic per-source retrain.
@router.post("/system/bertopic/retrain")
async def system_bertopic_retrain(
    days: int = Body(default=14, embed=True),
    min_docs_per_source: int = Body(default=30, embed=True),
    min_topic_size: int = Body(default=5, embed=True),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Fire one BERTopic per-source retrain cycle on demand.

    Returns the full result envelope from `retrain_once` —
    {status, n_signals, per_source_counts, trained, skipped,
    elapsed_s, saved_to}. Empty/invalid env flag NCL_CROSS_REF_BERTOPIC_ENABLED
    does NOT block retraining; the flag only gates whether the engine
    USES the per-source models. Retrained models are picked up on the
    next signal without a brain bounce (in-process cache invalidates).
    """
    from ...cross_reference.retrain_loop import retrain_once

    return await retrain_once(
        days=days,
        min_docs_per_source=min_docs_per_source,
        min_topic_size=min_topic_size,
    )


@router.get("/system/bertopic/status")
async def system_bertopic_status(_: None = Depends(verify_strike_token_dep)) -> dict:
    """Return current per-source BERTopic state — what's loaded, how
    many topics each model has, when each was trained.
    """
    import json
    from pathlib import Path

    base = Path(os.environ.get("NCL_BASE", str(Path.home() / "dev" / "NCL")))
    root = base / "data" / "cross_reference" / "bertopic_model"
    out: dict = {"root": str(root), "exists": root.exists(), "sources": {}}
    if not root.exists():
        return out
    for sub in sorted(root.iterdir()):
        if sub.is_dir() and not sub.name.startswith("_"):
            meta = sub / "meta.json"
            if meta.exists():
                try:
                    out["sources"][sub.name] = json.loads(meta.read_text())
                except Exception as e:
                    out["sources"][sub.name] = {"error": str(e)}
    # Also include the legacy global model if present
    global_meta = root / "meta.json"
    if global_meta.exists():
        try:
            out["_global"] = json.loads(global_meta.read_text())
        except Exception as e:
            out["_global"] = {"error": str(e)}
    return out


@router.post("/system/costs/reset")
async def system_costs_reset(_: None = Depends(verify_strike_token_dep)):
    """Reset today's cost tracking. Use at start of new billing period."""
    # The JSONL ledger is append-only — reset just clears in-memory totals
    from ...cost_tracker import get_tracker

    tracker = await get_tracker()
    async with tracker._lock:
        tracker._daily_totals.clear()
        tracker._daily_counts.clear()
        tracker._warned_sources.clear()
    return {"status": "reset", "date": datetime.now(timezone.utc).strftime("%Y-%m-%d")}


@router.get("/system/health/rollup")
async def system_health_rollup(
    brain=Depends(get_brain),
    autonomous=Depends(get_autonomous),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Return the latest rolled-up component health snapshot.

    Written every 60s by the ``ncl-health-rollup`` scheduler loop.
    Returns the in-memory copy (O(1)) if available; otherwise re-reads
    the JSON file on disk; otherwise builds a fresh rollup synchronously.
    Useful as a single-call status check for the iOS Dashboard.
    """
    # 1) In-memory (set by the loop after each successful tick)
    if autonomous is not None:
        cached = getattr(autonomous, "_latest_health_rollup", None)
        if cached:
            return cached

    # 2) Disk fallback
    try:
        from pathlib import Path as _P  # noqa: N814

        if autonomous is not None:
            data_dir = autonomous.data_dir
        else:
            data_dir = _P.home() / "dev" / "NCL" / "data"
        rollup_file = data_dir / "health" / "current.json"
        if rollup_file.exists():
            return json.loads(rollup_file.read_text())
    except Exception:
        pass

    # 3) Synchronous build fallback
    try:
        from ...health.rollup import build_health_rollup

        return await build_health_rollup(autonomous, brain)
    except Exception as e:
        return {
            "overall": "yellow",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "components": {},
            "warnings": [f"rollup unavailable: {e}"],
            "errors": [],
        }


@router.get("/system/memory-profile")
async def system_memory_profile(
    top_n: int = Query(default=20, ge=1, le=200),
    brain=Depends(get_brain),
    autonomous=Depends(get_autonomous),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Top-N Python object types by count, plus key in-process buffer sizes.

    Cheap profiler intended to track down the slow OOM that's been driving
    macOS jetsam to SIGKILL the Brain (4,982 restarts in 5 days at audit).
    Uses ``gc.get_objects()`` + Counter — no objgraph dependency required.

    Tail rates of interest:
    - ``chromadb_disk_mb``      — embedding store size on disk
    - ``contradicts_index_mb``  — unbounded JSONL (known unbounded growth)
    - ``working_context_count`` — capped at 50 by store.py, here for sanity
    - ``signal_buffer_24h``     — capped via maxlen by Awarebot agent
    - ``council_sessions_count``— capped by _COUNCIL_SESSIONS_MAX
    """
    import gc
    from collections import Counter

    rss_mb = None
    vms_mb = None
    try:
        import resource as _r

        # ru_maxrss is in bytes on macOS, kilobytes on Linux. We're on macOS.
        rss_mb = round(_r.getrusage(_r.RUSAGE_SELF).ru_maxrss / (1024 * 1024), 1)
    except Exception:
        pass

    # Type histogram (top N)
    types = Counter()
    objs = gc.get_objects()
    for o in objs:
        types[type(o).__name__] += 1
    top_types = [{"type": t, "count": c} for t, c in types.most_common(top_n)]
    total_objects = len(objs)
    del objs  # release ref so the counter result isn't padded

    # In-process buffer sizes
    buffers: dict = {}
    if brain is not None:
        try:
            buffers["council_sessions_count"] = len(brain.council_sessions)
        except Exception:
            pass
        try:
            ms = brain.memory_store
            ms_stats = await ms.get_stats()
            buffers["memory_units"] = ms_stats.get("total_units")
            buffers["memory_by_tier"] = ms_stats.get("by_tier", {})
        except Exception as e:
            buffers["memory_units_error"] = str(e)
        try:
            wc = getattr(brain, "working_context", None)
            if wc is not None:
                items = getattr(wc, "items", None) or {}
                buffers["working_context_count"] = len(items)
        except Exception:
            pass
        try:
            buffers["pending_dispatches"] = len(brain._pending_dispatches)
        except Exception:
            pass

    if autonomous is not None:
        try:
            ab = getattr(autonomous, "awarebot", None)
            if ab is not None:
                buffers["signal_buffer_24h"] = len(ab._context_24h)
                buffers["signal_buffer_7d"] = len(ab._context_7d)
        except Exception:
            pass

    # On-disk sizes for known unbounded growth
    disk: dict = {}
    try:
        base = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
        for label, rel in [
            ("chromadb_disk_mb", "data/memory/chromadb"),
            ("contradicts_index_mb", "data/memory/contradicts_index.jsonl"),
            ("kg_dir_mb", "data/memory/knowledge_graph"),
            ("bm25_dir_mb", "data/memory/bm25"),
            ("brain_stderr_mb", "logs/ncl-brain-stderr.log"),
        ]:
            p = base / rel
            if p.is_file():
                disk[label] = round(p.stat().st_size / (1024 * 1024), 1)
            elif p.is_dir():
                total = 0
                for f in p.rglob("*"):
                    if f.is_file():
                        try:
                            total += f.stat().st_size
                        except OSError:
                            pass
                disk[label] = round(total / (1024 * 1024), 1)
    except Exception as e:
        disk["error"] = str(e)

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "rss_mb": rss_mb,
        "vms_mb": vms_mb,
        "total_objects": total_objects,
        "top_types": top_types,
        "buffers": buffers,
        "disk": disk,
        "recommendation": (
            "If RSS > 3GB consistently: add SoftResourceLimits ResidentSetSize=4294967296 "
            "to the brain plist and restart. If contradicts_index_mb > 50MB: it's "
            "unbounded — see runtime/memory/conflict_resolver.py append path."
        ),
    }


# TODO: W4-13's new /system endpoints should join this router after their PR lands.
# Expected additions:
#   GET /system/persistence/status
#   GET /system/cold-start-ready
# They will land in routes.py first; the next consolidation wave moves them here.


# ── /metrics — Prometheus exposition (UNAUTH, localhost-only) ──────────────
# W8-A12 (2026-05-24): hand-formatted Prometheus text — prometheus_client is
# not on the host. Bound to 127.0.0.1 by an explicit request.client.host check
# so node_exporter / local Prometheus can scrape it without the strike token,
# but external callers get a 404 (no information leak about the existence of
# the surface). Brain LaunchAgent binds uvicorn to 0.0.0.0:8800, so the IP
# check is the only thing keeping non-localhost scrapers out.


def _esc(label_value: str) -> str:
    """Escape a Prometheus label value per the exposition format spec."""
    return label_value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _fmt_metric(name: str, value, *, labels: dict | None = None) -> str:
    """Format a single sample line. Coerces None/non-numeric to no-op."""
    if value is None:
        return ""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return ""
    if labels:
        label_str = ",".join(f'{k}="{_esc(str(v2))}"' for k, v2 in sorted(labels.items()))
        return f"{name}{{{label_str}}} {v}\n"
    return f"{name} {v}\n"


@router.get("/metrics", include_in_schema=False)
async def prometheus_metrics(
    request: Request,
    authorization: str = Header(default=""),
    brain=Depends(get_brain),
    autonomous=Depends(get_autonomous),
) -> PlainTextResponse:
    """
    Prometheus exposition endpoint. Strike-token authed.

    Auth model (revised 2026-05-24): the original W8-A12 design used a
    127.0.0.1-only client.host guard, which broke after W8-A1's Q1 change
    bound uvicorn to the Tailscale IP only (loopback is no longer a
    listening interface). Bearer token gating is the same pattern as every
    other authed endpoint — Prometheus scrape config sets `bearer_token`
    to the strike token.

    W10A-2 (2026-05-24): Accepts EITHER the master ``STRIKE_TOKEN`` OR a
    dedicated read-only ``STRIKE_METRICS_TOKEN`` so the Prometheus scraper
    no longer needs the master token. Prometheus scraper should use
    ``STRIKE_METRICS_TOKEN`` (read-only scope); master token continues to
    work for ops/debug.

    Sources:
      * Brain ``_started_at`` (uptime)
      * MemoryStore ``get_stats()`` + ``units.jsonl`` file size
      * CostTracker ``get_daily_summary()`` (per-source spend + budgets)
      * Scheduler tasks (active/dead counts)
      * AsyncMemoryWriter ``get_stats()`` (queue + DLQ depths)
      * Brain ``council_sessions`` dict (today's count)

    Each source is bounded by ``asyncio.wait_for(..., timeout=2.0)`` so
    a single laggy subsystem cannot make scrapes hang. Missing series is
    the right behaviour — Prometheus treats absent samples as gaps.

    Note: this endpoint cannot use ``Depends(verify_strike_token_dep)``
    because it accepts a second valid token (``STRIKE_METRICS_TOKEN``).
    The dual-token check is inline below — falls through to the master
    verifier on miss.
    """
    metrics_token = os.environ.get("STRIKE_METRICS_TOKEN", "").strip()
    auth_token = authorization.removeprefix("Bearer ").strip()
    if not auth_token:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    if auth_token == metrics_token and metrics_token:
        pass  # ok — read-only metrics scope
    else:
        # Fall back to master strike token — lazy-import the verifier so
        # we don't depend on routes.py at module load time.
        from .. import routes as _routes

        _routes._verify_strike_token(authorization)

    out: list[str] = []

    # ── ncl_brain_uptime_seconds ────────────────────────────────────────
    out.append("# HELP ncl_brain_uptime_seconds Seconds since the Brain process started.\n")
    out.append("# TYPE ncl_brain_uptime_seconds gauge\n")
    try:
        started_at = getattr(brain, "_started_at", None) if brain is not None else None
        if started_at is not None:
            uptime = (datetime.now(timezone.utc) - started_at).total_seconds()
            out.append(_fmt_metric("ncl_brain_uptime_seconds", uptime))
    except Exception:
        pass

    # ── ncl_memory_units_total / ncl_memory_units_bytes ──────────────────
    # Each metric source is bounded by a 2.0s timeout so a single laggy
    # subsystem (e.g. memory store contending on the read lock during a
    # consolidate burst) cannot make Prometheus scrapes hang. Missing series
    # is the right behaviour — Prometheus treats absent samples as gaps.
    out.append("# HELP ncl_memory_units_total Number of MemUnits in the MemoryStore.\n")
    out.append("# TYPE ncl_memory_units_total gauge\n")
    try:
        if brain is not None and brain.memory_store is not None:
            import asyncio as _asyncio

            ms_stats = await _asyncio.wait_for(brain.memory_store.get_stats(), timeout=2.0)
            total = ms_stats.get("total_units")
            out.append(_fmt_metric("ncl_memory_units_total", total))
    except Exception:
        pass

    out.append("# HELP ncl_memory_units_bytes On-disk size of data/memory/units.jsonl.\n")
    out.append("# TYPE ncl_memory_units_bytes gauge\n")
    try:
        base = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
        units_path = base / "data" / "memory" / "units.jsonl"
        if units_path.is_file():
            out.append(_fmt_metric("ncl_memory_units_bytes", units_path.stat().st_size))
    except Exception:
        pass

    # ── ncl_cost_today_usd{source="..."} ────────────────────────────────
    out.append("# HELP ncl_cost_today_usd Per-source USD spend so far today.\n")
    out.append("# TYPE ncl_cost_today_usd gauge\n")
    out.append("# HELP ncl_cost_budget_usd Per-source daily USD budget cap.\n")
    out.append("# TYPE ncl_cost_budget_usd gauge\n")
    out.append("# HELP ncl_cost_calls_today Per-source API call count so far today.\n")
    out.append("# TYPE ncl_cost_calls_today gauge\n")
    try:
        import asyncio as _asyncio  # noqa: I001
        from ...cost_tracker import get_tracker

        tracker = await _asyncio.wait_for(get_tracker(), timeout=2.0)
        summary = await _asyncio.wait_for(tracker.get_daily_summary(), timeout=2.0)
        for source, info in (summary.get("sources") or {}).items():
            out.append(
                _fmt_metric("ncl_cost_today_usd", info.get("spent_usd"), labels={"source": source})
            )  # noqa: E501
            out.append(
                _fmt_metric(
                    "ncl_cost_budget_usd", info.get("budget_usd"), labels={"source": source}
                )
            )  # noqa: E501
            out.append(
                _fmt_metric("ncl_cost_calls_today", info.get("calls"), labels={"source": source})
            )  # noqa: E501
    except Exception:
        pass

    # ── ncl_scheduler_active_tasks / ncl_scheduler_dead_tasks ───────────
    out.append("# HELP ncl_scheduler_active_tasks Number of scheduler tasks currently running.\n")
    out.append("# TYPE ncl_scheduler_active_tasks gauge\n")
    out.append(
        "# HELP ncl_scheduler_dead_tasks Number of scheduler tasks that have crashed and not yet been restarted.\n"  # noqa: E501
    )
    out.append("# TYPE ncl_scheduler_dead_tasks gauge\n")
    try:
        if autonomous is not None:
            active = [t for t in getattr(autonomous, "_tasks", []) if not t.done()]
            dead = [t for t in getattr(autonomous, "_tasks", []) if t.done()]
            out.append(_fmt_metric("ncl_scheduler_active_tasks", len(active)))
            out.append(_fmt_metric("ncl_scheduler_dead_tasks", len(dead)))
    except Exception:
        pass

    # ── ncl_async_writer_queue_depth / ncl_async_writer_dlq_depth ───────
    out.append(
        "# HELP ncl_async_writer_queue_depth Items currently queued in the async memory writer.\n"
    )  # noqa: E501
    out.append("# TYPE ncl_async_writer_queue_depth gauge\n")
    out.append(
        "# HELP ncl_async_writer_dlq_depth Items in the async memory writer dead-letter queue.\n"
    )  # noqa: E501
    out.append("# TYPE ncl_async_writer_dlq_depth gauge\n")
    out.append("# HELP ncl_async_writer_enqueued_total Total items enqueued since process start.\n")
    out.append("# TYPE ncl_async_writer_enqueued_total counter\n")
    out.append(
        "# HELP ncl_async_writer_drained_total Total items successfully drained since process start.\n"  # noqa: E501
    )
    out.append("# TYPE ncl_async_writer_drained_total counter\n")
    try:
        from ...memory.async_writer import get_async_writer

        aw_stats = get_async_writer().get_stats()
        out.append(_fmt_metric("ncl_async_writer_queue_depth", aw_stats.get("queue_size")))
        out.append(_fmt_metric("ncl_async_writer_dlq_depth", aw_stats.get("dlq_size")))
        out.append(_fmt_metric("ncl_async_writer_enqueued_total", aw_stats.get("enqueued_total")))
        out.append(_fmt_metric("ncl_async_writer_drained_total", aw_stats.get("drained_total")))
    except Exception:
        pass

    # ── ncl_council_sessions_today_total ────────────────────────────────
    out.append(
        "# HELP ncl_council_sessions_today_total Council sessions created so far today (UTC).\n"
    )  # noqa: E501
    out.append("# TYPE ncl_council_sessions_today_total counter\n")
    try:
        if brain is not None:
            today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            n = 0
            for sess in brain.council_sessions.values():
                created = getattr(sess, "created_at", None)
                if created is None:
                    continue
                created_str = created.isoformat() if hasattr(created, "isoformat") else str(created)
                if created_str.startswith(today_utc):
                    n += 1
            out.append(_fmt_metric("ncl_council_sessions_today_total", n))
    except Exception:
        pass

    return PlainTextResponse("".join(out), media_type="text/plain; version=0.0.4")
