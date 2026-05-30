"""Wave 14W-C smoke test — verify lane_router decisions on canonical inputs."""

import sys


sys.path.insert(0, "/Users/natrix/dev/NCL")
from runtime.lane_router import (
    DatumKind,
    Lane,
    apply_memory_gate,
    route,
    source_to_lane,
)


print("=== source_to_lane() ===")
cases = [
    ("awarebot:reddit", Lane.INTEL),
    ("awarebot:polymarket", Lane.INTEL),
    ("brief:morning_2026-05-28", Lane.INTEL),
    ("rotation:2026-05-28", Lane.INTEL),
    ("portfolio:auto_trader_emergency_stop", Lane.PORTFOLIO),
    ("portfolio:significant_move", Lane.PORTFOLIO),
    ("paper:trade-abc123", Lane.PORTFOLIO),
    ("auto_trader:open", Lane.PORTFOLIO),
    ("scanner:goat", Lane.PORTFOLIO),
    ("scanner:bravo", Lane.PORTFOLIO),
    ("calendar:fomc-2026-06", Lane.CALENDAR),
    ("lunar:full_moon_2026-06-12", Lane.CALENDAR),
    ("city_events:calgary", Lane.CALENDAR),
    ("journal:entry-xyz", Lane.JOURNAL),
    ("morning_quiz:2026-05-28", Lane.JOURNAL),
    ("life:vision-2026", Lane.JOURNAL),
    ("council:session-12345", Lane.MEMORY),
    ("mandate:auto_trader", Lane.MEMORY),
    ("pin:user-pin-001", Lane.MEMORY),
    ("first-strike-chat", Lane.MEMORY),
    ("narrative_thread:NVDA", Lane.MEMORY),
    ("unknown-source", Lane.UNKNOWN),
]
fail = 0
for src, expected in cases:
    actual = source_to_lane(src)
    ok = actual == expected
    fail += 0 if ok else 1
    print(f"  {'✓' if ok else 'X'} {src:42s} → {actual.value:10s} (expected {expected.value})")
print(f"\n=== {len(cases) - fail}/{len(cases)} passed ===")

print("\n=== apply_memory_gate() ===")
gate_cases = [
    # (kwargs, expect_pass, reason)
    ({"score": 0.80}, True, "CRITICAL score"),
    ({"score": 0.60}, False, "MEDIUM score, no other signals"),
    ({"cross_source": 3}, True, "x-source confirmed"),
    ({"importance": 95}, True, "high caller importance"),
    ({"authority_tier": 80}, True, "council tier"),
    ({"authority_tier": 100}, True, "natrix tier"),
    ({"tags": ["pinned"]}, True, "operator pin tag"),
    ({"kind": DatumKind.MANDATE}, True, "mandate kind auto-pass"),
    ({"kind": DatumKind.AGENT_REASONING_CHAIN}, True, "reasoning chain"),
    ({"memory_type": "procedural"}, True, "LML procedural"),
    ({"source": "council:abc"}, True, "council: allowlist"),
    ({"source": "awarebot:reddit", "score": 0.50}, False, "Awarebot MEDIUM no x-src"),
    (
        {"source": "awarebot:reddit", "score": 0.50, "cross_source": 2},
        True,
        "Awarebot MEDIUM confirmed",
    ),
]
gate_fail = 0
for kwargs, expected_pass, label in gate_cases:
    passed, reason = apply_memory_gate(**kwargs)
    ok = passed == expected_pass
    gate_fail += 0 if ok else 1
    print(f"  {'✓' if ok else 'X'} {label:38s} pass={passed:5} reason={reason[:60]}")
print(f"\n=== {len(gate_cases) - gate_fail}/{len(gate_cases)} passed ===")

print("\n=== route() integration ===")
d = route(source="awarebot:reddit", importance=50, score=0.55, cross_source=1)
print(
    f"  awarebot/reddit (HIGH-ish): lane={d.primary_lane.value} gate_passed={d.memory_gate_passed}"
)
assert d.primary_lane == Lane.INTEL
assert not d.memory_gate_passed, f"expected drop, got pass: {d.memory_gate_reason}"

d = route(source="awarebot:polymarket", score=0.80)
print(
    f"  awarebot/polymarket CRITICAL: lane={d.primary_lane.value} gate_passed={d.memory_gate_passed}"
)
assert d.memory_gate_passed

d = route(source="journal:morning_quiz", importance=80, kind=DatumKind.MORNING_QUIZ)
print(f"  journal morning quiz: lane={d.primary_lane.value} gate_passed={d.memory_gate_passed}")
assert d.primary_lane == Lane.JOURNAL
assert d.memory_gate_passed

d = route(source="portfolio:auto_trade_opened", importance=75, kind=DatumKind.AGENT_OPEN)
print(f"  agent open: lane={d.primary_lane.value} gate_passed={d.memory_gate_passed}")
assert d.primary_lane == Lane.PORTFOLIO
assert d.memory_gate_passed

print(
    f"\n=== ALL CHECKS PASSED ({len(cases) - fail + len(gate_cases) - gate_fail}/{len(cases) + len(gate_cases)}) ==="
)
