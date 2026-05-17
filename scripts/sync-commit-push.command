#!/bin/bash
# Sync, commit, and push both FirstStrike and NCL repos
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}============================================${NC}"
echo -e "${CYAN}  Sync Commit & Push — FirstStrike + NCL${NC}"
echo -e "${CYAN}============================================${NC}"
echo ""

# ── FirstStrike ──
echo -e "${YELLOW}[1/4] Committing FirstStrike...${NC}"
cd ~/dev/FirstStrike

git add Sources/ CLAUDE.md FUNCTION_TEST_SCORECARD.md project.yml apply-fixes.sh \
  .github/copilot-instructions.md build.command rebuild.command \
  regen-project.command regenerate-xcode.command Sources/Info.plist

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

echo -e "${YELLOW}[2/4] Pushing FirstStrike...${NC}"
git push origin main
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ FirstStrike pushed${NC}"
else
    echo -e "${RED}✗ FirstStrike push failed${NC}"
fi

# ── NCL ──
echo ""
echo -e "${YELLOW}[3/4] Committing NCL...${NC}"
cd ~/dev/NCL

git add runtime/ config/ scripts/ shared/ data/lde/ pyproject.toml run.sh \
  start-all.sh start-brain.sh start-brain.command restart-brain-intel.command \
  CLAUDE.md BUILD_SUMMARY.md CONTEXT.md INDEX.md MANIFEST.txt README.md \
  RUNTIME_GUIDE.md STRUCTURE.md Dockerfile \
  feedback-synthesis/ intelligence-scan/

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

echo -e "${YELLOW}[4/4] Pushing NCL...${NC}"
git push origin main
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ NCL pushed${NC}"
else
    echo -e "${RED}✗ NCL push failed${NC}"
fi

echo ""
echo -e "${CYAN}============================================${NC}"
echo -e "${GREEN}  Sync complete${NC}"
echo -e "${CYAN}============================================${NC}"
echo ""
echo "Press Enter to close..."
read
