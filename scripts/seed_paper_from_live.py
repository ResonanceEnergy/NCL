"""
Seed PaperTradingEngine with a snapshot of NATRIX's live portfolio.

Wave 14K post-build harness. Pure REST — reads live positions via
GET /portfolio/positions on the running brain, then POSTs each as a
new paper trade via POST /paper/trade. This avoids fighting with the
brain's process-isolated PortfolioManager singleton.

Each snapshot paper trade gets:
  - strategy = "snapshot"  (separate bucket from goat/bravo/options/etc
    so the auto-trader's NEW trades don't contaminate the baseline)
  - entry_price = position.avg_cost (or last_price fallback)
  - stop_loss = entry * 0.92 (8% protective stop on long; mirror on short)
  - target_1 = entry * 1.20 (20% upside target — 2.5 R:R, clears paper
    engine's 1.0 R:R minimum comfortably)
  - quantity = abs(position.quantity) (explicit; bypasses auto-sizing)
  - tags + scanner_data describing original broker/account

Idempotent: skips any symbol already present as an OPEN paper trade
tagged "snapshot" so re-runs are safe.

Usage:
  /opt/homebrew/bin/python3 scripts/seed_paper_from_live.py
"""

from __future__ import annotations

import json
import logging
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
log = logging.getLogger("seed_paper")

BRAIN_BASE = os.getenv("NCL_BRAIN_BASE", "http://100.72.223.123:8800")
TOKEN = os.getenv(
    "STRIKE_AUTH_TOKEN",
    "QKpHcK8lnL9s4P4mFkwzN4ugLP9sokvBWrmqNcs2ItU",
)


def _req(method: str, path: str, body: dict | None = None,
         timeout: int = 30) -> tuple[int, dict | list | None]:
    url = f"{BRAIN_BASE}{path}"
    data = None
    headers = {"Authorization": f"Bearer {TOKEN}"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            txt = resp.read().decode("utf-8")
            return resp.status, json.loads(txt) if txt else None
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        try:
            return e.code, json.loads(body)
        except Exception:
            return e.code, {"raw": body}
    except Exception as e:
        return -1, {"error": str(e)}


def main() -> int:
    # 1) Pull live positions
    log.info("[SEED] fetching live positions...")
    code, body = _req("GET", "/portfolio/positions")
    if code != 200:
        log.error("[SEED] /portfolio/positions HTTP %s", code)
        return 1
    # API returns either a bare list or {positions: [...]} envelope
    positions = body if isinstance(body, list) else (body or {}).get("positions")
    if not isinstance(positions, list) or not positions:
        log.error("[SEED] no positions in response — sync first?")
        return 1
    log.info("[SEED] got %d live positions", len(positions))

    # 2) Pull existing paper trades for idempotency
    log.info("[SEED] fetching existing paper trades...")
    code, paper_trades = _req("GET", "/paper/trades")
    if code != 200 or not isinstance(paper_trades, list):
        log.warning("[SEED] /paper/trades failed (%s) — proceeding without idempotency check", code)
        paper_trades = []
    # Dedup key = symbol|broker|avg_cost-bucket (SLV has 3 lots in IBKR at
    # different costs; each is a distinct paper position).
    def _dedup_key(symbol: str, broker: str, avg_cost) -> str:
        try:
            ac = round(float(avg_cost or 0), 2)
        except (TypeError, ValueError):
            ac = 0
        return f"{symbol.upper()}|{broker.upper()}|{ac}"

    already_seeded = set()
    for t in paper_trades:
        if not isinstance(t, dict):
            continue
        tags = t.get("tags") or []
        if t.get("status") == "open" and "snapshot" in tags:
            sym = (t.get("symbol") or "").upper()
            sd = t.get("scanner_data") or {}
            br = sd.get("original_broker", "")
            ac = sd.get("original_avg_cost")
            if sym:
                already_seeded.add(_dedup_key(sym, br, ac))
    log.info("[SEED] %d existing snapshot positions already in paper", len(already_seeded))

    snapshot_iso = datetime.now(timezone.utc).isoformat()
    seeded = 0
    skipped_existing = 0
    skipped_bad = 0
    errors = 0
    total_value_cad = 0.0

    for pos in positions:
        symbol = (pos.get("symbol") or "").upper()
        if not symbol:
            skipped_bad += 1
            continue
        dk = _dedup_key(symbol, pos.get("broker", ""), pos.get("avg_cost"))
        if dk in already_seeded:
            log.info("[SEED] SKIP %s (already snapshot, key=%s)", symbol, dk)
            skipped_existing += 1
            continue
        qty_raw = float(pos.get("quantity") or 0)
        if qty_raw == 0:
            log.info("[SEED] SKIP %s (zero quantity)", symbol)
            skipped_bad += 1
            continue
        direction = "long" if qty_raw > 0 else "short"
        qty = abs(qty_raw)

        # Prefer avg_cost → fall back to last_price
        entry = float(pos.get("avg_cost") or 0)
        last = pos.get("last_price")
        if entry <= 0 and last is not None:
            try:
                entry = float(last)
            except (TypeError, ValueError):
                entry = 0
        if entry <= 0:
            log.warning("[SEED] SKIP %s (no usable entry price)", symbol)
            skipped_bad += 1
            continue

        # 8% protective stop, 20% target
        if direction == "long":
            stop = round(entry * 0.92, 4)
            target = round(entry * 1.20, 4)
        else:
            stop = round(entry * 1.08, 4)
            target = round(entry * 0.80, 4)

        broker = pos.get("broker", "unknown") or "unknown"
        account_id = (pos.get("account_id") or "unknown")
        acct_short = account_id[:8] if account_id else "unknown"
        asset_class = (pos.get("asset_class") or "Equity")
        at = asset_class.lower()
        if "option" in at:
            asset_type = "options"
        elif "crypto" in at:
            asset_type = "crypto"
        elif "future" in at:
            asset_type = "futures"
        else:
            asset_type = "stock"

        payload = {
            "symbol": symbol,
            "direction": direction,
            "asset_type": asset_type,
            "strategy": "snapshot",
            "entry_price": entry,
            "quantity": qty,
            "stop_loss": stop,
            "target_1": target,
            "notes": (
                f"Live portfolio snapshot {snapshot_iso}. "
                f"Original broker={broker} account={acct_short}"
            ),
            "tags": [
                "snapshot", "live_mirror",
                f"broker:{broker}", f"account:{acct_short}",
            ],
            "scanner_data": {
                "source": "live_portfolio_snapshot",
                "snapshot_date_iso": snapshot_iso,
                "original_broker": broker,
                "original_account_id": account_id,
                "original_avg_cost": pos.get("avg_cost"),
                "original_last_price": pos.get("last_price"),
                "original_market_value": pos.get("market_value"),
                "original_market_value_cad": pos.get("market_value_cad"),
                "original_currency": pos.get("currency"),
                "original_sector": pos.get("sector"),
                "original_unrealized_pl": pos.get("unrealized_pl"),
                "original_weight_pct": pos.get("weight_pct"),
                "trade_idea_id": None,
            },
        }

        code, resp = _req("POST", "/paper/trade", body=payload, timeout=20)
        # API returns either {id, ...} or {status: "created", trade: {id, ...}}
        trade_id = None
        if isinstance(resp, dict):
            trade_id = resp.get("id") or (resp.get("trade") or {}).get("id")
        if code in (200, 201) and trade_id:
            seeded += 1
            mv = float(pos.get("market_value_cad") or 0)
            total_value_cad += mv
            log.info(
                "[SEED] OPENED %s qty=%.4f @ $%.4f (%s mv_cad=$%.2f) -> %s",
                symbol, qty, entry, pos.get("currency", "?"), mv, trade_id,
            )
        else:
            errors += 1
            log.error("[SEED] FAILED %s: HTTP %s -> %s",
                      symbol, code, str(resp)[:300])

    log.info(
        "[SEED] DONE — seeded=%d skipped_existing=%d skipped_bad=%d "
        "errors=%d total_seeded_value_cad≈$%.2f",
        seeded, skipped_existing, skipped_bad, errors, total_value_cad,
    )
    return 0 if errors == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
