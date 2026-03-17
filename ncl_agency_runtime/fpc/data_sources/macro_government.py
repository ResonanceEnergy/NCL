"""Macroeconomic & government data ingesters.

APIs: World Bank, U.S. Treasury Fiscal Data, BLS, Eurostat, IMF,
      Nasdaq Data Link (Quandl), FMP Economics.
"""

import contextlib
import json
import logging
import os
from datetime import datetime
from typing import ClassVar

from ..ingestion import Signal
from .base import BaseIngester

logger = logging.getLogger(__name__)


class WorldBankIngester(BaseIngester):
    """World Bank Indicators — 16,000+ indicators, no API key required."""

    source_name = "world_bank"
    BASE_URL = "https://api.worldbank.org/v2"

    # Key predictive indicators
    DEFAULT_INDICATORS: ClassVar[list[str]] = [
        "NY.GDP.MKTP.KD.ZG",   # GDP growth (annual %)
        "FP.CPI.TOTL.ZG",      # Inflation (CPI annual %)
        "SL.UEM.TOTL.ZS",      # Unemployment (% of labor force)
        "BN.CAB.XOKA.GD.ZS",   # Current account balance (% of GDP)
        "GC.DOD.TOTL.GD.ZS",   # Central govt debt (% of GDP)
        "NE.TRD.GNFS.ZS",      # Trade (% of GDP)
        "BX.KLT.DINV.WD.GD.ZS",# FDI net inflows (% of GDP)
        "FR.INR.RINR",          # Real interest rate (%)
    ]

    def fetch(
        self,
        country: str = "US",
        indicators: list[str] | None = None,
        date_range: str = "2015:2026",
        per_page: int = 100,
    ) -> list[Signal]:
        indicators = indicators or self.DEFAULT_INDICATORS
        signals: list[Signal] = []
        for ind in indicators:
            try:
                url = (
                    f"{self.BASE_URL}/country/{country}/indicator/{ind}"
                    f"?format=json&date={date_range}&per_page={per_page}"
                )
                data = self._get_json(url)
                if not isinstance(data, list) or len(data) < 2:
                    continue
                for obs in data[1] or []:
                    if obs.get("value") is None:
                        continue
                    signals.append(self._make_signal(
                        source=f"WorldBank:{ind}",
                        title=f"{ind} — {obs.get('date', '')} — {country}",
                        content=json.dumps(obs),
                        url=f"{self.BASE_URL}/country/{country}/indicator/{ind}",
                        timestamp=datetime(int(obs["date"]), 1, 1) if obs.get("date", "").isdigit() else datetime.now(),
                        meta={"indicator": ind, "country": country, "value": obs["value"]},
                    ))
            except Exception:
                logger.warning("WorldBank fetch failed for %s", ind)
        logger.info("WorldBank: ingested %d signals", len(signals))
        return signals


class TreasuryFiscalDataIngester(BaseIngester):
    """U.S. Treasury Fiscal Data API — no API key required."""

    source_name = "treasury"
    BASE_URL = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service"

    DEFAULT_ENDPOINTS: ClassVar[dict[str, str]] = {
        "avg_interest_rates": "/v2/accounting/od/avg_interest_rates",
        "debt_to_penny": "/v2/accounting/od/debt_to_penny",
        "rates_of_exchange": "/v1/accounting/od/rates_of_exchange",
        "treasury_statement": "/v1/accounting/dts/dts_table_1",
    }

    def fetch(
        self,
        endpoints: dict[str, str] | None = None,
        page_size: int = 50,
        sort: str = "-record_date",
    ) -> list[Signal]:
        endpoints = endpoints or self.DEFAULT_ENDPOINTS
        signals: list[Signal] = []
        for name, path in endpoints.items():
            try:
                url = f"{self.BASE_URL}{path}?page[size]={page_size}&sort={sort}"
                data = self._get_json(url)
                for rec in data.get("data", []):
                    ts = datetime.now()
                    if rec.get("record_date"):
                        with contextlib.suppress(ValueError):
                            ts = datetime.fromisoformat(rec["record_date"])
                    signals.append(self._make_signal(
                        source=f"Treasury:{name}",
                        title=f"{name} — {rec.get('record_date', '')}",
                        content=json.dumps(rec),
                        url=f"{self.BASE_URL}{path}",
                        timestamp=ts,
                        meta={"endpoint": name, "record": rec},
                    ))
            except Exception:
                logger.warning("Treasury fetch failed for %s", name)
        logger.info("Treasury: ingested %d signals", len(signals))
        return signals


class BLSIngester(BaseIngester):
    """Bureau of Labor Statistics — CPI, unemployment, wages."""

    source_name = "bls"
    BASE_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"

    DEFAULT_SERIES: ClassVar[list[str]] = [
        "CUUR0000SA0",   # CPI-U All Urban Consumers
        "LNS14000000",   # Unemployment rate
        "CES0000000001", # Total nonfarm employment
        "CES0500000003", # Avg hourly earnings, private
    ]

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("BLS_API_KEY", "")

    def fetch(
        self,
        series_ids: list[str] | None = None,
        start_year: int = 2020,
        end_year: int = 2026,
    ) -> list[Signal]:
        series_ids = series_ids or self.DEFAULT_SERIES
        signals: list[Signal] = []
        payload = json.dumps({
            "seriesid": series_ids,
            "startyear": str(start_year),
            "endyear": str(end_year),
            "registrationkey": self.api_key,
        }).encode()
        try:
            import urllib.request
            req = urllib.request.Request(
                self.BASE_URL,
                data=payload,
                headers={"Content-Type": "application/json", "User-Agent": "FPC/0.4"},
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode())
        except Exception:
            logger.warning("BLS API request failed")
            return signals

        for series in data.get("Results", {}).get("series", []):
            sid = series.get("seriesID", "")
            for obs in series.get("data", []):
                yr = int(obs.get("year", 2020))
                mo = int(obs.get("period", "M01").replace("M", "").replace("A", "1"))
                mo = max(1, min(12, mo))
                signals.append(self._make_signal(
                    source=f"BLS:{sid}",
                    title=f"{sid} — {obs.get('year')}-{obs.get('period')}",
                    content=json.dumps(obs),
                    url=f"https://data.bls.gov/timeseries/{sid}",
                    timestamp=datetime(yr, mo, 1),
                    meta={"series_id": sid, "value": obs.get("value", "")},
                ))
        logger.info("BLS: ingested %d signals", len(signals))
        return signals


class EurostatIngester(BaseIngester):
    """Eurostat — European economic statistics, no API key."""

    source_name = "eurostat"
    BASE_URL = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"

    DEFAULT_DATASETS: ClassVar[list[str]] = [
        "prc_hicp_manr",  # HICP inflation monthly
        "une_rt_m",       # Unemployment rate monthly
        "nama_10_gdp",    # GDP and main components
    ]

    def fetch(
        self,
        datasets: list[str] | None = None,
        geo: str = "EU27_2020",
    ) -> list[Signal]:
        datasets = datasets or self.DEFAULT_DATASETS
        signals: list[Signal] = []
        for ds in datasets:
            try:
                url = f"{self.BASE_URL}/{ds}?format=JSON&geo={geo}&lang=en"
                data = self._get_json(url)
                values = data.get("value", {})
                dims = data.get("dimension", {})
                time_dim = dims.get("time", {}).get("category", {}).get("index", {})
                for idx_str, val in values.items():
                    # Map numeric index back to time label
                    time_labels = {v: k for k, v in time_dim.items()}
                    period = time_labels.get(int(idx_str), idx_str)
                    signals.append(self._make_signal(
                        source=f"Eurostat:{ds}",
                        title=f"{ds} — {period} — {geo}",
                        content=json.dumps({"period": period, "value": val}),
                        url=f"https://ec.europa.eu/eurostat/databrowser/view/{ds}",
                        meta={"dataset": ds, "geo": geo, "value": val, "period": period},
                    ))
            except Exception:
                logger.warning("Eurostat fetch failed for %s", ds)
        logger.info("Eurostat: ingested %d signals", len(signals))
        return signals


class IMFIngester(BaseIngester):
    """IMF Data — International Financial Statistics, no API key."""

    source_name = "imf"
    BASE_URL = "https://dataservices.imf.org/REST/SDMX_JSON.svc"

    DEFAULT_INDICATORS: ClassVar[dict[str, str]] = {
        "NGDP_RPCH": "Real GDP growth",
        "PCPIPCH": "Inflation rate",
        "BCA_NGDPD": "Current account (% GDP)",
    }

    def fetch(
        self,
        database: str = "WEO",
        countries: list[str] | None = None,
    ) -> list[Signal]:
        countries = countries or ["US", "CN", "DE", "JP", "GB"]
        signals: list[Signal] = []
        try:
            url = f"{self.BASE_URL}/CompactData/IFS/M..FPOLM_PA"
            data = self._get_json(url)
            series_list = (
                data.get("CompactData", {})
                .get("DataSet", {})
                .get("Series", [])
            )
            if isinstance(series_list, dict):
                series_list = [series_list]
            for series in series_list[:200]:
                ref_area = series.get("@REF_AREA", "")
                indicator = series.get("@INDICATOR", "")
                obs_list = series.get("Obs", [])
                if isinstance(obs_list, dict):
                    obs_list = [obs_list]
                for obs in obs_list[-24:]:  # last 2 years
                    signals.append(self._make_signal(
                        source=f"IMF:{indicator}:{ref_area}",
                        title=f"IMF {indicator} — {ref_area} — {obs.get('@TIME_PERIOD', '')}",
                        content=json.dumps(obs),
                        url=f"https://data.imf.org/?sk={indicator}",
                        meta={"indicator": indicator, "country": ref_area, "value": obs.get("@OBS_VALUE", "")},
                    ))
        except Exception:
            logger.warning("IMF API request failed")
        logger.info("IMF: ingested %d signals", len(signals))
        return signals


class NasdaqDataLinkIngester(BaseIngester):
    """Nasdaq Data Link (formerly Quandl) — millions of datasets."""

    source_name = "nasdaq_data_link"
    BASE_URL = "https://data.nasdaq.com/api/v3/datasets"

    DEFAULT_DATASETS: ClassVar[list[str]] = [
        "FRED/GDP",
        "OPEC/ORB",            # OPEC basket oil price
        "MULTPL/SP500_PE_RATIO_MONTH",  # S&P 500 PE ratio
        "LBMA/GOLD",           # London gold fixing
        "CHRIS/CME_CL1",       # WTI crude oil futures
    ]

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("NASDAQ_DATA_LINK_KEY", "")

    def fetch(
        self,
        datasets: list[str] | None = None,
        limit: int = 100,
    ) -> list[Signal]:
        datasets = datasets or self.DEFAULT_DATASETS
        signals: list[Signal] = []
        for ds in datasets:
            try:
                url = f"{self.BASE_URL}/{ds}/data.json?limit={limit}"
                if self.api_key:
                    url += f"&api_key={self.api_key}"
                data = self._get_json(url)
                ds_data = data.get("dataset_data", {})
                cols = ds_data.get("column_names", [])
                for row in ds_data.get("data", []):
                    row_dict = dict(zip(cols, row)) if cols else {"raw": row}
                    date_str = row[0] if row else ""
                    ts = datetime.now()
                    if isinstance(date_str, str) and len(date_str) >= 10:
                        with contextlib.suppress(ValueError):
                            ts = datetime.fromisoformat(date_str[:10])
                    signals.append(self._make_signal(
                        source=f"NasdaqDL:{ds}",
                        title=f"{ds} — {date_str}",
                        content=json.dumps(row_dict),
                        url=f"https://data.nasdaq.com/{ds}",
                        timestamp=ts,
                        meta={"dataset": ds, **row_dict},
                    ))
            except Exception:
                logger.warning("NasdaqDataLink fetch failed for %s", ds)
        logger.info("NasdaqDataLink: ingested %d signals", len(signals))
        return signals


class CensusBureauIngester(BaseIngester):
    """U.S. Census Bureau — demographics, housing, business patterns."""

    source_name = "census"
    BASE_URL = "https://api.census.gov/data"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("CENSUS_API_KEY", "")

    def fetch(
        self,
        year: int = 2023,
        dataset: str = "acs/acs1",
        variables: list[str] | None = None,
        geo: str = "us:*",
    ) -> list[Signal]:
        variables = variables or ["B01001_001E", "B19013_001E", "B25077_001E"]
        signals: list[Signal] = []
        var_str = ",".join(variables)
        url = f"{self.BASE_URL}/{year}/{dataset}?get={var_str}&for={geo}"
        if self.api_key:
            url += f"&key={self.api_key}"
        try:
            data = self._get_json(url)
            if isinstance(data, list) and len(data) > 1:
                headers_row = data[0]
                for row in data[1:]:
                    row_dict = dict(zip(headers_row, row))
                    signals.append(self._make_signal(
                        source=f"Census:{dataset}",
                        title=f"Census {dataset} {year}",
                        content=json.dumps(row_dict),
                        url="https://data.census.gov/",
                        meta={"year": year, "dataset": dataset, **row_dict},
                    ))
        except Exception:
            logger.warning("Census fetch failed for %s/%d", dataset, year)
        logger.info("Census: ingested %d signals", len(signals))
        return signals
