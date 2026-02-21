#!/bin/bash
# Quick Three-Device Super Agency Deployment
# One-command setup for MacBook M1 + HP Laptop Windows + iPhone/iPad

set -e

# Colors for output
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

log_step() {
    echo -e "${PURPLE}[STEP]${NC} $(date '+%H:%M:%S') - $1"
}

# Pre-flight checks
preflight_checks() {
    log_step "Running pre-flight checks..."

    # Check if we're on macOS
    if [[ "$OSTYPE" != "darwin"* ]]; then
        log_error "This script must be run on macOS (MacBook M1)"
        exit 1
    fi

    # Check macOS version
    macos_version=$(sw_vers -productVersion)
    if [[ "$macos_version" != "15."* ]]; then
        log_warning "Expected macOS Sequoia 15.x, detected: $macos_version"
    fi

    # Check chip
    chip=$(sysctl -n machdep.cpu.brand_string)
    if [[ "$chip" != *"Apple M1"* ]]; then
        log_warning "Expected Apple M1 chip, detected: $chip"
    fi

    # Check RAM
    ram_gb=$(echo "scale=1; $(sysctl -n hw.memsize) / 1024 / 1024 / 1024" | bc)
    if (( $(echo "$ram_gb < 7.5" | bc -l) )); then
        log_error "Insufficient RAM: ${ram_gb}GB (minimum 8GB recommended)"
        exit 1
    fi

    log_success "Pre-flight checks passed"
}

# Setup MacBook M1
setup_macbook() {
    log_step "Setting up MacBook M1 (8GB optimized)..."

    if [ ! -f "macbook_8gb_m1_setup.sh" ]; then
        log_error "macbook_8gb_m1_setup.sh not found"
        exit 1
    fi

    chmod +x macbook_8gb_m1_setup.sh
    ./macbook_8gb_m1_setup.sh

    log_success "MacBook M1 setup complete"
}

# Setup three-device configuration
setup_three_device() {
    log_step "Setting up three-device configuration..."

    if [ ! -f "three_device_setup.sh" ]; then
        log_error "three_device_setup.sh not found"
        exit 1
    fi

    chmod +x three_device_setup.sh
    ./three_device_setup.sh

    log_success "Three-device configuration complete"
}

# Generate deployment instructions
generate_deployment_instructions() {
    log_step "Generating deployment instructions..."

    cat > DEPLOYMENT_INSTRUCTIONS.md << 'EOF'
# 🚀 Three-Device Super Agency Deployment Complete!

## ✅ What's Been Set Up

### MacBook M1 (Lightweight Hub)
- ✅ Ultra-lightweight mobile command center (<256MB RAM)
- ✅ SASP protocol endpoints
- ✅ Three-device configuration
- ✅ macOS M1 optimizations

### Generated Files for Other Devices
- ✅ `WINDOWS_THREE_DEVICE_SETUP.ps1` - HP Laptop setup
- ✅ `MOBILE_DEVICE_SETUP.md` - iPhone/iPad instructions
- ✅ `three_device_monitor.py` - Unified monitoring dashboard

## 🚀 Next Steps

### 1. Start MacBook Services
```bash
# Launch the ultra-lightweight hub
./m1_8gb_launch.sh
```

**Expected Output:**
```
🚀 Starting Ultra-Lightweight Super Agency Mobile Command Center
📊 macOS M1 8GB Mode - Maximum Memory Conservation
📱 Access from your phone at: http://YOUR_LOCAL_IP:8080
🔄 All heavy operations delegated to Windows
```

### 2. Setup HP Laptop Windows
Copy `WINDOWS_THREE_DEVICE_SETUP.ps1` to your HP laptop and run:

```powershell
# Complete Windows setup
.\WINDOWS_THREE_DEVICE_SETUP.ps1 -FullSetup

# Start heavy computation services
.\sync_to_windows.ps1 -StartServices
```

### 3. Setup Mobile Devices (iPhone/iPad)
Follow `MOBILE_DEVICE_SETUP.md`:
1. Open Safari → http://YOUR_MAC_IP:8080
2. Add to Home Screen (PWA install)
3. Enable notifications and background refresh

### 4. Start Unified Monitoring (Optional)
```bash
# Monitor all three devices
python three_device_monitor.py
# Access: http://localhost:9090
```

## 📱 Access Points

### Primary Interfaces
- **Mobile Command Center:** http://YOUR_MAC_IP:8080
- **Matrix Monitor:** http://YOUR_WINDOWS_IP:3000
- **Operations Interface:** http://YOUR_WINDOWS_IP:5000
- **AAC System:** http://YOUR_WINDOWS_IP:8081

### Unified Dashboard
- **Three-Device Monitor:** http://localhost:9090 (on MacBook)

## 🔧 Device Roles Summary

| Device | Role | Memory | Services | Access |
|--------|------|--------|----------|---------|
| MacBook M1 | Lightweight Hub | <256MB | Mobile Center | Always On |
| HP Laptop | Heavy Computation | 8-16GB | All Agents/AAC | High Performance |
| iPhone/iPad | Mobile Interface | <100MB | PWA Client | Battery Optimized |

## ⚡ Performance Optimizations Applied

### MacBook M1
- Neural Engine disabled (memory conservation)
- Memory compression maximum
- Aggressive cleanup every API call
- Always-on connectivity

### HP Laptop Windows
- High-performance power plan
- 16GB memory allocation for services
- Auto-start heavy computation services
- Primary storage for all data

### iPhone/iPad
- PWA with offline capabilities
- Background refresh for alerts
- Battery optimization
- Multi-device handoff

## 🔍 Testing Your Setup

### Quick Test Commands

**MacBook:**
```bash
# Check services
curl http://localhost:8080/api/status
curl http://localhost:8080/sasp/health
```

**Windows (from MacBook):**
```powershell
# Test connectivity
.\WINDOWS_THREE_DEVICE_SETUP.ps1 -MacIP YOUR_MAC_IP
```

**Mobile:**
- Open PWA on iPhone/iPad
- Check "Windows Operations" buttons
- Verify status updates

### Full System Test
```bash
# Run comprehensive test
python test_sasp_protocol.py
```

## 🆘 Troubleshooting

### MacBook Issues
```bash
# Restart services
pkill -f mobile_command_center
./m1_8gb_launch.sh
```

### Windows Connectivity
```powershell
# Re-sync with MacBook
.\sync_to_windows.ps1 -MacIP YOUR_MAC_IP -StartServices
```

### Mobile Issues
- Clear Safari cache
- Reinstall PWA
- Check network connectivity

## 📊 Monitoring & Maintenance

### Daily Checks
- MacBook memory usage (<256MB)
- Windows service status (all running)
- Mobile PWA connectivity

### Weekly Maintenance
- Update all device software
- Clear temporary files
- Review system logs

### Performance Tuning
- Adjust memory limits based on usage
- Optimize network settings
- Update power management profiles

## 🎯 Success Metrics

✅ **All Green Indicators:**
- MacBook: <256MB memory, services running
- Windows: All heavy services active, <80% resource usage
- Mobile: PWA installed, real-time updates working

✅ **Response Times:**
- Local commands: <2 seconds
- Cross-device sync: <5 seconds
- Mobile interface: <1 second load

✅ **Uptime:**
- MacBook hub: 99%+ (always-on)
- Windows services: 95%+ (high-performance)
- Mobile access: 100% (PWA offline capable)

---

## 🎉 Deployment Complete!

Your three-device Super Agency is now optimized and ready for operation. The system leverages each device's strengths:

- **MacBook M1:** Efficient coordination hub
- **HP Laptop:** Powerful computation engine
- **iPhone/iPad:** Mobile command interface

Enjoy your distributed Super Agency command center! 🚀
EOF

    log_success "Deployment instructions generated"
}

# Main deployment
main() {
    echo "🚀 Quick Three-Device Super Agency Deployment"
    echo "=============================================="
    echo "MacBook M1 8GB + HP Laptop Windows + iPhone/iPad"
    echo ""

    preflight_checks
    setup_macbook
    setup_three_device
    generate_deployment_instructions

    echo ""
    echo "🎉 DEPLOYMENT COMPLETE!"
    echo "======================="
    echo ""
    echo "📖 Next Steps: DEPLOYMENT_INSTRUCTIONS.md"
    echo ""
    echo "🚀 Quick Launch:"
    echo "   MacBook: ./m1_8gb_launch.sh"
    echo "   Windows: .\WINDOWS_THREE_DEVICE_SETUP.ps1 -FullSetup"
    echo "   Mobile: Follow MOBILE_DEVICE_SETUP.md"
    echo ""
    echo "📱 Access: http://YOUR_LOCAL_IP:8080"
}

main "$@"</content>
<parameter name="filePath">c:/Users/gripa/OneDrive - Grip and Ripp/Super Agency/Super-Agency/quick_three_device_deploy.sh