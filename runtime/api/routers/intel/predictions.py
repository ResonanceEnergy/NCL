"""Predictions endpoints carved out of intel.py (W10B-9, 2026-05-24).

Owns the ``/prediction*`` and ``/predictions*`` URL surface that the
FirstStrike iOS Predictions tab + accuracy / convergence tooling
hits. Lifted verbatim from ``runtime/api/routers/intel.py`` lines
1945-2660 with no behaviour changes — endpoint paths, response
shapes, and side-effects (Beta-Bernoulli authority feedback, SQLite
mirror, memory-store enrichment, on-disk JSON writes) are byte-for-byte
identical.

Wave-9 audit (#7 + A9) flagged intel.py at 2,628 LOC + 33 broad
``except`` blocks. The predictions cluster is independent of
morning_brief / youtube / reddit / focus / X, so this is the natural
first split — see CLAUDE.md §"Strike Point pipeline" for the bigger
picture on incremental routes-module slimming.

The router is re-exported from ``runtime.api.routers.intel.__init__``
via ``router.include_router(predictions_router)`` so existing
``app.include_router(intel_router)`` calls in routes.py keep mounting
the full Intel + Predictions surface. ``OutcomeBody`` is also
re-exported from the package root because
``tests/test_outcome_endpoint_schema.py`` imports it from
``runtime.api.routers.intel`` directly.

W10C-6 (2026-05-24): Converted from the legacy ``from ... import routes
as _routes`` lazy-import pattern to FastAPI ``Depends()`` injection.
Mirrors the W10C-2 conversion of routers/memory.py. Singletons
(``NCLBrain``, ``AutonomousScheduler``) arrive via ``Depends()`` from
``runtime.api.deps``; only ``_check_rate_limit`` / ``broadcast_event``
/ ``config`` (no DI factories) still go through the late-bound
``_routes_module()`` shim.
"""

from __future__ import annotations  # noqa: I001

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ...deps import (
    get_autonomous,
    get_brain,
    verify_strike_token_dep,
)

log = logging.getLogger(__name__)

router = APIRouter(tags=["intel", "predictions"])


# ===========================================================================
# Predictions
# ===========================================================================

# ── Helper regexes / keyword sets ──────────────────────────────────────────

_CONSENSUS_PREFIX_RE = re.compile(r"^\s*\[Consensus:[^\]]*\]\s*", re.IGNORECASE)
_SINGLE_MODEL_PREFIX_RE = re.compile(r"^\s*\[Single-model\]\s*", re.IGNORECASE)
_CONSENSUS_TRAILER_RE = re.compile(
    r"\s*\[[^\]]+(?:concurs|disagrees|agrees)[^\]]*\]\s*", re.IGNORECASE
)  # noqa: E501
_CONVERGING_TRAILER_RE = re.compile(r"\s*\[Converging[^\]]*\]\s*", re.IGNORECASE)
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)

# Parse model names from "[Consensus: 3 models, lead=claude@72%]" + "[xxx concurs@N%]"
_CONSENSUS_LEAD_RE = re.compile(r"\[Consensus:\s*\d+\s*models?\s*,\s*lead=([\w\-]+)", re.IGNORECASE)
_CONSENSUS_MEMBER_RE = re.compile(r"\[([\w\-]+)\s+(?:concurs|disagrees|agrees)", re.IGNORECASE)
_SINGLE_MODEL_NAME_RE = re.compile(r"\[Single-model(?::\s*([\w\-]+))?\]", re.IGNORECASE)

# Direction classifier keyword sets (kept in sync with awarebot.agent)
_PRED_BULL_TERMS = frozenset(
    {
        "bullish",
        "rally",
        "surge",
        "uptrend",
        "gain",
        "rise",
        "rises",
        "rose",
        "increase",
        "increases",
        "increased",
        "upside",
        "higher",
        "outperform",
        "beat",
        "beating",
        "exceed",
        "moon",
        "breakout",
    }
)
_PRED_BEAR_TERMS = frozenset(
    {
        "bearish",
        "crash",
        "drop",
        "drops",
        "dropped",
        "fall",
        "falls",
        "fell",
        "decline",
        "declines",
        "declined",
        "downside",
        "lower",
        "underperform",
        "miss",
        "missed",
        "downturn",
        "pullback",
        "breakdown",
        "sell-off",
        "selloff",
    }
)


def _classify_prediction_direction(text: str) -> str:
    """bullish | bearish | neutral | mixed — keyword classifier."""
    if not text:
        return "neutral"
    words = re.findall(r"[a-zA-Z][a-zA-Z\-]+", text.lower())
    bull = sum(1 for w in words if w in _PRED_BULL_TERMS)
    bear = sum(1 for w in words if w in _PRED_BEAR_TERMS)
    if bull == 0 and bear == 0:
        return "neutral"
    if bull > 0 and bear > 0 and abs(bull - bear) <= 1:
        return "mixed"
    return "bullish" if bull > bear else "bearish"


def _extract_prediction_models(pred: dict) -> list[str]:
    """Return contributing model names. Prefers pre-stored `models`, falls
    back to scraping `[Consensus: ...]` prefix + `[xxx concurs@N%]` trailers."""
    stored = pred.get("models")
    if isinstance(stored, list) and stored:
        clean = [str(m).strip().lower() for m in stored if isinstance(m, str) and m]
        if clean:
            return clean

    consensus = pred.get("consensus") or ""
    if not isinstance(consensus, str):
        return []

    found: list[str] = []
    m = _CONSENSUS_LEAD_RE.search(consensus)
    if m:
        found.append(m.group(1).lower())
    found.extend(t.lower() for t in _CONSENSUS_MEMBER_RE.findall(consensus))
    sm = _SINGLE_MODEL_NAME_RE.search(consensus)
    if sm and sm.group(1):
        found.append(sm.group(1).lower())

    seen: set[str] = set()
    out: list[str] = []
    for name in found:
        if name not in seen:
            seen.add(name)
            out.append(name)
    return out


def _extract_prediction_description(pred: dict) -> str:
    """Pull a human-readable prediction sentence from a prediction record."""
    for k in ("description", "claim", "prediction_text", "prediction"):
        v = pred.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()

    consensus = pred.get("consensus") or ""
    if not isinstance(consensus, str):
        return ""
    text = consensus

    text = _CONSENSUS_PREFIX_RE.sub("", text)
    text = _SINGLE_MODEL_PREFIX_RE.sub("", text)
    text = _CONSENSUS_TRAILER_RE.sub("", text)
    text = _CONVERGING_TRAILER_RE.sub("", text)

    match = _JSON_FENCE_RE.search(text)
    if match:
        try:
            inner = json.loads(match.group(1))
            inner_pred = inner.get("prediction")
            if isinstance(inner_pred, str) and inner_pred.strip():
                return inner_pred.strip()
        except json.JSONDecodeError:
            pass
        text = text[: match.start()] + text[match.end() :]

    return text.strip()


@router.post("/prediction")
async def run_prediction(
    topic: str,
    brain=Depends(get_brain),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Run Future Predictor ensemble forecast."""
    if not brain:
        raise HTTPException(status_code=503, detail="Service not initialized")
    return await brain.run_prediction(topic)


@router.get("/predictions")
async def list_predictions(
    limit: int = Query(default=20, ge=1, le=100),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """List recent predictions — returns cached predictions from disk (fast).

    Each item is enriched with a `description` field containing the
    cleaned, human-readable prediction text (the `[Consensus: ...]`
    prefix and trailing meta tags are stripped, and if the inner JSON
    block has a `prediction` key, that sentence is surfaced).
    """
    predictions = []

    council_pred_dir = Path(os.getenv("NCL_DATA_DIR", "data")) / "predictions" / "council"
    if council_pred_dir.exists():
        files = sorted(council_pred_dir.glob("council-pred-*.json"), reverse=True)
        for f in files[:limit]:
            try:
                data = json.loads(f.read_text())
                if isinstance(data, list):
                    predictions.extend(data)
                elif isinstance(data, dict) and "predictions" in data:
                    predictions.extend(data["predictions"])
                elif isinstance(data, dict):
                    predictions.append(data)
            except Exception:
                pass

    pred_dir = Path(os.getenv("NCL_DATA_DIR", "data")) / "predictions"
    if pred_dir.exists():
        files = sorted(pred_dir.glob("pred-*.json"), reverse=True)
        for f in files[:limit]:
            try:
                data = json.loads(f.read_text())
                if isinstance(data, dict):
                    data["_type"] = "ensemble"
                    predictions.append(data)
            except Exception:
                pass

    predictions.sort(
        key=lambda p: p.get("timestamp", p.get("generated_at", "")),
        reverse=True,
    )

    sliced = predictions[:limit]

    for p in sliced:
        if not isinstance(p, dict):
            continue
        desc = _extract_prediction_description(p)
        if desc:
            p["description"] = desc

        if not p.get("models"):
            p["models"] = _extract_prediction_models(p)

        if not p.get("direction"):
            p["direction"] = _classify_prediction_direction(
                p.get("description") or p.get("consensus") or ""
            )

        if "linked_signals" not in p or not isinstance(p.get("linked_signals"), list):
            p["linked_signals"] = []

    return {
        "status": "ok",
        "predictions": sliced,
        "total": len(predictions),
        "_meta": {
            "filter_applied": {"limit": limit},
            "raw_count": len(predictions),
            "filtered_count": len(sliced),
            "dedup_count": 0,
        },
    }


@router.post("/predictions/council")
async def generate_council_predictions(
    brain=Depends(get_brain),
    autonomous=Depends(get_autonomous),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Generate council-based predictions — each of the 5 council members
    (Claude, Grok, Gemini, GPT, Perplexity) makes a 24hr prediction on a
    different hot topic. Claude (chair) assigns topics to ensure diversity.
    """
    if not brain:
        raise HTTPException(status_code=503, detail="Service not initialized")

    from ....ncl_brain.models import CouncilMember

    council_engine = brain.council_engine
    # ── Step 1: Get hottest signals from last 24h ──
    hot_signals = []
    if autonomous and autonomous.awarebot:
        ctx24 = list(autonomous.awarebot._context_24h)
        ctx24.sort(key=lambda s: getattr(s, "score", 0), reverse=True)
        for s in ctx24[:10]:
            hot_signals.append(
                {
                    "title": s.title or s.content[:80],
                    "content": (s.content or "")[:200],
                    "source": s.source or "",
                    "score": getattr(s, "score", 0),
                    "tags": list(s.tags) if s.tags else [],
                }
            )

    if not hot_signals:
        return {
            "status": "no_signals",
            "predictions": [],
            "reason": "No signals in the last 24h to base predictions on",
        }

    # ── Step 2: Chair (Claude) assigns unique topics ──
    signals_summary = "\n".join(
        f"{i+1}. [{s['source']}] {s['title']} (score: {s['score']:.0f})"
        for i, s in enumerate(hot_signals)
    )

    assignment_prompt = f"""You are the chair of a prediction council with 5 members: Claude, Grok, Gemini, GPT, and Perplexity.

Here are the top intelligence signals from the last 24 hours:

{signals_summary}

Your job: Assign each council member a DIFFERENT topic to make a 24-hour prediction about.
Rules:
- Each member gets exactly ONE unique topic
- Topics must be based on the signals above but should NOT overlap
- Pick the most actionable and interesting angles
- Include relevant signal numbers so members have context

Respond ONLY in this exact JSON format (no markdown, no explanation):
{{"assignments": [
  {{"member": "claude", "topic": "...", "signal_refs": [1,2]}},
  {{"member": "grok", "topic": "...", "signal_refs": [3]}},
  {{"member": "gemini", "topic": "...", "signal_refs": [4,5]}},
  {{"member": "gpt", "topic": "...", "signal_refs": [6]}},
  {{"member": "perplexity", "topic": "...", "signal_refs": [7,8]}}
]}}"""  # noqa: E501

    try:
        assignment_raw = await asyncio.wait_for(
            council_engine._get_member_response_safe(
                CouncilMember.CLAUDE, assignment_prompt, "prediction-chair"
            ),
            timeout=30.0,
        )
    except Exception as e:
        log.error(f"[predictions:council] Chair assignment failed: {e}")
        return {"status": "error", "predictions": [], "error": f"Chair assignment failed: {e}"}

    try:
        cleaned = assignment_raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()
        if cleaned.startswith("json"):
            cleaned = cleaned[4:].strip()
        assignments = json.loads(cleaned)
        if isinstance(assignments, dict) and "assignments" in assignments:
            assignments = assignments["assignments"]
    except (json.JSONDecodeError, KeyError) as e:
        log.error(
            f"[predictions:council] Failed to parse assignments: {e}\nRaw: {assignment_raw[:500]}"
        )  # noqa: E501
        return {
            "status": "error",
            "predictions": [],
            "error": "Chair failed to produce valid topic assignments",
        }

    # ── Step 3: Each member makes their prediction in parallel ──
    async def get_member_prediction(assignment: dict) -> dict:
        member_name = assignment.get("member", "unknown")
        topic = assignment.get("topic", "general")
        signal_refs = assignment.get("signal_refs", [])

        context_lines = []
        for ref in signal_refs:
            idx = ref - 1
            if 0 <= idx < len(hot_signals):
                s = hot_signals[idx]
                context_lines.append(f"- {s['title']}: {s['content']}")

        context = "\n".join(context_lines) if context_lines else "No specific signals provided"

        pred_prompt = f"""You are {member_name.upper()}, a member of an intelligence prediction council.

Your assigned topic for a 24-HOUR prediction: {topic}

Supporting intelligence signals:
{context}

Make a specific, actionable prediction about what will happen in the next 24 hours regarding this topic.
Be concrete — include specific outcomes, probability estimates, and what to watch for.

Respond in this JSON format (no markdown, no explanation):
{{"prediction": "Your specific 24hr prediction here",
  "confidence": 0.75,
  "direction": "bullish|bearish|neutral",
  "watch_for": "Key indicator to watch",
  "reasoning": "Brief reasoning"}}"""  # noqa: E501

        member_enum = {
            "claude": CouncilMember.CLAUDE,
            "grok": CouncilMember.GROK,
            "gemini": CouncilMember.GEMINI,
            "gpt": CouncilMember.GPT,
            "perplexity": CouncilMember.PERPLEXITY,
        }.get(member_name.lower())

        if not member_enum:
            return {"member": member_name, "topic": topic, "error": "Unknown member"}

        try:
            raw = await asyncio.wait_for(
                council_engine._get_member_response_safe(
                    member_enum, pred_prompt, f"prediction-{member_name}"
                ),
                timeout=30.0,
            )

            cleaned = raw.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
                if cleaned.endswith("```"):
                    cleaned = cleaned[:-3]
                cleaned = cleaned.strip()
            if cleaned.startswith("json"):
                cleaned = cleaned[4:].strip()

            try:
                parsed = json.loads(cleaned)
            except json.JSONDecodeError:
                parsed = {"prediction": cleaned[:500]}

            return {
                "member": member_name,
                "topic": topic,
                "title": topic,
                "content": parsed.get("prediction", raw[:500]),
                "confidence": parsed.get("confidence", 0.5),
                "direction": parsed.get("direction", "neutral"),
                "watch_for": parsed.get("watch_for", ""),
                "reasoning": parsed.get("reasoning", ""),
                "tags": [
                    t
                    for s in signal_refs
                    if 0 <= s - 1 < len(hot_signals)
                    for t in hot_signals[s - 1].get("tags", [])
                ],
                "signal_refs": signal_refs,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source": f"council:{member_name}",
                "council_member": member_name,
            }
        except Exception as e:
            log.warning(f"[predictions:council] {member_name} prediction failed: {e}")
            return {
                "member": member_name,
                "topic": topic,
                "title": topic,
                "content": f"Prediction unavailable: {e}",
                "confidence": 0.0,
                "direction": "neutral",
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source": f"council:{member_name}",
                "council_member": member_name,
            }

    tasks = [get_member_prediction(a) for a in assignments[:5]]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    predictions = []
    for r in results:
        if isinstance(r, Exception):
            log.warning(f"[predictions:council] Prediction task failed: {r}")
        elif isinstance(r, dict):
            predictions.append(r)

    # ── Step 4: Save to disk ──
    data_dir = Path(os.getenv("NCL_DATA_DIR", "data")) / "predictions" / "council"
    data_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    pred_file = data_dir / f"council-pred-{ts}.json"
    try:
        save_data = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "signal_count": len(hot_signals),
            "predictions": predictions,
        }
        pred_file.write_text(json.dumps(save_data, indent=2, default=str))
        log.info(f"[predictions:council] Saved {len(predictions)} predictions to {pred_file}")
    except Exception as e:
        log.warning(f"[predictions:council] Disk save failed: {e}")

    # ── SQLite mirror (W10A-14) ──────────────────────────────────────
    # Gated by NCL_PREDICTIONS_SQLITE (default OFF). Outside the JSON
    # write try/except so a SQLite outage can't break the on-disk
    # source of truth. mirror_prediction_to_sqlite() catches its own
    # exceptions and never raises. The council-pred file holds a list
    # of per-member predictions — mirror each one as its own row.
    try:
        from runtime.persistence.predictions_writer import (
            mirror_prediction_to_sqlite,
        )

        # Fallback id = file stem + member index, mirrors the migration
        # script's strategy when a row has no prediction_id of its own.
        for idx, pred in enumerate(predictions):
            await mirror_prediction_to_sqlite(pred, fallback_id=f"{pred_file.stem}-{idx}")
    except Exception as sql_err:
        log.warning(f"[predictions:council] SQLite mirror import failed: {sql_err}")

    # ── Step 5: Memory storage ──
    if autonomous and autonomous.awarebot and autonomous.awarebot.memory_store:  # noqa: E501
        for pred in predictions:
            try:
                await autonomous.awarebot.memory_store.create_unit(
                    content=(
                        f"[Council Prediction] {pred.get('member', 'unknown').upper()}: "
                        f"{pred.get('topic', 'N/A')} — {pred.get('content', '')[:200]}"
                    ),
                    source=f"council:prediction:{pred.get('member', 'unknown')}",
                    importance=min(100.0, (pred.get("confidence", 0.5) * 100)),
                    tags=["prediction", "council", pred.get("member", "unknown")],
                )
            except Exception:
                pass

    return {
        "status": "ok",
        "predictions": predictions,
        "total": len(predictions),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


# IMPORTANT: Fixed paths MUST come before the parameterized {prediction_id}
# route, otherwise FastAPI matches "accuracy" / "convergence" as a prediction_id.


class OutcomeBody(BaseModel):
    """Request body for prediction outcome submission.

    iOS sends ``{"outcome": "correct"|"incorrect"|"partial"}`` — this is the
    primary path (PredictionDetailView.swift:669). Legacy callers can still
    pass explicit ``correct`` / ``partial`` booleans, and the query-param
    fallback below remains supported for ad-hoc curl debugging.
    """

    outcome: Optional[str] = Field(default=None, description="'correct' | 'incorrect' | 'partial'")
    correct: Optional[bool] = Field(default=None, description="Explicit boolean (legacy)")
    partial: Optional[bool] = Field(default=None, description="Half-credit outcome (legacy)")


@router.post("/prediction/{prediction_id}/outcome")
async def record_prediction_outcome(
    prediction_id: str,
    body: Optional[OutcomeBody] = Body(default=None),
    correct: Optional[bool] = Query(
        default=None, description="Whether the prediction was correct (legacy query-param fallback)"
    ),  # noqa: E501
    partial: Optional[bool] = Query(
        default=None, description="Half-credit outcome (legacy query-param fallback)"
    ),  # noqa: E501
    brain=Depends(get_brain),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Record a prediction outcome (correct/incorrect) for accuracy tracking.

    Side effects (added 2026-05-22 EOD swarm — Outcome → Authority feedback):
    - Walks the prediction file for ``cited_sources_platform`` and
      ``cited_sources_full``.
    - For each platform source, applies ``±1`` update to the Awarebot
      Beta-Bernoulli ``AuthorityLearner`` posterior (previously inert).
    - For each full source string, applies the same update to the general
      ``SourceAuthorityLearner`` in ``runtime.feedback.source_authority_learner``.
    - Appends an audit row to ``data/feedback/authority_history.jsonl``.

    Wire schema (fixed Wave-8 2026-05-24 — was HTTP 422 against iOS body):
    - PRIMARY: JSON body ``{"outcome": "correct"|"incorrect"|"partial"}``.
    - LEGACY: query params ``?correct=true&partial=false`` still honored as
      a fallback (so existing curl / postman flows don't break).
    """
    if not brain:
        raise HTTPException(status_code=503, detail="Service not initialized")
    if not brain.predictor:
        raise HTTPException(status_code=503, detail="Predictor not initialized")

    # ── Resolve (correct, partial) from body OR query-params ──
    # Body wins when present; otherwise fall back to query params.
    if body is not None and body.outcome:
        oc = (body.outcome or "").strip().lower()
        if oc == "correct":
            correct, partial = True, False
        elif oc == "incorrect":
            correct, partial = False, False
        elif oc == "partial":
            correct, partial = True, True  # partial flag dominates downstream
        else:
            raise HTTPException(
                status_code=422,
                detail=f"outcome must be 'correct'|'incorrect'|'partial', got {body.outcome!r}",
            )
    else:
        # Body had explicit booleans, or fall through to query params.
        if body is not None:
            if body.correct is not None:
                correct = body.correct
            if body.partial is not None:
                partial = body.partial
        if correct is None:
            raise HTTPException(
                status_code=422,
                detail="Must supply either body.outcome, body.correct, or ?correct= query param",
            )
        if partial is None:
            partial = False

    # 1. Original behavior — predictor rolling accuracy.
    brain.predictor.record_outcome(prediction_id, correct)
    stats = brain.predictor.accuracy_stats()

    # 2. Locate prediction file → extract cited sources.
    cited_platforms: list[str] = []
    cited_full: list[str] = []
    pred_topic: str = ""
    try:
        pred_dir = Path(os.getenv("NCL_DATA_DIR", "data")) / "predictions"
        for pattern in ["pred-*.json", "council/council-pred-*.json"]:
            for f in sorted(pred_dir.glob(pattern), reverse=True)[:200]:
                try:
                    data = json.loads(f.read_text())
                except Exception:
                    continue
                preds = (
                    data
                    if isinstance(data, list)
                    else (
                        data.get("predictions")
                        if isinstance(data, dict) and "predictions" in data
                        else [data]  # noqa: E501
                    )
                )
                for pred in preds or []:
                    if pred.get("prediction_id") != prediction_id:
                        continue
                    cited_platforms = list(pred.get("cited_sources_platform") or [])
                    cited_full = list(pred.get("cited_sources_full") or [])
                    pred_topic = pred.get("topic") or ""
                    break
                if cited_platforms or cited_full:
                    break
            if cited_platforms or cited_full:
                break
    except Exception as lookup_err:
        log.warning("[OUTCOME] prediction-file lookup failed: %s", lookup_err)

    # 3. Update the Awarebot Beta-Bernoulli learner (per-platform).
    awarebot_updates: dict[str, dict] = {}
    try:
        awarebot = getattr(brain, "awarebot", None)
        learner = getattr(awarebot, "_authority_learner", None) if awarebot else None
        if learner is not None and cited_platforms:
            for plat in cited_platforms:
                if partial:
                    learner.record_outcome(plat, True, weight=0.5)
                else:
                    learner.record_outcome(plat, bool(correct), weight=1.0)
            stats_map = learner.get_all_stats() if hasattr(learner, "get_all_stats") else {}
            awarebot_updates = {p: stats_map.get(p, {}) for p in cited_platforms}
    except Exception as awl_err:
        log.warning("[OUTCOME] awarebot learner update failed: %s", awl_err)

    # 4. Update the general source-authority learner (per-full-source).
    general_updates: dict[str, dict] = {}
    try:
        from runtime.feedback.source_authority_learner import (
            record_prediction_outcome as _gen_record,
        )  # noqa: E501, I001

        outcome_label = "partial" if partial else ("correct" if correct else "wrong")
        general_updates = await _gen_record(
            prediction_id=prediction_id,
            outcome=outcome_label,
            cited_sources=cited_full,
        )
    except Exception as gen_err:
        log.warning("[OUTCOME] general learner update failed: %s", gen_err)

    # 5. Stamp the outcome onto the SQLite predictions row (W10A-14).
    #    Gated by NCL_PREDICTIONS_SQLITE; no-ops + never raises when OFF
    #    or when the row hasn't been mirrored yet. Uses the same label
    #    vocabulary as the general learner so SQL queries can join.
    try:
        from runtime.persistence.predictions_writer import (
            mirror_outcome_to_sqlite,
        )

        _outcome_label = "partial" if partial else ("correct" if correct else "wrong")
        await mirror_outcome_to_sqlite(prediction_id, _outcome_label)
    except Exception as sql_err:
        log.warning("[OUTCOME] SQLite outcome mirror failed: %s", sql_err)

    return {
        "status": "recorded",
        "prediction_id": prediction_id,
        "topic": pred_topic,
        "correct": correct,
        "partial": partial,
        "cited_sources_platform": cited_platforms,
        "cited_sources_full": cited_full,
        "awarebot_updates": awarebot_updates,
        "general_learner_updates": general_updates,
        **stats,
    }


@router.get("/prediction/accuracy")
async def prediction_accuracy(
    brain=Depends(get_brain),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Get prediction accuracy metrics from the FuturePredictor's rolling window."""
    if not brain:
        raise HTTPException(status_code=503, detail="Service not initialized")
    if not brain.predictor:
        return {"status": "unavailable", "reason": "Predictor not initialized"}
    stats = brain.predictor.accuracy_stats()
    stats["status"] = "ok"
    return stats


@router.get("/prediction/convergence")
async def prediction_convergence(
    topic: str = Query(default="", description="Optional topic filter"),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Convergence analysis — where multiple prediction models agree.

    READ-ONLY: Loads predictions from disk files (no side effects).
    """
    convergence_data = []

    pred_dir = Path(os.getenv("NCL_DATA_DIR", "data")) / "predictions"
    for pattern in ["pred-*.json", "council/council-pred-*.json"]:
        for f in sorted(pred_dir.glob(pattern), reverse=True)[:50]:
            try:
                data = json.loads(f.read_text())
                preds = []
                if isinstance(data, list):
                    preds = data
                elif isinstance(data, dict) and "predictions" in data:
                    preds = data["predictions"]
                elif isinstance(data, dict):
                    preds = [data]
                for pred in preds:
                    conv = pred.get("convergence_signals", pred.get("convergence", []))
                    if conv:
                        entry = {
                            "prediction_id": pred.get("prediction_id"),
                            "topic": pred.get("topic"),
                            "confidence": pred.get("confidence"),
                            "convergence_signals": conv,
                            "signal_count": pred.get("signal_count", 0),
                        }
                        if not topic or topic.lower() in (pred.get("topic") or "").lower():
                            convergence_data.append(entry)
            except Exception:
                pass

    return {
        "status": "ok",
        "convergence_count": len(convergence_data),
        "convergences": convergence_data,
        "topic_filter": topic or None,
    }


@router.get("/prediction/{prediction_id}")
async def get_prediction_detail(
    prediction_id: str,
    brain=Depends(get_brain),
    _: None = Depends(verify_strike_token_dep),
) -> dict:
    """Get detail for a specific prediction by ID.

    READ-ONLY: Scans disk prediction files for a matching ID.
    """
    if not brain:
        raise HTTPException(status_code=503, detail="Service not initialized")

    pred_dir = Path(os.getenv("NCL_DATA_DIR", "data")) / "predictions"
    for pattern in ["pred-*.json", "council/council-pred-*.json"]:
        for f in sorted(pred_dir.glob(pattern), reverse=True):
            try:
                data = json.loads(f.read_text())
                preds = []
                if isinstance(data, list):
                    preds = data
                elif isinstance(data, dict) and "predictions" in data:
                    preds = data["predictions"]
                elif isinstance(data, dict):
                    preds = [data]
                for pred in preds:
                    if pred.get("prediction_id") == prediction_id:
                        return {"status": "found", "prediction": pred}
            except Exception:
                pass

    return {
        "status": "not_found",
        "prediction_id": prediction_id,
        "message": "Prediction not found on disk. Use POST /prediction with a topic to generate a new one.",  # noqa: E501
    }
