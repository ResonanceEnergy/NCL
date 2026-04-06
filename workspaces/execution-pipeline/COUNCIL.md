# NARTIX Execution Pipeline — MWP Layer 0 (COUNCIL.md)

## Purpose

This is the operational execution pipeline for pump prompts received by NCL. Pumps flow through five stages from intake to final output, with Claude chairing all council deliberations and running the hybrid Copilot coding loop.

## Stage Flow

```
01-Input → 02-Planning → 03-Execution → 04-Review → 05-Output
   ↑                                                      ↓
   └──────────── Feedback to NCL / iPhone ←───────────────┘
```

## File Naming Convention

`TYPE-STATUS-VERSION.md`
- TYPE: pump, council, task, code, review, output
- STATUS: pending, active, complete, failed
- VERSION: v1, v2, etc.

## Global Rules

- Claude is permanent council chair in 02-Planning
- Max 3 coding iterations in 03-Execution (Paperclip budget enforcement)
- Verification always runs in 04-Review before anything ships
- Results flow back to iPhone via relay /responses endpoint
- All artifacts are JSON-structured for machine readability
- `.github/copilot-instructions.md` governs Copilot behavior at all times

## Advanced Multi-LLM Collaboration Strategies

Claude selects from these strategies in 02-Planning based on task complexity:

### Strategy 1: Hierarchical Delegation
Claude delegates sub-problems to specialized sub-councils. Each sub-council returns a structured recommendation. Claude synthesizes across sub-council outputs.
- **When**: Complex multi-domain tasks (e.g., game launch requiring tech + marketing + finance)

### Strategy 2: Debate Tournament with Elimination Rounds
Models compete with proposals. Claude scores each round. Weakest proposals are eliminated. Surviving proposals are refined and re-competed.
- **When**: Multiple valid approaches exist and the best path is unclear

### Strategy 3: Meta-Reasoning Loop
Models generate responses, then critique their own and others' responses. Claude moderates the critique phase and extracts improved positions.
- **When**: High-stakes decisions where blind spots are dangerous

### Strategy 4: Simulated Annealing Collaboration
Start with creative/divergent brainstorming (high temperature). Gradually converge as models build on each other's best ideas. Final round is highly constrained.
- **When**: Creative tasks or novel architecture design

### Strategy 5: Cross-Model Knowledge Distillation
Phase 1: Each model generates broad knowledge on the topic. Phase 2: Claude distills to core insights. Phase 3: Models re-expand with specifics using the distilled core.
- **When**: Research-heavy tasks requiring comprehensive coverage

### Strategy 6: Uncertainty-Aware Voting
Each model includes confidence scores (0.0-1.0), risk assessments, and explicit uncertainty flags with their vote. Claude weights by confidence and flags low-agreement areas.
- **When**: Decisions under uncertainty (market predictions, risk assessment)

### Strategy 7: Escalation with Human-in-the-Loop Trigger
When council cannot reach 70%+ confidence or detects unresolvable disagreement, package open questions for NATRIX with options + recommendations + risk analysis.
- **When**: Automatic — triggers when other strategies stall

## Stage Responsibilities

### 01-Input
- Receive pump from relay or direct input
- Parse envelope (pump_id, priority, intent, target_pillar)
- Validate auth token
- Route to 02-Planning

### 02-Planning
- Claude chairs council using selected strategy
- Council produces `council-output-{PUMP_ID}.md` (debate log + decision)
- Claude produces `task-plan-{PUMP_ID}.md` (decomposed tasks + acceptance criteria)
- If coding task: route to 03-Execution
- If non-coding: route directly to 04-Review

### 03-Execution (Hybrid Claude→Copilot Loop)
- Claude reads council output + task plan
- Builds precise coding prompt using advanced techniques
- Sends to Copilot (Claude Opus 4.6) via Computer Use or `current-copilot-prompt.md`
- Copilot generates code in `working-files/`
- Claude reviews, tests, iterates (max 3 rounds)
- Signs off in `signed-off.md`

### 04-Review
- Parse `verification-report.json` from automated checks
- Run tests, compare against pump prompt acceptance criteria
- Output structured JSON: { success, issues, diffs, logs, fixPlan }
- Auto-fix max 2 rounds, then escalate to NATRIX if still failing

### 05-Output
- Package final artifacts
- Generate feedback payload for iPhone pump-back
- Archive artifacts by pump ID
- Update Paperclip issue status
- Notify NATRIX via relay /responses endpoint

## Budget Enforcement

- Per-council: $5 max
- Per-coding-iteration: $2 max
- Monthly total: $800 cap
- Alert at 80%, hard stop at 100%
- Tracked via Paperclip cost events per agent
