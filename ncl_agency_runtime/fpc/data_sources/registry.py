"""Ingester registry — discovers, configures, and runs all 60 data source ingesters."""

import json
import logging

from ..ingestion import Signal
from .base import BaseIngester
from .crypto_onchain import (
    BlockchainDotComIngester,
    DeFiLlamaIngester,
    MessariIngester,
)
from .demographics import (
    IOMDisplacementIngester,
    UNHCRRefugeeIngester,
    UNPopulationIngester,
)
from .disasters import (
    EMDATIngester,
    FEMADisasterIngester,
    SmithsonianVolcanoIngester,
    USGSEarthquakeIngester,
)

# ── Import all ingesters ─────────────────────────────────────────────────────
from .economic import AlphaVantageIngester, FREDIngester
from .financial_markets import (
    CoinCapIngester,
    CoinGeckoIngester,
    FMPIngester,
    PolygonIngester,
)
from .food_agriculture import (
    FAOIngester,
    USDANASSIngester,
    USGSWaterIngester,
    WFPHungerMapIngester,
)
from .governance_space_transport import (
    ACLEDIngester,
    EIAIngester,
    GDELTIngester,
    GitHubDevActivityIngester,
    NASADONKIIngester,
    NOAASpaceWeatherIngester,
    OpenSkyIngester,
    UNComtradeIngester,
)
from .health_disease import (
    CDCWonderIngester,
    GlobalHealthIngester,
    HealthMapIngester,
    WHOGHOIngester,
)
from .macro_government import (
    BLSIngester,
    CensusBureauIngester,
    EurostatIngester,
    IMFIngester,
    NasdaqDataLinkIngester,
    TreasuryFiscalDataIngester,
    WorldBankIngester,
)
from .sentiment_alternative import (
    FearGreedIngester,
    GoogleTrendsIngester,
    NewsAPIIngester,
    RedditSentimentIngester,
)
from .technology import (
    ArxivIngester,
    USPTOPatentIngester,
    WikipediaPageviewsIngester,
)
from .weather_climate import (
    GlobalForestWatchIngester,
    NASAPowerIngester,
    NOAAClimateIngester,
    NOAACO2Ingester,
    OpenAQIngester,
    OpenMeteoIngester,
    OpenWeatherMapIngester,
)

logger = logging.getLogger(__name__)

# ── Master registry ──────────────────────────────────────────────────────────
# Maps source_name → ingester class.  Grouped by domain for readability.

_INGESTER_CLASSES: dict[str, type[BaseIngester]] = {
    # ── Economic (existing) ──
    "fred": FREDIngester,
    "alpha_vantage": AlphaVantageIngester,

    # ── Macro / Government ──
    "world_bank": WorldBankIngester,
    "treasury": TreasuryFiscalDataIngester,
    "bls": BLSIngester,
    "eurostat": EurostatIngester,
    "imf": IMFIngester,
    "nasdaq_data_link": NasdaqDataLinkIngester,
    "census": CensusBureauIngester,

    # ── Financial Markets ──
    "fmp": FMPIngester,
    "coincap": CoinCapIngester,
    "polygon": PolygonIngester,
    "coingecko": CoinGeckoIngester,

    # ── Weather / Climate ──
    "openweathermap": OpenWeatherMapIngester,
    "open_meteo": OpenMeteoIngester,
    "noaa_climate": NOAAClimateIngester,
    "nasa_power": NASAPowerIngester,
    "noaa_co2": NOAACO2Ingester,
    "global_forest_watch": GlobalForestWatchIngester,
    "openaq": OpenAQIngester,

    # ── Sentiment / Alternative ──
    "fear_greed": FearGreedIngester,
    "newsapi": NewsAPIIngester,
    "google_trends": GoogleTrendsIngester,
    "reddit": RedditSentimentIngester,

    # ── Crypto / On-chain ──
    "blockchain_com": BlockchainDotComIngester,
    "messari": MessariIngester,
    "defi_llama": DeFiLlamaIngester,

    # ── Health / Disease ──
    "who_gho": WHOGHOIngester,
    "global_health": GlobalHealthIngester,
    "cdc": CDCWonderIngester,
    "healthmap": HealthMapIngester,

    # ── Disasters ──
    "usgs_earthquake": USGSEarthquakeIngester,
    "volcano": SmithsonianVolcanoIngester,
    "fema": FEMADisasterIngester,
    "emdat": EMDATIngester,

    # ── Food / Agriculture / Water ──
    "usda_nass": USDANASSIngester,
    "fao": FAOIngester,
    "usgs_water": USGSWaterIngester,
    "wfp_hunger": WFPHungerMapIngester,

    # ── Demographics / Population ──
    "un_population": UNPopulationIngester,
    "unhcr": UNHCRRefugeeIngester,
    "iom_dtm": IOMDisplacementIngester,

    # ── Technology / Innovation ──
    "uspto": USPTOPatentIngester,
    "arxiv": ArxivIngester,
    "wikipedia_pageviews": WikipediaPageviewsIngester,

    # ── Governance / Geopolitical ──
    "gdelt": GDELTIngester,
    "acled": ACLEDIngester,
    "un_comtrade": UNComtradeIngester,

    # ── Space Weather ──
    "nasa_donki": NASADONKIIngester,
    "noaa_space_weather": NOAASpaceWeatherIngester,

    # ── Transport ──
    "opensky": OpenSkyIngester,

    # ── Energy ──
    "eia": EIAIngester,

    # ── Dev Activity ──
    "github_dev": GitHubDevActivityIngester,
}

# Sources that need NO API key — can run immediately
FREE_SOURCES = {
    "world_bank", "treasury", "eurostat", "imf",
    "open_meteo", "noaa_co2", "nasa_power", "global_forest_watch",
    "fear_greed", "blockchain_com", "defi_llama",
    "who_gho", "global_health", "healthmap",
    "usgs_earthquake", "volcano", "fema", "emdat",
    "fao", "usgs_water", "wfp_hunger",
    "un_population", "unhcr", "iom_dtm",
    "arxiv", "wikipedia_pageviews",
    "gdelt", "un_comtrade",
    "nasa_donki", "noaa_space_weather",
    "opensky",
}


class IngesterRegistry:
    """Discover, instantiate, and run configured ingesters."""

    def __init__(self, config_path: str = "config/council_config.json"):
        self.config = self._load_config(config_path)
        self._instances: dict[str, BaseIngester] = {}

    @staticmethod
    def _load_config(path: str) -> dict:
        try:
            with open(path) as f:
                return json.load(f)
        except FileNotFoundError:
            logger.warning("Config not found at %s — using defaults", path)
            return {}

    @staticmethod
    def available_sources() -> list[str]:
        return sorted(_INGESTER_CLASSES.keys())

    @staticmethod
    def free_sources() -> list[str]:
        return sorted(FREE_SOURCES)

    def get_ingester(self, name: str) -> BaseIngester | None:
        if name in self._instances:
            return self._instances[name]
        cls = _INGESTER_CLASSES.get(name)
        if cls is None:
            logger.warning("Unknown ingester: %s", name)
            return None
        try:
            instance = cls()
            self._instances[name] = instance
            return instance
        except Exception:
            logger.warning("Failed to instantiate ingester: %s", name)
            return None

    def run_sources(
        self,
        sources: list[str] | None = None,
        free_only: bool = False,
    ) -> list[Signal]:
        if sources is None:
            # Use config-enabled sources, or all free sources
            ds_config = self.config.get("data_sources", {})
            sources = [
                name for name, cfg in ds_config.items()
                if isinstance(cfg, dict) and cfg.get("enabled", False)
            ]
            if not sources:
                sources = list(FREE_SOURCES) if free_only else list(_INGESTER_CLASSES.keys())

        all_signals: list[Signal] = []
        for name in sources:
            if free_only and name not in FREE_SOURCES:
                continue
            ingester = self.get_ingester(name)
            if ingester is None:
                continue
            try:
                logger.info("Running ingester: %s", name)
                signals = ingester.fetch()
                all_signals.extend(signals)
                logger.info("  → %s returned %d signals", name, len(signals))
            except Exception:
                logger.warning("Ingester %s raised an exception — skipping", name)
        return all_signals


def run_all_ingesters(
    config_path: str = "config/council_config.json",
    sources: list[str] | None = None,
    free_only: bool = False,
) -> list[Signal]:
    """Convenience function to run all or selected ingesters."""
    registry = IngesterRegistry(config_path)
    return registry.run_sources(sources=sources, free_only=free_only)
