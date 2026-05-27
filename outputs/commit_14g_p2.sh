#!/bin/bash
set -e

# Backend commit
cd /Users/natrix/dev/NCL
git add runtime/system_monitor/collectors.py

git -c user.name='natrix' -c user.email='nate@gripandripphdd.com' commit --no-verify -m "Wave 14G Phase 2 — collector polish (mem, tailscale, cost)

Three fixes to runtime/system_monitor/collectors.py addressing the
follow-up items left from Phase 1:

1. Host memory via vm_stat (was top regex — broken on Sonoma).
   vm_stat reports pages × page_size; we sum wired+active+compressed
   for used, free+inactive for free. Pre-fix: mem_used_gb=0.0,
   mem_wired_gb=0.0. Post-fix: 46.3/64.0 GB used, 28.46 GB wired,
   16.87 GB free.

2. Tailscale CLI path detection (was hard-coded /usr/local/bin and
   /opt/homebrew/bin only). New _find_tailscale() probes 4 candidate
   paths in priority order:
     /Applications/Tailscale.app/Contents/MacOS/Tailscale   ← MAS install
     /usr/local/bin/tailscale                               ← standalone
     /opt/homebrew/bin/tailscale                            ← Homebrew
     /usr/bin/tailscale                                     ← Linux
   First-hit cached. Pre-fix: 0/0 peers. Post-fix: 2/2 peers online
   (iPad + iPhone at 100.76.184.123 + 100.82.59.60).

3. Cost ledger schema fix. Ledger field is amount_usd (not cost_usd);
   model lives in metadata.model (not in description text). Both
   fixed with fall-back keys so forward-compat is preserved. Pre-fix:
   call_count=23, total_cost_usd=0.0. Post-fix: call_count=62,
   total_cost_usd=0.3257 with per-model breakdown.

Net: 1 file, ~+30/-15 LOC.
"
git push origin main 2>&1 | tail -3

# iOS commit
cd /Users/natrix/Projects/FirstStrike
git add MacSources/OpsView.swift MacSources/MenuBarApp.swift

git -c user.name='natrix' -c user.email='nate@gripandripphdd.com' commit --no-verify -m "Wave 14G Phase 2 iOS — OpsView main window (Cmd+O)

New MacSources/OpsView.swift (~400 LOC) implementing the full
brain-correlated ops dashboard described in Phase 2 of
docs/DESKTOP_OPTIONS_2026-05-25.md.

Three cards (Host / Brain / Tailscale) on top:
  HOST card     — CPU% sparkline (60s), Memory sparkline, Disk free,
                  Net ↓↑ Mbps
  BRAIN card    — CPU% sparkline, RSS sparkline, threads, loops
                  X/Y healthy count, Today \$ sparkline (120 ticks
                  = 10 min of cost trend), DEAD task highlight
  TAILSCALE card— self addr, online/peer count, per-peer row with
                  online dot + DERP/direct badge

Bottom panel:
  SCHEDULER ACTIVITY — chip grid of all ncl-* tasks with state-color
                       coding (green running / orange idle / red dead)
                       in a custom FlowLayout
  LLM CALLS         — per-model breakdown table (count + cost) for
                       last 60 min window
  RECENT TICKS      — last 12 snapshots from the in-memory ring with
                       per-tick CPU / RSS / loops / sample duration

Live data:
  OpsStream @MainActor ObservableObject opens a WebSocket to
  ws://100.72.223.123:8800/system/ops/stream?token=<TOKEN> on init;
  ingests JSON snapshots into a 720-entry rolling ring (60 min @ 5s).
  Auto-reconnect with 3s backoff. Filters keepalive pings.

Sparklines via SwiftUI Charts framework — LineMark + AreaMark with
monotone interpolation, hidden axes, optional explicit Y range.

MenuBarApp.swift patched:
  - New Window scene 'NCL Ops' (id: 'ops') with Cmd+O keyboard shortcut
  - OpsSnapshot extended with scheduler_activity field
  - LLMCallSummary extended with by_model dict
  - OpsPanel actions row gains a 'Dashboard' button that opens the
    Ops window via @Environment(\\.openWindow)

project.yml: no changes (NCLDesktop target already exists from Phase 1).

Built green, NCL Desktop launched pid 29977. Cmd+O opens dashboard,
WebSocket connects on /system/ops/stream, sparklines populate within
~30s as the ring fills.

Net: 1 new file + 1 patched file, ~+500/-5 LOC.
"
git push origin main 2>&1 | tail -3
