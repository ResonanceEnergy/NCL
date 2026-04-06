# Council Reports

Output directory for YouTube Council and X Council intelligence reports.

Reports are generated in pairs: `.md` (human-readable) and `.json` (machine-parseable).

Naming convention: `{council}-{session_id}.{ext}` (e.g., `youtube-20260406-120000.md`)

High-confidence actionable insights are also written to `../alerts/` as individual JSON files, and all insights append to the daily JSONL file in `../signals/`.
