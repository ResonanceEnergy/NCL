"""Tests for the provenance/authority tier system.

Coverage:
  1. Direct source -> tier mapping for every tier
  2. Prefix-match fallback (awarebot:newsource -> SCANNER)
  3. Consolidated source (a,b,c) resolves to max tier
  4. consolidation: transparent prefix stripping
  5. Unknown source -> RAW (and None/empty defaults)
  6. authority_weight bounds + linearity
  7. tier_at_least name + int forms
  8. filter_by_min_tier honors tier floor
  9. Salience integration — high-tier dud beats low-tier peak
 10. Fusion-style RRF reweighting flips ordering when expected
 11. backfill_authority_tiers stamps + is idempotent
 12. create_unit stamps authority_tier into metadata
"""

import json
import tempfile

import pytest

from runtime.memory.authority import (
    AuthorityTier,
    SOURCE_TIER_MAP,
    authority_weight,
    authority_weight_for_source,
    backfill_authority_tiers,
    filter_by_min_tier,
    tier_at_least,
    tier_for_source,
)
from runtime.memory.store import MemoryStore
from runtime.memory.working_context import DailyContextWindow
from runtime.ncl_brain.models import MemUnit


# ---------------------------------------------------------------------------
# 1. Direct source -> tier mapping
# ---------------------------------------------------------------------------


def test_source_mapping_covers_every_tier():
    """Every tier except RAW (which is the unknown-source fallback) has at
    least one concrete source that maps to it, and every mapped source
    round-trips through tier_for_source unchanged."""
    seen_tiers = set()
    for src, tier in SOURCE_TIER_MAP.items():
        assert tier_for_source(src) == tier, src
        seen_tiers.add(tier)
    expected = set(AuthorityTier) - {AuthorityTier.RAW}
    assert seen_tiers == expected, (
        f"missing tiers in SOURCE_TIER_MAP: {expected - seen_tiers}"
    )


@pytest.mark.parametrize("source,expected", [
    ("natrix-directive", AuthorityTier.NATRIX),
    ("pump-prompt", AuthorityTier.NATRIX),
    ("journal", AuthorityTier.NATRIX),
    ("first-strike-chat", AuthorityTier.NATRIX),
    ("council-decision", AuthorityTier.COUNCIL),
    ("council:claude", AuthorityTier.COUNCIL),
    ("mandate", AuthorityTier.COUNCIL),
    ("brain-chat-response", AuthorityTier.BRAIN),
    ("prediction", AuthorityTier.BRAIN),
    ("journal-reflection", AuthorityTier.BRAIN),
    ("calendar-event", AuthorityTier.CALENDAR),
    ("calendar-agent", AuthorityTier.CALENDAR),
    ("llm-haiku", AuthorityTier.LLM_SINGLE),
    ("claude-direct", AuthorityTier.LLM_SINGLE),
    ("awarebot", AuthorityTier.SCANNER),
    ("awarebot:reddit", AuthorityTier.SCANNER),
    ("awarebot:options_flow", AuthorityTier.SCANNER),
])
def test_known_sources_resolve_to_expected_tier(source, expected):
    assert tier_for_source(source) == expected


# ---------------------------------------------------------------------------
# 2. Prefix-match fallback
# ---------------------------------------------------------------------------


def test_prefix_match_for_novel_subtype():
    """An unknown awarebot subsource should still resolve to SCANNER."""
    assert tier_for_source("awarebot:brand-new-feed-2027") == AuthorityTier.SCANNER
    assert tier_for_source("council:youtube:ytc-dedicated-abc123") == AuthorityTier.COUNCIL
    assert tier_for_source("council:youtube:ytc-dedicated-xyz-789") == AuthorityTier.COUNCIL


def test_prefix_match_uses_longest_known_prefix():
    """`council:youtube:insight` is explicit; `council:youtube:novel-suffix`
    should fall back to `council:youtube` (still COUNCIL)."""
    assert tier_for_source("council:youtube:insight") == AuthorityTier.COUNCIL
    assert tier_for_source("council:youtube:something-new") == AuthorityTier.COUNCIL


# ---------------------------------------------------------------------------
# 3. Consolidated (comma-joined) — max tier wins
# ---------------------------------------------------------------------------


def test_consolidation_resolves_max_tier_across_parts():
    """A consolidation merging scanner + council + natrix sources resolves
    to NATRIX (the maximum tier present)."""
    assert tier_for_source(
        "awarebot:reddit,council:claude,pump-prompt"
    ) == AuthorityTier.NATRIX

    # Two scanners — should still be SCANNER, not RAW.
    assert tier_for_source(
        "awarebot:reddit,awarebot:news"
    ) == AuthorityTier.SCANNER


# ---------------------------------------------------------------------------
# 4. `consolidation:` transparent prefix
# ---------------------------------------------------------------------------


def test_consolidation_prefix_is_transparent():
    """`consolidation:awarebot:reddit` should resolve to SCANNER, not RAW."""
    assert tier_for_source("consolidation:awarebot:reddit") == AuthorityTier.SCANNER
    assert tier_for_source(
        "consolidation:awarebot:reddit,consolidation:awarebot:google_trends"
    ) == AuthorityTier.SCANNER
    # Nested doubles also handled
    assert tier_for_source(
        "consolidation:consolidation:awarebot:reddit"
    ) == AuthorityTier.SCANNER


# ---------------------------------------------------------------------------
# 5. Unknown sources fall back to RAW
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("source", [
    "",
    None,
    "totally-made-up-source",
    "random:garbage:string",
    "  ",
])
def test_unknown_source_is_raw(source):
    assert tier_for_source(source) == AuthorityTier.RAW


# ---------------------------------------------------------------------------
# 6. authority_weight bounds + linearity
# ---------------------------------------------------------------------------


def test_authority_weight_bounds_and_linearity():
    assert authority_weight(AuthorityTier.NATRIX) == pytest.approx(1.0)
    assert authority_weight(AuthorityTier.COUNCIL) == pytest.approx(0.8)
    assert authority_weight(AuthorityTier.BRAIN) == pytest.approx(0.6)
    assert authority_weight(AuthorityTier.CALENDAR) == pytest.approx(0.5)
    assert authority_weight(AuthorityTier.LLM_SINGLE) == pytest.approx(0.4)
    assert authority_weight(AuthorityTier.SCANNER) == pytest.approx(0.2)
    assert authority_weight(AuthorityTier.RAW) == pytest.approx(0.1)


def test_authority_weight_clamps_to_bounds():
    assert authority_weight(0) == 0.1     # below min clamps to 0.1
    assert authority_weight(5) == 0.1     # below min clamps to 0.1
    assert authority_weight(200) == 1.0   # above max clamps to 1.0
    assert authority_weight(None) == 0.1  # None -> RAW -> 0.1
    assert authority_weight(-10) == 0.1   # negative clamps


def test_authority_weight_for_source_combined_helper():
    assert authority_weight_for_source("pump-prompt") == pytest.approx(1.0)
    assert authority_weight_for_source("awarebot:reddit") == pytest.approx(0.2)
    assert authority_weight_for_source("garbage") == pytest.approx(0.1)


# ---------------------------------------------------------------------------
# 7. tier_at_least
# ---------------------------------------------------------------------------


def test_tier_at_least_name_and_int_forms():
    assert tier_at_least(AuthorityTier.NATRIX, "council") is True
    assert tier_at_least(AuthorityTier.SCANNER, "council") is False
    assert tier_at_least(AuthorityTier.COUNCIL, AuthorityTier.COUNCIL) is True
    assert tier_at_least(60, 50) is True
    assert tier_at_least(50, 60) is False

    with pytest.raises(ValueError):
        tier_at_least(AuthorityTier.NATRIX, "not-a-tier")


# ---------------------------------------------------------------------------
# 8. filter_by_min_tier
# ---------------------------------------------------------------------------


def test_filter_by_min_tier_uses_metadata_then_source():
    """filter_by_min_tier should:
    - honor an explicit metadata.authority_tier
    - fall back to tier_for_source(unit.source) when metadata is absent
    """
    u_natrix = MemUnit(
        unit_id="u1", content="x", source="pump-prompt", importance=50.0,
        metadata={"authority_tier": int(AuthorityTier.NATRIX)},
    )
    u_scanner_no_meta = MemUnit(
        unit_id="u2", content="x", source="awarebot:reddit", importance=50.0,
    )
    u_unknown = MemUnit(
        unit_id="u3", content="x", source="totally-unknown", importance=50.0,
    )
    units = [u_natrix, u_scanner_no_meta, u_unknown]

    council_floor = filter_by_min_tier(units, AuthorityTier.COUNCIL)
    assert [u.unit_id for u in council_floor] == ["u1"]

    scanner_floor = filter_by_min_tier(units, "scanner")
    assert sorted(u.unit_id for u in scanner_floor) == ["u1", "u2"]

    raw_floor = filter_by_min_tier(units, "raw")
    assert sorted(u.unit_id for u in raw_floor) == ["u1", "u2", "u3"]


# ---------------------------------------------------------------------------
# 9. Salience integration — high-tier dud beats low-tier peak
# ---------------------------------------------------------------------------


def test_salience_natrix_dud_beats_scanner_peak():
    """A NATRIX item with poor (recency, importance, relevance) should still
    outrank a peak SCANNER item — the whole point of the system."""
    window = DailyContextWindow.__new__(DailyContextWindow)  # bypass __init__

    natrix_dud = window.compute_salience(
        recency=0.10, importance=0.10, relevance=0.10,
        authority_weight=authority_weight(AuthorityTier.NATRIX),
    )
    scanner_peak = window.compute_salience(
        recency=1.0, importance=1.0, relevance=1.0,
        authority_weight=authority_weight(AuthorityTier.SCANNER),
    )

    assert natrix_dud > scanner_peak, (
        f"NATRIX dud {natrix_dud:.3f} should beat SCANNER peak "
        f"{scanner_peak:.3f}"
    )


def test_salience_higher_authority_strictly_dominates_on_equal_subscore():
    window = DailyContextWindow.__new__(DailyContextWindow)
    eq = dict(recency=0.5, importance=0.5, relevance=0.5)
    natrix = window.compute_salience(
        **eq, authority_weight=authority_weight(AuthorityTier.NATRIX),
    )
    scanner = window.compute_salience(
        **eq, authority_weight=authority_weight(AuthorityTier.SCANNER),
    )
    assert natrix > scanner


# ---------------------------------------------------------------------------
# 10. RRF-style reweighting flips ordering
# ---------------------------------------------------------------------------


def test_authority_reweighting_flips_rank_when_expected():
    """Numerical demonstration of the FusedRetriever reweighting math.

    A SCANNER unit at perfect RRF rank-1 across all 3 signals (~0.05 fused)
    should lose to a NATRIX unit at rank-3 on vector only (~0.016 fused)
    once authority is multiplied in.
    """
    # RRF with k=60: rank 1 contributes 1/(60+1)=~0.01639
    # Three signals at rank 1 each contributing equally:
    scanner_rrf = 3 * (1.0 / 61)
    # Vector only at rank 3: 1/(60+3) = ~0.01587
    natrix_rrf = 1.0 / 63

    scanner_final = scanner_rrf * authority_weight(AuthorityTier.SCANNER)
    natrix_final = natrix_rrf * authority_weight(AuthorityTier.NATRIX)

    assert natrix_final > scanner_final, (
        f"NATRIX rank-3 ({natrix_final:.4f}) should beat SCANNER rank-1 "
        f"({scanner_final:.4f}) after authority reweighting"
    )


# ---------------------------------------------------------------------------
# 11. backfill_authority_tiers — stamps + idempotent
# ---------------------------------------------------------------------------


@pytest.fixture
def temp_data_dir():
    with tempfile.TemporaryDirectory() as tmp:
        yield tmp


async def test_backfill_stamps_and_is_idempotent(temp_data_dir):
    store = MemoryStore(temp_data_dir)

    # Seed three units. The create_unit path already stamps tiers, so
    # strip the metadata manually to simulate pre-migration state.
    u_natrix = await store.create_unit(
        content="natrix says do the thing",
        source="pump-prompt",
        importance=80.0,
    )
    u_scanner = await store.create_unit(
        content="reddit r/wallstreetbets says doge moon",
        source="awarebot:reddit",
        importance=40.0,
    )
    u_unknown = await store.create_unit(
        content="who wrote this",
        source="some-rando-importer",
        importance=20.0,
    )

    # Strip authority_tier so backfill has something to do.
    units = await store._load_all_units()
    for u in units:
        if isinstance(u.metadata, dict):
            u.metadata.pop("authority_tier", None)
    await store._rewrite_units(units)

    # Verify they're actually stripped
    units = await store._load_all_units()
    for u in units:
        assert "authority_tier" not in (u.metadata or {})

    # First backfill — should update all 3
    result1 = await backfill_authority_tiers(store)
    assert result1["scanned"] == 3
    assert result1["updated"] == 3
    assert result1["already_set"] == 0
    assert result1["by_tier"]["natrix"] == 1
    assert result1["by_tier"]["scanner"] == 1
    assert result1["by_tier"]["raw"] == 1

    # Tiers persisted to disk?
    units = await store._load_all_units()
    by_id = {u.unit_id: u for u in units}
    assert by_id[u_natrix.unit_id].metadata["authority_tier"] == int(AuthorityTier.NATRIX)
    assert by_id[u_scanner.unit_id].metadata["authority_tier"] == int(AuthorityTier.SCANNER)
    assert by_id[u_unknown.unit_id].metadata["authority_tier"] == int(AuthorityTier.RAW)

    # Second backfill — should be a no-op
    result2 = await backfill_authority_tiers(store)
    assert result2["scanned"] == 3
    assert result2["updated"] == 0
    assert result2["already_set"] == 3


# ---------------------------------------------------------------------------
# 12. create_unit stamps authority_tier on write
# ---------------------------------------------------------------------------


async def test_create_unit_stamps_authority_tier(temp_data_dir):
    store = MemoryStore(temp_data_dir)

    u = await store.create_unit(
        content="trust me bro",
        source="awarebot:reddit",
        importance=50.0,
    )
    assert isinstance(u.metadata, dict)
    assert u.metadata.get("authority_tier") == int(AuthorityTier.SCANNER)

    u2 = await store.create_unit(
        content="natrix wants this done by friday",
        source="pump-prompt",
        importance=80.0,
    )
    assert u2.metadata.get("authority_tier") == int(AuthorityTier.NATRIX)

    # Round-trip via JSONL — the tier survives serialization
    loaded = await store._load_all_units()
    by_id = {u_.unit_id: u_ for u_ in loaded}
    assert by_id[u.unit_id].metadata["authority_tier"] == int(AuthorityTier.SCANNER)
    assert by_id[u2.unit_id].metadata["authority_tier"] == int(AuthorityTier.NATRIX)
