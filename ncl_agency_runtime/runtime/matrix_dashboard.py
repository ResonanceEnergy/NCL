#!/usr/bin/env python3
"""
NCC Matrix Monitor — Browser Dashboard & API Server
════════════════════════════════════════════════════════
Serves a live browser dashboard for the NCC Matrix Monitor.

Architecture:
    NCC (Master) ──→ Matrix Monitor Orchestrator
        ├── NCL  (Brain)    ─ slave
        ├── AAC  (Bank)     ─ slave
        └── BRS  (Systems)  ─ slave

Endpoints:
    GET  /              – HTML dashboard (auto-refreshes)
    GET  /api/report    – full MatrixReport JSON
    GET  /api/tiles     – dashboard tiles only
    GET  /api/alerts    – active alerts
    GET  /api/history   – score history for trend chart
    GET  /api/slos      – SLO definitions and status
    POST /api/refresh   – trigger a new collection cycle
    GET  /health        – liveness probe

Usage:
    python -m ncl_agency_runtime.runtime.matrix_dashboard
    # Then open http://localhost:8787 in your browser
"""

from __future__ import annotations

import json
import logging
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

LOG = logging.getLogger("ncl.matrix_dashboard")
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# ═══════════════════════════════════════════════════════════════
#  Background Collector — keeps the cache fresh every 30s
# ═══════════════════════════════════════════════════════════════

_COLLECT_INTERVAL = 30  # seconds


def _run_background_collector(interval: int) -> None:
    """Daemon thread: run collect_all() once, then every `interval` seconds."""
    # Brief startup delay so uvicorn finishes binding before first collection
    time.sleep(3)
    while True:
        try:
            monitor = _get_monitor()
            monitor.collect_all()
            LOG.debug("Background collection complete")
        except Exception as exc:
            LOG.warning("Background collection error: %s", exc)
        time.sleep(interval)


@asynccontextmanager
async def _lifespan(application: FastAPI):
    t = threading.Thread(
        target=_run_background_collector,
        args=(_COLLECT_INTERVAL,),
        daemon=True,
        name="matrix-collector",
    )
    t.start()
    LOG.info("Matrix Monitor background collector started (interval=%ds)", _COLLECT_INTERVAL)
    yield
    # Daemon thread stops automatically with the process


app = FastAPI(
    title="NCC Matrix Monitor Dashboard",
    version="1.0.0",
    description="NCC Master — NCL/AAC/BRS Slave Browser Dashboard",
    lifespan=_lifespan,
)

# Lazy-init orchestrator on first request to avoid import-time side effects
_monitor = None


def _get_monitor():
    global _monitor
    if _monitor is None:
        from ncl_agency_runtime.runtime.matrix_monitor import MatrixMonitorOrchestrator
        _monitor = MatrixMonitorOrchestrator(repo_root=_REPO_ROOT)
    return _monitor


# ═══════════════════════════════════════════════════════════════
#  API Endpoints
# ═══════════════════════════════════════════════════════════════

@app.get("/health")
def health():
    return {"status": "ok", "service": "ncc_matrix_dashboard"}


@app.get("/api/report")
def api_report():
    """Return the full latest MatrixReport as JSON."""
    monitor = _get_monitor()
    latest = monitor.store.get_latest()
    if latest:
        return JSONResponse(content=latest)
    # No cached report — run a fresh cycle
    report = monitor.collect_all()
    return JSONResponse(content=report.to_dict())


@app.get("/api/tiles")
def api_tiles():
    """Return dashboard tiles only."""
    monitor = _get_monitor()
    return JSONResponse(content=monitor.get_tiles())


@app.get("/api/alerts")
def api_alerts():
    """Return active alerts."""
    monitor = _get_monitor()
    return JSONResponse(content=monitor.get_active_alerts())


@app.get("/api/history")
def api_history(metric: str = "score", limit: int = 100):
    """Return score history for trend plotting."""
    monitor = _get_monitor()
    history = monitor.store.get_history(max_entries=limit)
    return JSONResponse(content=history)


@app.get("/api/slos")
def api_slos():
    """Return SLO definitions."""
    monitor = _get_monitor()
    return JSONResponse(content=monitor.get_slo_definitions())


@app.post("/api/refresh")
def api_refresh():
    """Trigger a fresh collection cycle and return the report."""
    monitor = _get_monitor()
    report = monitor.collect_all()
    monitor.publish_to_bus(report)
    return JSONResponse(content=report.to_dict())


# ═══════════════════════════════════════════════════════════════
#  HTML Dashboard
# ═══════════════════════════════════════════════════════════════

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>NCC Matrix Monitor — Command &amp; Control</title>
<style>
:root {
  --bg: #0a0a0f;
  --panel: #111118;
  --border: #1e1e2e;
  --text: #c8cad0;
  --text-dim: #6c7086;
  --green: #00e676;
  --yellow: #ffab00;
  --red: #ff1744;
  --blue: #448aff;
  --purple: #7c4dff;
  --cyan: #00e5ff;
  --master-gold: #ffd700;
}
* { margin:0; padding:0; box-sizing:border-box; }
body {
  font-family: 'Segoe UI', 'Inter', -apple-system, sans-serif;
  background: var(--bg);
  color: var(--text);
  min-height: 100vh;
}

/* Header - NCC Master Banner */
.header {
  background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
  border-bottom: 2px solid var(--master-gold);
  padding: 16px 24px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.header h1 {
  font-size: 1.5rem;
  font-weight: 700;
  color: var(--master-gold);
  letter-spacing: 2px;
}
.header h1 span.sub {
  font-size: 0.75rem;
  color: var(--text-dim);
  letter-spacing: 1px;
  display: block;
  margin-top: 2px;
}
.header-right {
  display: flex;
  align-items: center;
  gap: 16px;
}
.score-badge {
  font-size: 2rem;
  font-weight: 800;
  padding: 4px 16px;
  border-radius: 8px;
  border: 2px solid;
}
.score-badge.excellent { color: var(--green); border-color: var(--green); }
.score-badge.good { color: var(--yellow); border-color: var(--yellow); }
.score-badge.fair { color: var(--yellow); border-color: var(--yellow); }
.score-badge.degraded { color: var(--red); border-color: var(--red); }
.score-badge.critical { color: var(--red); border-color: var(--red); background: rgba(255,23,68,0.1); }
.status-label {
  font-size: 0.85rem;
  color: var(--text-dim);
  text-align: right;
}
.status-label .val { font-size: 1rem; color: var(--text); font-weight: 600; }

/* Refresh bar */
.refresh-bar {
  background: var(--panel);
  border-bottom: 1px solid var(--border);
  padding: 6px 24px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 0.75rem;
  color: var(--text-dim);
}
.refresh-bar button {
  background: var(--blue);
  color: #fff;
  border: none;
  padding: 4px 14px;
  border-radius: 4px;
  cursor: pointer;
  font-size: 0.75rem;
  font-weight: 600;
}
.refresh-bar button:hover { opacity: 0.85; }

/* Main grid */
.main { padding: 16px 24px; }

/* NCC Master / Slave Architecture */
.arch-section {
  margin-bottom: 20px;
}
.arch-section h2 {
  font-size: 0.85rem;
  color: var(--master-gold);
  letter-spacing: 2px;
  margin-bottom: 10px;
  text-transform: uppercase;
}
.pillar-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}
.pillar-card {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 14px;
  text-align: center;
  position: relative;
}
.pillar-card.master {
  border-color: var(--master-gold);
  background: linear-gradient(180deg, rgba(255,215,0,0.08) 0%, var(--panel) 100%);
}
.pillar-card .role-tag {
  font-size: 0.6rem;
  letter-spacing: 1.5px;
  text-transform: uppercase;
  padding: 2px 8px;
  border-radius: 3px;
  display: inline-block;
  margin-bottom: 6px;
}
.pillar-card.master .role-tag {
  background: rgba(255,215,0,0.2);
  color: var(--master-gold);
}
.pillar-card:not(.master) .role-tag {
  background: rgba(68,138,255,0.15);
  color: var(--blue);
}
.pillar-name {
  font-size: 1.1rem;
  font-weight: 700;
  margin-bottom: 4px;
}
.pillar-role-desc {
  font-size: 0.7rem;
  color: var(--text-dim);
  margin-bottom: 8px;
}
.pillar-status {
  font-size: 0.8rem;
  font-weight: 700;
  padding: 3px 10px;
  border-radius: 4px;
  display: inline-block;
}
.pillar-status.online { background: rgba(0,230,118,0.15); color: var(--green); }
.pillar-status.degraded { background: rgba(255,171,0,0.15); color: var(--yellow); }
.pillar-status.bootstrapping { background: rgba(255,171,0,0.1); color: var(--yellow); }
.pillar-status.offline { background: rgba(255,23,68,0.15); color: var(--red); }

/* Tiles grid */
.tiles-section { margin-bottom: 20px; }
.tiles-section h2 {
  font-size: 0.85rem;
  color: var(--cyan);
  letter-spacing: 2px;
  margin-bottom: 10px;
  text-transform: uppercase;
}
.tiles-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 10px;
}
.tile {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
  border-left: 3px solid var(--border);
}
.tile.green { border-left-color: var(--green); }
.tile.yellow { border-left-color: var(--yellow); }
.tile.red { border-left-color: var(--red); }
.tile-title { font-size: 0.7rem; color: var(--text-dim); text-transform: uppercase; letter-spacing: 1px; }
.tile-value { font-size: 1.4rem; font-weight: 700; margin: 4px 0; }
.tile-sub { font-size: 0.7rem; color: var(--text-dim); }

/* Checks and Alerts in two-column */
.two-col {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-bottom: 20px;
}
@media (max-width: 900px) { .two-col { grid-template-columns: 1fr; } }

.section-card {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 14px;
  max-height: 400px;
  overflow-y: auto;
}
.section-card h3 {
  font-size: 0.8rem;
  color: var(--purple);
  letter-spacing: 1.5px;
  text-transform: uppercase;
  margin-bottom: 10px;
  border-bottom: 1px solid var(--border);
  padding-bottom: 6px;
}
.check-row {
  display: flex;
  align-items: center;
  padding: 4px 0;
  border-bottom: 1px solid rgba(30,30,46,0.5);
  font-size: 0.8rem;
}
.check-icon {
  width: 20px;
  font-weight: 700;
  flex-shrink: 0;
}
.check-icon.pass { color: var(--green); }
.check-icon.fail { color: var(--red); }
.check-icon.warn { color: var(--yellow); }
.check-name { flex: 1; color: var(--text); }
.check-score { width: 48px; text-align: right; font-weight: 600; color: var(--text-dim); }
.check-source { width: 100px; text-align: right; font-size: 0.7rem; color: var(--text-dim); }

.alert-row {
  padding: 6px 0;
  border-bottom: 1px solid rgba(30,30,46,0.5);
  font-size: 0.8rem;
}
.alert-severity {
  font-size: 0.65rem;
  font-weight: 700;
  padding: 1px 6px;
  border-radius: 3px;
  display: inline-block;
  margin-right: 6px;
}
.alert-severity.critical { background: var(--red); color: #fff; }
.alert-severity.error { background: rgba(255,23,68,0.3); color: var(--red); }
.alert-severity.warning { background: rgba(255,171,0,0.3); color: var(--yellow); }
.alert-severity.info { background: rgba(68,138,255,0.2); color: var(--blue); }
.alert-title { font-weight: 600; }
.alert-detail { color: var(--text-dim); font-size: 0.75rem; margin-top: 2px; }

/* SLO section */
.slo-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 10px;
  margin-bottom: 20px;
}
.slo-card {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 14px;
}
.slo-name { font-size: 0.8rem; font-weight: 600; margin-bottom: 6px; }
.slo-bar-track {
  height: 8px;
  background: rgba(255,255,255,0.05);
  border-radius: 4px;
  overflow: hidden;
  margin-bottom: 6px;
}
.slo-bar-fill {
  height: 100%;
  border-radius: 4px;
  transition: width 0.5s;
}
.slo-meta { font-size: 0.7rem; color: var(--text-dim); display: flex; justify-content: space-between; }

/* History trend */
.trend-section { margin-bottom: 20px; }
.trend-section h2 {
  font-size: 0.85rem;
  color: var(--cyan);
  letter-spacing: 2px;
  margin-bottom: 10px;
  text-transform: uppercase;
}
.trend-chart {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 14px;
  height: 120px;
  display: flex;
  align-items: flex-end;
  gap: 2px;
}
.trend-bar {
  flex: 1;
  min-width: 4px;
  max-width: 12px;
  border-radius: 2px 2px 0 0;
  transition: height 0.3s;
}
.trend-bar.green { background: var(--green); }
.trend-bar.yellow { background: var(--yellow); }
.trend-bar.red { background: var(--red); }

.no-data {
  color: var(--text-dim);
  font-size: 0.8rem;
  text-align: center;
  padding: 30px;
}

/* Footer */
.footer {
  text-align: center;
  padding: 12px;
  font-size: 0.65rem;
  color: var(--text-dim);
  border-top: 1px solid var(--border);
}
</style>
</head>
<body>

<div class="header">
  <h1>
    NCC MATRIX MONITOR
    <span class="sub">NATRIX COMMAND &amp; CONTROL — MASTER GOVERNANCE</span>
  </h1>
  <div class="header-right">
    <div class="status-label">
      Checks <span class="val" id="h-checks">--/--</span><br>
      Violations <span class="val" id="h-violations">--</span><br>
      Alerts <span class="val" id="h-alerts">--</span>
    </div>
    <div class="score-badge" id="score-badge">--</div>
  </div>
</div>

<div class="refresh-bar">
  <span>Auto-refresh: <span id="countdown">30</span>s &nbsp;|&nbsp; Last: <span id="last-update">--</span></span>
  <button onclick="doRefresh()">&#x21bb; Refresh Now</button>
</div>

<div class="main">

  <!-- NCC Master / Slave Pillar Architecture -->
  <div class="arch-section">
    <h2>&#x2694; Pillar Command Hierarchy</h2>
    <div class="pillar-grid" id="pillar-grid"></div>
  </div>

  <!-- Dashboard Tiles -->
  <div class="tiles-section">
    <h2>&#x25a3; Dashboard Tiles</h2>
    <div class="tiles-grid" id="tiles-grid"></div>
  </div>

  <!-- SLO Status -->
  <div class="arch-section">
    <h2>&#x2691; Service Level Objectives</h2>
    <div class="slo-grid" id="slo-grid"></div>
  </div>

  <!-- Checks + Alerts two-column -->
  <div class="two-col">
    <div class="section-card">
      <h3>Health Checks</h3>
      <div id="checks-list"></div>
    </div>
    <div class="section-card">
      <h3>Alerts</h3>
      <div id="alerts-list"></div>
    </div>
  </div>

  <!-- Score Trend -->
  <div class="trend-section">
    <h2>&#x1f4c8; Score History</h2>
    <div class="trend-chart" id="trend-chart"></div>
  </div>

</div>

<div class="footer">
  NCC Matrix Monitor v1.0 &nbsp;|&nbsp; Resonance Energy &nbsp;|&nbsp;
  NCC (Master) &rarr; NCL &middot; AAC &middot; BRS (Slaves)
</div>

<script>
const PILLAR_META = {
  ncc: { name: "NCC", role: "Governance", desc: "Natrix Command & Control", master: true },
  ncl: { name: "NCL", role: "Brain", desc: "NUREALCORTEXLINK — Cognitive Augmentation" },
  aac: { name: "AAC", role: "Bank", desc: "Autonomous Asset Commander" },
  brs: { name: "BRS", role: "Systems", desc: "Bit Rage Systems — Agent Workforce + Labour" },
};

let refreshInterval = null;
let countdown = 30;

async function fetchReport() {
  try {
    const res = await fetch("/api/report");
    if (!res.ok) throw new Error("fetch failed");
    return await res.json();
  } catch(e) {
    console.error("Failed to fetch report:", e);
    return null;
  }
}

async function fetchHistory() {
  try {
    const res = await fetch("/api/history?limit=50");
    if (!res.ok) return [];
    return await res.json();
  } catch(e) { return []; }
}

function renderPillars(report) {
  const grid = document.getElementById("pillar-grid");
  const pillars = (report.pillar_summary || {}).pillars || {};
  // Ensure NCC is first
  const order = ["ncc", "ncl", "aac", "brs"];
  let html = "";
  for (const pid of order) {
    const info = pillars[pid] || {};
    const meta = PILLAR_META[pid] || {};
    const status = (info.status || "offline").toLowerCase();
    const isMaster = meta.master || false;
    html += `
      <div class="pillar-card ${isMaster ? "master" : ""}">
        <div class="role-tag">${isMaster ? "MASTER" : "SLAVE"}</div>
        <div class="pillar-name">${meta.name || pid.toUpperCase()}</div>
        <div class="pillar-role-desc">${meta.role || ""} — ${meta.desc || ""}</div>
        <div class="pillar-status ${status}">${status.toUpperCase()}</div>
      </div>`;
  }
  grid.innerHTML = html;
}

function renderTiles(report) {
  const grid = document.getElementById("tiles-grid");
  const tiles = report.tiles || [];
  // Filter out pillar tiles (shown separately) and source breakdown
  const display = tiles.filter(t => t.tile_type !== "pillar");
  let html = "";
  for (const t of display) {
    html += `
      <div class="tile ${t.status}">
        <div class="tile-title">${esc(t.title)}</div>
        <div class="tile-value">${esc(String(t.value))}</div>
        <div class="tile-sub">${esc(t.subtitle)}</div>
      </div>`;
  }
  grid.innerHTML = html || '<div class="no-data">No tiles available</div>';
}

function renderSLOs(report) {
  const grid = document.getElementById("slo-grid");
  const slos = report.slo_statuses || [];
  let html = "";
  for (const s of slos) {
    const pct = Math.round((s.current_value || 0) * 100);
    const target = Math.round((s.slo.target || 0) * 100);
    const budget = Math.round((s.budget_remaining || 0) * 100);
    const color = s.in_violation ? "var(--red)" : "var(--green)";
    html += `
      <div class="slo-card">
        <div class="slo-name">${esc(s.slo.name.replace(/_/g, " "))}</div>
        <div class="slo-bar-track">
          <div class="slo-bar-fill" style="width:${pct}%;background:${color}"></div>
        </div>
        <div class="slo-meta">
          <span>Current: ${pct}%</span>
          <span>Target: ${target}%</span>
          <span>Budget: ${budget}%</span>
        </div>
      </div>`;
  }
  grid.innerHTML = html || '<div class="no-data">No SLOs defined</div>';
}

function renderChecks(report) {
  const list = document.getElementById("checks-list");
  const checks = report.checks || [];
  let html = "";
  for (const c of checks) {
    const icon = c.passed ? "&#x2713;" : (c.score > 0 ? "!" : "&#x2717;");
    const cls = c.passed ? "pass" : (c.score > 0 ? "warn" : "fail");
    html += `
      <div class="check-row">
        <span class="check-icon ${cls}">${icon}</span>
        <span class="check-name">${esc(c.name)}</span>
        <span class="check-score">${(c.score * 100).toFixed(0)}%</span>
        <span class="check-source">${esc(c.source)}</span>
      </div>`;
  }
  list.innerHTML = html || '<div class="no-data">No checks</div>';
}

function renderAlerts(report) {
  const list = document.getElementById("alerts-list");
  const alerts = report.alerts || [];
  if (!alerts.length) {
    list.innerHTML = '<div class="no-data">No active alerts — all clear</div>';
    return;
  }
  let html = "";
  for (const a of alerts) {
    html += `
      <div class="alert-row">
        <span class="alert-severity ${a.severity}">${a.severity.toUpperCase()}</span>
        <span class="alert-title">${esc(a.title)}</span>
        <div class="alert-detail">${esc(a.details)}</div>
      </div>`;
  }
  list.innerHTML = html;
}

function renderTrend(history) {
  const chart = document.getElementById("trend-chart");
  if (!history.length) {
    chart.innerHTML = '<div class="no-data" style="width:100%;text-align:center;">No history data yet — will populate after multiple collection cycles</div>';
    return;
  }
  const maxBars = 50;
  const data = history.slice(-maxBars);
  let html = "";
  for (const h of data) {
    const score = h.score || 0;
    const pct = Math.max(4, Math.round(score * 100));
    const cls = score >= 0.9 ? "green" : (score >= 0.7 ? "yellow" : "red");
    html += `<div class="trend-bar ${cls}" style="height:${pct}%" title="${(score*100).toFixed(1)}%"></div>`;
  }
  chart.innerHTML = html;
}

function renderHeader(report) {
  const badge = document.getElementById("score-badge");
  const pct = Math.round((report.overall_score || 0) * 100);
  badge.textContent = pct + "%";
  badge.className = "score-badge " + (report.health_status || "critical").toLowerCase();

  document.getElementById("h-checks").textContent =
    `${report.checks_passed || 0}/${report.checks_total || 0}`;
  document.getElementById("h-violations").textContent = report.slos_in_violation || 0;
  document.getElementById("h-alerts").textContent = (report.alerts || []).length;
  document.getElementById("last-update").textContent = new Date().toLocaleTimeString();
}

function esc(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

async function update() {
  const [report, history] = await Promise.all([fetchReport(), fetchHistory()]);
  if (!report) return;
  renderHeader(report);
  renderPillars(report);
  renderTiles(report);
  renderSLOs(report);
  renderChecks(report);
  renderAlerts(report);
  renderTrend(history);
}

async function doRefresh() {
  try {
    await fetch("/api/refresh", { method: "POST" });
  } catch(e) {}
  await update();
  countdown = 30;
}

function startCountdown() {
  setInterval(() => {
    countdown--;
    document.getElementById("countdown").textContent = countdown;
    if (countdown <= 0) {
      countdown = 30;
      update();
    }
  }, 1000);
}

// Initial load
update();
startCountdown();
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
def dashboard():
    """Serve the browser dashboard."""
    return DASHBOARD_HTML


# ═══════════════════════════════════════════════════════════════
#  Entry point
# ═══════════════════════════════════════════════════════════════

def main() -> None:
    """Start the NCC Matrix Monitor dashboard server."""

    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)-8s %(name)s  %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    # Dashboard port — separate from relay_port (8787) which may be in use
    port = 8788
    try:
        config_path = _REPO_ROOT / "ncl_config.json"
        if config_path.exists():
            cfg = json.loads(config_path.read_text(encoding="utf-8"))
            port = cfg.get("network", {}).get("dashboard_port", 8788)
    except Exception:
        pass

    host = "127.0.0.1"
    print(f"\n{'='*60}")
    print("  NCC MATRIX MONITOR — BROWSER DASHBOARD")
    print(f"  http://{host}:{port}")
    print(f"{'='*60}\n")

    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
