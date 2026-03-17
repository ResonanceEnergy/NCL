"""Health, disease & epidemiology ingesters.

APIs: WHO Global Health Observatory, CDC WONDER, Global.health, HealthMap.
"""

import json
import logging
from datetime import datetime
from typing import ClassVar

from ..ingestion import Signal
from .base import BaseIngester

logger = logging.getLogger(__name__)


class WHOGHOIngester(BaseIngester):
    """WHO Global Health Observatory — 2,000+ health indicators. No key."""

    source_name = "who_gho"
    BASE_URL = "https://ghoapi.azureedge.net/api"

    DEFAULT_INDICATORS: ClassVar[list[str]] = [
        "WHOSIS_000001",  # Life expectancy at birth
        "MDG_0000000001", # Under-five mortality rate
        "WHS4_543",       # Total NCD deaths
        "WHS6_102",       # Current health expenditure (% GDP)
        "WHS4_100",       # HIV incidence rate
        "NUTRITION_ANAEMIA_CHILDREN_PREV",  # Anaemia prevalence
    ]

    def fetch(
        self,
        indicators: list[str] | None = None,
        country: str = "USA",
        top_n: int = 50,
    ) -> list[Signal]:
        indicators = indicators or self.DEFAULT_INDICATORS
        signals: list[Signal] = []
        for ind in indicators:
            try:
                url = (
                    f"{self.BASE_URL}/{ind}"
                    f"?$filter=SpatialDim eq '{country}'"
                    f"&$orderby=TimeDim desc&$top={top_n}"
                )
                data = self._get_json(url)
                for rec in data.get("value", []):
                    yr = rec.get("TimeDim")
                    ts = datetime(int(yr), 1, 1) if yr and str(yr).isdigit() else datetime.now()
                    signals.append(self._make_signal(
                        source=f"WHO:{ind}",
                        title=f"WHO {ind} — {country} — {yr} — {rec.get('NumericValue', '')}",
                        content=json.dumps(rec),
                        timestamp=ts,
                        meta={
                            "indicator": ind,
                            "country": country,
                            "year": yr,
                            "value": rec.get("NumericValue"),
                        },
                    ))
            except Exception:
                logger.warning("WHO GHO fetch failed for %s", ind)
        logger.info("WHO GHO: ingested %d signals", len(signals))
        return signals


class GlobalHealthIngester(BaseIngester):
    """Global.health — real-time infectious disease outbreak tracking."""

    source_name = "global_health"
    BASE_URL = "https://data.global.health/api"

    def fetch(self, limit: int = 50) -> list[Signal]:
        signals: list[Signal] = []
        try:
            url = f"{self.BASE_URL}/cases?limit={limit}&sort=-dateConfirmed"
            data = self._get_json(url)
            entries = data if isinstance(data, list) else data.get("data", data.get("cases", []))
            if isinstance(entries, list):
                for case in entries[:limit]:
                    signals.append(self._make_signal(
                        source="GlobalHealth",
                        title=f"Outbreak — {case.get('pathogen', case.get('disease', 'unknown'))} — {case.get('country', '')}",
                        content=json.dumps(case),
                        meta={
                            "pathogen": case.get("pathogen", case.get("disease")),
                            "country": case.get("country"),
                            "date": case.get("dateConfirmed"),
                        },
                    ))
        except Exception:
            logger.warning("Global.health fetch failed")
        logger.info("GlobalHealth: ingested %d signals", len(signals))
        return signals


class CDCWonderIngester(BaseIngester):
    """CDC data — mortality, natality, disease surveillance.

    Uses CDC's public SODA-compatible endpoints rather than WONDER SOAP API.
    """

    source_name = "cdc"
    BASE_URL = "https://data.cdc.gov/resource"

    # Key public health datasets on CDC SODA API
    DATASETS: ClassVar[dict[str, str]] = {
        "covid_cases": "pwn4-m3yp",          # COVID-19 case surveillance
        "flu_surveillance": "ks3g-spdg",       # ILINet flu surveillance
        "vaccination_coverage": "fhky-rtsk",   # Vaccination coverage
        "chronic_disease": "g4ie-h725",        # Chronic disease indicators
    }

    def fetch(
        self,
        datasets: dict[str, str] | None = None,
        limit: int = 50,
    ) -> list[Signal]:
        datasets = datasets or self.DATASETS
        signals: list[Signal] = []
        for name, resource_id in datasets.items():
            try:
                url = f"{self.BASE_URL}/{resource_id}.json?$limit={limit}&$order=:id DESC"
                data = self._get_json(url)
                for rec in (data if isinstance(data, list) else []):
                    signals.append(self._make_signal(
                        source=f"CDC:{name}",
                        title=f"CDC {name} — {rec.get('state', rec.get('location', ''))}",
                        content=json.dumps(rec),
                        meta={"dataset": name, "resource_id": resource_id},
                    ))
            except Exception:
                logger.warning("CDC fetch failed for %s", name)
        logger.info("CDC: ingested %d signals", len(signals))
        return signals


class HealthMapIngester(BaseIngester):
    """HealthMap/OpenDisease — automated disease surveillance from media."""

    source_name = "healthmap"
    BASE_URL = "https://www.healthmap.org/HM/index.php"

    def fetch(self) -> list[Signal]:
        signals: list[Signal] = []
        try:
            # HealthMap provides a GeoJSON/JSON feed of recent alerts
            url = "https://www.healthmap.org/getAlerts.php?output=json"
            data = self._get_json(url)
            entries = data if isinstance(data, list) else data.get("alerts", [])
            for alert in (entries if isinstance(entries, list) else [])[:50]:
                signals.append(self._make_signal(
                    source="HealthMap",
                    title=f"Alert: {alert.get('disease', alert.get('summary', 'unknown'))}",
                    content=json.dumps(alert),
                    url=alert.get("link", ""),
                    meta={
                        "disease": alert.get("disease"),
                        "country": alert.get("country"),
                        "lat": alert.get("lat"),
                        "lon": alert.get("lng"),
                    },
                ))
        except Exception:
            logger.warning("HealthMap fetch failed")
        logger.info("HealthMap: ingested %d signals", len(signals))
        return signals
