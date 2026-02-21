#!/bin/bash
# Super Agency 16GB MacBook Setup
# Optimized for 16GB RAM - Operations focused

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
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check RAM
check_ram() {
    local ram_gb=$(echo "scale=1; $(sysctl -n hw.memsize) / 1024 / 1024 / 1024" | bc)
    echo "$ram_gb"
}

# Memory-optimized agent deployment
setup_16gb_config() {
    log_info "Setting up 16GB MacBook configuration..."

    # Create memory-optimized config
    cat > config/16gb_macbook.json << EOF
{
    "memory_optimization": {
        "max_agents": 3,
        "agent_memory_limit": "2GB",
        "cpu_cores_limit": 6,
        "background_priority": "low",
        "swap_usage": "conservative"
    },
    "services": {
        "matrix_monitor": {
            "enabled": true,
            "memory_limit": "1GB",
            "port": 3000
        },
        "operations_interface": {
            "enabled": true,
            "memory_limit": "1GB",
            "port": 5000
        },
        "mobile_command_center": {
            "enabled": true,
            "memory_limit": "512MB",
            "port": 8080
        },
        "aac_system": {
            "enabled": false,
            "reason": "Memory conservation - run on Windows"
        }
    },
    "distributed_mode": {
        "enabled": true,
        "windows_primary": true,
        "mac_operations": true,
        "cross_platform_sync": true
    }
}
EOF

    log_success "16GB configuration created"
}

# Install dependencies (lightweight)
install_dependencies() {
    log_info "Installing lightweight dependencies..."

    # Check if Python is available
    if ! command -v python3 &> /dev/null; then
        log_error "Python 3 required. Please install from https://www.python.org/"
        exit 1
    fi

    # Install only essential packages
    pip3 install flask requests python-dotenv psutil

    # Optional: ngrok for remote access
    if ! command -v ngrok &> /dev/null; then
        log_warning "ngrok not found. Install for remote access: brew install ngrok"
    fi

    log_success "Dependencies installed"
}

# Setup distributed communication
setup_distributed_comms() {
    log_info "Setting up Mac ↔ Windows communication..."

    # Create distributed config
    cat > config/distributed.json << EOF
{
    "mac_endpoints": {
        "operations": "http://localhost:5000",
        "mobile": "http://localhost:8080",
        "matrix": "http://localhost:3000"
    },
    "windows_endpoints": {
        "discovery": "auto-detect",
        "heavy_compute": "windows_machine_ip:9090",
        "aac_system": "windows_machine_ip:8081"
    },
    "sync_config": {
        "method": "git_sync",
        "interval": 300,
        "conflict_resolution": "windows_priority"
    }
}
EOF

    log_success "Distributed communication configured"
}

# Create lightweight launch script
create_launch_script() {
    log_info "Creating 16GB-optimized launch script..."

    cat > macbook_launch.sh << 'EOF'
#!/bin/bash
# 16GB MacBook Launch Script
# Memory-optimized operations

echo "🚀 Starting Super Agency (16GB MacBook Mode)"
echo "📊 Memory: $(echo "scale=1; $(sysctl -n hw.memsize) / 1024 / 1024 / 1024" | bc)GB"

# Start services sequentially to manage memory
echo "📱 Starting Mobile Command Center..."
python3 mobile_command_center.py &
MOBILE_PID=$!
sleep 2

echo "⚙️ Starting Operations Interface..."
python3 operations_launcher.py &
OPS_PID=$!
sleep 2

echo "🧠 Starting Matrix Monitor..."
python3 matrix_monitor.py &
MATRIX_PID=$!
sleep 2

echo "✅ Services started!"
echo "📱 Mobile Access: http://localhost:8080"
echo "⚙️ Operations: http://localhost:5000"
echo "🧠 Matrix Monitor: http://localhost:3000"
echo ""
echo "💻 Heavy computation delegated to Windows machine"
echo "🔄 Cross-platform sync active"

# Wait for user input to stop
read -p "Press Enter to stop services..."

echo "🛑 Stopping services..."
kill $MOBILE_PID $OPS_PID $MATRIX_PID 2>/dev/null
echo "✅ All services stopped"
EOF

    chmod +x macbook_launch.sh
    log_success "Launch script created"
}

# Create Windows sync script
create_windows_sync() {
    log_info "Creating Windows synchronization script..."

    cat > sync_to_windows.ps1 << 'EOF'
# Windows Sync Script for MacBook Operations
# Heavy lifting on Windows, operations on Mac

param(
    [string]$MacIP = "auto-detect"
)

Write-Host "🔄 Syncing MacBook Operations to Windows..." -ForegroundColor Cyan

# Auto-detect Mac IP if not provided
if ($MacIP -eq "auto-detect") {
    # Find Mac on network (assuming same subnet)
    $MacIP = "192.168.1.100"  # Replace with actual Mac IP
}

# Sync endpoints
$endpoints = @{
    "Operations" = "http://$MacIP`:5000"
    "Mobile" = "http://$MacIP`:8080"
    "Matrix" = "http://$MacIP`:3000"
}

# Test connections
foreach ($service in $endpoints.Keys) {
    try {
        $response = Invoke-WebRequest -Uri $endpoints[$service] -TimeoutSec 5
        Write-Host "✅ $service connected" -ForegroundColor Green
    } catch {
        Write-Host "❌ $service unreachable" -ForegroundColor Red
    }
}

# Start Windows heavy lifting services
Write-Host "💪 Starting Windows heavy computation..." -ForegroundColor Yellow

# Start AAC System (memory intensive)
Start-Process python -ArgumentList "repos\AAC\aac_dashboard.py" -WindowStyle Hidden

# Start CPU Maximizer
Start-Process python -ArgumentList "cpu_maximizer.py" -WindowStyle Hidden

# Start Intelligence Gathering
Start-Process python -ArgumentList "youtube_intelligence_monitor.py" -WindowStyle Hidden

Write-Host "✅ Windows heavy lifting active" -ForegroundColor Green
Write-Host "📱 MacBook operations available at:" -ForegroundColor Cyan
foreach ($service in $endpoints.Keys) {
    Write-Host "  $service`: $($endpoints[$service])" -ForegroundColor White
}
EOF

    log_success "Windows sync script created"
}

# Main setup
main() {
    echo "🍎 Super Agency 16GB MacBook Setup"
    echo "=================================="

    # Check RAM
    local ram=$(check_ram)
    if (( $(echo "$ram < 16" | bc -l) )); then
        log_warning "RAM is ${ram}GB. 16GB+ recommended for optimal performance."
    else
        log_success "RAM check passed: ${ram}GB"
    fi

    setup_16gb_config
    install_dependencies
    setup_distributed_comms
    create_launch_script
    create_windows_sync

    echo ""
    log_success "🎉 16GB MacBook setup complete!"
    echo ""
    echo "🚀 Next steps:"
    echo "1. On MacBook: ./macbook_launch.sh"
    echo "2. On Windows: .\sync_to_windows.ps1 -MacIP [your-mac-ip]"
    echo "3. Access mobile interface: http://localhost:8080"
    echo ""
    echo "💡 Heavy computation runs on Windows, operations on MacBook"
}

main "$@"</content>
<parameter name="filePath">c:/Users/gripa/OneDrive - Grip and Ripp/Super Agency/Super-Agency/macbook_16gb_setup.sh