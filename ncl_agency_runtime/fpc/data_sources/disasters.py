"""Natural disaster & seismic data ingesters.

APIs: USGS Earthquake Hazards, Smithsonian Volcanism,
      FEMA Disaster Declarations, EM-DAT.
"""

import contextlib
import json
import logging
from datetime import datetime

from ..ingestion import Signal
from .base import BaseIngester

logger = logging.getLogger(__name__)


class USGSEarthquakeIngester(BaseIngester):
    """USGS Earthquake Hazards — real-time seismic events. No key."""

    source_name = "usgs_earthquake"
    BASE_URL = "https://earthquake.usgs.gov/fdsnws/event/1"

    def fetch(
        self,
        min_magnitude: float = 4.5,
        limit: int = 50,
        order: str = "time",
    ) -> list[Signal]:
        signals: list[Signal] = []
        try:
            url = (
                f"{self.BASE_URL}/query?format=geojson"
                f"&minmagnitude={min_magnitude}"
                f"&limit={limit}&orderby={order}"
            )
            data = self._get_json(url)
            for feat in data.get("features", []):
                props = feat.get("properties", {})
                coords = feat.get("geometry", {}).get("coordinates", [0, 0, 0])
                ts_ms = props.get("time", 0)
                ts = datetime.fromtimestamp(ts_ms / 1000) if ts_ms else datetime.now()
                signals.append(self._make_signal(
                    source="USGS:earthquake",
                    title=f"M{props.get('mag', '?')} — {props.get('place', 'unknown')}",
                    content=json.dumps(props),
                    url=props.get("url", ""),
                    timestamp=ts,
                    meta={
                        "magnitude": props.get("mag"),
                        "place": props.get("place"),
                        "depth_km": coords[2] if len(coords) > 2 else None,
                        "tsunami": props.get("tsunami"),
                        "lon": coords[0] if coords else None,
                        "lat": coords[1] if len(coords) > 1 else None,
                        "alert": props.get("alert"),
                    },
                ))
        except Exception:
            logger.warning("USGS Earthquake fetch failed")
        logger.info("USGS Earthquakes: ingested %d signals", len(signals))
        return signals


class SmithsonianVolcanoIngester(BaseIngester):
    """Smithsonian Global Volcanism Program — eruption data."""

    source_name = "smithsonian_volcano"
    # GVP provides data as downloadable files; we use their API-like endpoint
    BASE_URL = "https://volcano.si.edu"

    def fetch(self) -> list[Signal]:
        signals: list[Signal] = []
        try:
            # Use the USGS/Smithsonian feed of current volcanic activity
            url = "https://volcanoes.usgs.gov/hans2/api/volcanoAlerts"
            data = self._get_json(url)
            entries = data if isinstance(data, list) else data.get("features", data.get("alerts", []))
            for entry in (entries if isinstance(entries, list) else [])[:30]:
                props = entry.get("properties", entry) if isinstance(entry, dict) else {}
                signals.append(self._make_signal(
                    source="Volcano:USGS",
                    title=f"Volcano Alert: {props.get('volcanoName', props.get('name', 'unknown'))}",
                    content=json.dumps(props),
                    url=props.get("url", ""),
                    meta={
                        "volcano": props.get("volcanoName", props.get("name")),
                        "alert_level": props.get("alertLevel"),
                        "color_code": props.get("colorCode"),
                    },
                ))
        except Exception:
            logger.warning("Volcano alert fetch failed")
        logger.info("Volcano: ingested %d signals", len(signals))
        return signals


class FEMADisasterIngester(BaseIngester):
    """FEMA Disaster Declarations API — U.S. federal disasters since 1953. No key."""

    source_name = "fema"
    BASE_URL = "https://www.fema.gov/api/open/v2"

    def fetch(
        self,
        limit: int = 50,
        order: str = "declarationDate desc",
    ) -> list[Signal]:
        signals: list[Signal] = []
        try:
            import urllib.parse
            url = (
                f"{self.BASE_URL}/DisasterDeclarations"
                f"?$top={limit}&$orderby={urllib.parse.quote(order)}"
            )
            data = self._get_json(url)
            for dec in data.get("DisasterDeclarations", []):
                ts = datetime.now()
                if dec.get("declarationDate"):
                    with contextlib.suppress(ValueError):
                        ts = datetime.fromisoformat(dec["declarationDate"][:19])
                signals.append(self._make_signal(
                    source="FEMA:disaster",
                    title=f"{dec.get('declarationTitle', '')} — {dec.get('state', '')}",
                    content=json.dumps(dec),
                    url="https://www.fema.gov/disaster/" + str(dec.get("disasterNumber", "")),
                    timestamp=ts,
                    meta={
                        "disaster_number": dec.get("disasterNumber"),
                        "type": dec.get("incidentType"),
                        "state": dec.get("state"),
                        "title": dec.get("declarationTitle"),
                        "fy_declared": dec.get("fyDeclared"),
                    },
                ))
        except Exception:
            logger.warning("FEMA Disaster fetch failed")
        logger.info("FEMA: ingested %d signals", len(signals))
        return signals


class EMDATIngester(BaseIngester):
    """EM-DAT International Disaster Database — 22,000+ disasters since 1900."""

    source_name = "emdat"
    BASE_URL = "https://public.emdat.be/api"

    def fetch(self, limit: int = 50) -> list[Signal]:
        signals: list[Signal] = []
        try:
            url = f"{self.BASE_URL}/data?limit={limit}"
            data = self._get_json(url)
            entries = data if isinstance(data, list) else data.get("data", [])
            for rec in (entries if isinstance(entries, list) else [])[:limit]:
                yr = rec.get("year", rec.get("Year"))
                ts = datetime(int(yr), 1, 1) if yr and str(yr).isdigit() else datetime.now()
                signals.append(self._make_signal(
                    source="EMDAT",
                    title=f"{rec.get('disasterType', rec.get('Disaster Type', ''))} — "
                          f"{rec.get('country', rec.get('Country', ''))} — {yr}",
                    content=json.dumps(rec),
                    timestamp=ts,
                    meta={
                        "type": rec.get("disasterType", rec.get("Disaster Type")),
                        "country": rec.get("country", rec.get("Country")),
                        "deaths": rec.get("totalDeaths", rec.get("Total Deaths")),
                        "affected": rec.get("totalAffected", rec.get("Total Affected")),
                        "damage_usd": rec.get("totalDamage", rec.get("Total Damage")),
                    },
                ))
        except Exception:
            logger.warning("EM-DAT fetch failed")
        logger.info("EMDAT: ingested %d signals", len(signals))
        return signals
