"""Sample collectors — sysctl / ps / getifaddrs / tailscale / process info.

Pure-Python, no pyobjc dependency. Shells out to macOS CLIs which are
fast (<30ms each on Apple Silicon) and stable across OS versions.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import time
from typing import Optional

from .models import (
    BrainStats,
    HostStats,
    LLMCallSummary,
    TailscaleMesh,
    TailscalePeer,
)

log = logging.getLogger("ncl.system_monitor.collectors")

# Cache prior-tick interface counters so we can derive bytes/sec deltas.
_prior_if_counters: dict[str, tuple[int, int, float]] = {}  # ifname -> (rx, tx, ts)
_prior_brain_cpu: dict[int, tuple[float, float]] = {}       # pid -> (cputime_s, walltime_s)


async def _run(cmd: list[str], *, timeout: float = 3.0) -> str:
    """Run a CLI command, return stdout or empty string on failure."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return out.decode("utf-8", errors="replace")
    except (asyncio.TimeoutError, FileNotFoundError, Exception) as e:
        log.debug("[collectors] %s failed: %s", cmd[0], e)
        return ""


# ── HOST ─────────────────────────────────────────────────────────────────


async def collect_host() -> HostStats:
    out = HostStats()
    out.hostname = socket.gethostname()

    # CPU count, load avg, uptime via sysctl
    sysctl_out = await _run(["/usr/sbin/sysctl", "-n",
                              "hw.ncpu",
                              "vm.loadavg",
                              "kern.boottime",
                              "hw.memsize"])
    if sysctl_out:
        try:
            lines = sysctl_out.strip().split("\n")
            if len(lines) >= 1:
                out.cpu_count = int(lines[0])
            if len(lines) >= 2:
                # loadavg format: "{ 1.23 1.45 1.67 }"
                la_parts = lines[1].strip().strip("{}").split()
                if len(la_parts) >= 3:
                    out.load_avg_1m = float(la_parts[0])
                    out.load_avg_5m = float(la_parts[1])
                    out.load_avg_15m = float(la_parts[2])
            if len(lines) >= 3:
                # kern.boottime format: "{ sec = 1745000000, usec = 0 } Wed ..."
                import re as _re

                m = _re.search(r"sec\s*=\s*(\d+)", lines[2])
                if m:
                    boot = int(m.group(1))
                    out.uptime_seconds = int(time.time()) - boot
            if len(lines) >= 4:
                out.mem_total_gb = int(lines[3]) / (1024 ** 3)
        except Exception as e:
            log.debug("[collectors] sysctl parse failed: %s", e)

    # CPU% via top -l 1 (faster than parsing host_statistics)
    top_out = await _run(["/usr/bin/top", "-l", "1", "-n", "0", "-s", "0"])
    if top_out:
        for line in top_out.split("\n"):
            if line.startswith("CPU usage:"):
                # "CPU usage: 12.34% user, 5.67% sys, 82.0% idle"
                try:
                    parts = [p.strip() for p in line.replace("CPU usage:", "").split(",")]
                    user = float(parts[0].split("%")[0])
                    sys_ = float(parts[1].split("%")[0])
                    out.cpu_pct = round(user + sys_, 1)
                except Exception:
                    pass
                break
            if line.startswith("PhysMem:"):
                # "PhysMem: 24G used (3G wired, 1G compressor), 40G unused."
                try:
                    import re as _re

                    used_m = _re.search(r"(\d+)([KMG])\s*used", line)
                    unused_m = _re.search(r"(\d+)([KMG])\s*unused", line)
                    wired_m = _re.search(r"(\d+)([KMG])\s*wired", line)
                    if used_m:
                        out.mem_used_gb = _to_gb(used_m.group(1), used_m.group(2))
                    if unused_m:
                        out.mem_free_gb = _to_gb(unused_m.group(1), unused_m.group(2))
                    if wired_m:
                        out.mem_wired_gb = _to_gb(wired_m.group(1), wired_m.group(2))
                    out.mem_active_gb = round(out.mem_used_gb - out.mem_wired_gb, 1)
                except Exception:
                    pass

    # Disk free via df /
    df_out = await _run(["/bin/df", "-g", "/"])
    if df_out:
        try:
            for line in df_out.split("\n")[1:]:
                if line.strip():
                    cols = line.split()
                    if len(cols) >= 4:
                        out.disk_total_gb = float(cols[1])
                        out.disk_free_gb = float(cols[3])
                    break
        except Exception:
            pass

    # Net throughput via netstat -ib (cumulative bytes per interface)
    netstat_out = await _run(["/usr/sbin/netstat", "-ibn"])
    if netstat_out:
        total_rx_delta = 0
        total_tx_delta = 0
        now = time.time()
        seen_ifs: set[str] = set()
        for line in netstat_out.split("\n")[1:]:
            cols = line.split()
            if len(cols) < 10:
                continue
            ifname = cols[0]
            if ifname in seen_ifs or ifname.startswith(("lo", "gif", "stf", "utun")):
                continue
            seen_ifs.add(ifname)
            try:
                # Find Ibytes (col 6) and Obytes (col 9) — netstat -ib layout
                rx_bytes = int(cols[6])
                tx_bytes = int(cols[9])
            except (ValueError, IndexError):
                continue
            prior = _prior_if_counters.get(ifname)
            if prior is not None:
                prx, ptx, pts = prior
                dt = max(now - pts, 0.001)
                total_rx_delta += max(0, rx_bytes - prx) / dt
                total_tx_delta += max(0, tx_bytes - ptx) / dt
            _prior_if_counters[ifname] = (rx_bytes, tx_bytes, now)
        out.net_rx_mbps = round(total_rx_delta / (1024 * 1024), 2)
        out.net_tx_mbps = round(total_tx_delta / (1024 * 1024), 2)

    return out


def _to_gb(num: str, unit: str) -> float:
    n = float(num)
    if unit == "K":
        return round(n / (1024 * 1024), 2)
    if unit == "M":
        return round(n / 1024, 2)
    if unit == "G":
        return round(n, 2)
    return n


# ── BRAIN PROCESS ────────────────────────────────────────────────────────


async def collect_brain(pid: Optional[int] = None) -> BrainStats:
    out = BrainStats()
    if pid is None:
        pid = os.getpid()
    out.pid = pid

    # ps -p PID -o pid,%cpu,rss,nlwp,etime,fd_count
    # Note: macOS ps lacks nlwp/fd_count; use ps -M for threads and
    # lsof for FDs (lsof is slow — sample once per 60s in v1).
    ps_out = await _run(["/bin/ps", "-p", str(pid), "-o", "%cpu,rss,etime"])
    if ps_out:
        lines = ps_out.strip().split("\n")
        if len(lines) >= 2:
            cols = lines[1].split()
            try:
                out.cpu_pct = float(cols[0])
                out.rss_mb = round(int(cols[1]) / 1024, 1)
                # etime format: dd-hh:mm:ss or hh:mm:ss or mm:ss
                out.uptime_seconds = _parse_etime(cols[2])
            except (ValueError, IndexError):
                pass

    # Thread count via ps -M (one row per thread)
    ps_m = await _run(["/bin/ps", "-M", "-p", str(pid)])
    if ps_m:
        out.threads = max(0, ps_m.count("\n") - 1)

    return out


def _parse_etime(s: str) -> int:
    """Parse ps etime (dd-hh:mm:ss / hh:mm:ss / mm:ss) into seconds."""
    try:
        if "-" in s:
            days, rest = s.split("-", 1)
            base = int(days) * 86400
        else:
            days, rest = None, s
            base = 0
        parts = rest.split(":")
        if len(parts) == 3:
            h, m, s_ = parts
            return base + int(h) * 3600 + int(m) * 60 + int(s_)
        if len(parts) == 2:
            m, s_ = parts
            return base + int(m) * 60 + int(s_)
        return base + int(parts[0])
    except Exception:
        return 0


# ── TAILSCALE ────────────────────────────────────────────────────────────


async def collect_tailscale() -> TailscaleMesh:
    out = TailscaleMesh()
    raw = await _run(["/usr/local/bin/tailscale", "status", "--json"], timeout=5.0)
    if not raw:
        # try Homebrew location too
        raw = await _run(["/opt/homebrew/bin/tailscale", "status", "--json"], timeout=5.0)
    if not raw:
        return out

    try:
        data = json.loads(raw)
    except Exception as e:
        log.debug("[collectors] tailscale json parse: %s", e)
        return out

    self_d = data.get("Self", {}) or {}
    out.self_name = self_d.get("HostName", "") or self_d.get("DNSName", "")
    addrs = self_d.get("TailscaleIPs", []) or []
    if addrs:
        out.self_addr = addrs[0]

    peers_dict = data.get("Peer", {}) or {}
    out.peer_count = len(peers_dict)
    online = 0
    peers_list: list[TailscalePeer] = []
    for pkey, p in peers_dict.items():
        try:
            peer_online = bool(p.get("Online", False))
            if peer_online:
                online += 1
            paddrs = p.get("TailscaleIPs", []) or []
            # Latency: best-effort from p.get("CurAddr") + p.get("Relay")
            relayed = bool(p.get("Relay", ""))
            last_handshake_iso = p.get("LastHandshake", "") or ""
            last_age = 0
            if last_handshake_iso:
                try:
                    from datetime import datetime as _dt

                    lh = _dt.fromisoformat(last_handshake_iso.replace("Z", "+00:00"))
                    from datetime import timezone as _tz

                    last_age = max(0, int((_dt.now(_tz.utc) - lh).total_seconds()))
                except Exception:
                    pass
            peers_list.append(TailscalePeer(
                name=p.get("HostName", "") or p.get("DNSName", "") or pkey[:12],
                addr=paddrs[0] if paddrs else "",
                latency_ms=0.0,  # tailscale status doesn't include latency without --peers
                last_handshake_secs=last_age,
                relayed_via_derp=relayed,
                online=peer_online,
            ))
        except Exception:
            continue
    out.online_count = online
    # sort by online first then by name
    peers_list.sort(key=lambda p: (not p.online, p.name.lower()))
    out.peers = peers_list

    return out


# ── LLM CALLS ────────────────────────────────────────────────────────────


def collect_llm_summary(window_minutes: int = 60) -> LLMCallSummary:
    """Read the cost_tracker ledger for the trailing window."""
    out = LLMCallSummary(window_minutes=window_minutes)
    ledger_path = (
        f"{os.environ.get('NCL_BASE', os.path.expanduser('~/dev/NCL'))}"
        f"/data/costs/cost_ledger.jsonl"
    )
    if not os.path.exists(ledger_path):
        return out

    from datetime import datetime as _dt
    from datetime import timezone as _tz

    cutoff = _dt.now(_tz.utc).timestamp() - window_minutes * 60
    by_model: dict[str, dict] = {}
    count = 0
    total_cost = 0.0
    try:
        with open(ledger_path, "r") as f:
            for line in f:
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                ts_str = e.get("timestamp", "")
                if not ts_str:
                    continue
                try:
                    ts = _dt.fromisoformat(ts_str.replace("Z", "+00:00")).timestamp()
                except Exception:
                    continue
                if ts < cutoff:
                    continue
                cost = float(e.get("cost_usd", 0) or 0)
                model = e.get("description", "") or e.get("source", "?")
                # Extract model substring if description has 'claude-...' pattern
                import re as _re

                mm = _re.search(r"(claude-[a-z0-9-]+)", model)
                model_key = mm.group(1) if mm else (e.get("source", "?") or "?")
                by_model.setdefault(model_key, {"count": 0, "cost_usd": 0.0})
                by_model[model_key]["count"] += 1
                by_model[model_key]["cost_usd"] += cost
                count += 1
                total_cost += cost
    except Exception as e:
        log.debug("[collectors] ledger read: %s", e)

    out.call_count = count
    out.total_cost_usd = round(total_cost, 4)
    out.by_model = {k: {"count": v["count"], "cost_usd": round(v["cost_usd"], 4)}
                    for k, v in by_model.items()}
    return out
