# NCL → RESONANCE ENERGY GAMES Routing Contract

**Purpose**: Defines how pump prompts about game development are routed from NCL through NCC to the RESONANCE ENERGY GAMES.

---

## Strike Point → NCL → NCC → RESONANCE ENERGY GAMES Flow

```
NATRIX (iPhone)
  │ First Strike via Grok
  ▼
Pump Prompt arrives at NCL (port 8787)
  │ NCL detects game-related intent
  ▼
NCL runs council (Claude chairs debate)
  │ Council produces mandate
  ▼
NATRIX approves mandate (Approval Gate on Strike Point app)
  │
  ▼
NCL dispatches mandate to NCC (port 8765)
  │ NCC decomposes mandate into lane-specific tasks
  ▼
NCC routes task to RESONANCE ENERGY GAMES
  │ target_lane: CC | AOE | ATL | TAR | AH | FAC
  ▼
RESONANCE ENERGY GAMES executes in target lane repo
  │ Feedback reports flow back
  ▼
NCC aggregates lane feedback into division summary
  │ Claude-validated synthesis
  ▼
NCL receives interpreted feedback → updates mandate status
  │
  ▼
Strike Point Dashboard shows updated status to NATRIX
```

---

## Intent Detection Keywords

When a pump prompt contains any of these keywords/patterns, NCL should classify it as a RESONANCE ENERGY GAMES mandate:

| Pattern | Target Lane | Priority Hint |
|---------|-------------|---------------|
| crimson compass, CC, spy game, espionage | CC | Based on context |
| archive of echoes, AoE, memory puzzle, lore game | AOE | Based on context |
| atlantis, world of wonder, ATL, civilization game | ATL | Based on context |
| tartaria, TAR, hidden history, resonance game | TAR | Based on context |
| adventure hero, AH, chronicles of glory, hero game | AH | Based on context |
| game engine, shared factory, module format, tooling | FAC | P2 default |
| ship game, launch game, testflight, app store, steam | Inferred from context | P0 if ship |
| game bug, game fix, playtest, QA | Inferred from context | P1 if blocker |

---

## Mandate Fields for RESONANCE ENERGY GAMES

When NCL generates a mandate targeting the RESONANCE ENERGY GAMES, it MUST include:

```json
{
  "target_pillar": "NCC",
  "target_division": "resonance-energy-games",
  "target_lane": "CC|AOE|ATL|TAR|AH|FAC",
  "division_context": {
    "repo": "github-repo-name",
    "current_status": "from lane-config.json",
    "build_stage": "design|implement|qa|build|ship"
  }
}
```

---

## Paperclip Issue Routing

When NCC creates Paperclip issues for RESONANCE ENERGY GAMES tasks:

- Company: `resonance-energy-games`
- Issue prefix: `GAMES-{LANE}-{NUMBER}` (e.g., `GAMES-CC-0042`)
- Agent assignment: route to lane-specific agent (cc-lane, aoe-lane, etc.)
- Cross-lane tasks use `GAMES-FAC-{NUMBER}` prefix

---

## Feedback Routing (Reverse Flow)

RESONANCE ENERGY GAMES → NCC → NCL:

1. **Lane Agent** completes task, writes feedback JSON to Paperclip activity log
2. **NCC** aggregates per-lane feedback into division-level summary
3. **NCC** applies Claude-validated interpretation (no raw metrics to NCL)
4. **NCL** receives synthesis, updates mandate status, adjusts roadmap if needed
5. **Strike Point Dashboard** reflects updated status for NATRIX

Feedback categories:
- `build-status`: compilation, test results, CI/CD outcomes
- `playtest-results`: FPS, crash rate, player feedback
- `milestone-completion`: vertical slice done, beta ship, etc.
- `blockers`: impediments requiring NCC/NCL escalation
- `metrics`: performance data, build sizes, test coverage
