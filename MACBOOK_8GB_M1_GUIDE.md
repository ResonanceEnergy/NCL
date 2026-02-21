# Super Agency 8GB M1 MacBook Setup Guide
## Quick Start for Mac Users

**Date:** February 20, 2026
**System:** MacBook with 8GB RAM + Apple M1/M2 chip

---

## 🚀 One-Command Setup

```bash
# Make scripts executable
chmod +x macbook_8gb_m1_setup.sh test_8gb_m1_setup.sh macbook_launch.sh

# Run setup
./macbook_8gb_m1_setup.sh

# Test setup
./test_8gb_m1_setup.sh

# Launch system
./macbook_launch.sh
```

---

## 📋 Prerequisites

### 1. System Requirements
- **macOS:** Sequoia 15.x (or later)
- **RAM:** 8GB minimum (M1/M2 chip)
- **Storage:** 20GB free space

### 2. Install Dependencies
```bash
# Install Homebrew (if not installed)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install Python 3.9+
brew install python

# Install required packages
pip3 install flask requests psutil
```

---

## 🛠️ Manual Setup Steps

### Step 1: Clone Repository
```bash
git clone https://github.com/ResonanceEnergy/ResonanceEnergy_SuperAgency.git
cd ResonanceEnergy_SuperAgency
```

### Step 2: Configure for 8GB M1
```bash
# Run 8GB M1 optimized setup
./macbook_8gb_m1_setup.sh
```

### Step 3: Test Configuration
```bash
# Verify everything works
./test_8gb_m1_setup.sh
```

### Step 4: Launch Services
```bash
# Start the system
./macbook_launch.sh
```

---

## 📱 Mobile Access

Once running, access from your iPhone/iPad:

1. **Find Mac IP:** Check system status output
2. **Open Browser:** Go to `http://[MAC_IP]:8080`
3. **Install PWA:** Add to home screen for offline access

---

## 🔄 Windows Integration

For heavy computation:

1. **Connect Windows Laptop:** Ensure on same network
2. **Auto-Discovery:** System will find Windows automatically
3. **Delegate Tasks:** Heavy processing sent to Windows
4. **Monitor Results:** View on mobile interface

---

## ⚡ Performance Notes

- **Memory Mode:** Ultra-conservative (512MB per agent)
- **Max Agents:** 1 simultaneous agent
- **Heavy Tasks:** Automatically delegated to Windows
- **Battery Life:** Optimized for mobile use

---

## 🆘 Troubleshooting

### Common Issues:

**"Python not found"**
```bash
brew install python
```

**"Permission denied"**
```bash
chmod +x *.sh
```

**"Memory error"**
- Close other applications
- Restart Mac
- Check Activity Monitor

**"Windows not found"**
- Ensure Windows laptop on same WiFi
- Check firewall settings
- Restart both devices

---

## 📊 System Status

Check system health:
```bash
./test_8gb_m1_setup.sh
```

View running services:
```bash
ps aux | grep python
```

---

## 🎯 Next Steps

1. **Connect Windows:** Add HP laptop for heavy computation
2. **Configure Mobile:** Set up iPhone/iPad access
3. **Run Daily Operations:** Enable automated portfolio management
4. **Monitor Performance:** Check system health regularly

---

**Ready to deploy your Super Agency on 8GB M1 MacBook! 🚀**