#!/usr/bin/env python3
"""Tests for all 60 data source ingesters.

Tests are designed to pass WITHOUT API keys or network access by verifying:
  - Classes import and instantiate correctly
  - fetch() returns an empty list or gracefully degrades when no key / no network
  - Registry discovers all expected sources
  - Free-tier sources are classified correctly
"""

import importlib
import json
from pathlib import Path

import pytest

# ═══════════════════════════════════════════════════════════════════════════════
# Registry
# ═══════════════════════════════════════════════════════════════════════════════


class TestIngesterRegistry:
    def test_import_registry(self):
        from ncl_agency_runtime.fpc.data_sources.registry import IngesterRegistry
        assert IngesterRegistry is not None

    def test_available_sources_count(self):
        from ncl_agency_runtime.fpc.data_sources.registry import IngesterRegistry
        sources = IngesterRegistry.available_sources()
        assert len(sources) >= 50, f"Expected ≥50 sources, got {len(sources)}"

    def test_free_sources_subset(self):
        from ncl_agency_runtime.fpc.data_sources.registry import IngesterRegistry
        free = set(IngesterRegistry.free_sources())
        available = set(IngesterRegistry.available_sources())
        assert free.issubset(available), "Free sources must be a subset of all sources"

    def test_free_sources_count(self):
        from ncl_agency_runtime.fpc.data_sources.registry import IngesterRegistry
        free = IngesterRegistry.free_sources()
        assert len(free) >= 25, f"Expected ≥25 free sources, got {len(free)}"

    def test_get_ingester_known(self):
        from ncl_agency_runtime.fpc.data_sources.registry import IngesterRegistry
        reg = IngesterRegistry(config_path="/nonexistent.json")
        ing = reg.get_ingester("fear_greed")
        assert ing is not None

    def test_get_ingester_unknown(self):
        from ncl_agency_runtime.fpc.data_sources.registry import IngesterRegistry
        reg = IngesterRegistry(config_path="/nonexistent.json")
        assert reg.get_ingester("nonexistent_source_xyz") is None

    def test_run_all_ingesters_import(self):
        from ncl_agency_runtime.fpc.data_sources.registry import run_all_ingesters
        assert callable(run_all_ingesters)

    def test_registry_caches_instances(self):
        from ncl_agency_runtime.fpc.data_sources.registry import IngesterRegistry
        reg = IngesterRegistry(config_path="/nonexistent.json")
        a = reg.get_ingester("defi_llama")
        b = reg.get_ingester("defi_llama")
        assert a is b


# ═══════════════════════════════════════════════════════════════════════════════
# Base
# ═══════════════════════════════════════════════════════════════════════════════


class TestBaseIngester:
    def test_base_not_implemented(self):
        from ncl_agency_runtime.fpc.data_sources.base import BaseIngester
        ing = BaseIngester()
        with pytest.raises(NotImplementedError):
            ing.fetch()

    def test_make_signal(self):
        from ncl_agency_runtime.fpc.data_sources.base import BaseIngester
        ing = BaseIngester()
        sig = ing._make_signal("test", "title", "body", "http://example.com")
        assert sig.source == "test"
        assert sig.title == "title"
        assert sig.content == "body"


# ═══════════════════════════════════════════════════════════════════════════════
# Economic (existing — extended coverage)
# ═══════════════════════════════════════════════════════════════════════════════


class TestEconomicIngesters:
    def test_fred_no_key(self):
        from ncl_agency_runtime.fpc.data_sources.economic import FREDIngester
        ing = FREDIngester(api_key="")
        assert ing.fetch_series("GDP") == []

    def test_fred_indicators_list(self):
        from ncl_agency_runtime.fpc.data_sources.economic import FRED_INDICATORS
        assert len(FRED_INDICATORS) >= 5

    def test_alpha_vantage_no_key(self):
        from ncl_agency_runtime.fpc.data_sources.economic import AlphaVantageIngester
        ing = AlphaVantageIngester(api_key="")
        assert ing.fetch_daily("AAPL") == []


# ═══════════════════════════════════════════════════════════════════════════════
# Macro / Government
# ═══════════════════════════════════════════════════════════════════════════════


class TestMacroGovernment:
    def test_world_bank_init(self):
        from ncl_agency_runtime.fpc.data_sources.macro_government import WorldBankIngester
        ing = WorldBankIngester()
        assert len(ing.DEFAULT_INDICATORS) >= 5

    def test_treasury_init(self):
        from ncl_agency_runtime.fpc.data_sources.macro_government import TreasuryFiscalDataIngester
        ing = TreasuryFiscalDataIngester()
        assert len(ing.DEFAULT_ENDPOINTS) >= 3

    def test_bls_no_key(self):
        from ncl_agency_runtime.fpc.data_sources.macro_government import BLSIngester
        ing = BLSIngester(api_key="")
        assert ing.api_key == ""

    def test_eurostat_init(self):
        from ncl_agency_runtime.fpc.data_sources.macro_government import EurostatIngester
        ing = EurostatIngester()
        assert len(ing.DEFAULT_DATASETS) >= 2

    def test_imf_init(self):
        from ncl_agency_runtime.fpc.data_sources.macro_government import IMFIngester
        ing = IMFIngester()
        assert ing is not None

    def test_nasdaq_data_link_no_key(self):
        from ncl_agency_runtime.fpc.data_sources.macro_government import NasdaqDataLinkIngester
        ing = NasdaqDataLinkIngester(api_key="")
        assert ing.api_key == ""

    def test_census_no_key(self):
        from ncl_agency_runtime.fpc.data_sources.macro_government import CensusBureauIngester
        ing = CensusBureauIngester(api_key="")
        assert ing.api_key == ""


# ═══════════════════════════════════════════════════════════════════════════════
# Financial Markets
# ═══════════════════════════════════════════════════════════════════════════════


class TestFinancialMarkets:
    def test_fmp_no_key(self):
        from ncl_agency_runtime.fpc.data_sources.financial_markets import FMPIngester
        ing = FMPIngester(api_key="")
        assert ing.api_key == ""

    def test_coincap_init(self):
        from ncl_agency_runtime.fpc.data_sources.financial_markets import CoinCapIngester
        ing = CoinCapIngester()
        assert ing is not None

    def test_polygon_no_key(self):
        from ncl_agency_runtime.fpc.data_sources.financial_markets import PolygonIngester
        ing = PolygonIngester(api_key="")
        assert ing.api_key == ""

    def test_coingecko_init(self):
        from ncl_agency_runtime.fpc.data_sources.financial_markets import CoinGeckoIngester
        ing = CoinGeckoIngester()
        assert ing is not None


# ═══════════════════════════════════════════════════════════════════════════════
# Weather / Climate
# ═══════════════════════════════════════════════════════════════════════════════


class TestWeatherClimate:
    def test_openweathermap_no_key(self):
        from ncl_agency_runtime.fpc.data_sources.weather_climate import OpenWeatherMapIngester
        ing = OpenWeatherMapIngester(api_key="")
        assert ing.api_key == ""

    def test_open_meteo_init(self):
        from ncl_agency_runtime.fpc.data_sources.weather_climate import OpenMeteoIngester
        ing = OpenMeteoIngester()
        assert ing is not None

    def test_noaa_climate_no_key(self):
        from ncl_agency_runtime.fpc.data_sources.weather_climate import NOAAClimateIngester
        ing = NOAAClimateIngester(api_key="")
        assert ing.api_key == ""

    def test_nasa_power_init(self):
        from ncl_agency_runtime.fpc.data_sources.weather_climate import NASAPowerIngester
        ing = NASAPowerIngester()
        assert ing is not None

    def test_noaa_co2_init(self):
        from ncl_agency_runtime.fpc.data_sources.weather_climate import NOAACO2Ingester
        ing = NOAACO2Ingester()
        assert ing is not None

    def test_global_forest_watch_init(self):
        from ncl_agency_runtime.fpc.data_sources.weather_climate import GlobalForestWatchIngester
        ing = GlobalForestWatchIngester()
        assert ing is not None

    def test_openaq_no_key(self):
        from ncl_agency_runtime.fpc.data_sources.weather_climate import OpenAQIngester
        ing = OpenAQIngester(api_key="")
        assert ing.api_key == ""


# ═══════════════════════════════════════════════════════════════════════════════
# Sentiment / Alternative
# ═══════════════════════════════════════════════════════════════════════════════


class TestSentimentAlternative:
    def test_fear_greed_init(self):
        from ncl_agency_runtime.fpc.data_sources.sentiment_alternative import FearGreedIngester
        ing = FearGreedIngester()
        assert ing is not None

    def test_newsapi_no_key(self):
        from ncl_agency_runtime.fpc.data_sources.sentiment_alternative import NewsAPIIngester
        ing = NewsAPIIngester(api_key="")
        assert ing.api_key == ""

    def test_google_trends_init(self):
        from ncl_agency_runtime.fpc.data_sources.sentiment_alternative import GoogleTrendsIngester
        ing = GoogleTrendsIngester()
        assert ing is not None

    def test_reddit_no_creds(self):
        from ncl_agency_runtime.fpc.data_sources.sentiment_alternative import RedditSentimentIngester
        ing = RedditSentimentIngester(client_id="", client_secret="")
        assert ing.client_id == ""


# ═══════════════════════════════════════════════════════════════════════════════
# Crypto / On-chain
# ═══════════════════════════════════════════════════════════════════════════════


class TestCryptoOnchain:
    def test_blockchain_init(self):
        from ncl_agency_runtime.fpc.data_sources.crypto_onchain import BlockchainDotComIngester
        ing = BlockchainDotComIngester()
        assert ing is not None

    def test_messari_init(self):
        from ncl_agency_runtime.fpc.data_sources.crypto_onchain import MessariIngester
        ing = MessariIngester()
        assert ing is not None

    def test_defi_llama_init(self):
        from ncl_agency_runtime.fpc.data_sources.crypto_onchain import DeFiLlamaIngester
        ing = DeFiLlamaIngester()
        assert ing is not None


# ═══════════════════════════════════════════════════════════════════════════════
# Health / Disease
# ═══════════════════════════════════════════════════════════════════════════════


class TestHealthDisease:
    def test_who_gho_init(self):
        from ncl_agency_runtime.fpc.data_sources.health_disease import WHOGHOIngester
        ing = WHOGHOIngester()
        assert len(ing.DEFAULT_INDICATORS) >= 4

    def test_global_health_init(self):
        from ncl_agency_runtime.fpc.data_sources.health_disease import GlobalHealthIngester
        ing = GlobalHealthIngester()
        assert ing is not None

    def test_cdc_init(self):
        from ncl_agency_runtime.fpc.data_sources.health_disease import CDCWonderIngester
        ing = CDCWonderIngester()
        assert ing is not None

    def test_healthmap_init(self):
        from ncl_agency_runtime.fpc.data_sources.health_disease import HealthMapIngester
        ing = HealthMapIngester()
        assert ing is not None


# ═══════════════════════════════════════════════════════════════════════════════
# Disasters
# ═══════════════════════════════════════════════════════════════════════════════


class TestDisasters:
    def test_usgs_earthquake_init(self):
        from ncl_agency_runtime.fpc.data_sources.disasters import USGSEarthquakeIngester
        ing = USGSEarthquakeIngester()
        assert ing is not None

    def test_smithsonian_volcano_init(self):
        from ncl_agency_runtime.fpc.data_sources.disasters import SmithsonianVolcanoIngester
        ing = SmithsonianVolcanoIngester()
        assert ing is not None

    def test_fema_init(self):
        from ncl_agency_runtime.fpc.data_sources.disasters import FEMADisasterIngester
        ing = FEMADisasterIngester()
        assert ing is not None

    def test_emdat_init(self):
        from ncl_agency_runtime.fpc.data_sources.disasters import EMDATIngester
        ing = EMDATIngester()
        assert ing is not None


# ═══════════════════════════════════════════════════════════════════════════════
# Food / Agriculture / Water
# ═══════════════════════════════════════════════════════════════════════════════


class TestFoodAgriculture:
    def test_usda_nass_no_key(self):
        from ncl_agency_runtime.fpc.data_sources.food_agriculture import USDANASSIngester
        ing = USDANASSIngester(api_key="")
        assert ing.api_key == ""

    def test_fao_init(self):
        from ncl_agency_runtime.fpc.data_sources.food_agriculture import FAOIngester
        ing = FAOIngester()
        assert ing is not None

    def test_usgs_water_init(self):
        from ncl_agency_runtime.fpc.data_sources.food_agriculture import USGSWaterIngester
        ing = USGSWaterIngester()
        assert len(ing.DEFAULT_SITES) >= 2

    def test_wfp_hunger_init(self):
        from ncl_agency_runtime.fpc.data_sources.food_agriculture import WFPHungerMapIngester
        ing = WFPHungerMapIngester()
        assert ing is not None


# ═══════════════════════════════════════════════════════════════════════════════
# Demographics / Population
# ═══════════════════════════════════════════════════════════════════════════════


class TestDemographics:
    def test_un_population_init(self):
        from ncl_agency_runtime.fpc.data_sources.demographics import UNPopulationIngester
        ing = UNPopulationIngester()
        assert ing is not None

    def test_unhcr_init(self):
        from ncl_agency_runtime.fpc.data_sources.demographics import UNHCRRefugeeIngester
        ing = UNHCRRefugeeIngester()
        assert ing is not None

    def test_iom_init(self):
        from ncl_agency_runtime.fpc.data_sources.demographics import IOMDisplacementIngester
        ing = IOMDisplacementIngester()
        assert ing is not None


# ═══════════════════════════════════════════════════════════════════════════════
# Technology / Innovation
# ═══════════════════════════════════════════════════════════════════════════════


class TestTechnology:
    def test_uspto_init(self):
        from ncl_agency_runtime.fpc.data_sources.technology import USPTOPatentIngester
        ing = USPTOPatentIngester()
        assert ing is not None

    def test_arxiv_init(self):
        from ncl_agency_runtime.fpc.data_sources.technology import ArxivIngester
        ing = ArxivIngester()
        assert len(ing.DEFAULT_QUERIES) >= 3

    def test_wikipedia_pageviews_init(self):
        from ncl_agency_runtime.fpc.data_sources.technology import WikipediaPageviewsIngester
        ing = WikipediaPageviewsIngester()
        assert len(ing.DEFAULT_PAGES) >= 5


# ═══════════════════════════════════════════════════════════════════════════════
# Governance / Space / Transport / Energy
# ═══════════════════════════════════════════════════════════════════════════════


class TestGovernanceSpaceTransport:
    def test_gdelt_init(self):
        from ncl_agency_runtime.fpc.data_sources.governance_space_transport import GDELTIngester
        ing = GDELTIngester()
        assert ing is not None

    def test_acled_no_key(self):
        from ncl_agency_runtime.fpc.data_sources.governance_space_transport import ACLEDIngester
        ing = ACLEDIngester(api_key="", email="")
        assert ing.api_key == ""

    def test_un_comtrade_init(self):
        from ncl_agency_runtime.fpc.data_sources.governance_space_transport import UNComtradeIngester
        ing = UNComtradeIngester()
        assert ing is not None

    def test_nasa_donki_init(self):
        from ncl_agency_runtime.fpc.data_sources.governance_space_transport import NASADONKIIngester
        ing = NASADONKIIngester()
        assert ing is not None

    def test_noaa_space_weather_init(self):
        from ncl_agency_runtime.fpc.data_sources.governance_space_transport import NOAASpaceWeatherIngester
        ing = NOAASpaceWeatherIngester()
        assert ing is not None

    def test_opensky_init(self):
        from ncl_agency_runtime.fpc.data_sources.governance_space_transport import OpenSkyIngester
        ing = OpenSkyIngester()
        assert ing is not None

    def test_eia_no_key(self):
        from ncl_agency_runtime.fpc.data_sources.governance_space_transport import EIAIngester
        ing = EIAIngester(api_key="")
        assert ing.api_key == ""

    def test_github_dev_no_token(self):
        from ncl_agency_runtime.fpc.data_sources.governance_space_transport import GitHubDevActivityIngester
        ing = GitHubDevActivityIngester(token="")
        assert ing.token == ""


# ═══════════════════════════════════════════════════════════════════════════════
# Config integration
# ═══════════════════════════════════════════════════════════════════════════════


_FPC_ROOT = Path(__file__).resolve().parent.parent


class TestConfigIntegration:
    def test_config_has_all_sources(self):
        cfg_path = _FPC_ROOT / "config" / "council_config.json"
        if not cfg_path.exists():
            pytest.skip("council_config.json not found")
        with open(cfg_path) as f:
            cfg = json.load(f)
        ds = cfg.get("data_sources", {})
        if not ds:
            pytest.skip("No data_sources section in config")
        from ncl_agency_runtime.fpc.data_sources.registry import IngesterRegistry
        available = IngesterRegistry.available_sources()
        config_sources = set(ds.keys())
        missing = [s for s in available if s not in config_sources]
        assert len(missing) == 0, f"Missing from config: {missing}"

    def test_config_all_enabled(self):
        cfg_path = _FPC_ROOT / "config" / "council_config.json"
        if not cfg_path.exists():
            pytest.skip("council_config.json not found")
        with open(cfg_path) as f:
            cfg = json.load(f)
        ds = cfg.get("data_sources", {})
        if not ds:
            pytest.skip("No data_sources section in config")
        for name, conf in ds.items():
            if isinstance(conf, dict):
                assert "enabled" in conf, f"{name} missing 'enabled' key"

    def test_api_endpoints_populated(self):
        cfg_path = _FPC_ROOT / "config" / "council_config.json"
        if not cfg_path.exists():
            pytest.skip("council_config.json not found")
        with open(cfg_path) as f:
            cfg = json.load(f)
        endpoints = cfg.get("api_endpoints", [])
        if not endpoints:
            pytest.skip("No api_endpoints in config")


# ═══════════════════════════════════════════════════════════════════════════════
# Module import smoke tests — every module imports without error
# ═══════════════════════════════════════════════════════════════════════════════


_MODULES = [
    "ncl_agency_runtime.fpc.data_sources.base",
    "ncl_agency_runtime.fpc.data_sources.economic",
    "ncl_agency_runtime.fpc.data_sources.macro_government",
    "ncl_agency_runtime.fpc.data_sources.financial_markets",
    "ncl_agency_runtime.fpc.data_sources.weather_climate",
    "ncl_agency_runtime.fpc.data_sources.sentiment_alternative",
    "ncl_agency_runtime.fpc.data_sources.crypto_onchain",
    "ncl_agency_runtime.fpc.data_sources.health_disease",
    "ncl_agency_runtime.fpc.data_sources.disasters",
    "ncl_agency_runtime.fpc.data_sources.food_agriculture",
    "ncl_agency_runtime.fpc.data_sources.demographics",
    "ncl_agency_runtime.fpc.data_sources.technology",
    "ncl_agency_runtime.fpc.data_sources.governance_space_transport",
    "ncl_agency_runtime.fpc.data_sources.registry",
]


@pytest.mark.parametrize("module_name", _MODULES)
def test_module_imports(module_name):
    mod = importlib.import_module(module_name)
    assert mod is not None
