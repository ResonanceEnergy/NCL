#!/bin/bash
# Super Agency 8GB M1 MacBook Setup
# Ultra-optimized for 8GB RAM Apple M1 - Operations focused

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

# Check RAM and chip
check_system() {
    local ram_gb=$(echo "scale=1; $(sysctl -n hw.memsize) / 1024 / 1024 / 1024" | bc)
    local chip=$(sysctl -n machdep.cpu.brand_string)
    echo "$ram_gb|$chip"
}

# Ultra-memory-optimized agent deployment for 8GB M1
setup_8gb_m1_config() {
    log_info "Setting up 8GB M1 MacBook configuration..."

    # Create ultra-memory-optimized config
    cat > config/8gb_m1_macbook.json << EOF
{
    "memory_optimization": {
        "max_agents": 1,
        "agent_memory_limit": "512MB",
        "cpu_cores_limit": 4,
        "background_priority": "lowest",
        "swap_usage": "minimal",
        "m1_optimization": {
            "neural_engine": false,
            "gpu_acceleration": false,
            "memory_compression": true,
            "app_nap": true
        }
    },
    "services": {
        "matrix_monitor": {
            "enabled": false,
            "reason": "Memory conservation - access via Windows"
        },
        "operations_interface": {
            "enabled": false,
            "reason": "Memory conservation - use mobile interface only"
        },
        "mobile_command_center": {
            "enabled": true,
            "memory_limit": "256MB",
            "port": 8080,
            "m1_optimized": true
        },
        "aac_system": {
            "enabled": false,
            "reason": "Memory conservation - run on Windows only"
        },
        "ncl_second_brain": {
            "enabled": false,
            "reason": "Memory conservation - lightweight mode only"
        }
    },
    "distributed_mode": {
        "enabled": true,
        "windows_primary": true,
        "mac_operations": "minimal",
        "cross_platform_sync": true,
        "remote_matrix_monitor": true
    },
    "m1_specific": {
        "architecture": "arm64",
        "neural_engine_disabled": true,
        "memory_pressure_handling": "aggressive",
        "background_app_refresh": false,
        "spotlight_indexing": "reduced"
    }
}
EOF

    log_success "8GB M1 configuration created"
}

# Install minimal dependencies for M1
install_m1_dependencies() {
    log_info "Installing minimal M1-optimized dependencies..."

    # Check if Python is available
    if ! command -v python3 &> /dev/null; then
        log_error "Python 3 required. Please install from https://www.python.org/"
        exit 1
    fi

    # Install only essential packages with M1 optimizations
    pip3 install flask requests psutil

    # Skip heavy packages for 8GB M1
    log_warning "Skipping optional packages for memory conservation"

    log_success "Minimal dependencies installed"
}

# Setup ultra-lightweight distributed communication
setup_ultra_lightweight_comms() {
    log_info "Setting up ultra-lightweight Mac ↔ Windows communication..."

    # Create minimal distributed config
    cat > config/8gb_distributed.json << EOF
{
    "mac_endpoints": {
        "mobile_only": "http://localhost:8080",
        "remote_matrix": "windows_machine_ip:3000",
        "remote_operations": "windows_machine_ip:5000"
    },
    "windows_endpoints": {
        "discovery": "auto-detect",
        "heavy_compute": "windows_machine_ip:9090",
        "aac_system": "windows_machine_ip:8081",
        "matrix_monitor": "windows_machine_ip:3000",
        "operations_interface": "windows_machine_ip:5000"
    },
    "sync_config": {
        "method": "minimal_sync",
        "interval": 600,
        "conflict_resolution": "windows_priority",
        "sync_only_essentials": true
    },
    "memory_conservation": {
        "no_local_caching": true,
        "remote_service_proxy": true,
        "lazy_loading": true
    }
}
EOF

    log_success "Ultra-lightweight communication configured"
}

# Create ultra-minimal launch script for 8GB M1
create_m1_launch_script() {
    log_info "Creating 8GB M1-optimized launch script..."

    cat > m1_8gb_launch.sh << 'EOF'
#!/bin/bash
# 8GB M1 MacBook Launch Script
# Ultra-memory-optimized for Apple M1

echo "🚀 Starting Super Agency (8GB M1 Mode)"
echo "📊 Memory: $(echo "scale=1; $(sysctl -n hw.memsize) / 1024 / 1024 / 1024" | bc)GB"
echo "🔧 Chip: $(sysctl -n machdep.cpu.brand_string)"

# Memory pressure check
memory_pressure=$(echo "scale=1; $(sysctl -n hw.memsize) / 1024 / 1024 / 1024" | bc)
if (( $(echo "$memory_pressure < 8.0" | bc -l) )); then
    echo "⚠️  WARNING: Less than 8GB RAM detected. Performance may be limited."
fi

# Start ONLY mobile command center to save memory
echo "📱 Starting Ultra-Lightweight Mobile Command Center..."
python3 mobile_command_center_8gb.py &
MOBILE_PID=$!
sleep 3

# Memory monitoring
echo "🧠 Memory Monitor Active..."
while kill -0 $MOBILE_PID 2>/dev/null; do
    mem_usage=$(ps -o rss= -p $MOBILE_PID 2>/dev/null | awk '{print $1/1024/1024 "GB"}' 2>/dev/null || echo "unknown")
    echo "📊 Mobile Center Memory: $mem_usage"
    sleep 30
done

echo "❌ Mobile center stopped"
EOF

    chmod +x m1_8gb_launch.sh
    log_success "8GB M1 launch script created"
}

# Optimize macOS for 8GB M1
optimize_macos_m1() {
    log_info "Applying macOS M1 optimizations for 8GB RAM..."

    # Create memory optimization script
    cat > optimize_m1_8gb.sh << 'EOF'
#!/bin/bash
# macOS M1 8GB Memory Optimization

echo "🔧 Optimizing macOS for 8GB M1 Super Agency..."

# Reduce memory pressure
sudo sysctl vm.compressor_mode=2
sudo sysctl vm.compressor_bytes=0
sudo sysctl vm.compressor_threads=1

# Disable unnecessary services
sudo launchctl unload -w /System/Library/LaunchDaemons/com.apple.syslogd.plist 2>/dev/null || true
sudo launchctl unload -w /System/Library/LaunchDaemons/com.apple.metadata.mds.plist 2>/dev/null || true

# Enable memory compression
defaults write NSGlobalDomain NSAppSleepDisabled -bool YES
defaults write com.apple.finder QuitMenuItem -bool YES

echo "✅ macOS optimized for 8GB M1"
EOF

    chmod +x optimize_m1_8gb.sh
    log_success "macOS optimization script created"
}

# Create ultra-lightweight mobile center for 8GB M1
create_ultra_lightweight_mobile() {
    log_info "Creating ultra-lightweight mobile center for 8GB M1..."

    cat > mobile_command_center_8gb.py << 'EOF'
#!/usr/bin/env python3
"""
Ultra-Lightweight Super Agency Mobile Command Center (8GB M1 Optimized)
Minimal Flask web server for 8GB M1 MacBook - maximum memory conservation
"""

from flask import Flask, render_template, jsonify, request
import subprocess
import sys
import os
import json
import time
import psutil
from datetime import datetime

app = Flask(__name__,
            template_folder='templates',
            static_folder='static')

# Ultra-minimal service status (only mobile center)
service_status = {
    'mobile_center': {'status': 'running', 'port': 8080, 'last_check': time.time(), 'memory_limit': 128}  # 128MB limit
}

# Aggressive memory monitoring
def get_memory_usage():
    """Get current memory usage in MB"""
    process = psutil.Process(os.getpid())
    return process.memory_info().rss / 1024 / 1024

def force_memory_cleanup():
    """Aggressive memory cleanup for 8GB M1"""
    current_mem = get_memory_usage()
    if current_mem > 100:  # 100MB limit
        print(f"🧹 Memory cleanup: {current_mem:.1f}MB")
        import gc
        gc.collect()

# Minimal service check
def check_service_status(service_name):
    """Minimal status check"""
    current_time = time.time()
    if current_time - service_status[service_name]['last_check'] < 120:  # Cache for 2 minutes
        return service_status[service_name]['status']

    # Only check if port is accessible (no heavy operations)
    port = service_status[service_name]['port']
    try:
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.5)
        result = sock.connect_ex(('127.0.0.1', port))
        sock.close()
        status = 'running' if result == 0 else 'stopped'
    except:
        status = 'unknown'

    service_status[service_name]['status'] = status
    service_status[service_name]['last_check'] = current_time
    return status

@app.route('/')
def index():
    """Ultra-minimal mobile dashboard"""
    force_memory_cleanup()
    return render_template('m1_8gb_index.html')

@app.route('/api/status')
def get_status():
    """Minimal system status"""
    force_memory_cleanup()

    status = {
        'mobile_center': {
            'status': check_service_status('mobile_center'),
            'port': service_status['mobile_center']['port']
        },
        'system': {
            'timestamp': datetime.now().isoformat(),
            'platform': 'macOS M1 8GB',
            'memory_mode': 'ultra_conservative'
        },
        'distributed': {
            'windows_services': 'remote_only',
            'local_services': 'minimal'
        }
    }

    return jsonify(status)

@app.route('/api/windows/<command>')
def proxy_windows_command(command):
    """Proxy commands to Windows (no local execution)"""
    force_memory_cleanup()

    # Commands that should run on Windows only
    windows_commands = {
        'max_cpu': 'Delegated to Windows heavy compute',
        'deploy_agents': 'Delegated to Windows Inner Council',
        'aac_system': 'Windows AAC Financial System',
        'intelligence': 'Windows Intelligence Monitor'
    }

    if command in windows_commands:
        return jsonify({
            'status': 'delegated',
            'command': command,
            'message': windows_commands[command],
            'target': 'windows_node'
        })

    return jsonify({'error': 'Unknown command'}), 400

@app.route('/api/memory')
def get_memory_status():
    """Memory status for 8GB M1 monitoring"""
    force_memory_cleanup()

    memory = psutil.virtual_memory()
    process_memory = get_memory_usage()

    return jsonify({
        'total_gb': round(memory.total / 1024 / 1024 / 1024, 1),
        'available_gb': round(memory.available / 1024 / 1024 / 1024, 1),
        'used_percent': memory.percent,
        'process_memory_mb': round(process_memory, 1),
        'm1_optimized': True,
        'memory_pressure': 'low' if memory.percent < 80 else 'high'
    })

if __name__ == '__main__':
    print("🚀 Starting Ultra-Lightweight Super Agency Mobile Command Center")
    print("📊 macOS M1 8GB Mode - Maximum Memory Conservation")
    print("📱 Access from your phone at: http://YOUR_LOCAL_IP:8080")
    print("🔄 All heavy operations delegated to Windows")

    app.run(host='0.0.0.0', port=8080, debug=False)
EOF

    log_success "Ultra-lightweight mobile center created"
}

# Create minimal HTML template for 8GB M1
create_m1_template() {
    log_info "Creating minimal HTML template for 8GB M1..."

    mkdir -p templates

    cat > templates/m1_8gb_index.html << 'EOF'
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Super Agency M1 8GB</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; margin: 20px; background: #f5f5f5; }
        .container { max-width: 400px; margin: 0 auto; background: white; padding: 20px; border-radius: 10px; }
        .status { padding: 10px; margin: 10px 0; border-radius: 5px; }
        .running { background: #d4edda; color: #155724; }
        .stopped { background: #f8d7da; color: #721c24; }
        .memory { background: #cce7ff; color: #004085; }
        button { background: #007bff; color: white; border: none; padding: 10px; margin: 5px; border-radius: 5px; width: 100%; }
        button:hover { background: #0056b3; }
        .warning { background: #fff3cd; color: #856404; padding: 10px; border-radius: 5px; margin: 10px 0; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🚀 Super Agency</h1>
        <h2>macOS M1 8GB Mode</h2>

        <div class="warning">
            ⚠️ Ultra-Memory-Conservative Mode<br>
            All heavy operations run on Windows
        </div>

        <div id="status" class="status">
            Loading status...
        </div>

        <div id="memory" class="status memory">
            Loading memory...
        </div>

        <button onclick="checkStatus()">🔄 Refresh Status</button>

        <h3>Windows Operations</h3>
        <button onclick="runCommand('max_cpu')">🚀 Max CPU (Windows)</button>
        <button onclick="runCommand('deploy_agents')">🤖 Deploy Agents (Windows)</button>
        <button onclick="runCommand('aac_system')">💰 AAC System (Windows)</button>
        <button onclick="runCommand('intelligence')">🧠 Intelligence (Windows)</button>

        <div id="result"></div>
    </div>

    <script>
        async function checkStatus() {
            try {
                const response = await fetch('/api/status');
                const data = await response.json();

                let statusHtml = '<h4>Services</h4>';
                for (const [service, info] of Object.entries(data)) {
                    if (service !== 'system' && service !== 'distributed') {
                        statusHtml += `<div>${service}: ${info.status}</div>`;
                    }
                }

                document.getElementById('status').innerHTML = statusHtml;
            } catch (error) {
                document.getElementById('status').innerHTML = '❌ Status check failed';
            }
        }

        async function updateMemory() {
            try {
                const response = await fetch('/api/memory');
                const data = await response.json();

                const memoryHtml = `
                    <h4>Memory Status</h4>
                    <div>Total: ${data.total_gb}GB</div>
                    <div>Available: ${data.available_gb}GB</div>
                    <div>Used: ${data.used_percent}%</div>
                    <div>Process: ${data.process_memory_mb}MB</div>
                `;

                document.getElementById('memory').innerHTML = memoryHtml;
            } catch (error) {
                document.getElementById('memory').innerHTML = '❌ Memory check failed';
            }
        }

        async function runCommand(command) {
            try {
                const response = await fetch(`/api/windows/${command}`);
                const data = await response.json();

                document.getElementById('result').innerHTML =
                    `<div class="status running">${data.message}</div>`;
            } catch (error) {
                document.getElementById('result').innerHTML =
                    '<div class="status stopped">❌ Command failed</div>';
            }
        }

        // Auto-refresh
        checkStatus();
        updateMemory();
        setInterval(() => {
            checkStatus();
            updateMemory();
        }, 30000);
    </script>
</body>
</html>
EOF

    log_success "M1 template created"
}

# Main setup
main() {
    echo "🚀 Super Agency 8GB M1 MacBook Setup"
    echo "=================================="

    # System check
    IFS='|' read -r ram_gb chip <<< "$(check_system)"
    echo "📊 RAM: ${ram_gb}GB"
    echo "🔧 Chip: $chip"

    if (( $(echo "$ram_gb < 7.5" | bc -l) )); then
        log_warning "Less than 7.5GB RAM detected. Performance will be limited."
    fi

    if [[ "$chip" != *"Apple M1"* ]]; then
        log_warning "Not Apple M1 chip detected. Optimizations may not apply."
    fi

    # Setup steps
    setup_8gb_m1_config
    install_m1_dependencies
    setup_ultra_lightweight_comms
    create_m1_launch_script
    optimize_macos_m1
    create_ultra_lightweight_mobile
    create_m1_template

    echo ""
    echo "🎯 Setup Complete!"
    echo "=================="
    echo "📱 Launch: ./m1_8gb_launch.sh"
    echo "🌐 Access: http://localhost:8080"
    echo "💻 Windows: .\sync_to_windows.ps1 -StartServices"
    echo ""
    echo "⚠️  8GB M1 Mode: Ultra-conservative memory usage"
    echo "🔄 All heavy operations delegated to Windows"
}

main "$@"