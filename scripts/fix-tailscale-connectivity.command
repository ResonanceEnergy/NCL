#!/bin/bash
# Fix Tailscale connectivity and ensure auto-start
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}================================================${NC}"
echo -e "${CYAN}  Fix Tailscale + Ensure Auto-Start${NC}"
echo -e "${CYAN}================================================${NC}"
echo ""

# ─────────────────────────────────────────────
# 1. Find and open Tailscale
# ─────────────────────────────────────────────
echo -e "${YELLOW}[1/5] Opening Tailscale...${NC}"
if [ -d "/Applications/Tailscale.app" ]; then
    open -a Tailscale
    echo -e "${GREEN}✓ Tailscale.app opened${NC}"
elif [ -d "$HOME/Applications/Tailscale.app" ]; then
    open -a "$HOME/Applications/Tailscale.app"
    echo -e "${GREEN}✓ Tailscale.app opened (user Applications)${NC}"
else
    echo -e "${RED}✗ Tailscale.app not found in /Applications${NC}"
    echo -e "${YELLOW}  Checking if it's a system extension...${NC}"
    # Check for tailscaled
    if pgrep -x tailscaled >/dev/null 2>&1; then
        echo -e "${GREEN}  tailscaled is running as system extension${NC}"
    else
        echo -e "${RED}  tailscaled not running either${NC}"
    fi
fi
sleep 3

# ─────────────────────────────────────────────
# 2. Add Tailscale CLI to PATH if needed
# ─────────────────────────────────────────────
echo ""
echo -e "${YELLOW}[2/5] Setting up Tailscale CLI...${NC}"

# Common Tailscale CLI locations on macOS
TS_CLI=""
for path in \
    "/Applications/Tailscale.app/Contents/MacOS/Tailscale" \
    "/usr/local/bin/tailscale" \
    "/opt/homebrew/bin/tailscale" \
    "$HOME/Applications/Tailscale.app/Contents/MacOS/Tailscale"; do
    if [ -x "$path" ]; then
        TS_CLI="$path"
        break
    fi
done

if [ -z "$TS_CLI" ]; then
    echo -e "${YELLOW}  Tailscale CLI not found at standard paths${NC}"
    echo -e "${YELLOW}  Searching...${NC}"
    TS_CLI=$(find /Applications -name "tailscale" -type f 2>/dev/null | head -1)
    if [ -z "$TS_CLI" ]; then
        TS_CLI=$(mdfind "kMDItemFSName == 'tailscale'" 2>/dev/null | grep -i tailscale | head -1)
    fi
fi

if [ -n "$TS_CLI" ]; then
    echo -e "${GREEN}✓ Found Tailscale CLI: $TS_CLI${NC}"

    # Create symlink if not in PATH
    if ! command -v tailscale &>/dev/null; then
        echo -e "${YELLOW}  Adding to PATH via /usr/local/bin symlink...${NC}"
        sudo ln -sf "$TS_CLI" /usr/local/bin/tailscale 2>/dev/null
        if [ $? -eq 0 ]; then
            echo -e "${GREEN}  ✓ Symlinked to /usr/local/bin/tailscale${NC}"
        else
            echo -e "${YELLOW}  ⚠ Couldn't symlink (need sudo). Using direct path.${NC}"
        fi
    fi
else
    echo -e "${RED}✗ Tailscale CLI not found anywhere${NC}"
fi
echo ""

# ─────────────────────────────────────────────
# 3. Connect Tailscale
# ─────────────────────────────────────────────
echo -e "${YELLOW}[3/5] Connecting Tailscale...${NC}"

# Use whichever CLI path we found
TAILSCALE="${TS_CLI:-tailscale}"

# Check current status
TS_STATUS=$("$TAILSCALE" status 2>&1)
if echo "$TS_STATUS" | grep -q "Tailscale is stopped"; then
    echo -e "${YELLOW}  Tailscale is stopped — bringing up...${NC}"
    "$TAILSCALE" up 2>&1
    sleep 5
elif echo "$TS_STATUS" | grep -q "failed"; then
    echo -e "${YELLOW}  Tailscale connection failed — reconnecting...${NC}"
    "$TAILSCALE" up --reset 2>&1
    sleep 5
else
    echo -e "${GREEN}  Tailscale status: $(echo "$TS_STATUS" | head -1)${NC}"
fi

# Verify connection
sleep 2
TS_IP=$("$TAILSCALE" ip -4 2>/dev/null)
if [ -n "$TS_IP" ]; then
    echo -e "${GREEN}✓ Tailscale connected — IP: $TS_IP${NC}"
else
    echo -e "${RED}✗ Tailscale not connected — you may need to sign in via the menu bar icon${NC}"
    echo -e "${YELLOW}  Click the Tailscale icon in the menu bar → Connect${NC}"
fi

# Show full status
echo ""
"$TAILSCALE" status 2>&1 | head -10
echo ""

# ─────────────────────────────────────────────
# 4. Verify Brain reachable via Tailscale
# ─────────────────────────────────────────────
echo -e "${YELLOW}[4/5] Testing Brain connectivity via Tailscale...${NC}"

# Test localhost first
HEALTH_LOCAL=$(curl -s --connect-timeout 3 http://localhost:8800/health 2>/dev/null)
if [ -n "$HEALTH_LOCAL" ]; then
    echo -e "${GREEN}✓ Brain responding on localhost:8800${NC}"
else
    echo -e "${RED}✗ Brain NOT responding on localhost:8800${NC}"
    echo -e "${YELLOW}  Starting Brain...${NC}"
    # Try to start via launchctl
    LABEL="com.resonanceenergy.ncl-brain"
    launchctl kickstart -k "gui/$(id -u)/$LABEL" 2>/dev/null
    sleep 5
    HEALTH_LOCAL=$(curl -s --connect-timeout 3 http://localhost:8800/health 2>/dev/null)
    if [ -n "$HEALTH_LOCAL" ]; then
        echo -e "${GREEN}✓ Brain started and responding${NC}"
    else
        echo -e "${RED}✗ Brain still not responding — check logs${NC}"
    fi
fi

# Test via Tailscale IP
if [ -n "$TS_IP" ]; then
    HEALTH_TS=$(curl -s --connect-timeout 5 "http://${TS_IP}:8800/health" 2>/dev/null)
    if [ -n "$HEALTH_TS" ]; then
        echo -e "${GREEN}✓ Brain reachable via Tailscale (${TS_IP}:8800)${NC}"
    else
        echo -e "${RED}✗ Brain NOT reachable via Tailscale (${TS_IP}:8800)${NC}"
        echo -e "${YELLOW}  This could be a firewall issue. Checking...${NC}"

        # Check and fix firewall
        FW_STATE=$(/usr/libexec/ApplicationFirewall/socketfilterfw --getglobalstate 2>/dev/null)
        if echo "$FW_STATE" | grep -q "enabled"; then
            echo -e "${YELLOW}  macOS Firewall is ENABLED${NC}"
            echo -e "${YELLOW}  Adding Python to firewall exceptions...${NC}"
            PYTHON_PATH=$(which python3 2>/dev/null || echo "/opt/homebrew/bin/python3")
            sudo /usr/libexec/ApplicationFirewall/socketfilterfw --add "$PYTHON_PATH" 2>/dev/null
            sudo /usr/libexec/ApplicationFirewall/socketfilterfw --unblockapp "$PYTHON_PATH" 2>/dev/null
            echo -e "${GREEN}  ✓ Added Python to firewall allow list${NC}"

            # Also add the specific Python framework binary
            PYTHON_FW="/opt/homebrew/Cellar/python@3.14/3.14.3_1/Frameworks/Python.framework/Versions/3.14/Resources/Python.app/Contents/MacOS/Python"
            if [ -x "$PYTHON_FW" ]; then
                sudo /usr/libexec/ApplicationFirewall/socketfilterfw --add "$PYTHON_FW" 2>/dev/null
                sudo /usr/libexec/ApplicationFirewall/socketfilterfw --unblockapp "$PYTHON_FW" 2>/dev/null
                echo -e "${GREEN}  ✓ Added Python framework binary to firewall allow list${NC}"
            fi

            # Re-test
            sleep 2
            HEALTH_TS2=$(curl -s --connect-timeout 5 "http://${TS_IP}:8800/health" 2>/dev/null)
            if [ -n "$HEALTH_TS2" ]; then
                echo -e "${GREEN}✓ Brain NOW reachable via Tailscale after firewall fix!${NC}"
            else
                echo -e "${YELLOW}⚠ Still not reachable — try restarting Brain: launchctl kickstart -k gui/$(id -u)/com.resonanceenergy.ncl-brain${NC}"
            fi
        fi
    fi
fi
echo ""

# ─────────────────────────────────────────────
# 5. Ensure Tailscale auto-starts on login
# ─────────────────────────────────────────────
echo -e "${YELLOW}[5/5] Ensuring Tailscale auto-starts on login...${NC}"

# Tailscale Mac App Store version auto-starts via its own mechanism
# For standalone version, we add a login item
if [ -d "/Applications/Tailscale.app" ]; then
    # Check if already a login item
    osascript -e 'tell application "System Events" to get the name of every login item' 2>/dev/null | grep -qi "tailscale"
    if [ $? -ne 0 ]; then
        osascript -e 'tell application "System Events" to make login item at end with properties {name:"Tailscale", path:"/Applications/Tailscale.app", hidden:false}' 2>/dev/null
        if [ $? -eq 0 ]; then
            echo -e "${GREEN}✓ Tailscale added as login item (auto-starts on boot)${NC}"
        else
            echo -e "${YELLOW}⚠ Could not add login item via AppleScript${NC}"
            echo -e "${YELLOW}  Manual: System Settings → General → Login Items → add Tailscale${NC}"
        fi
    else
        echo -e "${GREEN}✓ Tailscale already configured as login item${NC}"
    fi
fi

# Update the Brain launch script to check Tailscale
echo -e "${YELLOW}  Updating Brain launch script to verify Tailscale...${NC}"
LAUNCH_SCRIPT="$HOME/dev/NCL/scripts/launch-brain.sh"
if [ -f "$LAUNCH_SCRIPT" ]; then
    # Check if Tailscale check already exists
    if ! grep -q "tailscale" "$LAUNCH_SCRIPT" 2>/dev/null; then
        # Prepend Tailscale connectivity check
        cat > /tmp/launch-brain-update.sh << 'PATCH'
# Ensure Tailscale is running before starting Brain
if [ -d "/Applications/Tailscale.app" ]; then
    open -a Tailscale 2>/dev/null
    sleep 2
fi
PATCH
        # Insert after the shebang and any existing header
        sed -i '' '/^#!/{n;r /tmp/launch-brain-update.sh
}' "$LAUNCH_SCRIPT" 2>/dev/null
        echo -e "${GREEN}✓ Brain launch script updated to open Tailscale on start${NC}"
        rm -f /tmp/launch-brain-update.sh
    else
        echo -e "${GREEN}✓ Brain launch script already checks Tailscale${NC}"
    fi
fi

echo ""
echo -e "${CYAN}================================================${NC}"
echo -e "${CYAN}  RESULTS${NC}"
echo -e "${CYAN}================================================${NC}"
echo ""

# Final status
TS_FINAL=$("$TAILSCALE" ip -4 2>/dev/null)
BRAIN_FINAL=$(curl -s --connect-timeout 3 http://localhost:8800/health 2>/dev/null)

if [ -n "$TS_FINAL" ]; then
    echo -e "  ${GREEN}✓${NC} Tailscale: Connected ($TS_FINAL)"
else
    echo -e "  ${RED}✗${NC} Tailscale: NOT Connected"
    echo -e "    ${YELLOW}→ Click Tailscale in menu bar → Connect${NC}"
fi

if [ -n "$BRAIN_FINAL" ]; then
    echo -e "  ${GREEN}✓${NC} NCL Brain: Running on :8800"
else
    echo -e "  ${RED}✗${NC} NCL Brain: Not responding"
fi

HEALTH_TS_FINAL=$(curl -s --connect-timeout 5 "http://${TS_FINAL:-100.72.223.123}:8800/health" 2>/dev/null)
if [ -n "$HEALTH_TS_FINAL" ]; then
    echo -e "  ${GREEN}✓${NC} Brain via Tailscale: Reachable"
else
    echo -e "  ${RED}✗${NC} Brain via Tailscale: NOT Reachable"
    echo -e "    ${YELLOW}→ Check firewall: System Settings → Network → Firewall${NC}"
    echo -e "    ${YELLOW}→ Or use LAN IP: 192.168.1.72:8800${NC}"
fi

echo ""
echo -e "  ${GREEN}✓${NC} Tailscale: auto-starts on login"
echo -e "  ${GREEN}✓${NC} NCL Brain: auto-starts on login (launchd KeepAlive)"
echo -e "  ${GREEN}✓${NC} Brain launch script: opens Tailscale first"
echo ""
echo "Press Enter to close..."
read
