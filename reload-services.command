#!/bin/bash
# ============================================================
# NCL Services Reloader
# Reloads ncl-brain and ncl-watcher launchd agents from the
# updated plists at ~/dev/NCL after the BRL→NCL repo move.
#
# Double-click this file (Finder) OR run from terminal.
# Requires: macOS, plists living next to this script.
# ============================================================

set -e

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

# Always operate from the script's own directory so paths resolve
# regardless of where the .command file is invoked from.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

LAUNCH_DIR="$HOME/Library/LaunchAgents"
UID_NUM="$(id -u)"

BRAIN_PLIST_NAME="com.resonanceenergy.ncl-brain.plist"
WATCHER_PLIST_NAME="com.resonanceenergy.ncl-watcher.plist"
BRAIN_LABEL="com.resonanceenergy.ncl-brain"
WATCHER_LABEL="com.resonanceenergy.ncl-watcher"

echo -e "${CYAN}============================================${NC}"
echo -e "${CYAN}  NCL Services Reloader${NC}"
echo -e "${CYAN}  Source: ${SCRIPT_DIR}${NC}"
echo -e "${CYAN}============================================${NC}"
echo ""

# -------- pre-flight checks --------
mkdir -p "$LAUNCH_DIR"

for plist in "$BRAIN_PLIST_NAME" "$WATCHER_PLIST_NAME"; do
    if [[ ! -f "$SCRIPT_DIR/$plist" ]]; then
        echo -e "${RED}  ✗ Missing source plist: $SCRIPT_DIR/$plist${NC}"
        echo -e "${RED}    Aborting. Make sure both plists live next to this script.${NC}"
        exit 1
    fi
done
echo -e "${GREEN}  ✓ Both source plists present${NC}"

# Sanity check: ensure plists reference the new path, not the old one.
if grep -q "/Projects/NCL" "$SCRIPT_DIR/$BRAIN_PLIST_NAME" "$SCRIPT_DIR/$WATCHER_PLIST_NAME" 2>/dev/null; then
    echo -e "${YELLOW}  ! Warning: plists still reference /Projects/NCL — expected /dev/NCL.${NC}"
    echo -e "${YELLOW}    Continuing, but you may want to fix the paths first.${NC}"
fi

# -------- kill stragglers --------
echo ""
echo -e "${YELLOW}Stopping any old processes...${NC}"
pkill -f "runtime.api.routes" 2>/dev/null && echo -e "${GREEN}  ✓ Old brain killed${NC}" || echo -e "  (no old brain running)"
pkill -f "pump_watcher" 2>/dev/null && echo -e "${GREEN}  ✓ Old watcher killed${NC}" || echo -e "  (no old watcher running)"
sleep 1

# -------- reload helper --------
reload_agent() {
    local plist_name="$1"
    local label="$2"
    local src="$SCRIPT_DIR/$plist_name"
    local dst="$LAUNCH_DIR/$plist_name"

    echo ""
    echo -e "${CYAN}>> $label${NC}"

    # bootout (modern equivalent of unload). Tolerates "not loaded" state.
    if launchctl bootout "gui/$UID_NUM/$label" 2>/dev/null; then
        echo -e "${GREEN}  ✓ Booted out existing agent${NC}"
    else
        echo -e "  (not currently loaded, that's fine)"
    fi

    # copy fresh plist into LaunchAgents
    cp "$src" "$dst"
    echo -e "${GREEN}  ✓ Copied $plist_name -> $LAUNCH_DIR/${NC}"

    # bootstrap (modern equivalent of load).
    if launchctl bootstrap "gui/$UID_NUM" "$dst"; then
        echo -e "${GREEN}  ✓ Bootstrapped $label${NC}"
    else
        echo -e "${RED}  ✗ launchctl bootstrap failed for $label${NC}"
        echo -e "${RED}    Inspect: launchctl print gui/$UID_NUM/$label${NC}"
        return 1
    fi

    # kickstart so it actually starts running now (don't wait for trigger)
    launchctl kickstart -k "gui/$UID_NUM/$label" 2>/dev/null && \
        echo -e "${GREEN}  ✓ Kickstarted $label${NC}" || \
        echo -e "${YELLOW}  ! Could not kickstart (may already be running)${NC}"
}

# -------- reload both --------
reload_agent "$BRAIN_PLIST_NAME"   "$BRAIN_LABEL"
reload_agent "$WATCHER_PLIST_NAME" "$WATCHER_LABEL"

# -------- verify --------
echo ""
echo -e "${CYAN}============================================${NC}"
echo -e "${CYAN}  Verifying...${NC}"
echo -e "${CYAN}============================================${NC}"

sleep 2

for label in "$BRAIN_LABEL" "$WATCHER_LABEL"; do
    if launchctl print "gui/$UID_NUM/$label" >/dev/null 2>&1; then
        # Pull state + last exit + pid for a quick health snapshot.
        info=$(launchctl print "gui/$UID_NUM/$label" 2>/dev/null | grep -E "^\s*(state|pid|last exit code) " | head -3)
        echo -e "${GREEN}  ✓ $label registered${NC}"
        echo "$info" | sed 's/^/      /'
    else
        echo -e "${RED}  ✗ $label NOT registered${NC}"
    fi
done

# Hit the brain endpoint to confirm it's actually serving.
echo ""
echo -e "${YELLOW}Pinging brain at http://127.0.0.1:8800/health ...${NC}"
sleep 3
if curl -fsS --max-time 5 http://127.0.0.1:8800/health >/dev/null 2>&1; then
    echo -e "${GREEN}  ✓ NCL brain is responding on :8800${NC}"
else
    echo -e "${YELLOW}  ! Brain not yet responding on :8800${NC}"
    echo -e "${YELLOW}    Tail logs: tail -f $SCRIPT_DIR/logs/ncl-brain.log${NC}"
fi

echo ""
echo -e "${GREEN}Done.${NC}"
echo ""
echo -e "Useful follow-ups:"
echo -e "  Status:    launchctl print gui/$UID_NUM/$BRAIN_LABEL"
echo -e "  Logs:      tail -f $SCRIPT_DIR/logs/ncl-brain.log"
echo -e "  Stop:      launchctl bootout gui/$UID_NUM/$BRAIN_LABEL"
echo ""
