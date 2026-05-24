"""
Council Pack — Universal Context Assembly + Council Pipeline Improvements
=========================================================================

Single entry point that every Council surface calls instead of building its
own ad-hoc prompt. Replaces the per-caller string-concat that lived in
ncl_brain/council.py, council_runner/agents.py, and councils/runner.py.

Twelve fixes shipped together (May 2026):

1. Citation grounding via Anthropic Citations API (cites verbatim;
   source-hallucination rate drops from ~10% to ~0%).
2. Conflict surfacing — reads ``contradicts_index.jsonl`` and presents open
   disputes as a dedicated CONFLICTS section the chair must address.
3. MMR diversity over candidates before packing — kills paraphrase echo.
4. Temporal split — "LAST 4H HOT" and "30D NARRATIVE ARC" as separate
   labeled sections (models attend better unblended).
5. Calibrated verbalized confidence + forced base rates (Tetlock).
6. Anonymized peer-review round (Karpathy stage 2) between member responses
   and the chair synthesis — strips model identity to remove deference.
7. Hierarchical 3-tier write-back (Reflexion / H²R) — every council yields
   a 1-line gist, a 200-token summary, and the full transcript.
8. Outcome → authority feedback — when a prediction resolves, ±1 weight on
   cited sources via the SourceAuthorityLearner Beta-Bernoulli posterior.
9. Position trick — top-3 most salient items duplicated at start AND end of
   the pack (mitigates lost-in-middle on long contexts).
10. 40% context utilization rule — hard cap on assembled pack at ~40% of the
    model's context window. Performance degrades past that.
11. Universal entry-point — every Council surface calls
    ``assemble_council_pack(...)``. No per-caller drift.
12. MapReduce compression — when the unpacked pack exceeds 30K tokens, run
    per-section Sonnet fan-out summarization then merge.

Public API
----------
- ``assemble_council_pack(topic, query, ...)`` — the universal assembler.
- ``CouncilPack`` — the structured pack returned to runners.
- ``run_calibrated_member(...)`` — round-1 call that forces base rate + verbalized confidence.
- ``run_peer_review_round(...)`` — anonymized rebuttal pass.
- ``write_back_council(...)`` — 3-tier persist.
- ``record_prediction_outcome(...)`` — outcome → authority feedback.
"""

from .assembler import (  # noqa: I001
    CouncilPack,
    PackSection,
    PackItem,
    assemble_council_pack,
    DEFAULT_MODEL_CONTEXT_TOKENS,
    UTILIZATION_CAP_FRACTION,
    MAPREDUCE_TRIGGER_TOKENS,
)
from .calibration import (
    build_calibration_preamble,
    run_calibrated_member,
    parse_verbalized_confidence,
)
from .peer_review import run_peer_review_round, anonymize
from .write_back import write_back_council
from .citations import build_citation_documents, parse_citations
from .runners import enrich_prompt_with_pack, run_council_with_pack

# ── Council session storage + replay (relocated from council_runner in W5-06) ──
# The pack now owns persistence for the legacy v1 ``CouncilRunRecord`` shape.
# ``runtime/council_runner/`` is archived at
# ``archive/strike-point-pre-merge/council_runner/``.
from .models import (
    AgentRole,
    AgentConfig,
    AgentOutput,
    ConsensusResult,
    CouncilRunRecord,
    ReplayConfig,
)
from .store import CouncilRunStore
from .replay import ReplayEngine
from .legacy import run_parallel_council  # DEPRECATED — back-compat shim only

__all__ = [
    "enrich_prompt_with_pack",
    "run_council_with_pack",
    "parse_citations",
    "CouncilPack",
    "PackSection",
    "PackItem",
    "assemble_council_pack",
    "DEFAULT_MODEL_CONTEXT_TOKENS",
    "UTILIZATION_CAP_FRACTION",
    "MAPREDUCE_TRIGGER_TOKENS",
    "build_calibration_preamble",
    "run_calibrated_member",
    "parse_verbalized_confidence",
    "run_peer_review_round",
    "anonymize",
    "write_back_council",
    "build_citation_documents",
    # Relocated from council_runner (W5-06)
    "AgentRole",
    "AgentConfig",
    "AgentOutput",
    "ConsensusResult",
    "CouncilRunRecord",
    "ReplayConfig",
    "CouncilRunStore",
    "ReplayEngine",
    "run_parallel_council",
]
