# Agent Development

Four-stage pipeline for creating and hardening NCL agents. Takes an agent concept
from design through implementation, testing, and hardening.

## Task Routing

| Task                        | Go To                              |
|-----------------------------|------------------------------------|
| Define agent purpose/scope  | `stages/01-design/CONTEXT.md`      |
| Write agent code            | `stages/02-implement/CONTEXT.md`   |
| Run golden task evaluation  | `stages/03-test/CONTEXT.md`        |
| Harden for production       | `stages/04-harden/CONTEXT.md`      |

## Stage Handoffs

```
  [01-design]  ------>  [02-implement]  ------>  [03-test]  ------>  [04-harden]
```

Each stage writes to its `output/` folder. The next stage reads from there.

## Shared Resources

| Resource | Location | What It Provides |
|----------|----------|-----------------|
| Agent base classes | `../../ncl_agency_runtime/agents/` | Existing agent code |
| Test suite | `../../tests/` | Test patterns and fixtures |
| Golden tasks | `../../evaluation/golden_tasks/` | Evaluation criteria |
| Eval harness | `../../evaluation_harness.py` | Scoring engine |
