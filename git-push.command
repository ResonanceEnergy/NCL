#!/usr/bin/env bash
# ============================================================
# NCL Git Push — Clone-overlay-push strategy
# WARNING: This replaces remote main with local working tree.
# A backup branch is created before pushing.
# ============================================================
set -e
cd "$(dirname "$0")"
export GIT_PAGER=cat
export PAGER=cat
REPO_URL="https://github.com/ResonanceEnergy/NCL.git"

echo ""
echo "⚠️  This will push your local NCL directory to remote main."
echo "   A backup branch (backup/pre-push-$(date +%Y%m%d-%H%M%S)) will be created first."
echo ""
read -p "Continue? [y/N] " confirm
if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
    echo "Aborted."
    exit 0
fi

rm -rf /tmp/ncl-push
git clone "$REPO_URL" /tmp/ncl-push 2>&1

# Create backup branch from current remote state
cd /tmp/ncl-push
BACKUP_BRANCH="backup/pre-push-$(date +%Y%m%d-%H%M%S)"
git branch "$BACKUP_BRANCH"
git push origin "$BACKUP_BRANCH" 2>&1
echo "  ✓ Backup branch created: $BACKUP_BRANCH"

# Overlay local files
rsync -av --exclude='.git' "$(dirname "$0")/" /tmp/ncl-push/ 2>/dev/null
git add -A
git commit -m "feat: MANDATE-2026-008 STRIKE-POINT pipeline + doctrine + roadmap" 2>/dev/null || echo "(nothing new)"
git push origin main 2>&1
cp -r /tmp/ncl-push/.git "$HOME/dev/NCL/.git"
rm -rf /tmp/ncl-push
echo ""; echo "✅ Done"; read -n1
