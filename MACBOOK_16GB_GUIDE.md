# Super Agency 16GB MacBook Quick Start Guide
# Distributed Operations: Mac (light) + Windows (heavy)

## 🚀 QUICK START (5 minutes)

### Step 1: MacBook Setup
```bash
# On your MacBook
cd /path/to/Super-Agency
chmod +x macbook_16gb_setup.sh
./macbook_16gb_setup.sh
```

### Step 2: Launch Mac Services
```bash
# Still on MacBook
./macbook_launch.sh
```
**Expected output:**
- Mobile Command Center: http://localhost:8080
- Operations Interface: http://localhost:5000
- Matrix Monitor: http://localhost:3000

### Step 3: Windows Heavy Lifting
```powershell
# On Windows machine
cd C:\path\to\Super-Agency
.\sync_to_windows.ps1 -MacIP [your-mac-ip] -StartServices
```

### Step 4: Access from Mobile
- **Local:** http://[mac-ip]:8080
- **Install PWA:** Tap share button → "Add to Home Screen"

---

## 📊 WHAT RUNS WHERE

### MacBook (16GB - Operations Focus)
- ✅ **Mobile Command Center** (512MB)
- ✅ **Operations Interface** (1GB)
- ✅ **Matrix Monitor** (1GB)
- ✅ **Lightweight Commands** (2-3 agents max)

### Windows (Heavy Computation)
- ✅ **AAC Financial System** (unlimited RAM)
- ✅ **CPU Maximizer** (full cores)
- ✅ **Intelligence Gathering** (heavy AI/ML)
- ✅ **Inner Council Agents** (4-6 agents)

---

## 🎯 PHASED ROLLOUT PLAN

### Phase 1: Core Operations (This Week)
- [ ] MacBook setup complete
- [ ] Windows sync working
- [ ] Mobile access functional
- [ ] Basic command execution

### Phase 2: Full Integration (Next Week)
- [ ] Cross-platform communication
- [ ] Shared data synchronization
- [ ] Remote access (ngrok/cloudflare)
- [ ] Performance monitoring

### Phase 3: Scale Up (1-3 Months)
- [ ] Upgrade MacBook RAM if needed
- [ ] Add more Windows capacity
- [ ] Implement AWS overflow
- [ ] Full agent deployment

---

## 🔧 TROUBLESHOOTING

### MacBook Issues
```bash
# Check memory usage
top -l 1 | head -10

# Restart services
pkill -f python
./macbook_launch.sh
```

### Windows Issues
```powershell
# Check status
.\sync_to_windows.ps1 -Status

# Restart services
.\sync_to_windows.ps1 -StopServices
.\sync_to_windows.ps1 -StartServices
```

### Connection Issues
```bash
# Find Mac IP
ifconfig | grep inet
```
```powershell
# Test connection
Test-NetConnection [mac-ip] -Port 8080
```

---

## 📈 EXPECTED PERFORMANCE

### Memory Usage (MacBook)
- **Idle:** 800MB - 1.2GB
- **Active:** 1.5GB - 2.5GB
- **Peak:** < 4GB (with limits)

### Agent Capacity
- **MacBook:** 2-3 lightweight agents
- **Windows:** 4-6 full agents
- **Combined:** 6-9 agents total

### Response Times
- **Local access:** < 100ms
- **Cross-platform:** < 500ms
- **Mobile interface:** < 1s

---

## 🎮 USING YOUR SYSTEM

### Mobile Commands (Lightweight)
- ⚡ **Max CPU Light:** Balanced processing (4 cores)
- 🤖 **Deploy Agents Light:** 2 agents, 3-minute duration
- 🧠 **Intelligence Light:** Basic monitoring
- 💾 **Backup Light:** Compressed backup

### Windows Operations
- Full AAC financial system
- Unlimited CPU maximization
- Heavy intelligence gathering
- Complete Inner Council deployment

---

## 🔄 DAILY OPERATIONS

### Morning Startup
1. **MacBook:** `./macbook_launch.sh`
2. **Windows:** `.\sync_to_windows.ps1 -StartServices`
3. **Mobile:** Open PWA, check status

### Evening Shutdown
1. **Windows:** `.\sync_to_windows.ps1 -StopServices`
2. **MacBook:** Ctrl+C in terminal

### Weekly Maintenance
- Run memory doctrine backup
- Update agent configurations
- Test cross-platform sync

---

## 🚀 UPGRADE PATH

### Immediate (Next Month)
- MacBook RAM upgrade to 32GB (~$200-400)
- Additional Windows machine
- Network optimization

### Medium-term (3-6 Months)
- Mac Studio 128GB workstation
- Dedicated Windows server
- AWS integration for overflow

### Long-term (6-12 Months)
- Full data center setup
- Multiple Mac/Windows clusters
- Global distributed operations

---

**This 16GB setup gives you a fully functional Super Agency command center today, with room to scale as your operations grow!** 🎯</content>
<parameter name="filePath">c:/Users/gripa/OneDrive - Grip and Ripp/Super Agency/Super-Agency/MACBOOK_16GB_GUIDE.md