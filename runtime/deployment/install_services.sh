#!/bin/bash
# NCL launchd Service Installation Script
# Install and start all 4 NCL brain pipeline services

set -e

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "=========================================="
echo "NCL launchd Service Installation"
echo "=========================================="
echo ""

# Check for python3
echo -n "Checking for python3... "
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}FAIL${NC}"
    echo "python3 not found. Install with: brew install python3"
    exit 1
fi
echo -e "${GREEN}OK${NC}"

# Define paths
NCL_ROOT=~/dev/NCL
LAUNCH_AGENTS=~/Library/LaunchAgents

# Check NCL directory exists
echo -n "Checking NCL directory at $NCL_ROOT... "
if [ ! -d "$NCL_ROOT" ]; then
    echo -e "${RED}FAIL${NC}"
    echo "NCL directory not found at $NCL_ROOT"
    exit 1
fi
echo -e "${GREEN}OK${NC}"

# Create LaunchAgents directory if needed
echo -n "Creating LaunchAgents directory... "
mkdir -p "$LAUNCH_AGENTS"
echo -e "${GREEN}OK${NC}"
echo ""

# Define services
declare -a SERVICES=(
    "com.resonanceenergy.ncl-brain:NCL Brain API"
    "com.resonanceenergy.ncl-watcher:Pump Watcher"
    "com.resonanceenergy.ncl-orchestrator:Strike Point Orchestrator"
    "com.resonanceenergy.ncl-councils:Council Sweep"
)

# Define plist paths
declare -A PLIST_PATHS=(
    ["com.resonanceenergy.ncl-brain"]="$NCL_ROOT/com.resonanceenergy.ncl-brain.plist"
    ["com.resonanceenergy.ncl-watcher"]="$NCL_ROOT/com.resonanceenergy.ncl-watcher.plist"
    ["com.resonanceenergy.ncl-orchestrator"]="$NCL_ROOT/config/com.resonanceenergy.ncl-orchestrator.plist"
    ["com.resonanceenergy.ncl-councils"]="$NCL_ROOT/config/com.resonanceenergy.ncl-councils.plist"
)

# Install each service
INSTALLED=0
FAILED=0

for SERVICE in "${SERVICES[@]}"; do
    LABEL="${SERVICE%%:*}"
    DESCRIPTION="${SERVICE##*:}"
    PLIST="${PLIST_PATHS[$LABEL]}"

    echo -n "Installing $DESCRIPTION ($LABEL)... "

    if [ ! -f "$PLIST" ]; then
        echo -e "${RED}SKIP${NC} (plist not found at $PLIST)"
        FAILED=$((FAILED + 1))
        continue
    fi

    cp "$PLIST" "$LAUNCH_AGENTS/$LABEL.plist"
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    if launchctl bootstrap "gui/$(id -u)" "$LAUNCH_AGENTS/$LABEL.plist" 2>/dev/null; then
        echo -e "${GREEN}OK${NC}"
        INSTALLED=$((INSTALLED + 1))
    else
        # In some cases, service may be installed but not loaded. That's OK.
        echo -e "${YELLOW}LOAD${NC} (plist copied, bootstrap skipped or already loaded)"
        INSTALLED=$((INSTALLED + 1))
    fi
done

echo ""
echo "=========================================="
echo "Installation Summary"
echo "=========================================="

echo "Checking service status..."
echo ""

# Verify services are loaded
for SERVICE in "${SERVICES[@]}"; do
    LABEL="${SERVICE%%:*}"
    DESCRIPTION="${SERVICE##*:}"

    echo -n "  $DESCRIPTION: "
    if launchctl list | grep -q "$LABEL"; then
        echo -e "${GREEN}Loaded${NC}"
    else
        echo -e "${YELLOW}Not Loaded${NC}"
    fi
done

echo ""
echo "=========================================="
echo "Service Details:"
echo "=========================================="
echo "View logs:"
echo "  tail -f ~/dev/NCL/logs/ncl-brain-stdout.log"
echo "  tail -f ~/dev/NCL/logs/pump-watcher-stdout.log"
echo ""
echo "Service control:"
echo "  launchctl list | grep com.resonanceenergy"
echo "  launchctl start com.resonanceenergy.ncl-brain"
echo "  launchctl stop com.resonanceenergy.ncl-brain"
echo ""
echo "Uninstall:"
echo "  launchctl bootout gui/\$(id -u)/com.resonanceenergy.ncl-brain"
echo ""
echo -e "${GREEN}Installation complete!${NC}"
