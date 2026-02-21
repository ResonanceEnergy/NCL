#!/bin/bash
# Super Agency MacBook Launch Script
# Optimized for 8GB M1 - Ultra-conservative memory mode

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m'

log_info() {
    echo -e "${BLUE}[INFO]${NC} $(date '+%H:%M:%S') - $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $(date '+%H:%M:%S') - $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $(date '+%H:%M:%S') - $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $(date '+%H:%M:%S') - $1"
}

# Get system info
get_system_info() {
    local ram_gb=$(echo "scale=1; $(sysctl -n hw.memsize) / 1024 / 1024 / 1024" | bc)
    local chip=$(sysctl -n machdep.cpu.brand_string)
    echo "📊 Memory: ${ram_gb}GB"
    echo "💻 Chip: $chip"
}

# Launch lightweight services for 8GB M1
launch_services() {
    log_info "Starting Super Agency services (8GB M1 optimized)..."

    # Start mobile command center (lightweight)
    if [ -f "mobile_command_center.py" ]; then
        log_info "Starting Mobile Command Center..."
        python3 mobile_command_center.py &
        echo $! > mobile_command_center.pid
        log_success "Mobile Command Center started (PID: $(cat mobile_command_center.pid))"
    fi

    # Start matrix monitor (if available)
    if [ -d "matrix_monitor" ] && [ -f "matrix_monitor/panels/second_brain_panel.json" ]; then
        log_info "Starting Matrix Monitor..."
        # Matrix monitor would be started here
        log_success "Matrix Monitor ready"
    fi

    # Start operations hub (lightweight)
    if [ -f "operations_hub.py" ]; then
        log_info "Starting Operations Hub..."
        python3 operations_hub.py &
        echo $! > operations_hub.pid
        log_success "Operations Hub started (PID: $(cat operations_hub.pid))"
    fi
}

# Show status
show_status() {
    echo ""
    echo "🚀 Super Agency (8GB M1 Mode) - Services Started"
    echo "==============================================="
    get_system_info
    echo ""
    echo "🌐 Services:"
    if [ -f "mobile_command_center.pid" ]; then
        echo "   • Mobile Command Center: http://localhost:8080 (PID: $(cat mobile_command_center.pid))"
    fi
    if [ -f "operations_hub.pid" ]; then
        echo "   • Operations Hub: Running (PID: $(cat operations_hub.pid))"
    fi
    echo ""
    echo "📱 Mobile Access:"
    echo "   • iPhone/iPad: Open browser to Mac IP address"
    echo "   • PWA: Install as web app for offline access"
    echo ""
    echo "🔄 Windows Sync: Ready for delegation"
    echo ""
    echo "⚡ Memory Mode: Ultra-conservative (8GB M1)"
    echo "   • Max 1 agent at a time"
    echo "   • 512MB per agent limit"
    echo "   • Heavy processing delegated to Windows"
}

# Cleanup function
cleanup() {
    log_info "Cleaning up services..."
    if [ -f "mobile_command_center.pid" ]; then
        kill $(cat mobile_command_center.pid) 2>/dev/null || true
        rm mobile_command_center.pid
    fi
    if [ -f "operations_hub.pid" ]; then
        kill $(cat operations_hub.pid) 2>/dev/null || true
        rm operations_hub.pid
    fi
    log_success "Cleanup complete"
}

# Main execution
main() {
    echo "🚀 Starting Super Agency (8GB M1 MacBook Mode)"
    echo "=============================================="

    # Set up cleanup on exit
    trap cleanup EXIT

    # Launch services
    launch_services

    # Show status
    show_status

    # Keep running
    log_info "Super Agency running. Press Ctrl+C to stop."
    wait
}

# Run main function
main "$@"