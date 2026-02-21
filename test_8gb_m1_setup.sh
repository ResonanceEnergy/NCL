#!/bin/bash
# 8GB M1 MacBook Test Script
# Verify ultra-optimized setup works correctly

echo "🧪 Super Agency 8GB M1 MacBook Test"
echo "==================================="

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
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
if (( $(echo "$ram_gb >= 8" | bc -l) )); then
    log_success "RAM: ${ram_gb}GB (sufficient for 8GB M1 mode)"
else
    log_error "RAM: ${ram_gb}GB (8GB+ required)"
fi

# Test 2: Chip Check
echo "2. Checking chip..."
chip=$(sysctl -n machdep.cpu.brand_string)
if [[ "$chip" == *"Apple"* ]]; then
    log_success "Chip: $chip (Apple Silicon detected)"
else
    log_error "Chip: $chip (Apple Silicon recommended)"
fi

# Test 3: Python Check
echo "3. Checking Python..."
if command -v python3 &> /dev/null; then
    python_version=$(python3 --version)
    log_success "Python: $python_version"
else
    log_error "Python 3 not found"
fi

# Test 4: Dependencies Check
echo "4. Checking dependencies..."
deps=("flask" "requests" "psutil")
for dep in "${deps[@]}"; do
    if python3 -c "import $dep" 2>/dev/null; then
        log_success "$dep installed"
    else
        log_error "$dep missing"
    fi
done

# Test 5: Config Files Check
echo "5. Checking configuration..."
config_files=("config/8gb_m1_macbook.json" "config/distributed.json")
for config in "${config_files[@]}"; do
    if [ -f "$config" ]; then
        log_success "$config exists"
    else
        log_error "$config missing"
    fi
done

# Test 6: Scripts Check
echo "6. Checking scripts..."
scripts=("macbook_launch.sh" "sync_to_windows.ps1")
for script in "${scripts[@]}"; do
    if [ -f "$script" ]; then
        log_success "$script exists"
    else
        log_error "$script missing"
    fi
done

# Test 7: Memory Limits Check
echo "7. Checking memory limits..."
if python3 -c "
import json
try:
    with open('config/8gb_m1_macbook.json', 'r') as f:
        config = json.load(f)
    limits = config['memory_optimization']
    if limits['max_agents'] == 1 and limits['agent_memory_limit'] == '512MB':
        print('Memory limits optimized for 8GB M1')
    else:
        print('Memory limits not optimized')
        exit(1)
except:
    print('Config file error')
    exit(1)
" 2>/dev/null; then
    log_success "Memory limits optimized for 8GB M1"
else
    log_error "Memory limits not optimized"
fi

echo ""
echo "🧪 Test complete. Check results above."