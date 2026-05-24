"""
Calibrated verbalized confidence + forced base rates
====================================================

RLHF-aligned models are systematically miscalibrated. When asked "how
confident are you," base Claude / GPT / Grok return 80-100% even on questions
where their true accuracy is closer to 60%. Tetlock's 30 years of Good
Judgment Project work shows the fix:

1. Force a *base rate* before the answer ("of all $TICKER-style 4% moves
   in the last month, X% reversed within 24h — that's the base rate").
2. Force the model to state confidence as a probability (verbalized) in a
   structured slot — never embedded mid-prose.
3. Force the model to name TWO disconfirming observations that would lower
   its confidence (forecasting accuracy training shows this halves
   over-confidence on contested claims).

This module emits a preamble that goes at the top of each member's round-1
prompt, and a parser that yanks the structured calibration block back out.

Output contract
---------------
Each member is required to end its round-1 reply with a fenced block::

    ```calibration
    base_rate: 0.30                       # "what fraction of similar past
                                          #  cases came out this way"
    confidence: 0.65                      # the model's verbalized probability
    disconfirmers:
      - "If X happened, I'd lower this."
      - "If Y were true, this falls apart."
    ```

We parse the fenced block, validate the floats are in ``[0, 1]``, and attach
the dict to the member's response object for downstream scoring + write-back.
Members that fail to emit a block get ``calibration: null`` rather than a
hard error — the rest of the pipeline still works.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional


log = logging.getLogger("ncl.council_pack.calibration")


CALIBRATION_PREAMBLE = """\
=== CALIBRATION CONTRACT (Tetlock / GJP) ===
You MUST end your reply with a fenced block in EXACTLY this shape:

```calibration
base_rate: <float 0..1>
confidence: <float 0..1>
disconfirmers:
  - "<one observation that, if true, would meaningfully lower your confidence>"
  - "<a second, distinct, observation that would do the same>"
```

Rules:
- ``base_rate`` is the long-run frequency of outcomes-like-yours among the
  reference class of similar past situations. NOT your subjective belief.
  If you can't anchor on a real reference class, write your best estimate
  and one sentence above the block explaining the reference class you used.
- ``confidence`` is your subjective probability that your recommendation /
  conclusion is correct. RLHF defaults will pull you toward 90% — actively
  resist that. If you are confident, justify it in prose ABOVE the block.
- ``disconfirmers`` are concrete observations, not hedges. "Markets are
  volatile" is not a disconfirmer. "If $AAPL closes below $180 tomorrow,
  this recommendation falls apart" IS.

The downstream scorer rejects:
- Missing block.
- ``confidence`` ≥ 0.95 without two disconfirmers AND prose justification.
- ``base_rate`` and ``confidence`` differing by more than 0.4 without a
  named regime change explaining why.

=== END CALIBRATION CONTRACT ===
"""


def build_calibration_preamble() -> str:
    """Return the calibration preamble to prepend to round-1 member prompts."""
    return CALIBRATION_PREAMBLE


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(
    r"```calibration\s*\n(?P<body>.*?)\n```",
    re.IGNORECASE | re.DOTALL,
)
_FLOAT_RE = re.compile(r"-?\d+(?:\.\d+)?")


def _parse_float(line: str) -> Optional[float]:
    m = _FLOAT_RE.search(line)
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def parse_verbalized_confidence(reply_text: str) -> Optional[dict[str, Any]]:
    """Extract the ``calibration`` block from a member's reply.

    Returns
    -------
    dict | None
        ``{"base_rate": float, "confidence": float, "disconfirmers": list[str], "valid": bool, "warnings": list[str]}``
        or ``None`` if no block was present.

    Validation
    ----------
    Sets ``valid=False`` and populates ``warnings`` for any of:
    * floats out of ``[0, 1]``
    * ``confidence >= 0.95`` without ≥2 disconfirmers
    * ``|confidence - base_rate| > 0.4``
    * fewer than 2 disconfirmers
    """  # noqa: E501
    if not reply_text:
        return None
    match = _FENCE_RE.search(reply_text)
    if not match:
        return None

    body = match.group("body")
    base_rate: Optional[float] = None
    confidence: Optional[float] = None
    disconfirmers: list[str] = []
    warnings: list[str] = []

    in_disconf = False
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.lower().startswith("base_rate"):
            base_rate = _parse_float(line)
            in_disconf = False
        elif line.lower().startswith("confidence"):
            confidence = _parse_float(line)
            in_disconf = False
        elif line.lower().startswith("disconfirmers"):
            in_disconf = True
        elif in_disconf and (line.startswith("-") or line.startswith("*")):
            disc = line.lstrip("-* ").strip().strip('"').strip("'")
            if disc:
                disconfirmers.append(disc)

    valid = True
    if base_rate is None:
        warnings.append("missing base_rate")
        valid = False
    elif not (0.0 <= base_rate <= 1.0):
        warnings.append(f"base_rate out of range: {base_rate}")
        valid = False
    if confidence is None:
        warnings.append("missing confidence")
        valid = False
    elif not (0.0 <= confidence <= 1.0):
        warnings.append(f"confidence out of range: {confidence}")
        valid = False
    if len(disconfirmers) < 2:
        warnings.append(f"only {len(disconfirmers)} disconfirmers (require ≥2)")
        valid = False
    if confidence is not None and confidence >= 0.95 and len(disconfirmers) < 2:
        warnings.append("confidence ≥0.95 without two disconfirmers")
        valid = False
    if base_rate is not None and confidence is not None:
        if abs(confidence - base_rate) > 0.4:
            warnings.append(
                f"|confidence-base_rate|={abs(confidence-base_rate):.2f} >0.4 "
                "(named regime change required in prose)"
            )

    return {
        "base_rate": base_rate,
        "confidence": confidence,
        "disconfirmers": disconfirmers,
        "valid": valid,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Helper for the council runner: wraps a member-call coroutine and parses
# calibration on the way back. Returns (text, calibration).
# ---------------------------------------------------------------------------


async def run_calibrated_member(member_call, prompt: str) -> tuple[str, Optional[dict]]:
    """Invoke ``member_call(prompt)`` and parse calibration block on return.

    ``member_call`` is any async callable that accepts a single string prompt
    and returns the raw text reply. We don't reach into HTTP plumbing here —
    keeping the surface tiny means every runner (v1 council, v2 council,
    YouTube council) can pass its own LLM caller.

    Returns
    -------
    (reply_text, calibration_dict_or_None)
    """
    full_prompt = CALIBRATION_PREAMBLE + "\n\n" + prompt
    reply = await member_call(full_prompt)
    calibration = parse_verbalized_confidence(reply)
    if calibration and not calibration["valid"]:
        log.info("[CALIBRATION] member returned invalid block: %s", calibration["warnings"])
    return reply, calibration


__all__ = [
    "CALIBRATION_PREAMBLE",
    "build_calibration_preamble",
    "parse_verbalized_confidence",
    "run_calibrated_member",
]
