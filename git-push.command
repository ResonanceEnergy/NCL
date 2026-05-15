#!/usr/bin/env bash
cd "$(dirname "$0")"
export GIT_PAGER=cat
export PAGER=cat
REPO_URL="https://github.com/ResonanceEnergy/NCL.git"

# Clean approach: clone remote, overlay local, push
rm -rf /tmp/ncl-push
git clone "$REPO_URL" /tmp/ncl-push 2>&1
rsync -av --exclude='.git' ./ /tmp/ncl-push/ 2>/dev/null
cd /tmp/ncl-push
git add -A
git commit -m "feat: MANDATE-2026-008 STRIKE-POINT pipeline + doctrine + roadmap" 2>/dev/null || echo "(nothing new)"
git push origin main 2>&1
cp -r /tmp/ncl-push/.git "$HOME/dev/NCL/.git"
rm -rf /tmp/ncl-push
echo ""; echo "✅ Done"; read -n1
