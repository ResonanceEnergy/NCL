"""Demographics, population & migration ingesters.

APIs: UN Population Division, UNHCR Refugee Data, IOM Displacement Tracking.
"""

import json
import logging
from datetime import datetime
from typing import ClassVar

from ..ingestion import Signal
from .base import BaseIngester

logger = logging.getLogger(__name__)


class UNPopulationIngester(BaseIngester):
    """UN Population Division — estimates & projections to 2100. No key."""

    source_name = "un_population"
    BASE_URL = "https://population.un.org/dataportalapi/api/v1"

    DEFAULT_INDICATORS: ClassVar[list[int]] = [1, 19, 49, 65, 68]  # pop total, fertility, median age, life expectancy, dependency ratio

    def fetch(
        self,
        locations: list[int] | None = None,
        indicators: list[int] | None = None,
        start_year: int = 2020,
        end_year: int = 2100,
    ) -> list[Signal]:
        locations = locations or [840, 156, 356, 276, 826]  # US, China, India, Germany, UK
        indicators = indicators or self.DEFAULT_INDICATORS
        signals: list[Signal] = []

        for ind_id in indicators:
            try:
                url = (
                    f"{self.BASE_URL}/data/indicators/{ind_id}"
                    f"?locations={','.join(str(loc_id) for loc_id in locations)}"
                    f"&startYear={start_year}&endYear={end_year}"
                    f"&pageSize=100"
                )
                data = self._get_json(url)
                for rec in data.get("data", data) if isinstance(data, dict) else (data if isinstance(data, list) else []):
                    if not isinstance(rec, dict):
                        continue
                    yr = rec.get("timeLabel", rec.get("year"))
                    ts = datetime(int(yr), 1, 1) if yr and str(yr).isdigit() else datetime.now()
                    signals.append(self._make_signal(
                        source=f"UN_Pop:{ind_id}",
                        title=f"UN Pop — {rec.get('location', '')} — {yr} — {rec.get('value', '')}",
                        content=json.dumps(rec),
                        timestamp=ts,
                        meta={
                            "indicator_id": ind_id,
                            "location": rec.get("location"),
                            "year": yr,
                            "value": rec.get("value"),
                            "variant": rec.get("variant"),
                        },
                    ))
            except Exception:
                logger.warning("UN Population fetch failed for indicator %s", ind_id)
        logger.info("UN Population: ingested %d signals", len(signals))
        return signals


class UNHCRRefugeeIngester(BaseIngester):
    """UNHCR Refugee Data — displacement flows, asylum seekers. No key."""

    source_name = "unhcr"
    BASE_URL = "https://api.unhcr.org/population/v1"

    def fetch(
        self,
        year_from: int = 2015,
        year_to: int = 2025,
        limit: int = 100,
    ) -> list[Signal]:
        signals: list[Signal] = []
        try:
            url = (
                f"{self.BASE_URL}/population/"
                f"?yearFrom={year_from}&yearTo={year_to}"
                f"&limit={limit}&download=false"
            )
            data = self._get_json(url)
            items = data.get("items", data.get("data", []))
            for rec in (items if isinstance(items, list) else []):
                yr = rec.get("year")
                ts = datetime(int(yr), 1, 1) if yr and str(yr).isdigit() else datetime.now()
                signals.append(self._make_signal(
                    source="UNHCR",
                    title=(
                        f"Refugees — {rec.get('country_of_origin_en', '')} → "
                        f"{rec.get('country_of_asylum_en', '')} — {yr}"
                    ),
                    content=json.dumps(rec),
                    timestamp=ts,
                    meta={
                        "origin": rec.get("country_of_origin_en"),
                        "asylum": rec.get("country_of_asylum_en"),
                        "refugees": rec.get("refugees"),
                        "asylum_seekers": rec.get("asylum_seekers"),
                        "idps": rec.get("idps"),
                        "year": yr,
                    },
                ))
        except Exception:
            logger.warning("UNHCR fetch failed")
        logger.info("UNHCR: ingested %d signals", len(signals))
        return signals


class IOMDisplacementIngester(BaseIngester):
    """IOM Displacement Tracking Matrix — internal displacement events."""

    source_name = "iom_dtm"
    BASE_URL = "https://dtm.iom.int/api/v2"

    def fetch(self, limit: int = 50) -> list[Signal]:
        signals: list[Signal] = []
        try:
            url = f"{self.BASE_URL}/idmc/idps?limit={limit}"
            data = self._get_json(url)
            entries = data.get("results", data.get("data", data))
            for rec in (entries if isinstance(entries, list) else [])[:limit]:
                yr = rec.get("year")
                ts = datetime(int(yr), 1, 1) if yr and str(yr).isdigit() else datetime.now()
                signals.append(self._make_signal(
                    source="IOM_DTM",
                    title=f"Displacement — {rec.get('country', '')} — {yr}",
                    content=json.dumps(rec),
                    timestamp=ts,
                    meta={
                        "country": rec.get("country"),
                        "idps": rec.get("displacement_total", rec.get("idps")),
                        "year": yr,
                        "cause": rec.get("cause", rec.get("displacement_type")),
                    },
                ))
        except Exception:
            logger.warning("IOM DTM fetch failed")
        logger.info("IOM DTM: ingested %d signals", len(signals))
        return signals
