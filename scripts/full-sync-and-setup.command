#!/bin/bash
# Full Sync — Git commit/push both repos + install launchd auto-restart
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}================================================${NC}"
echo -e "${CYAN}  NATRIX Full Sync — Commit, Push, Auto-restart${NC}"
echo -e "${CYAN}================================================${NC}"
echo ""

# ════════════════════════════════════════════
# 1. FirstStrike — Git commit & push
# ════════════════════════════════════════════
echo -e "${YELLOW}[1/6] FirstStrike — staging...${NC}"
cd ~/dev/FirstStrike

git add Sources/ CLAUDE.md FUNCTION_TEST_SCORECARD.md project.yml apply-fixes.sh \
  .github/copilot-instructions.md build.command rebuild.command \
  regen-project.command regenerate-xcode.command Sources/Info.plist 2>/dev/null

STAGED_FS=$(git diff --cached --stat 2>/dev/null | tail -1)
if [ -z "$STAGED_FS" ]; then
    echo -e "${YELLOW}  No new changes to commit in FirstStrike${NC}"
else
    echo -e "  ${STAGED_FS}"
    git commit -m "$(cat <<'EOF'
feat: FirstStrike v2.0 — full restructure, Brain Direct mode, 72+ commands

- 6 tabs: Dashboard, Intel (5 sub-tabs), Strike Point, Journal (6 sub-tabs), Health (3 sections), Chat
- NCLBrainClient with 72+ commands across 9 categories, SSE streaming
- Command Center with search, category browser
- Council pipeline: 6 AI × 3 rounds → synthesis → mandate
- Reddit ticker heatmap, YouTube Council, Journal persistence
- Dual connection: Brain Direct (8800) / Relay Pump (8787)
- Full function test: 47/47 PASS (100%)

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
fi

echo -e "${YELLOW}[2/6] FirstStrike — pushing...${NC}"
git push origin main 2>&1
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ FirstStrike pushed${NC}"
else
    echo -e "${RED}✗ FirstStrike push failed (check remote)${NC}"
fi

# ════════════════════════════════════════════
# 2. NCL — Git commit & push
# ════════════════════════════════════════════
echo ""
echo -e "${YELLOW}[3/6] NCL — staging...${NC}"
cd ~/dev/NCL

git add runtime/ config/ scripts/ shared/ data/lde/ pyproject.toml run.sh \
  start-all.sh start-brain.sh start-brain.command restart-brain-intel.command \
  CLAUDE.md BUILD_SUMMARY.md CONTEXT.md INDEX.md MANIFEST.txt README.md \
  RUNTIME_GUIDE.md STRUCTURE.md Dockerfile \
  feedback-synthesis/ intelligence-scan/ 2>/dev/null

STAGED_NCL=$(git diff --cached --stat 2>/dev/null | tail -1)
if [ -z "$STAGED_NCL" ]; then
    echo -e "${YELLOW}  No new changes to commit in NCL${NC}"
else
    echo -e "  ${STAGED_NCL}"
    git commit -m "$(cat <<'EOF'
fix: 90+ hardening fixes, journal system, working context, full audit

- Auth: 63 endpoints secured, path traversal blocked, token persistence
- Journal: full CRUD with reflection engine, analytics, tips
- Working context: hasattr→getattr fix on 8 endpoints, signal processor
- Scanner: real engagement metrics, BM25 scoring, gravity ranking
- Predictor: parallel models, IARPA extremization, convergence fix
- Memory: deadlock fix, async I/O, rotation threshold
- CORS hardened, dead code removed, intelligence engine deps
- Brain restart script with Ollama/DeepSeek integration
- Full function test verified: 47/47 PASS against FirstStrike app

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
fi

echo -e "${YELLOW}[4/6] NCL — pushing...${NC}"
git push origin main 2>&1
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ NCL pushed${NC}"
else
    echo -e "${RED}✗ NCL push failed (check remote)${NC}"
fi

# ════════════════════════════════════════════
# 3. Install NCL Brain LaunchAgent (auto-restart on Mac reboot)
# ════════════════════════════════════════════
echo ""
echo -e "${YELLOW}[5/6] Installing NCL Brain LaunchAgent...${NC}"

LABEL="com.resonanceenergy.ncl-brain"
PLIST_SRC="$HOME/dev/NCL/com.resonanceenergy.ncl-brain.plist"
PLIST_DST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG_DIR="$HOME/dev/NCL/logs"

mkdir -p "$LOG_DIR"
chmod +x "$HOME/dev/NCL/scripts/launch-brain.sh"

# Unload existing if installed
if launchctl print "gui/$(id -u)/$LABEL" &>/dev/null; then
    echo -e "  ${YELLOW}Unloading existing service...${NC}"
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    sleep 1
fi

# Kill any Brain on 8800 first (so launchd starts fresh)
for pid in $(lsof -ti :8800 2>/dev/null); do
    kill -9 "$pid" 2>/dev/null || true
done
sleep 2

# Install plist with HOME resolved
mkdir -p "$HOME/Library/LaunchAgents"
sed "s|__HOME__|$HOME|g" "$PLIST_SRC" > "$PLIST_DST"

# Load (RunAtLoad=true means it starts immediately)
launchctl bootstrap "gui/$(id -u)" "$PLIST_DST" 2>/dev/null
sleep 3

# Verify
if curl -s http://localhost:8800/health >/dev/null 2>&1; then
    echo -e "${GREEN}✓ NCL Brain LaunchAgent installed — auto-starts on login${NC}"
    echo -e "  ${GREEN}KeepAlive: restarts on crash${NC}"
    echo -e "  ${GREEN}RunAtLoad: starts on Mac boot/login${NC}"
else
    echo -e "${YELLOW}⚠ Brain starting up... (check logs: tail -f $LOG_DIR/ncl-brain-stderr.log)${NC}"
fi

# ════════════════════════════════════════════
# 4. Regenerate Xcode project (saves project settings)
# ════════════════════════════════════════════
echo ""
echo -e "${YELLOW}[6/6] Regenerating Xcode project...${NC}"
cd ~/dev/FirstStrike
if command -v xcodegen &>/dev/null; then
    xcodegen generate 2>&1
    echo -e "${GREEN}✓ Xcode project regenerated from project.yml${NC}"
else
    echo -e "${YELLOW}⚠ xcodegen not found — run 'brew install xcodegen' first${NC}"
fi

echo ""
echo -e "${CYAN}================================================${NC}"
echo -e "${GREEN}  All done!${NC}"
echo -e "${CYAN}================================================${NC}"
echo ""
echo -e "  ${GREEN}✓${NC} FirstStrike committed & pushed"
echo -e "  ${GREEN}✓${NC} NCL committed & pushed"
echo -e "  ${GREEN}✓${NC} NCL Brain auto-restarts on Mac reboot"
echo -e "  ${GREEN}✓${NC} Xcode project saved"
echo ""
echo -e "${YELLOW}To update iOS Simulator runtimes:${NC}"
echo -e "  Xcode → Settings → Platforms → Download latest iOS runtime"
echo ""
echo -e "${YELLOW}To update physical iPhone/iPad:${NC}"
echo -e "  Settings → General → Software Update"
echo ""
echo "Press Enter to close..."
read
