#!/usr/bin/env python3
"""Add CoinPaprika fallback to CryptoMarketCollector."""

p = "/Users/natrix/Projects/FirstStrike"  # wrong! actually NCL
p = "/Users/natrix/dev/NCL/runtime/intelligence/collectors.py"
s = open(p).read()

old = """    BASE_URL = "https://api.coingecko.com/api/v3"

    TRACKED_COINS = {
        "bitcoin": "BTC",
        "ethereum": "ETH",
        "solana": "SOL",
        "cardano": "ADA",
        "ripple": "XRP",
        "dogecoin": "DOGE","""

new = """    BASE_URL = "https://api.coingecko.com/api/v3"

    # Wave 14G P14-C — CoinPaprika fallback when CoinGecko rate-limits.
    # Free tier ~25k calls/month with no API key. Similar data shape; we
    # try CoinGecko first (richer metadata) and fall through on 429/error.
    PAPRIKA_BASE = "https://api.coinpaprika.com/v1"
    PAPRIKA_IDS = {
        "bitcoin":  "btc-bitcoin",
        "ethereum": "eth-ethereum",
        "solana":   "sol-solana",
        "cardano":  "ada-cardano",
        "ripple":   "xrp-xrp",
        "dogecoin": "doge-dogecoin",
    }

    TRACKED_COINS = {
        "bitcoin": "BTC",
        "ethereum": "ETH",
        "solana": "SOL",
        "cardano": "ADA",
        "ripple": "XRP",
        "dogecoin": "DOGE","""

if "PAPRIKA_BASE" not in s:
    s = s.replace(old, new, 1)
    print("added Coinpaprika constants")

# Insert a paprika fallback helper before collect_market_overview
old2 = '''    async def collect_market_overview(self) -> list[MarketSignal]:
        """Fetch current prices and 24h changes for tracked coins."""
        signals = []
        try:
            ids = ",".join(self.TRACKED_COINS.keys())
            data = await _fetch_json(
                self._client,
                f"{self.BASE_URL}/coins/markets",'''

new2 = '''    async def _paprika_market_overview(self) -> list[dict]:
        """CoinPaprika fallback — fetch tracked coins via /tickers/{id}.

        Returns a list of dicts shaped roughly like CoinGecko's
        /coins/markets response so the downstream parser can reuse the
        same field names with minimal branching.
        """
        out: list[dict] = []
        for gecko_id, symbol in self.TRACKED_COINS.items():
            paprika_id = self.PAPRIKA_IDS.get(gecko_id)
            if not paprika_id:
                continue
            try:
                t = await _fetch_json(
                    self._client,
                    f"{self.PAPRIKA_BASE}/tickers/{paprika_id}",
                    limiter=self._limiter,
                )
            except Exception:
                continue
            if not isinstance(t, dict):
                continue
            q = (t.get("quotes") or {}).get("USD") or {}
            out.append({
                "id": gecko_id,
                "symbol": symbol,
                "current_price": q.get("price", 0),
                "price_change_percentage_24h": q.get("percent_change_24h", 0),
                "price_change_percentage_7d_in_currency": q.get("percent_change_7d", 0),
                "price_change_percentage_30d_in_currency": q.get("percent_change_30d", 0),
                "total_volume": q.get("volume_24h", 0),
                "market_cap": q.get("market_cap", 0),
                "high_24h": q.get("price", 0),  # paprika lacks 24h high/low — use current as fallback
                "low_24h": q.get("price", 0),
                "ath": q.get("ath_price", 0),
                "_source": "coinpaprika",
            })
        return out

    async def collect_market_overview(self) -> list[MarketSignal]:
        """Fetch current prices and 24h changes for tracked coins."""
        signals = []
        try:
            ids = ",".join(self.TRACKED_COINS.keys())
            data = await _fetch_json(
                self._client,
                f"{self.BASE_URL}/coins/markets",'''

if "_paprika_market_overview" not in s:
    s = s.replace(old2, new2, 1)
    print("added _paprika_market_overview")

# In the except branch of collect_market_overview, fall through to paprika
old3 = """        except Exception as e:
            log.warning(f"CoinGecko market overview failed: {e}")

        return signals"""

new3 = """        except Exception as e:
            log.warning(f"CoinGecko market overview failed: {e}; falling back to CoinPaprika")
            try:
                data = await self._paprika_market_overview()
                for coin in data:
                    symbol = coin.get("symbol", "")
                    price = float(coin.get("current_price", 0) or 0)
                    change_24h = float(coin.get("price_change_percentage_24h", 0) or 0)
                    change_7d = float(coin.get("price_change_percentage_7d_in_currency", 0) or 0)
                    change_30d = float(coin.get("price_change_percentage_30d_in_currency", 0) or 0)
                    volume = float(coin.get("total_volume", 0) or 0)
                    market_cap = float(coin.get("market_cap", 0) or 0)
                    ath = float(coin.get("ath", 0) or 0)
                    if change_7d > 10:
                        direction = SignalDirection.BULLISH
                    elif change_7d < -10:
                        direction = SignalDirection.BEARISH
                    else:
                        direction = SignalDirection.NEUTRAL
                    signals.append(MarketSignal(
                        source=SourceType.CRYPTO,
                        category="crypto",
                        title=f"{symbol} ${price:,.2f} ({change_24h:+.1f}%)",
                        content=(
                            f"{symbol}: ${price:,.2f} | 24h: {change_24h:+.1f}% | "
                            f"7d: {change_7d:+.1f}% | 30d: {change_30d:+.1f}% | "
                            f"Vol: ${volume:,.0f} | MCap: ${market_cap:,.0f} | src=coinpaprika"
                        ),
                        symbol=symbol,
                        current_price=price,
                        market_cap=market_cap,
                        value=price,
                        change_pct=change_24h,
                        volume=volume,
                        direction=direction,
                        confidence=0.8,
                        tags=["crypto", symbol.lower(), "market_data", "coinpaprika"],
                        metadata={"change_7d": change_7d, "change_30d": change_30d, "ath": ath, "source": "coinpaprika"},
                    ))
                log.info(f"CoinPaprika fallback succeeded: {len(signals)} signals")
            except Exception as e2:
                log.warning(f"CoinPaprika fallback also failed: {e2}")

        return signals"""

if "CoinPaprika fallback succeeded" not in s:
    s = s.replace(old3, new3, 1)
    print("added Coinpaprika fallback in except branch")

open(p, "w").write(s)
print("DONE")
