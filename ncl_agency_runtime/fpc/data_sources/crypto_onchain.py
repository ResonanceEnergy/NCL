"""Crypto & blockchain on-chain data ingesters.

APIs: Blockchain.com, Messari, DeFi Llama.
"""

import json
import logging
from datetime import datetime
from typing import ClassVar

from ..ingestion import Signal
from .base import BaseIngester

logger = logging.getLogger(__name__)


class BlockchainDotComIngester(BaseIngester):
    """Blockchain.com — Bitcoin on-chain metrics. No key required."""

    source_name = "blockchain_com"
    BASE_URL = "https://api.blockchain.info"

    # Key BTC on-chain metrics
    CHART_NAMES: ClassVar[list[str]] = [
        "hash-rate",             # Network hash rate
        "difficulty",            # Mining difficulty
        "n-transactions",        # Daily transaction count
        "mempool-size",          # Mempool size (bytes)
        "avg-block-size",        # Average block size
        "n-unique-addresses",    # Unique addresses used
        "estimated-transaction-volume-usd",  # Est. tx volume (USD)
        "miners-revenue",        # Miner revenue (USD)
    ]

    def fetch(
        self,
        charts: list[str] | None = None,
        timespan: str = "30days",
    ) -> list[Signal]:
        charts = charts or self.CHART_NAMES
        signals: list[Signal] = []
        for chart_name in charts:
            try:
                url = f"{self.BASE_URL}/charts/{chart_name}?timespan={timespan}&format=json"
                data = self._get_json(url)
                for point in data.get("values", []):
                    ts = datetime.fromtimestamp(point.get("x", 0))
                    val = point.get("y", 0)
                    signals.append(self._make_signal(
                        source=f"Blockchain:{chart_name}",
                        title=f"BTC {chart_name} — {ts.date()} — {val:,.2f}",
                        content=json.dumps({"date": str(ts.date()), "value": val}),
                        timestamp=ts,
                        meta={"metric": chart_name, "value": val},
                    ))
            except Exception:
                logger.warning("Blockchain.com fetch failed for %s", chart_name)
        logger.info("Blockchain.com: ingested %d signals", len(signals))
        return signals


class MessariIngester(BaseIngester):
    """Messari — crypto asset profiles, on-chain metrics."""

    source_name = "messari"
    BASE_URL = "https://data.messari.io/api/v1"

    def fetch(
        self,
        assets: list[str] | None = None,
    ) -> list[Signal]:
        assets = assets or ["bitcoin", "ethereum", "solana", "cardano", "polkadot"]
        signals: list[Signal] = []
        for asset in assets:
            try:
                url = f"{self.BASE_URL}/assets/{asset}/metrics"
                data = self._get_json(url)
                metrics = data.get("data", {})
                market = metrics.get("market_data", {})
                onchain = metrics.get("on_chain_data", {})
                dev_activity = metrics.get("developer_activity", {})

                signals.append(self._make_signal(
                    source=f"Messari:{asset}",
                    title=f"{asset} — ${market.get('price_usd', '')}",
                    content=json.dumps({
                        "price_usd": market.get("price_usd"),
                        "market_cap": market.get("real_volume_last_24_hours"),
                        "volume_24h": market.get("volume_last_24_hours"),
                        "nvt_ratio": onchain.get("txn_count_last_24_hours"),
                        "active_addresses": onchain.get("active_addresses"),
                        "hash_rate": onchain.get("hash_rate"),
                        "dev_stars": dev_activity.get("stars"),
                        "dev_commits_30d": dev_activity.get("commits_last_30_days"),
                    }),
                    meta={
                        "asset": asset,
                        "price": market.get("price_usd"),
                        "active_addresses": onchain.get("active_addresses"),
                    },
                ))
            except Exception:
                logger.warning("Messari fetch failed for %s", asset)
        logger.info("Messari: ingested %d signals", len(signals))
        return signals


class DeFiLlamaIngester(BaseIngester):
    """DeFi Llama — TVL, stablecoin supply, protocol revenue. No key."""

    source_name = "defi_llama"
    BASE_URL = "https://api.llama.fi"

    def fetch(self) -> list[Signal]:
        signals: list[Signal] = []

        # Total TVL across all DeFi
        try:
            data = self._get_json(f"{self.BASE_URL}/v2/historicalChainTvl")
            for point in (data or [])[-30:]:
                ts = datetime.fromtimestamp(point.get("date", 0))
                tvl = point.get("tvl", 0)
                signals.append(self._make_signal(
                    source="DeFiLlama:totalTVL",
                    title=f"DeFi Total TVL — {ts.date()} — ${tvl:,.0f}",
                    content=json.dumps(point),
                    timestamp=ts,
                    meta={"tvl": tvl},
                ))
        except Exception:
            logger.warning("DeFi Llama total TVL failed")

        # Top protocols by TVL
        try:
            data = self._get_json(f"{self.BASE_URL}/protocols")
            for proto in (data or [])[:20]:
                signals.append(self._make_signal(
                    source=f"DeFiLlama:protocol:{proto.get('name', '')}",
                    title=f"{proto.get('name', '')} — TVL: ${proto.get('tvl', 0):,.0f}",
                    content=json.dumps({
                        "name": proto.get("name"),
                        "tvl": proto.get("tvl"),
                        "chain": proto.get("chain"),
                        "category": proto.get("category"),
                        "change_1h": proto.get("change_1h"),
                        "change_1d": proto.get("change_1d"),
                        "change_7d": proto.get("change_7d"),
                    }),
                    meta={
                        "protocol": proto.get("name"),
                        "tvl": proto.get("tvl"),
                        "change_1d": proto.get("change_1d"),
                    },
                ))
        except Exception:
            logger.warning("DeFi Llama protocols failed")

        # Stablecoins
        try:
            data = self._get_json(f"{self.BASE_URL}/stablecoins?includePrices=true")
            for stable in data.get("peggedAssets", [])[:10]:
                mc = stable.get("circulating", {}).get("peggedUSD", 0)
                signals.append(self._make_signal(
                    source=f"DeFiLlama:stable:{stable.get('name', '')}",
                    title=f"Stablecoin {stable.get('name', '')} — MCap: ${mc:,.0f}",
                    content=json.dumps(stable),
                    meta={"stablecoin": stable.get("name"), "market_cap": mc},
                ))
        except Exception:
            logger.warning("DeFi Llama stablecoins failed")

        logger.info("DeFiLlama: ingested %d signals", len(signals))
        return signals
