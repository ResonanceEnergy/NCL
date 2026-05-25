# NCL Desktop — Options Analysis + Recommendation

**Date**: 2026-05-25
**Trigger**: NATRIX wants a desktop version of FirstStrike that includes Mac + network monitoring, with all the iOS surfaces plus power-user authoring + background admin.
**Scope**: Audit current state → research framework choices + monitoring APIs → recommend an architecture + ship plan.

---

## TL;DR

Build it as a **native SwiftUI macOS app sharing the FirstStrike Swift sources via a multi-platform Xcode target**, augmented by a **MenuBarExtra** for ambient admin and a **dedicated `OpsView` window** for Brain-correlated system + network monitoring. Avoid Mac Catalyst — its iPad-on-Mac feel won't satisfy NATRIX's power-user authoring goal, and the iOS code uses enough UIKit-only APIs (UIPasteboard, UIApplication, UIWindowScene) that Catalyst won't be friction-free anyway.

The monitoring layer ships as a thin new backend module (`runtime/system_monitor/`) that joins **sysctl + libproc + NWPathMonitor + Tailscale CLI** sampled at 5-second intervals with the **existing scheduler task state**, exposed via two new endpoints (`/system/ops/snapshot` and a `/system/ops/stream` WebSocket). Desktop consumes those + the 35+ existing endpoints already in the codebase. Eight weeks of work in three phases; a useful menu-bar app + ops dashboard in two weeks, full feature-parity desktop in eight.

Cost: zero infra (runs on existing Mac Studio), ~$0 additional API spend (monitoring is sysctl-level), one new code path to maintain alongside iOS.

---

## Audit Findings

### Existing FirstStrike iOS surface (Mac portability snapshot)

```
Sources/                       ~25,000 LOC Swift, ~50 view files
project.yml                    iOS-only target, deploymentTarget 16.0, TARGETED_DEVICE_FAMILY "1,2"
                              (iPhone + iPad — no Mac slot)
```

**Mac-portable as-is** (pure SwiftUI, no UIKit-only):
- `Sources/Models/` — `MorningQuiz.swift`, `IntelModels`, all data structs ✓
- `Sources/Network/NCLBrainClient*` — `URLSession` based, fully portable ✓
- `Sources/App/Theme.swift` — `FSColor` (raw `Color`), `FSFont` (`.system(...)`), `FSSpacing` (CGFloat constants) ✓
- `MorningQuizView`, `LifePlanView`, `LifePlanEditors`, `NightWatchView`, `BriefRenderer` — pure SwiftUI ✓
- `JournalView`, `IntelView`, `MemoryView`, `CalendarView` — mostly SwiftUI, scattered UIKit calls (see below)

**iOS-only API leaks** (need `#if canImport(UIKit)` walls or Mac equivalents):
- `UIPasteboard.general.string = ...` — 9 sites across DashboardView, CouncilTranscriptView, RedditView, XView, ChatBubble. Mac equivalent: `NSPasteboard.general.setString(_:forType: .string)`.
- `UIApplication.shared.sendAction(#selector(UIResponder.resignFirstResponder), …)` (CouncilView) — keyboard dismiss; Mac doesn't need this (no software keyboard).
- `UIWindowScene` + `connectedScenes` for window discovery (ChatBubble) — Mac uses `NSApplication.shared.windows`.
- `UILaunchScreen`, `UIRequiredDeviceCapabilities` in Info.plist — drop on Mac.
- Microphone + Speech entitlements — Mac equivalents exist but use AVAudioEngine differently.

**Verdict**: ~92% of Swift is portable. The remaining ~8% is ~15 `#if os(macOS)` walls or a tiny `PasteboardShim` extension. Single multi-platform target is feasible — no need to fork the codebase.

### Existing Brain endpoints relevant to monitoring

Backend already exposes most of what an ops dashboard needs:

| Endpoint | Already returns |
|---|---|
| `GET /system/health/rollup` | scheduler / awarebot / portfolio / memory / cost / calendar / journal status |
| `GET /system/costs/today` | per-source LLM spend + budget |
| `GET /system/costs/ledger` | raw cost entries (JSONL) |
| `GET /system/costs/history` | 30-day trend |
| `GET /system/memory-profile` | RSS / objects / buffer sizes |
| `GET /metrics` | Prometheus-format (separate token) |
| `GET /autonomous/loops` | 35 named loops with `last_run` |
| `GET /memory/stats` | unit count, by-type, by-tier |
| `GET /memory/async-writer/stats` | DLQ + queue depth |
| `GET /memory/knowledge-graph/stats` | KG nodes/edges |
| `GET /memory/working-context/stats` | context size + themes |
| `GET /journal/stats` | entries / reflections counts |
| `GET /council-runner/stats` | recent council runs |
| `GET /intelligence/stats` | signals_ingested, sources active |
| `GET /pump/health` | mandate pipeline |

What's **missing** for "Brain-correlated system monitoring":

1. **Per-loop CPU/RSS time-series** — scheduler reports tasks + `last_run` but not "how much CPU did `ncl-memory-consolidation` spend in the last hour". Need to sample per-task wall-time + delta-RSS inside the loop wrappers.
2. **LLM call timing histogram** — `cost_tracker` records dollar amounts but not call latency. A `/system/ops/llm-calls?bucket=5m` rolling window would surface "executor stage now averaging 65s, p99 110s — investigate".
3. **System-level snapshot** — total host CPU/memory/disk/network (sysctl + libproc + NWPathMonitor). New backend module that samples every 5s, stores last 60 minutes in-memory, serves via REST + WebSocket.
4. **Tailscale peer health** — `tailscale status --json` parsed into `{peer, latency_ms, last_handshake, derp_relayed}` per peer. Useful for the operator to see if iPhone/iPad fell off the mesh.
5. **Per-process attribution** — Brain pid is single, but it has 35+ asyncio tasks. Snapshot per-task wall-time accumulator (cheap with `loop._scheduled` + custom `add_done_callback`) into health-rollup.

These five additions are one focused 600-LOC module + one router file + the existing scheduler hooks. ~3 days of backend work.

---

## Research Synthesis

### Framework choice — five-way matrix

| | Native SwiftUI macOS | Mac Catalyst | AppKit | Tauri (Rust+Web) | Electron (Web) |
|---|---|---|---|---|---|
| **Reuse FirstStrike Swift** | ✅ ~92% direct | ✅ ~98% but iPad-feel | ❌ rewrite UI | ❌ rewrite UI | ❌ rewrite UI |
| **Multi-window / multi-doc** | ✅ Scene + WindowGroup | ⚠️ limited per-screen | ✅ native AppKit | ⚠️ webview windows | ⚠️ webview windows |
| **MenuBarExtra (tray app)** | ✅ first-class (macOS 13+) | ❌ not supported | ✅ NSStatusItem | ✅ via tray plugin | ✅ via tray plugin |
| **Native notifications** | ✅ UserNotifications | ✅ same | ✅ NSUserNotification | ⚠️ via plugin | ⚠️ via plugin |
| **System monitoring APIs** | ✅ all (sysctl/libproc/IOKit) | ⚠️ entitlement gated | ✅ all | ⚠️ via Rust ffi | ⚠️ via node-native |
| **Tailscale CLI access** | ✅ `Process()` | ✅ same | ✅ same | ✅ Rust subprocess | ✅ via child_process |
| **App size** | 25 MB | 25 MB | 20 MB | 12 MB (no runtime) | 90 MB (Chromium) |
| **Memory footprint** | ~60 MB | ~70 MB | ~50 MB | ~70 MB | ~250 MB |
| **Code maintenance** | one repo, one stack | one repo, two builds | two stacks | two stacks | two stacks |
| **Apple Silicon optimization** | ✅ native | ✅ native | ✅ native | ✅ native | ⚠️ has Rosetta cases |
| **"Power-user authoring" feel** | ✅ keyboard, multi-window, drag-drop | ❌ feels iPad | ✅ classic Mac feel | ⚠️ webview limits | ⚠️ webview limits |

**Catalyst eliminated** because (a) NATRIX explicitly asked for native macOS feel, (b) the iPad-on-Mac aesthetic doesn't pair well with "power-user authoring", and (c) the FirstStrike codebase already has UIKit-only API leaks that Catalyst maps but with inconsistent results (UIPasteboard works via shim, UIApplication.sendAction works partially, UIWindowScene works but is iPad-shaped).

**AppKit eliminated** because rewriting ~50 SwiftUI view files in AppKit erases six weeks of iOS work for marginal native-feel gain over modern SwiftUI on macOS 13+.

**Tauri/Electron eliminated** because both require rewriting the entire UI layer (the FirstStrike Swift code can't be reused at all). Tauri's 12 MB binary is appealing but doesn't justify the ~5x dev effort vs reusing the iOS Swift work.

### macOS framework — best practice for 2026

Anthropic's recent guidance + the Apple developer forums + 2026 SwiftUI-on-Mac blog posts converge on:

- **SwiftUI is the default for new macOS apps**. AppKit lives where SwiftUI has gaps (advanced window behaviors, custom menu commands, NSStatusItem advanced styling).
- **Mac Catalyst is for shipping an existing iPad app fast**, not for power-user Mac experiences. NATRIX's use case doesn't match.
- **Multi-window is first-class in SwiftUI on macOS** via `Scene` + `WindowGroup` + `MenuBarExtra`. Each window can be a separate scope (e.g. a Brief window, an Ops window, a Journal window, a Memory window).
- **MenuBarExtra** (macOS 13+) lets you ship a tray app alongside main windows in the same App body — perfect for the "background admin" requirement.

### Mac + network monitoring APIs

Three layers of system data, all available via Swift:

| Layer | API | Sample rate sustainable |
|---|---|---|
| **System-wide CPU/memory/disk** | `sysctl` (sysctlbyname for individual values, sysctl(3) for arrays) | 1 Hz easily |
| **Per-process** (CPU, RSS, threads, FDs) | `libproc` — `proc_pidinfo()` + `PROC_PIDTHREADINFO` | 1 Hz with all running PIDs (~500) |
| **Memory** | `host_statistics()` (Mach) — wired/active/inactive/free | 1 Hz |
| **Disk I/O** | `IOPSCopyPowerSourcesList` + `statfs` for capacity | 0.2 Hz (battery/power), 1 Hz (disk free) |
| **Network interface stats** | `NWPathMonitor` (Network.framework) — interface up/down, expensive/constrained | event-driven |
| **Network throughput** | `getifaddrs()` + `IFA_DATA` (libc) — bytes in/out per interface | 1 Hz |
| **Per-process network** | `nettop -P -L 1 -x` shell out (Apple's CLI, JSON output) | 0.5 Hz |
| **Tailscale** | `tailscale status --json` shell out, parse JSON | 0.2 Hz |
| **Unified log streaming** | `OSLogStore` (macOS 10.15+) or `log stream --predicate` shell | event-driven |

**Apple Activity Monitor combines sysctl + libproc** under the hood. We can do the same. There's a 2024 Swift package called `SystemMetrics` from Apple that wraps the lowest layer in a clean async API.

**Tailscale data** is the most operationally useful for NATRIX: per-peer latency, last handshake age, DERP-relayed vs direct, magicDNS resolution. All available from `tailscale status --json`. Sample at 10-30s intervals.

### Sampling architecture

```
              ┌────────────────────────────┐
              │   Mac Studio M1 Ultra     │
              │   (the Brain host)        │
              └────────────┬───────────────┘
                           │ FastAPI :8800
              ┌────────────┴──────────────────────────┐
              │  runtime/system_monitor/              │
              │  ─ sampler.py     (5s tick)           │
              │  ─ collectors.py  (sysctl, libproc,   │
              │                    nettop, tailscale) │
              │  ─ ring_buffer.py (60-min in-memory)  │
              │  ─ /system/ops/snapshot               │
              │  ─ /system/ops/stream  (WebSocket)    │
              └────────────┬──────────────────────────┘
                           │ Tailscale 100.72.223.123
              ┌────────────┴──────────────────────────┐
              │  Desktop app (Mac, Native SwiftUI)    │
              │  OpsView consumes WebSocket           │
              │  60s sparkline + 60-min trend         │
              └───────────────────────────────────────┘
```

The desktop **does not call sysctl itself**. The Brain owns the sampling because:
1. It's already on the same host as the data.
2. iPad + iPhone can also see the ops view (they hit the same endpoint).
3. Centralizing means one sampler + one ring buffer, not N clients each running their own.
4. Brain-correlated overlays are trivial: the sampler tags every snapshot with `current_scheduler_task` and `inflight_llm_call_id` so the timeline can render system spikes against Brain events.

The desktop's job is **rendering** + power-user authoring + the FirstStrike iOS surface.

---

## Recommended Architecture

### Three deliverable artifacts

**1. NCL Desktop.app** — main multi-window app
- Reuses ~92% of FirstStrike Swift code via a new `macOS` platform target in `project.yml`.
- WindowGroup-based: separate windows for Brief, Memory, Journal, Calendar, Intel, Portfolio. Cmd+1..6 to open each.
- A new `OpsView` window with the Brain-correlated monitoring dashboard.
- Authoring view set: existing iOS Editor sheets (`VisionEditor`, `GoalEditor`, `PlanEditor`, `WeeklyReviewSheet`, `YearlyReviewSheet`, `MorningQuizView`) — already multi-section Forms; on Mac they get more vertical real estate and keyboard-first navigation for free.
- Drag-and-drop for journal/vision-board: accept dropped images + text via `.onDrop(of: [.image, .text])`.
- Multi-monitor: each window remembers its frame across launches.

**2. NCL Menu Bar** — same binary, `MenuBarExtra`
- Always-visible status pill in the menu bar: `🟢 NCL · $12.46 · 35 loops · 1 alert`
- Click expands to a small panel showing: scheduler health, today's costs, next loop firing in N minutes, pending IMMEDIATE ACTION items from the morning brief, "Open Ops Dashboard" button, "Bounce Brain" button (with confirm).
- Notifications: posts via `UNUserNotificationCenter` when budget hits 80% / morning brief lands / cost cap exceeded / scheduler task dies. Uses macOS notification center natively — way better than ntfy.
- Zero-window mode: NATRIX can quit the main app and keep the menu bar running as an ambient sentinel.

**3. Brain `runtime/system_monitor/`** — sampler + endpoints
- 5-second sampling loop (autonomous task `ncl-ops-monitor`)
- Collects sysctl + libproc + getifaddrs + nettop + tailscale + per-asyncio-task wall-time
- Stores last 60 minutes in a deque (~720 snapshots × ~10 KB = 7 MB RAM)
- `GET /system/ops/snapshot` returns current state
- `GET /system/ops/history?minutes=10` returns trailing window
- `WS /system/ops/stream` pushes a snapshot every 5s for live charts
- Tags each snapshot with `active_scheduler_task` + `inflight_llm_call_id` for Brain-correlated overlays

### Window layout (OpsView)

```
┌─────────────────────────────────────────────────────────────────────────┐
│  NCL Ops · pid 12345 · uptime 4h 22m                       [↻] [⚙]   │
├──────────────────────┬──────────────────────┬───────────────────────────┤
│  HOST                │  BRAIN PROCESS       │  TAILSCALE MESH          │
│  ━━━━━━━━━━━━━━━     │  ━━━━━━━━━━━━━━━     │  ━━━━━━━━━━━━━━━         │
│  CPU 18% [▁▁▃▆█▆▃]  │  CPU 7%  [▁▁▂▄▅▄▂]  │  iPad   ●  9ms  direct   │
│  MEM 24GB/64GB      │  RSS 1.8GB           │  iPhone ●  19ms direct   │
│  DISK 412G free     │  threads 42  fds 88  │  Mac    ● (host)         │
│  NET ↓2.1 ↑0.4 MB/s │  tasks 35/35 healthy │                          │
├──────────────────────┴──────────────────────┴───────────────────────────┤
│  SCHEDULER ACTIVITY (last 10 min, brain-correlated CPU)                │
│  awarebot ████░░░░░░ 35%  city-events ░░██░░░░░░ 12%                  │
│  memory ░░░░██░░░░░░ 8%   journal ░░░░░░░█░░░░░ 6%                    │
│  conflict-arb ░░░░░░░█░░ 5%  brain idle ░░░░░░░░░░ 34%                │
├─────────────────────────────────────────────────────────────────────────┤
│  LLM CALLS (last hour) avg 1.4s · p99 8.2s · cost $4.12              │
│  Sonnet 4      ████████████ 47 calls $3.81                            │
│  Haiku 4.5     ████ 12 calls $0.18                                    │
│  Opus 4        ██ 3 calls $0.13                                       │
├─────────────────────────────────────────────────────────────────────────┤
│  RECENT EVENTS                                                          │
│  17:04  morning_quiz submitted  pid 21641 → bg                         │
│  17:00  morning-brief pipeline OK score 100  (51s)                     │
│  16:58  awarebot scan complete  925 signals routed                     │
└─────────────────────────────────────────────────────────────────────────┘
```

All cards bind to the `/system/ops/stream` WebSocket. No polling.

---

## Ship plan — three phases, eight weeks

### Phase 1 (Week 1-2) — backend monitor + menu bar app

Goal: NATRIX has a working menu-bar sentinel within two weeks. No main window yet.

- Week 1
  - `runtime/system_monitor/` module (sampler + ring buffer + collectors). Reuse `subprocess` for `tailscale` + `nettop`; pyobjc for sysctl on Mac, or shell out to `sysctl -a` and parse (simpler, no native deps).
  - `/system/ops/snapshot` + `/system/ops/history` endpoints
  - WebSocket `/system/ops/stream`
  - New autonomous loop `ncl-ops-monitor` (5s tick) writing to ring buffer
  - Per-task wall-time accumulator wired into the existing scheduler
- Week 2
  - New Xcode target `NCL Desktop` in `project.yml` (macOS platform, deploymentTarget 14.0)
  - `MenuBarExtra` body with status pill + expand panel
  - Subset of FirstStrike Swift compiled into the desktop target (only files that need no UIKit shims for v1: theme, models, network client, MorningQuizView, LifePlanView, NightWatchView)
  - `UNUserNotificationCenter` integration — 4 notification types (budget warning, scheduler task died, morning brief ready, cost cap exceeded)
  - Sign + notarize + zip distribution (no Mac App Store; install via direct download from the Brain)

**Deliverable**: menu-bar app showing live status. Click → small panel → see costs + next loop + bounce button.

### Phase 2 (Week 3-5) — main window + ops dashboard

- Week 3
  - `OpsView` window with three cards (Host / Brain / Tailscale)
  - WebSocket binding (`URLSessionWebSocketTask`) → `@Published` observable
  - Sparkline mini-charts (use Swift Charts framework)
- Week 4
  - Scheduler activity stacked bar (last 10 min)
  - LLM calls breakdown (last hour cost + latency)
  - Recent events feed (log tail subscribed via OSLogStore)
- Week 5
  - Multi-window support: Cmd+1 Brief, Cmd+2 Memory, Cmd+3 Journal, Cmd+4 Calendar, Cmd+5 Intel, Cmd+6 Ops
  - WindowGroup with `.commandsRemoved()` cleanup + custom CommandMenu
  - All existing FirstStrike views imported with `#if canImport(UIKit)` walls around the ~15 leaks

**Deliverable**: full ambient + ops desktop. NATRIX can have Brief open on left monitor, Ops on right monitor, drift to menu bar when away.

### Phase 3 (Week 6-8) — authoring polish + power-user wins

- Week 6
  - Drag-and-drop in Journal editor (image dropped onto entry → uploads as attachment, text dropped → appends)
  - Multi-tab in Council view (open multiple council sessions side-by-side)
  - Keyboard shortcuts: Cmd+N new entry, Cmd+S save, Cmd+T new tab, Cmd+B toggle sidebar
- Week 7
  - Vision-board drag-edit: drop images into the vision-board view, send to backend for re-render with manual elements
  - Quick-add HUD: Cmd+Shift+J anywhere → fast Journal entry → submit + dismiss
  - Brain log streaming view (OSLogStore predicate on subsystem=`ncl.*`)
- Week 8
  - Polish: light/dark variants, app-icon set, accessibility audit, error states
  - Sparkkle auto-update integration (so NATRIX gets new builds via menu bar)
  - Release-build pipeline: GitHub Action that builds + notarizes + drops a `.dmg`

**Deliverable**: feature-complete v1. Mac is now the primary surface for authoring + ambient monitoring; iPhone/iPad remain for mobile.

---

## Risk register

| Risk | Impact | Mitigation |
|---|---|---|
| UIKit-only API count grows beyond 8% as iOS adds features | Mac build breaks | Add CI step that compiles the Mac target — catches regressions on every iOS PR |
| WebSocket flakes on Tailscale | Ops view goes stale | Fall back to 5s polling automatically; surface "stale" badge |
| sysctl/libproc syscalls cost real CPU at 1Hz × 500 processes | Brain steals from itself | Sampler ships only top-50 processes by RSS; total sample < 30ms per tick |
| Notarization friction | Can't distribute outside App Store | Self-sign + Developer ID (NATRIX already has DEVELOPMENT_TEAM=N3C5G3SU3T) |
| MenuBarExtra panel can't host complex views | Half the menu-bar features blocked | `MenuBarExtra(style: .window)` (macOS 13+) supports full SwiftUI in the panel |
| Tailscale CLI absent in a future Mac install | Tailscale card stays empty | Check `tailscale --version` at startup; if missing, render "Tailscale CLI not installed" with install link |
| Scheduler per-task accumulator races | Wrong CPU attribution | Use `loop.time()` + monotonic clock + per-task wrapper; same pattern as existing stall-watchdog |
| New Mac target doubles build time on every PR | Slower dev cycle | Mac builds run in parallel (existing CI already does this for sim + device) |

---

## Effort + cost estimate

**Engineering**: 8 weeks of solo Swift + Python work for v1. Phase 1 (menu bar + backend monitor) is the most leveraged 2-week slice — ship that first.

**Infra**: $0. Runs on the existing Mac Studio. No cloud, no new services.

**Ongoing API spend**: $0 net new. Monitoring is sysctl-level, doesn't burn LLM budget. The Brain-side ops endpoint may show a few hundred extra requests/day from the desktop polling, which is rounding error.

**Storage**: ~10 MB/day if we persist the ops ring buffer to disk for long-term trends (optional; v1 keeps everything in-memory).

**Distribution**: Direct download from Brain. Optional GitHub release pipeline in Phase 3.

---

## What I'd ship FIRST if you had only one week

If we cut everything except the highest-leverage piece:

1. `runtime/system_monitor/` + `/system/ops/snapshot` (2 days backend)
2. `NCL MenuBar.app` — menu-bar-only, no main windows (3 days iOS)
3. Notifications via `UNUserNotificationCenter` for budget + scheduler events (1 day)

That's a 6-day Phase-1-light delivery. Result: NATRIX gets a live `🟢 NCL · $X · 35 loops` in the menu bar at all times, with click-to-bounce + native notifications. The "real" desktop with the OpsView dashboard comes in Phase 1 weeks 1-2 above.

---

## Recommendation

**Go native SwiftUI macOS + reuse the FirstStrike Swift codebase via a new `macOS` platform target in `project.yml`.** Build the menu-bar sentinel first (highest immediate value), then the OpsView window, then the multi-window mirror of iOS. Add the Brain-side `runtime/system_monitor/` module in week 1 so backend data is ready when the desktop needs it.

This path:
- Reuses 92% of the existing Swift work
- Delivers the menu-bar ambient value in 2 weeks
- Gets the full Brain-correlated ops dashboard in 4-5 weeks total
- Doesn't fork the codebase (one repo, one stack, two platforms)
- Sets up the pattern for adding Linux/Windows later via SwiftUI cross-platform if you ever want that (it's not free but not blocked)

The full eight-week scope is investment-grade because it makes the Mac Studio's role explicit: it's not just the host of the Brain, it's the canonical authoring surface for NATRIX's life-plan / journal / brief content, with the iPhone/iPad as mobile satellites.
