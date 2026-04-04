# NARTIX Execution Pipeline — MWP Layer 0

## Purpose
This is the operational execution pipeline for pump prompts that have been received by NCL. Pumps flow through five stages from intake to final output, with Claude chairing all council deliberations and running the hybrid Copilot coding loop.

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

## Rules
- Claude is permanent council chair in 02-Planning
- Max 3 coding iterations in 03-Execution (Paperclip budget enforcement)
- Verification always runs in 04-Review before anything ships
- Results flow back to iPhone via relay /responses endpoint
- All artifacts are JSON-structured for machine readability
