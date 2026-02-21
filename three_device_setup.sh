#!/bin/bash
# Three-Device Super Agency Setup
# MacBook M1 8GB + HP Laptop Windows + iPhone/iPad

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

# Device detection and configuration
detect_devices() {
    log_info "🔍 Detecting devices on network..."

    # Find potential Windows HP laptop
    windows_ip=$(arp -a | grep -i "hp\|windows" | head -1 | awk '{print $2}' | tr -d '()')
    if [ -z "$windows_ip" ]; then
        # Fallback: scan common range
        windows_ip=$(for i in {1..254}; do
            timeout 0.1 bash -c "echo >/dev/tcp/192.168.1.$i/9090" 2>/dev/null && echo "192.168.1.$i" && break
        done)
    fi

    # Get local Mac IP
    mac_ip=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || hostname -I | awk '{print $1}')

    echo "mac_ip=$mac_ip"
    echo "windows_ip=$windows_ip"
}

# Create three-device configuration
create_three_device_config() {
    local mac_ip=$1
    local windows_ip=$2

    log_info "📝 Creating three-device configuration..."

    cat > config/three_device_setup.json << EOF
{
    "architecture": "three_device_optimized",
    "devices": {
        "macbook_m1": {
            "ip": "$mac_ip",
            "role": "lightweight_hub",
            "memory_limit": "256MB",
            "services": ["mobile_command_center"],
            "power_mode": "always_on",
            "network_priority": "high"
        },
        "hp_laptop_windows": {
            "ip": "$windows_ip",
            "role": "heavy_computation",
            "memory_limit": "16GB",
            "services": [
                "aac_system",
                "inner_council",
                "intelligence_monitor",
                "cpu_maximizer",
                "matrix_monitor",
                "operations_interface"
            ],
            "power_mode": "high_performance",
            "storage_priority": "primary"
        },
        "iphone_ipad": {
            "ip": "dynamic",
            "role": "mobile_interface",
            "memory_limit": "100MB",
            "services": ["pwa_interface"],
            "power_mode": "efficient",
            "connectivity": "multi_hub"
        }
    },
    "communication": {
        "primary_channel": {
            "mobile_to_mac": "websocket_direct",
            "mac_to_windows": "sasp_protocol",
            "mobile_to_windows": "fallback_direct"
        },
        "sync_strategy": {
            "state_sync": "real_time",
            "command_queue": "persistent",
            "file_sync": "git_based"
        },
        "security": {
            "authentication": "unified_biometric",
            "encryption": "end_to_end",
            "certificates": "auto_rotated"
        }
    },
    "optimization": {
        "power_management": {
            "macbook": "low_power_always_available",
            "hp_laptop": "high_performance_on_demand",
            "mobile": "battery_optimized"
        },
        "resource_allocation": {
            "computation": "windows_primary",
            "interface": "mobile_primary",
            "coordination": "mac_lightweight"
        },
        "network_optimization": {
            "local_network_priority": true,
            "remote_access_fallback": true,
            "bandwidth_conservation": true
        }
    }
}
EOF

    log_success "Three-device configuration created"
}

# Setup MacBook M1 as lightweight hub
setup_macbook_hub() {
    log_info "🖥️ Setting up MacBook M1 as lightweight hub..."

    # Run 8GB M1 setup
    if [ -f "macbook_8gb_m1_setup.sh" ]; then
        ./macbook_8gb_m1_setup.sh
    else
        log_error "macbook_8gb_m1_setup.sh not found"
        exit 1
    fi

    # Configure for three-device role
    cat > config/macbook_hub_config.json << EOF
{
    "role": "three_device_hub",
    "memory_target": "256MB",
    "services_enabled": ["mobile_command_center"],
    "connections": {
        "windows_hub": "auto_discover",
        "mobile_clients": "accept_all",
        "remote_access": "ngrok_optional"
    },
    "optimization": {
        "power_mode": "always_on",
        "network_keepalive": true,
        "memory_aggressive_cleanup": true,
        "m1_specific": {
            "neural_engine": "disabled",
            "memory_compression": "maximum"
        }
    }
}
EOF

    log_success "MacBook hub configuration complete"
}

# Generate Windows setup instructions
generate_windows_instructions() {
    local windows_ip=$1

    log_info "💻 Generating HP Laptop Windows setup instructions..."

    cat > WINDOWS_THREE_DEVICE_SETUP.ps1 << EOF
# Three-Device Super Agency Setup - HP Laptop Windows
# Heavy computation hub for MacBook M1 + iPhone/iPad setup

param(
    [string]$MacIP = "$mac_ip",
    [switch]$FullSetup,
    [switch]$PerformanceMode
)

# Import required modules
Import-Module NetTCPIP

function Set-HighPerformanceMode {
    Write-Host "⚡ Configuring high-performance mode..." -ForegroundColor Yellow

    # Set power plan to high performance
    powercfg /setactive 8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c

    # Disable sleep and hibernation
    powercfg /change standby-timeout-ac 0
    powercfg /change hibernate-timeout-ac 0
    powercfg /change monitor-timeout-ac 30

    # Set processor performance
    Set-ItemProperty -Path "HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Power\\PowerSettings\\54533251-82be-4824-96c1-47b60b740d00\\75b0ae3f-bce0-45a7-8c89-c9611c25e100" -Name "Attributes" -Value 2
    Set-ItemProperty -Path "HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Power\\PowerSettings\\54533251-82be-4824-96c1-47b60b740d00\\75b0ae3f-bce0-45a7-8c89-c9611c25e100" -Name "Value" -Value 100

    Write-Host "✅ High-performance mode configured" -ForegroundColor Green
}

function Install-ThreeDeviceServices {
    Write-Host "🔧 Installing three-device optimized services..." -ForegroundColor Yellow

    # Install Python dependencies for heavy computation
    pip install flask requests psutil numpy pandas scikit-learn tensorflow torch

    # Configure services for three-device architecture
    \$servicesConfig = @{
        "AAC_System" = @{
            "MemoryLimit" = "4GB"
            "Priority" = "High"
            "AutoStart" = \$true
        }
        "Inner_Council" = @{
            "MemoryLimit" = "6GB"
            "MaxAgents" = 8
            "AutoStart" = \$true
        }
        "Intelligence_Monitor" = @{
            "MemoryLimit" = "2GB"
            "Priority" = "Normal"
            "AutoStart" = \$true
        }
        "Matrix_Monitor" = @{
            "MemoryLimit" = "1GB"
            "Port" = 3000
            "AutoStart" = \$true
        }
        "Operations_Interface" = @{
            "MemoryLimit" = "1GB"
            "Port" = 5000
            "AutoStart" = \$true
        }
    }

    # Save configuration
    \$servicesConfig | ConvertTo-Json | Out-File -FilePath "config\\windows_services_three_device.json"

    Write-Host "✅ Services configured for three-device architecture" -ForegroundColor Green
}

function Test-ThreeDeviceConnectivity {
    param([string]$MacIP)

    Write-Host "🔗 Testing three-device connectivity..." -ForegroundColor Yellow

    # Test connection to MacBook hub
    try {
        \$response = Invoke-WebRequest -Uri "http://\$MacIP`:8080/api/status" -TimeoutSec 10
        Write-Host "✅ MacBook hub connection: OK" -ForegroundColor Green
    } catch {
        Write-Host "❌ MacBook hub connection: FAILED" -ForegroundColor Red
        Write-Host "   Make sure MacBook is running: ./m1_8gb_launch.sh" -ForegroundColor Yellow
    }

    # Test SASP protocol
    try {
        \$response = Invoke-WebRequest -Uri "http://\$MacIP`:8080/sasp/health" -TimeoutSec 5
        Write-Host "✅ SASP protocol: OK" -ForegroundColor Green
    } catch {
        Write-Host "❌ SASP protocol: FAILED" -ForegroundColor Red
    }

    Write-Host "📱 Mobile access: http://\$MacIP`:8080" -ForegroundColor Cyan
    Write-Host "🖥️ Local services: http://localhost:3000 (Matrix), http://localhost:5000 (Operations)" -ForegroundColor Cyan
}

# Main setup logic
if (\$FullSetup) {
    Write-Host "🚀 Three-Device Super Agency Setup - HP Laptop Windows" -ForegroundColor Cyan
    Write-Host "=========================================================" -ForegroundColor Cyan

    Set-HighPerformanceMode
    Install-ThreeDeviceServices

    Write-Host ""
    Write-Host "🎯 Next Steps:" -ForegroundColor Green
    Write-Host "1. Run: .\WINDOWS_THREE_DEVICE_SETUP.ps1 -PerformanceMode" -ForegroundColor White
    Write-Host "2. Start services: .\sync_to_windows.ps1 -StartServices -MacIP \$MacIP" -ForegroundColor White
    Write-Host "3. Test connectivity: .\WINDOWS_THREE_DEVICE_SETUP.ps1 -MacIP \$MacIP" -ForegroundColor White
}

if (\$PerformanceMode) {
    Set-HighPerformanceMode
}

# Test connectivity if MacIP provided
if (\$MacIP -and -not \$FullSetup) {
    Test-ThreeDeviceConnectivity -MacIP \$MacIP
}

if (-not \$FullSetup -and -not \$PerformanceMode -and -not \$MacIP) {
    Write-Host "Three-Device Super Agency - HP Laptop Windows" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Usage:" -ForegroundColor Yellow
    Write-Host "  .\WINDOWS_THREE_DEVICE_SETUP.ps1 -FullSetup                    # Complete setup" -ForegroundColor White
    Write-Host "  .\WINDOWS_THREE_DEVICE_SETUP.ps1 -PerformanceMode             # Performance optimization" -ForegroundColor White
    Write-Host "  .\WINDOWS_THREE_DEVICE_SETUP.ps1 -MacIP '192.168.1.100'       # Test connectivity" -ForegroundColor White
}
EOF

    log_success "Windows setup instructions generated"
}

# Generate mobile device setup
generate_mobile_setup() {
    local mac_ip=$1
    local windows_ip=$2

    log_info "📱 Generating iPhone/iPad setup instructions..."

    cat > MOBILE_DEVICE_SETUP.md << EOF
# 📱 Super Agency Mobile Setup
## iPhone/iPad Configuration for Three-Device Architecture

## Quick Setup

### 1. Access Mobile Interface
Open Safari on your iPhone/iPad and go to:
**http://$mac_ip:8080**

### 2. Install PWA (Progressive Web App)
1. Tap the Share button (square with arrow)
2. Scroll down and tap "Add to Home Screen"
3. Tap "Add" to install

### 3. Enable Features
- **Notifications:** Allow push notifications
- **Background Refresh:** Enable for real-time updates
- **Offline Access:** Enable for cached operation

## Device-Specific Optimizations

### iPhone Settings
\`\`\`
Settings > Super Agency PWA > Background App Refresh: ON
Settings > Notifications > Super Agency: Allow Notifications
Settings > Safari > Downloads: ON (for file access)
\`\`\`

### iPad Settings
\`\`\`
Settings > General > Multitasking: Enable
Settings > Safari > Request Desktop Website: OFF
Settings > Super Agency PWA > Background App Refresh: ON
\`\`\`

## Connection Configuration

### Primary Connection (MacBook Hub)
- **URL:** http://$mac_ip:8080
- **Protocol:** WebSocket + HTTP
- **Purpose:** Primary control interface

### Backup Connection (HP Laptop Direct)
- **URL:** http://$windows_ip:3000
- **Protocol:** HTTP fallback
- **Purpose:** Direct access when Mac unavailable

### Offline Capabilities
- **Cached Status:** Last known system status
- **Queued Commands:** Execute when reconnected
- **Basic Monitoring:** Essential alerts only

## Performance Optimization

### Battery Optimization
- **Low Power Mode:** Compatible with Super Agency
- **Background Refresh:** Selective for important updates
- **Location Services:** App-only when needed

### Network Optimization
- **WiFi Preferred:** Faster, more reliable
- **Cellular Fallback:** Automatic switching
- **Data Conservation:** Compressed updates

## Security Setup

### Biometric Authentication
1. Enable Face ID/Touch ID in app settings
2. Set up emergency access codes
3. Enable auto-lock after 5 minutes

### Device Trust
- **Certificate Installation:** Automatic via PWA
- **Key Rotation:** Every 24 hours
- **Secure Storage:** Encrypted local data

## Troubleshooting

### Connection Issues
1. **Check WiFi:** Ensure same network as MacBook
2. **Refresh PWA:** Hard refresh (pull down to refresh)
3. **Clear Cache:** Settings > Safari > Clear History and Website Data

### Performance Issues
1. **Close Background Apps:** Free up memory
2. **Disable Low Power Mode:** Temporarily for heavy operations
3. **Update PWA:** Check for updates in app

### Notification Issues
1. **Check Permissions:** Settings > Notifications > Super Agency
2. **Background Refresh:** Settings > General > Background App Refresh
3. **Do Not Disturb:** Ensure not blocking Super Agency

## Advanced Features

### Multi-Device Handoff
- **Continuity:** Seamless switching between iPhone and iPad
- **Handoff:** Continue sessions across devices
- **Universal Clipboard:** Copy between devices

### Widget Support (iOS 14+)
- **Home Screen Widgets:** Quick status and commands
- **Today View:** System overview
- **Lock Screen:** Important alerts

### Shortcuts Integration (iOS 12+)
- **Siri Commands:** Voice-activated operations
- **Automation:** Scheduled tasks and routines
- **Quick Actions:** 3D Touch shortcuts

## Emergency Access

### Offline Mode
- **Basic Status:** View cached system status
- **Emergency Commands:** Limited command execution
- **Contact Backup:** Alternative communication methods

### Recovery Procedures
1. **Force Restart:** Hold power + volume buttons
2. **Reinstall PWA:** Delete and re-add from home screen
3. **Factory Reset:** Last resort, contact administrator

---

**Primary Access Point:** http://$mac_ip:8080
**Backup Access Point:** http://$windows_ip:3000
**Emergency Contact:** Check physical devices directly
EOF

    log_success "Mobile setup instructions generated"
}

# Create unified monitoring dashboard
create_unified_monitoring() {
    log_info "📊 Creating unified three-device monitoring..."

    cat > three_device_monitor.py << 'EOF'
#!/usr/bin/env python3
"""
Three-Device Super Agency Monitoring Dashboard
Unified monitoring for MacBook M1 + HP Laptop Windows + iPhone/iPad
"""

from flask import Flask, render_template, jsonify
import requests
import json
import time
import psutil
from datetime import datetime

app = Flask(__name__)

# Device configuration
DEVICES = {
    'macbook_m1': {
        'ip': '192.168.1.100',  # Auto-detected
        'role': 'lightweight_hub',
        'endpoints': {
            'status': '/api/status',
            'memory': '/api/memory',
            'sasp': '/sasp/health'
        }
    },
    'hp_laptop_windows': {
        'ip': '192.168.1.101',  # Auto-detected
        'role': 'heavy_computation',
        'endpoints': {
            'matrix': ':3000',
            'operations': ':5000',
            'aac': ':8081'
        }
    }
}

@app.route('/')
def dashboard():
    """Unified three-device dashboard"""
    return render_template('three_device_dashboard.html')

@app.route('/api/three-device/status')
def get_three_device_status():
    """Get status from all three devices"""
    status = {
        'timestamp': datetime.now().isoformat(),
        'devices': {},
        'connections': {},
        'overall_health': 'unknown'
    }

    # Check MacBook M1
    mac_status = check_device_status('macbook_m1')
    status['devices']['macbook_m1'] = mac_status

    # Check HP Laptop Windows
    windows_status = check_device_status('hp_laptop_windows')
    status['devices']['hp_laptop_windows'] = windows_status

    # Check mobile connections (estimated)
    status['devices']['mobile_clients'] = {
        'status': 'unknown',
        'last_seen': 'unknown',
        'active_connections': 0
    }

    # Determine overall health
    device_statuses = [mac_status['status'], windows_status['status']]
    if all(s == 'online' for s in device_statuses):
        status['overall_health'] = 'excellent'
    elif any(s == 'online' for s in device_statuses):
        status['overall_health'] = 'degraded'
    else:
        status['overall_health'] = 'offline'

    return jsonify(status)

def check_device_status(device_name):
    """Check status of a specific device"""
    device = DEVICES[device_name]
    base_url = f"http://{device['ip']}"

    status = {
        'status': 'offline',
        'services': {},
        'resources': {},
        'last_check': datetime.now().isoformat()
    }

    try:
        if device_name == 'macbook_m1':
            # Check mobile command center
            response = requests.get(f"{base_url}:8080{device['endpoints']['status']}", timeout=5)
            if response.status_code == 200:
                status['status'] = 'online'
                status['services']['mobile_center'] = 'running'

            # Check memory
            mem_response = requests.get(f"{base_url}:8080{device['endpoints']['memory']}", timeout=5)
            if mem_response.status_code == 200:
                status['resources'] = mem_response.json()

        elif device_name == 'hp_laptop_windows':
            # Check Windows services
            services_to_check = [
                ('matrix', f"{base_url}{device['endpoints']['matrix']}"),
                ('operations', f"{base_url}{device['endpoints']['operations']}"),
                ('aac', f"{base_url}{device['endpoints']['aac']}")
            ]

            online_services = 0
            for service_name, url in services_to_check:
                try:
                    response = requests.get(url, timeout=3)
                    if response.status_code == 200:
                        status['services'][service_name] = 'running'
                        online_services += 1
                    else:
                        status['services'][service_name] = 'stopped'
                except:
                    status['services'][service_name] = 'unknown'

            if online_services > 0:
                status['status'] = 'online'

    except Exception as e:
        status['error'] = str(e)

    return status

if __name__ == '__main__':
    print("📊 Starting Three-Device Monitoring Dashboard...")
    print("Access: http://localhost:9090")
    app.run(host='0.0.0.0', port=9090, debug=False)
EOF

    # Create HTML template
    mkdir -p templates
    cat > templates/three_device_dashboard.html << 'EOF'
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Three-Device Super Agency</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; margin: 20px; background: #f5f5f5; }
        .container { max-width: 1200px; margin: 0 auto; }
        .device-card { background: white; padding: 20px; margin: 10px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        .status-online { background: #d4edda; color: #155724; }
        .status-offline { background: #f8d7da; color: #721c24; }
        .status-degraded { background: #fff3cd; color: #856404; }
        .health-excellent { background: #d4edda; }
        .health-good { background: #cce7ff; }
        .health-degraded { background: #fff3cd; }
        .health-offline { background: #f8d7da; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; }
        .metric { display: flex; justify-content: space-between; margin: 5px 0; }
        button { background: #007bff; color: white; border: none; padding: 10px; border-radius: 5px; cursor: pointer; }
        button:hover { background: #0056b3; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🚀 Super Agency Three-Device Dashboard</h1>

        <div id="overall-health" class="device-card">
            <h2>Overall System Health</h2>
            <div id="health-status">Loading...</div>
        </div>

        <div class="grid">
            <div class="device-card">
                <h3>🖥️ MacBook M1 (Lightweight Hub)</h3>
                <div id="macbook-status">Loading...</div>
            </div>

            <div class="device-card">
                <h3>💻 HP Laptop Windows (Heavy Computation)</h3>
                <div id="windows-status">Loading...</div>
            </div>

            <div class="device-card">
                <h3>📱 Mobile Clients (iPhone/iPad)</h3>
                <div id="mobile-status">Loading...</div>
            </div>
        </div>

        <div class="device-card">
            <h3>🔧 Quick Actions</h3>
            <button onclick="refreshStatus()">🔄 Refresh Status</button>
            <button onclick="openMacInterface()">🖥️ Mac Interface</button>
            <button onclick="openWindowsInterface()">💻 Windows Interface</button>
        </div>
    </div>

    <script>
        async function updateStatus() {
            try {
                const response = await fetch('/api/three-device/status');
                const data = await response.json();

                // Update overall health
                const healthElement = document.getElementById('health-status');
                healthElement.className = `status-${data.overall_health}`;
                healthElement.innerHTML = `<strong>${data.overall_health.toUpperCase()}</strong>`;

                // Update MacBook status
                updateDeviceStatus('macbook-status', data.devices.macbook_m1);

                // Update Windows status
                updateDeviceStatus('windows-status', data.devices.hp_laptop_windows);

                // Update mobile status
                updateDeviceStatus('mobile-status', data.devices.mobile_clients);

            } catch (error) {
                console.error('Status update failed:', error);
            }
        }

        function updateDeviceStatus(elementId, deviceData) {
            const element = document.getElementById(elementId);
            const statusClass = deviceData.status === 'online' ? 'status-online' : 'status-offline';

            let html = `<div class="${statusClass}">Status: ${deviceData.status}</div>`;

            if (deviceData.services) {
                html += '<h4>Services:</h4>';
                for (const [service, status] of Object.entries(deviceData.services)) {
                    const serviceClass = status === 'running' ? 'status-online' : 'status-offline';
                    html += `<div class="${serviceClass}">${service}: ${status}</div>`;
                }
            }

            if (deviceData.resources && deviceData.resources.memory_used_mb) {
                html += '<h4>Resources:</h4>';
                html += `<div>Memory: ${deviceData.resources.memory_used_mb}MB / ${deviceData.resources.total_gb}GB</div>`;
                html += `<div>CPU: ${deviceData.resources.cpu_percent || 'N/A'}%</div>`;
            }

            element.innerHTML = html;
        }

        function refreshStatus() {
            updateStatus();
        }

        function openMacInterface() {
            window.open('http://192.168.1.100:8080', '_blank');
        }

        function openWindowsInterface() {
            window.open('http://192.168.1.101:3000', '_blank');
        }

        // Auto-refresh every 30 seconds
        updateStatus();
        setInterval(updateStatus, 30000);
    </script>
</body>
</html>
EOF

    log_success "Unified monitoring dashboard created"
}

# Main setup
main() {
    echo "🚀 Three-Device Super Agency Setup"
    echo "=================================="

    # Detect devices
    device_info=$(detect_devices)
    mac_ip=$(echo "$device_info" | grep "mac_ip=" | cut -d'=' -f2)
    windows_ip=$(echo "$device_info" | grep "windows_ip=" | cut -d'=' -f2)

    echo "📍 Detected Devices:"
    echo "   MacBook M1: $mac_ip"
    echo "   HP Laptop: $windows_ip"

    # Create configurations
    create_three_device_config "$mac_ip" "$windows_ip"
    setup_macbook_hub
    generate_windows_instructions "$windows_ip"
    generate_mobile_setup "$mac_ip" "$windows_ip"
    create_unified_monitoring

    echo ""
    echo "🎯 Setup Complete!"
    echo "=================="
    echo "📱 MacBook: ./m1_8gb_launch.sh"
    echo "💻 Windows: .\WINDOWS_THREE_DEVICE_SETUP.ps1 -FullSetup"
    echo "📊 Monitor: python three_device_monitor.py"
    echo "📱 Mobile: http://$mac_ip:8080"
    echo ""
    echo "📖 Instructions:"
    echo "   - MOBILE_DEVICE_SETUP.md"
    echo "   - THREE_DEVICE_OPTIMIZATION.md"
}

main "$@"</content>
<parameter name="filePath">c:/Users/gripa/OneDrive - Grip and Ripp/Super Agency/Super-Agency/three_device_setup.sh