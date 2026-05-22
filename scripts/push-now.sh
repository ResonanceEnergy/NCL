#!/usr/bin/env bash
set -x
cd ~/dev/NCL
git status -sb
echo "---"
git push origin main 2>&1
echo "exit: $?"
echo "===FIRSTSTRIKE==="
cd ~/Projects/FirstStrike
git status -sb
git add -A
git commit -m "iOS Settings moved to gear icon in Dashboard header (frees bottom bar slot)" 2>&1 || true
git push origin main 2>&1
echo "exit: $?"
