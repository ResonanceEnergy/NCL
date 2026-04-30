#!/bin/bash
# prep-commit.command — Clears the launchctl blocker, then populates GitHub Desktop's
# Summary field (via clipboard) plus a Description file so NATRIX can paste-and-push.
#
# Does NOT run git add/commit/push — that's done in GitHub Desktop.

set -u
REPO="$HOME/dev/NCL"
cd "$REPO" || { echo "ERROR: cannot cd to $REPO"; exit 1; }

echo "============================================================"
echo "  NCL — prep-commit"
echo "  $(date)"
echo "============================================================"
echo ""

# ---------------------------------------------------------------
# 1. Clear ALL stale git lock files
# ---------------------------------------------------------------
echo "[1/5] Sweeping stale git lock files ..."
LOCK_PATHS=(
  "$REPO/.git/index.lock"
  "$REPO/.git/HEAD.lock"
  "$REPO/.git/config.lock"
  "$REPO/.git/packed-refs.lock"
  "$REPO/.git/objects/maintenance.lock"
  "$REPO/.git/gc.pid.lock"
  "$REPO/.git/shallow.lock"
)
FOUND_ANY=0
for L in "${LOCK_PATHS[@]}"; do
  if [ -e "$L" ]; then
    echo "    found: $L"
    rm -f "$L" 2>/dev/null && echo "    removed." || echo "    FAILED to remove (permission denied?)"
    FOUND_ANY=1
  fi
done
# Sweep any per-ref locks under refs/
find "$REPO/.git/refs" -name "*.lock" 2>/dev/null | while read -r L; do
  echo "    found ref lock: $L"
  rm -f "$L" 2>/dev/null && echo "    removed." || echo "    FAILED to remove."
  FOUND_ANY=1
done
[ "$FOUND_ANY" -eq 0 ] && echo "    none found — clean."
echo ""

# ---------------------------------------------------------------
# 2. Reload launchd services (the other open blocker)
# ---------------------------------------------------------------
echo "[2/5] Reloading launchd services via reload-services.command ..."
if [ -x "$REPO/reload-services.command" ]; then
  "$REPO/reload-services.command" || echo "  (reload script returned non-zero — review output above)"
else
  echo "  reload-services.command not executable, skipping"
fi
echo ""

# ---------------------------------------------------------------
# 3. Show what GitHub Desktop will see
# ---------------------------------------------------------------
echo "[3/5] Pending changes:"
git status --short
echo ""

# ---------------------------------------------------------------
# 4. Build commit summary + description
# ---------------------------------------------------------------
SUMMARY="NCL build complete: 10 phases, 133 endpoints, 4-tab dashboard, launchd swap"

DESCRIPTION=$(cat <<'EOF'
Full NCL (NuRealCortexLink) build-out — incremental scheduled-task work, all ten phases complete.

Phases:
- P1  BRL material purged
- P2  Broken subsystems repaired (incl. Reddit OAuth)
- P3  Intelligence engine wired
- P4  Council engine wired
- P5  Memory system wired
- P6  Pump pipeline end-to-end (POST /pump -> council -> mandate -> approval gate)
- P7  Awarebot scanner + Future Predictor ensemble (Claude + Ollama)
- P8  UNI Research Cortex (planner -> gatherer -> synthesizer)
- P9  Governance kernel, LDE, eval runner, review queue, search indexer, telemetry, deployment monitor
- P10 Dashboard 4-tab live (Overview / Intel / Reports / Actions); launchd plists updated; reload-services.command added

Verification (pass 45):
- runtime/api/routes.py            132,665 b   133 endpoints
- runtime/awarebot/scanner.py       12,776 b
- runtime/uni/cortex.py             10,416 b
- runtime/ncl_brain/brain.py        46,449 b
- dashboard/command-center.html     59,194 b   4 tab IDs present
- reload-services.command            5,164 b   exec mode 700
- AST parse OK on routes.py + brain.py

Endpoint buckets: pump=5 awarebot=1 prediction=1 uni=4 council=17 memory=5
intelligence=13 governance=12 lde=9 mandates=4 deployment=5 evaluation=3
review-queue=13 search=4 telemetry=5 autonomous=7 availability=4 feedback=2
notifications=2 orchestrator=3 shortcuts=3 network=1 services=1 dashboard=2
app=4 root=1 health=1.

Files in this commit:
- .build-progress.json                        (phase tracker, 45 verification passes)
- dashboard/command-center.html               (4-tab live dashboard)
- notifications/intelligence/intel-*.json     (autonomous scheduler output)
- reload-services.command                     (launchctl swap to clean NCL service)
EOF
)

# ---------------------------------------------------------------
# 5. Write description file + copy summary line to clipboard
# ---------------------------------------------------------------
MSG_FILE="$REPO/.git/NCL_COMMIT_MSG.txt"
{
  echo "$SUMMARY"
  echo ""
  echo "$DESCRIPTION"
} > "$MSG_FILE"

# Summary -> clipboard for GitHub Desktop's "Summary" field
printf "%s" "$SUMMARY" | pbcopy

# Description -> separate clipboard-able file
DESC_FILE="$REPO/.git/NCL_COMMIT_DESCRIPTION.txt"
printf "%s" "$DESCRIPTION" > "$DESC_FILE"

echo "[4/5] Commit summary copied to clipboard:"
echo "    \"$SUMMARY\""
echo ""
echo "[5/5] Files written:"
echo "    $MSG_FILE       (summary + full description)"
echo "    $DESC_FILE      (description only, paste into GitHub Desktop's Description box)"
echo ""

# ---------------------------------------------------------------
# Final hand-off
# ---------------------------------------------------------------
echo "------------------------------------------------------------"
echo "NEXT STEPS in GitHub Desktop:"
echo "  1. Summary field    -> Cmd+V (already on clipboard)"
echo "  2. Description box  -> open $DESC_FILE, copy, paste"
echo "  3. Click Commit to main, then Push origin"
echo "------------------------------------------------------------"

# Try to bring GitHub Desktop forward (non-fatal if not installed)
open -a "GitHub Desktop" "$REPO" 2>/dev/null || true

echo ""
echo "Done. Press any key to close this window."
read -n 1 -s
