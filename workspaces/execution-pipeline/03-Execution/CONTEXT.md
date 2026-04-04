# 03-Execution — Hybrid Claude→Copilot Coding Loop

## Purpose
Claude Desktop Max reads the council output and task plan, builds precise coding prompts, and sends them to GitHub Copilot (Claude Opus 4.6) in VS Code Agent Mode. Claude then reviews the output and iterates.

## Process
1. Read `council-output.md` + `task-plan.md`
2. Build high-quality prompt using techniques:
   - Outcome + Constraints + Examples
   - Context Puck (inject relevant file snippets)
   - Acceptance Criteria (testable conditions)
   - Debugging Loop (reference exact bug, preserve logic)
3. Write prompt to `current-copilot-prompt.md` or send via Computer Use
4. Copilot (Opus 4.6) generates code in `working-files/`
5. Claude Code reviews, runs tests
6. If issues: build fix prompt → repeat (max 3 iterations)
7. If good: commit, create `signed-off.md`, move to 04-Review

## Files
- `council-output.md` — input from 02-Planning
- `task-plan.md` — input from 02-Planning
- `current-copilot-prompt.md` — the prompt Claude builds for Copilot
- `working-files/` — where Copilot writes code
- `signed-off.md` — Claude's sign-off when execution is complete

## Budget
- Max 3 coding iterations per task (Paperclip enforcement)
- If 3 iterations fail: escalate to NATRIX with diagnostic
