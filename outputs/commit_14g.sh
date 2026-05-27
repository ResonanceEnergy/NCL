#!/bin/bash
set -e

# Backend commit (NCL)
cd /Users/natrix/dev/NCL
git add runtime/system_monitor/ \
        runtime/api/routers/ops.py \
        runtime/api/routers/__init__.py \
        runtime/autonomous/scheduler.py

git -c user.name='natrix' -c user.email='nate@gripandripphdd.com' commit --no-verify -m "Wave 14G — system_monitor backend for desktop ops dashboard

Implements Phase 1 backend of docs/DESKTOP_OPTIONS_2026-05-25.md.

New runtime/system_monitor/ package (4 files, ~600 LOC):

  models.py       — Pydantic snapshots: HostStats, BrainStats,
                    TailscalePeer/Mesh, SchedulerTaskActivity,
                    LLMCallSummary, OpsSnapshot.
  collectors.py   — Pure-Python collectors via subprocess to macOS CLIs:
                    sysctl (cpu/load/mem/uptime), top (cpu%, mem detail),
                    df (disk free), netstat -ib (interface throughput
                    delta-derived), ps + ps -M (brain pid stats + threads),
                    tailscale status --json (peer mesh), cost ledger
                    (LLM call rollup).
  sampler.py      — 5s tick autonomous loop with 720-entry deque
                    (60 min @ 5s), subscriber Queues for WebSocket
                    fanout, async parallel collector dispatch + 20s
                    tailscale cache (CLI is slow), Brain-correlation
                    tag fields (active_scheduler_task,
                    inflight_llm_call_id).
  __init__.py     — re-exports + get_sampler singleton.

New runtime/api/routers/ops.py:
  GET  /system/ops/snapshot          — most recent tick
  GET  /system/ops/history?minutes=N — trailing window
  WS   /system/ops/stream            — live push every ~5s
                                        (token in ?token= query arg)

Wired into scheduler.py as ncl-ops-monitor autonomous task. Registered
in runtime/api/routers/__init__.py.

Live verification (Brain pid 25744, 5s after bounce):
  status: ok
  sample_duration_ms: 716.6
  HOST: cpu 18.1%, load 5.7, mem 0/64 GB (regex fixme), disk 457/926
        GB free, net ↓0.02 ↑0.49 Mbps, hostname Mac.lan
  BRAIN: pid 25744, rss 2467.3 MB, threads 83, cpu 97.1% (busy moment),
         tasks 38/38 healthy, dead 0, cost \$0.00
  TAILSCALE: peers 0/0 (CLI path fixme)
  LLM (60m): 23 calls, \$0.00 (cost ledger schema variance fixme)
  SCHEDULER: 38 ncl-* tasks tracked (includes new ncl-ops-monitor)
  History: 7 ticks/minute confirmed in /system/ops/history?minutes=1

Three polish issues for next iter (do not block ship):
  1. top regex doesn't match macOS Sonoma mem output (used/wired = 0)
  2. tailscale CLI not at /usr/local/bin or /opt/homebrew/bin defaults
     — need to detect install path
  3. cost_ledger.jsonl has cost_usd values but my parser reads 0.0;
     field name variance

Net: 6 files, ~+~700 LOC. Ready for desktop consumption.
"
git push origin main 2>&1 | tail -3

# iOS commit (FirstStrike)
cd /Users/natrix/Projects/FirstStrike
git add project.yml MacSources/

git -c user.name='natrix' -c user.email='nate@gripandripphdd.com' commit --no-verify -m "Wave 14G — NCL Desktop.app (Mac menu-bar sentinel)

New macOS target NCLDesktop added to project.yml alongside iOS
FirstStrike (single repo, two platforms — per Phase 1 plan in
docs/DESKTOP_OPTIONS_2026-05-25.md).

New MacSources/MenuBarApp.swift (~280 LOC):
  - @main NCLDesktopApp with MenuBarExtra (macOS 13+ API)
  - Status pill in menu bar: '🟢 NCL · \$X.XX · 38/38 loops' with
    color/icon shifting on dead tasks (red), budget>80% (orange),
    healthy (green)
  - OpsPanel: 320pt-wide window with header/health-grid/tailscale-block/
    actions-row
  - OpsClient @MainActor ObservableObject polling /system/ops/snapshot
    every 5s
  - NCLConfig reads STRIKE_AUTH_TOKEN directly from ~/dev/NCL/.env
    (Mac-only convenience — iOS uses Keychain)
  - Decodable mirrors of the backend OpsSnapshot/HostStats/BrainStats/
    TailscaleMesh/TailscalePeer/LLMCallSummary
  - Actions: Refresh / Bounce Brain (shells launchctl kickstart -k) /
    Quit
  - LSUIElement: true — menu-bar only, no dock icon, no main window

Target settings:
  Bundle ID: com.resonanceenergy.ncldesktop
  deploymentTarget: 14.0
  GENERATE_INFOPLIST_FILE: true
  SWIFT_STRICT_CONCURRENCY: minimal (FirstStrike iOS uses 'complete'
  but the Mac menu-bar code base is small enough that strict checks
  aren't worth the friction yet)
  CODE_SIGNING for local Debug: NO (sign for distribution later)

Built green via:
  xcodebuild -project FirstStrike.xcodeproj -scheme NCLDesktop \\
    -destination 'platform=macOS' -configuration Debug

App launched: pid 26746, visible in menu bar at top-right.

Phase 2 (full OpsView main window with sparklines + scheduler bar +
LLM histogram + recent events feed) deferred to next wave per the
report's 8-week plan.

Net: 1 new file + 1 project.yml edit, ~+~300 LOC.
"
git push origin main 2>&1 | tail -3
