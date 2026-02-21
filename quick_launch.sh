#!/bin/bash
# Super Agency Quick Launch
# One-command deployment for MacBook + Windows

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m'

log_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

log_error() {
    echo -e "${RED}❌ $1${NC}"
}

log_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

log_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

# Get local IP
get_local_ip() {
    ifconfig | grep "inet " | grep -v 127.0.0.1 | awk '{print $2}' | head -1
}

# Check if service is running
check_service() {
    local port=$1
    local name=$2
    if lsof -Pi :$port -sTCP:LISTEN -t >/dev/null 2>&1; then
        log_success "$name running on port $port"
        return 0
    else
        log_error "$name not running on port $port"
        return 1
    fi
}

# Main launch function
launch_system() {
    echo "🚀 SUPER AGENCY QUICK LAUNCH"
    echo "============================"

    local mac_ip=$(get_local_ip)
    log_info "Mac IP: $mac_ip"

    # Phase 1: Setup
    log_info "Phase 1: System Setup"
    if [ ! -f "config/8gb_m1_macbook.json" ]; then
        log_info "Running initial setup..."
        ./macbook_8gb_m1_setup.sh
    else
        log_success "Setup already complete"
    fi

    # Phase 2: Test
    log_info "Phase 2: System Test"
    if ./test_8gb_m1_setup.sh | grep -q "❌"; then
        log_error "System test failed. Check output above."
        exit 1
    else
        log_success "All system tests passed"
    fi

    # Phase 3: Launch Services
    log_info "Phase 3: Launching Services"
    ./macbook_launch.sh &
    local launch_pid=$!

    # Wait for services to start
    log_info "Waiting for services to initialize..."
    sleep 5

    # Phase 4: Verify Services
    log_info "Phase 4: Verifying Services"
    local services_up=0
    local total_services=3

    check_service 8080 "Mobile Command Center" && ((services_up++))
    check_service 5000 "Operations Interface" && ((services_up++))
    check_service 3000 "Matrix Monitor" && ((services_up++))

    if [ $services_up -eq $total_services ]; then
        log_success "All $total_services services running"
    else
        log_warning "$services_up/$total_services services running"
    fi

    # Phase 5: Windows Instructions
    log_info "Phase 5: Windows Setup Instructions"
    echo ""
    echo "🔄 ON WINDOWS MACHINE, RUN:"
    echo "cd C:\\path\\to\\Super-Agency"
    echo ".\\sync_to_windows.ps1 -MacIP $mac_ip -StartServices"
    echo ""

    # Phase 6: Mobile Access
    log_info "Phase 6: Mobile Access"
    echo ""
    echo "📱 MOBILE ACCESS URLS:"
    echo "Local:    http://localhost:8080"
    echo "Network:  http://$mac_ip:8080"
    echo "Operations: http://$mac_ip:5000"
    echo "Matrix:   http://$mac_ip:3000"
    echo ""
    echo "📲 PWA INSTALLATION:"
    echo "1. Open URL in mobile browser"
    echo "2. Tap share button → 'Add to Home Screen'"
    echo "3. Name: 'Super Agency Command'"
    echo ""

    # Phase 7: Status Monitoring
    log_info "Phase 7: System Status"
    echo ""
    echo "🔍 MONITOR COMMANDS:"
    echo "Check status:     ./check_status.sh"
    echo "View logs:        tail -f logs/*.log"
    echo "Memory usage:     top -l 1 | grep PhysMem"
    echo "Stop services:    pkill -f python"
    echo ""

    log_success "Super Agency launch complete!"
    log_info "Press Ctrl+C to stop all services"

    # Keep running and show status
    while true; do
        echo ""
        log_info "System Status (updates every 30s):"
        check_service 8080 "Mobile Center"
        check_service 5000 "Operations"
        check_service 3000 "Matrix"
        echo "Memory: $(echo "scale=1; $(ps aux | awk 'BEGIN {sum=0} {sum += $6} END {print sum/1024/1024}')MB" | bc)GB used"
        sleep 30
    done
}

# Quick status check
check_status() {
    echo "📊 SUPER AGENCY STATUS CHECK"
    echo "============================"

    local mac_ip=$(get_local_ip)
    log_info "Mac IP: $mac_ip"

    echo ""
    log_info "MacBook Services:"
    check_service 8080 "Mobile Command Center"
    check_service 5000 "Operations Interface"
    check_service 3000 "Matrix Monitor"

    echo ""
    log_info "System Resources:"
    echo "Memory: $(echo "scale=1; $(sysctl -n hw.memsize) / 1024 / 1024 / 1024" | bc)GB total"
    echo "Used: $(echo "scale=1; $(ps aux | awk 'BEGIN {sum=0} {sum += $6} END {print sum/1024/1024}')MB" | bc)GB by Python"

    echo ""
    log_info "Windows Status (run on Windows):"
    echo ".\\sync_to_windows.ps1 -Status"
}

# Help
show_help() {
    echo "Super Agency Quick Launch"
    echo "Usage: $0 [command]"
    echo ""
    echo "Commands:"
    echo "  launch    - Full system launch (default)"
    echo "  status    - Check system status"
    echo "  help      - Show this help"
    echo ""
    echo "Examples:"
    echo "  $0              # Launch everything"
    echo "  $0 status       # Check current status"
}

# Main
case "${1:-launch}" in
    "launch")
        launch_system
        ;;
    "status")
        check_status
        ;;
    "help"|"-h"|"--help")
        show_help
        ;;
    *)
        log_error "Unknown command: $1"
        show_help
        exit 1
        ;;
esac</content>
<parameter name="filePath">c:/Users/gripa/OneDrive - Grip and Ripp/Super Agency/Super-Agency/quick_launch.sh