#!/bin/bash
# 16GB MacBook Test Script
# Verify distributed setup works correctly

echo "🧪 Super Agency 16GB MacBook Test"
echo "================================="

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
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

# Test 1: RAM Check
echo "1. Checking RAM..."
ram_gb=$(echo "scale=1; $(sysctl -n hw.memsize) / 1024 / 1024 / 1024" | bc)
if (( $(echo "$ram_gb >= 16" | bc -l) )); then
    log_success "RAM: ${ram_gb}GB (sufficient)"
else
    log_error "RAM: ${ram_gb}GB (upgrade recommended)"
fi

# Test 2: Python Check
echo "2. Checking Python..."
if command -v python3 &> /dev/null; then
    python_version=$(python3 --version)
    log_success "Python: $python_version"
else
    log_error "Python 3 not found"
fi

# Test 3: Dependencies Check
echo "3. Checking dependencies..."
deps=("flask" "requests" "psutil")
for dep in "${deps[@]}"; do
    if python3 -c "import $dep" 2>/dev/null; then
        log_success "$dep installed"
    else
        log_error "$dep missing"
    fi
done

# Test 4: Config Files Check
echo "4. Checking configuration..."
config_files=("config/16gb_macbook.json" "config/distributed.json")
for config in "${config_files[@]}"; do
    if [ -f "$config" ]; then
        log_success "$config exists"
    else
        log_error "$config missing"
    fi
done

# Test 5: Scripts Check
echo "5. Checking scripts..."
scripts=("macbook_launch.sh" "sync_to_windows.ps1")
for script in "${scripts[@]}"; do
    if [ -f "$script" ]; then
        log_success "$script exists"
    else
        log_error "$script missing"
    fi
done

# Test 6: Mobile Interface Check
echo "6. Checking mobile interface..."
if [ -f "templates/index.html" ] && [ -f "static/css/mobile.css" ] && [ -f "static/js/mobile.js" ]; then
    log_success "Mobile interface files present"
else
    log_error "Mobile interface files missing"
fi

# Test 7: Port Availability Check
echo "7. Checking port availability..."
ports=(8080 5000 3000)
for port in "${ports[@]}"; do
    if lsof -Pi :$port -sTCP:LISTEN -t >/dev/null 2>&1; then
        log_error "Port $port in use"
    else
        log_success "Port $port available"
    fi
done

echo ""
log_info "Test complete! Review results above."
echo ""
echo "🚀 If all tests pass, run:"
echo "   ./macbook_launch.sh"
echo ""
echo "🔄 Then on Windows:"
echo "   .\sync_to_windows.ps1 -MacIP [your-mac-ip] -StartServices"</content>
<parameter name="filePath">c:/Users/gripa/OneDrive - Grip and Ripp/Super Agency/Super-Agency/test_16gb_setup.sh