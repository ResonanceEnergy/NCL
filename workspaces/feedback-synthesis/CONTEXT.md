# Feedback Synthesis Workspace

Process feedback from NCC, BRS, AAC into mandate updates and doctrine refinement.

## Stages

| Stage | Name | Purpose |
|-------|------|---------|
| 01 | Report Intake | Receive structured feedback reports from NCC/BRS/AAC |
| 02 | Validation | Claude-validated synthesis of feedback signals |
| 03 | Pattern Detection | Identify recurring themes across reports |
| 04 | Recommendation | Propose mandate adjustments based on patterns |
| 05 | Mandate Update | Apply approved changes to active mandates |

## Key Artifacts

- **Input**: NCC execution reports, BRS revenue reports, AAC P&L + performance
- **Intermediate**: Validation summary, pattern matrix, recommendations
- **Output**: Updated mandates (versioned), doctrine refinements

## Authority

Feedback flows upward (NCC/BRS/AAC → NCL). NCL synthesizes and updates mandates only.

## Execution Model

Stages 01-03 continuous (event-driven). Stages 04-05 weekly synthesis + approval gate.

## Storage

- Incoming reports: `/dev/NCL/feedback/reports/{pillar}/`
- Validation summaries: `/dev/NCL/feedback/validations/`
- Patterns: `/dev/NCL/feedback/patterns_{date}.json`
- Recommendations: `/dev/NCL/feedback/recommendations_{date}.md`
- Updated mandates: `/dev/NCL/mandates/approved/` (versioned)
