#!/bin/bash
# 🚀 Super Agency macOS Coordination Hub Launcher
# Lightweight I/O coordination for distributed architecture
# February 21, 2026

set -e

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PATH="$SCRIPT_DIR/.venv"
LOG_FILE="$SCRIPT_DIR/mac_coordination_$(date +%Y%m%d_%H%M%S).log"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging function
log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') $1" | tee -a "$LOG_FILE"
}

# Check if port is available
check_port() {
    local port=$1
    if lsof -Pi :$port -sTCP:LISTEN -t >/dev/null ; then
        log "❌ Port $port is already in use"
        return 1
    else
        log "✅ Port $port is available"
        return 0
    fi
}

# Start service in background
start_service() {
    local name=$1
    local command=$2
    local port=$3

    log "🚀 Starting $name on port $port..."

    # Check if port is available
    if ! check_port $port; then
        log "⚠️  $name port $port in use, attempting to free it..."
        lsof -ti :$port | xargs kill -9 2>/dev/null || true
        sleep 2
    fi

    # Start service
    eval "$command" >> "$LOG_FILE" 2>&1 &
    local pid=$!

    # Wait for service to start
    local attempts=0
    while [ $attempts -lt 10 ]; do
        if lsof -Pi :$port -sTCP:LISTEN -t >/dev/null 2>/dev/null; then
            log "✅ $name started successfully (PID: $pid)"
            echo $pid > ".$name.pid"
            return 0
        fi
        sleep 1
        attempts=$((attempts + 1))
    done

    log "❌ Failed to start $name"
    return 1
}

# Main coordination launcher
main() {
    log "🎯 Super Agency macOS Coordination Hub Launcher"
    log "📍 Role: I/O Coordination (Lightweight)"
    log "📊 Target: <4GB RAM, <30% CPU"

    # Activate virtual environment if it exists
    if [ -d "$VENV_PATH" ]; then
        log "🐍 Activating virtual environment..."
        source "$VENV_PATH/bin/activate"
    fi

    # Get local IP
    LOCAL_IP=$(ifconfig | grep "inet " | grep -v 127.0.0.1 | head -1 | awk '{print $2}')
    log "🌐 Local IP: $LOCAL_IP"

    # Start coordination services (lightweight)
    log "🏗️  Starting coordination services..."

    # 1. Mobile Command Center (Primary I/O coordination)
    if start_service "mobile_command_center" "python3 mobile_command_center_simple.py" 8081; then
        log "📱 Mobile Command Center: http://$LOCAL_IP:8081"
        log "   ├── Pocket Pulsar (iPhone): http://$LOCAL_IP:8081/iphone"
        log "   ├── Tablet Titan (iPad): http://$LOCAL_IP:8081/ipad"
        log "   └── Desktop Dashboard: http://$LOCAL_IP:8081/desktop"
    fi

    # 2. Operations API (Conversational interface)
    if start_service "operations_api" "python3 operations_api.py" 5001; then
        log "⚙️  Operations API: http://$LOCAL_IP:5001"
    fi

    # 3. Matrix Monitor (Real-time visualization)
    if start_service "matrix_monitor" "python3 matrix_maximizer.py" 3000; then
        log "🧠 Matrix Monitor: http://$LOCAL_IP:3000"
    fi

    # Wait for services to stabilize
    sleep 3

    # Check system resources
    log "📊 System Resources:"
    log "$(top -l 1 | head -5 | tail -3)"

    # Display service status
    log "🔍 Service Status:"
    ps aux | grep -E "(matrix_maximizer|operations_api|mobile_command_center)" | grep -v grep | while read line; do
        log "   $line"
    done

    # Display access information
    echo ""
    echo "🎯 Super Agency Coordination Hub Active!"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "📍 Local IP: $LOCAL_IP"
    echo "🏗️  Role: I/O Coordination Hub"
    echo ""
    echo "📱 Mobile Access:"
    echo "   • Pocket Pulsar (iPhone): http://$LOCAL_IP:8081/iphone"
    echo "   • Tablet Titan (iPad): http://$LOCAL_IP:8081/ipad"
    echo "   • Desktop Dashboard: http://$LOCAL_IP:8081/desktop"
    echo ""
    echo "⚙️  APIs:"
    echo "   • Operations API: http://$LOCAL_IP:5001"
    echo "   • Matrix Monitor: http://$LOCAL_IP:3000"
    echo ""
    echo "🔄 Windows Processing Node:"
    echo "   Run: .\sync_to_windows.ps1 -MacIP $LOCAL_IP -StartServices"
    echo ""
    echo "📊 Logs: $LOG_FILE"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    # Keep running and monitor
    log "👀 Monitoring services... (Ctrl+C to stop)"
    while true; do
        sleep 30

        # Check if services are still running
        if ! pgrep -f "mobile_command_center_simple.py" > /dev/null; then
            log "⚠️  Mobile Command Center stopped, restarting..."
            start_service "mobile_command_center" "python3 mobile_command_center_simple.py" 8081
        fi

        if ! pgrep -f "operations_api.py" > /dev/null; then
            log "⚠️  Operations API stopped, restarting..."
            start_service "operations_api" "python3 operations_api.py" 5001
        fi

        if ! pgrep -f "matrix_maximizer.py" > /dev/null; then
            log "⚠️  Matrix Monitor stopped, restarting..."
            start_service "matrix_monitor" "python3 matrix_maximizer.py" 3000
        fi
    done
}

# Cleanup function
cleanup() {
    log "🧹 Cleaning up coordination services..."
    pkill -f "mobile_command_center_simple.py" || true
    pkill -f "operations_api.py" || true
    pkill -f "matrix_maximizer.py" || true
    rm -f .*.pid
    log "✅ Cleanup complete"
    exit 0
}

# Set up signal handlers
trap cleanup SIGINT SIGTERM

# Run main function
main "$@"
