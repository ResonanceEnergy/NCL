"""Food, agriculture & water data ingesters.

APIs: USDA NASS, FAO FAOSTAT, USGS Water Services, WFP HungerMap.
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


class USDANASSIngester(BaseIngester):
    """USDA NASS Quick Stats — U.S. crop production, yields, prices."""

    source_name = "usda_nass"
    BASE_URL = "https://quickstats.nass.usda.gov/api/api_GET/"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("USDA_NASS_KEY", "")

    def fetch(
        self,
        commodity: str = "CORN",
        year: int = 2025,
        stat_category: str = "PRODUCTION",
    ) -> list[Signal]:
        if not self.api_key:
            logger.warning("USDA_NASS_KEY not set — skipping")
            return []

        signals: list[Signal] = []
        try:
            url = (
                f"{self.BASE_URL}"
                f"?key={self.api_key}"
                f"&commodity_desc={commodity}"
                f"&year={year}"
                f"&statisticcat_desc={stat_category}"
                f"&format=json"
            )
            data = self._get_json(url)
            for rec in data.get("data", [])[:50]:
                signals.append(self._make_signal(
                    source=f"USDA:{commodity}",
                    title=f"{commodity} {stat_category} — {rec.get('state_name', 'US')} — {rec.get('year', '')}",
                    content=json.dumps(rec),
                    meta={
                        "commodity": commodity,
                        "state": rec.get("state_name"),
                        "value": rec.get("Value"),
                        "unit": rec.get("unit_desc"),
                    },
                ))
        except Exception:
            logger.warning("USDA NASS fetch failed for %s", commodity)
        logger.info("USDA NASS: ingested %d signals", len(signals))
        return signals


class FAOIngester(BaseIngester):
    """FAO FAOSTAT — global food production, prices, land use. No key."""

    source_name = "fao"
    BASE_URL = "https://fenixservices.fao.org/faostat/api/v1"

    def fetch(
        self,
        domain: str = "QCL",  # Crops and livestock products
        area: int = 231,      # USA (FAO area code)
        element: int = 5510,  # Production (tonnes)
        item: int = 56,       # Maize
        year_start: int = 2015,
        year_end: int = 2025,
    ) -> list[Signal]:
        signals: list[Signal] = []
        try:
            url = (
                f"{self.BASE_URL}/en/data/{domain}"
                f"?area={area}&element={element}&item={item}"
                f"&year={year_start}:{year_end}&output_type=objects"
            )
            data = self._get_json(url, timeout=30)
            records = data.get("data", data) if isinstance(data, dict) else data
            for rec in (records if isinstance(records, list) else [])[:50]:
                yr = rec.get("Year", rec.get("year"))
                ts = datetime(int(yr), 1, 1) if yr and str(yr).isdigit() else datetime.now()
                signals.append(self._make_signal(
                    source=f"FAO:{domain}",
                    title=f"FAO {rec.get('Item', '')} — {rec.get('Area', '')} — {yr}",
                    content=json.dumps(rec),
                    timestamp=ts,
                    meta={
                        "domain": domain,
                        "area": rec.get("Area"),
                        "item": rec.get("Item"),
                        "value": rec.get("Value"),
                        "unit": rec.get("Unit"),
                    },
                ))
        except Exception:
            logger.warning("FAO FAOSTAT fetch failed")
        logger.info("FAO: ingested %d signals", len(signals))
        return signals


class USGSWaterIngester(BaseIngester):
    """USGS Water Services — streamflow, groundwater. No key."""

    source_name = "usgs_water"
    BASE_URL = "https://waterservices.usgs.gov/nwis"

    DEFAULT_SITES: ClassVar[list[str]] = [
        "01646500",  # Potomac River (Washington D.C.)
        "09380000",  # Colorado River (Lees Ferry, AZ)
        "07010000",  # Mississippi River (St. Louis, MO)
    ]

    def fetch(
        self,
        sites: list[str] | None = None,
        period: str = "P30D",  # Last 30 days
        param_codes: list[str] | None = None,
    ) -> list[Signal]:
        sites = sites or self.DEFAULT_SITES
        param_codes = param_codes or ["00060", "00065"]  # Discharge, Gage height
        signals: list[Signal] = []

        site_str = ",".join(sites)
        param_str = ",".join(param_codes)
        try:
            url = (
                f"{self.BASE_URL}/iv/"
                f"?format=json&sites={site_str}"
                f"&parameterCd={param_str}&period={period}"
            )
            data = self._get_json(url, timeout=30)
            ts_data = data.get("value", {}).get("timeSeries", [])
            for ts_entry in ts_data:
                site_info = ts_entry.get("sourceInfo", {})
                site_name = site_info.get("siteName", "")
                variable = ts_entry.get("variable", {})
                var_name = variable.get("variableName", "")
                values_list = ts_entry.get("values", [{}])
                for val_set in values_list:
                    for val in (val_set.get("value", []) or [])[-10:]:
                        ts = datetime.now()
                        if val.get("dateTime"):
                            with contextlib.suppress(ValueError):
                                ts = datetime.fromisoformat(val["dateTime"][:19])
                        signals.append(self._make_signal(
                            source=f"USGS_Water:{site_name[:30]}",
                            title=f"{site_name} — {var_name} — {val.get('value', '')}",
                            content=json.dumps({"site": site_name, "variable": var_name, "value": val.get("value"), "datetime": val.get("dateTime")}),
                            timestamp=ts,
                            meta={
                                "site": site_name,
                                "variable": var_name,
                                "value": val.get("value"),
                            },
                        ))
        except Exception:
            logger.warning("USGS Water fetch failed")
        logger.info("USGS Water: ingested %d signals", len(signals))
        return signals


class WFPHungerMapIngester(BaseIngester):
    """WFP HungerMap — near real-time food insecurity estimates."""

    source_name = "wfp_hunger"
    BASE_URL = "https://api.hungermapdata.org/v2"

    def fetch(self) -> list[Signal]:
        signals: list[Signal] = []
        try:
            url = f"{self.BASE_URL}/adm0/world"
            data = self._get_json(url)
            body = data.get("body", data)
            countries = body.get("countries", body) if isinstance(body, dict) else body
            for c in (countries if isinstance(countries, list) else [])[:50]:
                metrics = c.get("metrics", c) if isinstance(c, dict) else {}
                fcs = metrics.get("fcs", {}) if isinstance(metrics, dict) else {}
                signals.append(self._make_signal(
                    source=f"WFP:{c.get('country', {}).get('name', c.get('name', ''))}",
                    title=f"Hunger — {c.get('country', {}).get('name', c.get('name', ''))} — "
                          f"FCS insufficient: {fcs.get('people', '?')}",
                    content=json.dumps(c),
                    meta={
                        "country": c.get("country", {}).get("name", c.get("name")),
                        "fcs_people": fcs.get("people"),
                        "fcs_prevalence": fcs.get("prevalence"),
                    },
                ))
        except Exception:
            logger.warning("WFP HungerMap fetch failed")
        logger.info("WFP: ingested %d signals", len(signals))
        return signals
