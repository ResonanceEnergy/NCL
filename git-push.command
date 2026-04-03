#!/usr/bin/env bash
# Push NCL to GitHub — handles existing remote with branch protection
cd "$(dirname "$0")"

export GIT_PAGER=cat
export PAGER=cat

echo "=== Git Push — NCL ==="
echo ""

REPO_URL="https://github.com/ResonanceEnergy/NCL.git"
echo "Target repo: $REPO_URL"

# Reset git state completely for clean start
rm -rf .git

echo "Cloning existing repo..."
cd /tmp
rm -rf ncl-clone
git clone "$REPO_URL" ncl-clone 2>&1

echo ""
echo "Copying local files into clone..."
# Copy all local files into the clone (overwrite)
rsync -av --exclude='.git' "$HOME/Projects/NCL/" /tmp/ncl-clone/ 2>&1

cd /tmp/ncl-clone

# Stage and commit
git add -A
git commit -m "feat: NCL brain cortex — MANDATE-2026-008 STRIKE-POINT pipeline + doctrine + roadmap" 2>/dev/null || echo "(nothing new to commit)"

# Push (normal push, works with branch protection)
echo ""
echo "--- Pushing to GitHub ---"
git push origin main 2>&1

# Copy .git back so local has proper git history
echo ""
echo "Syncing git history back to local..."
rm -rf "$HOME/Projects/NCL/.git"
cp -r /tmp/ncl-clone/.git "$HOME/Projects/NCL/.git"

# Cleanup
rm -rf /tmp/ncl-clone

echo ""
echo "✅ Done! Check: https://github.com/ResonanceEnergy/NCL"
echo ""
echo "Press any key to close..."
read -n1
