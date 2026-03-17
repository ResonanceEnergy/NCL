"""Weather, climate, and environment ingesters.

APIs: OpenWeatherMap, Open-Meteo, NOAA CDO, NASA POWER,
      NOAA CO2/GHG, NASA Sea Level, Global Forest Watch, OpenAQ.
"""

import contextlib
import json
import logging
import os
from datetime import datetime
from typing import Any

from ..ingestion import Signal
from .base import BaseIngester

logger = logging.getLogger(__name__)


class OpenWeatherMapIngester(BaseIngester):
    """OpenWeatherMap — current weather, forecasts, air pollution."""

    source_name = "openweathermap"
    BASE_URL = "https://api.openweathermap.org"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("OPENWEATHER_API_KEY", "")

    def fetch(
        self,
        cities: list[dict[str, float]] | None = None,
    ) -> list[Signal]:
        if not self.api_key:
            logger.warning("OPENWEATHER_API_KEY not set — skipping")
            return []

        # Major economic hubs
        cities = cities or [
            {"name": "New York", "lat": 40.71, "lon": -74.01},
            {"name": "London", "lat": 51.51, "lon": -0.13},
            {"name": "Tokyo", "lat": 35.68, "lon": 139.69},
            {"name": "Shanghai", "lat": 31.23, "lon": 121.47},
            {"name": "Dubai", "lat": 25.20, "lon": 55.27},
        ]
        signals: list[Signal] = []

        for city in cities:
            # Current weather
            try:
                url = (
                    f"{self.BASE_URL}/data/2.5/weather"
                    f"?lat={city['lat']}&lon={city['lon']}&appid={self.api_key}&units=metric"
                )
                data = self._get_json(url)
                signals.append(self._make_signal(
                    source=f"OpenWeather:{city['name']}",
                    title=f"{city['name']} — {data.get('main', {}).get('temp', '')}°C",
                    content=json.dumps(data),
                    meta={
                        "city": city["name"],
                        "temp": data.get("main", {}).get("temp"),
                        "humidity": data.get("main", {}).get("humidity"),
                        "pressure": data.get("main", {}).get("pressure"),
                        "wind_speed": data.get("wind", {}).get("speed"),
                        "weather": data.get("weather", [{}])[0].get("main", ""),
                    },
                ))
            except Exception:
                logger.warning("OpenWeather current failed for %s", city["name"])

            # Air pollution
            try:
                url = (
                    f"{self.BASE_URL}/data/2.5/air_pollution"
                    f"?lat={city['lat']}&lon={city['lon']}&appid={self.api_key}"
                )
                data = self._get_json(url)
                for entry in data.get("list", [])[:1]:
                    comps = entry.get("components", {})
                    signals.append(self._make_signal(
                        source=f"OpenWeather:AQ:{city['name']}",
                        title=f"Air Quality {city['name']} — AQI {entry.get('main', {}).get('aqi', '')}",
                        content=json.dumps(entry),
                        meta={
                            "city": city["name"],
                            "aqi": entry.get("main", {}).get("aqi"),
                            "pm25": comps.get("pm2_5"),
                            "pm10": comps.get("pm10"),
                            "no2": comps.get("no2"),
                            "o3": comps.get("o3"),
                        },
                    ))
            except Exception:
                logger.warning("OpenWeather air pollution failed for %s", city["name"])

        logger.info("OpenWeatherMap: ingested %d signals", len(signals))
        return signals


class OpenMeteoIngester(BaseIngester):
    """Open-Meteo — weather + 80yr climate history. No key required."""

    source_name = "open_meteo"
    BASE_URL = "https://api.open-meteo.com/v1"

    def fetch(
        self,
        locations: list[dict[str, Any]] | None = None,
        past_days: int = 30,
    ) -> list[Signal]:
        locations = locations or [
            {"name": "New York", "lat": 40.71, "lon": -74.01},
            {"name": "London", "lat": 51.51, "lon": -0.13},
            {"name": "Beijing", "lat": 39.90, "lon": 116.40},
        ]
        signals: list[Signal] = []
        for loc in locations:
            try:
                url = (
                    f"{self.BASE_URL}/forecast"
                    f"?latitude={loc['lat']}&longitude={loc['lon']}"
                    f"&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,"
                    f"windspeed_10m_max,weathercode"
                    f"&past_days={past_days}&forecast_days=14&timezone=auto"
                )
                data = self._get_json(url)
                daily = data.get("daily", {})
                dates = daily.get("time", [])
                temps_max = daily.get("temperature_2m_max", [])
                temps_min = daily.get("temperature_2m_min", [])
                precip = daily.get("precipitation_sum", [])
                wind = daily.get("windspeed_10m_max", [])
                for i, d in enumerate(dates):
                    signals.append(self._make_signal(
                        source=f"OpenMeteo:{loc['name']}",
                        title=f"{loc['name']} — {d} — {temps_max[i] if i < len(temps_max) else '?'}°C",
                        content=json.dumps({
                            "date": d,
                            "temp_max": temps_max[i] if i < len(temps_max) else None,
                            "temp_min": temps_min[i] if i < len(temps_min) else None,
                            "precip_mm": precip[i] if i < len(precip) else None,
                            "wind_max": wind[i] if i < len(wind) else None,
                        }),
                        timestamp=datetime.fromisoformat(d) if d else datetime.now(),
                        meta={
                            "location": loc["name"],
                            "temp_max": temps_max[i] if i < len(temps_max) else None,
                            "precip": precip[i] if i < len(precip) else None,
                        },
                    ))
            except Exception:
                logger.warning("OpenMeteo fetch failed for %s", loc["name"])
        logger.info("OpenMeteo: ingested %d signals", len(signals))
        return signals


class NOAAClimateIngester(BaseIngester):
    """NOAA Climate Data Online — 100+ year U.S. weather records."""

    source_name = "noaa_climate"
    BASE_URL = "https://www.ncdc.noaa.gov/cdo-web/api/v2"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("NOAA_CDO_TOKEN", "")

    def fetch(
        self,
        dataset: str = "GHCND",
        location: str = "CITY:US360019",  # NYC
        start: str = "2025-01-01",
        end: str = "2026-01-01",
        limit: int = 100,
    ) -> list[Signal]:
        if not self.api_key:
            logger.warning("NOAA_CDO_TOKEN not set — skipping")
            return []
        signals: list[Signal] = []
        try:
            url = (
                f"{self.BASE_URL}/data"
                f"?datasetid={dataset}&locationid={location}"
                f"&startdate={start}&enddate={end}&limit={limit}"
            )
            data = self._get_json(url, headers={"token": self.api_key})
            for rec in data.get("results", []):
                ts = datetime.now()
                if rec.get("date"):
                    with contextlib.suppress(ValueError):
                        ts = datetime.fromisoformat(rec["date"][:19])
                signals.append(self._make_signal(
                    source=f"NOAA:{dataset}",
                    title=f"{rec.get('datatype', '')} — {rec.get('date', '')}",
                    content=json.dumps(rec),
                    timestamp=ts,
                    meta={"datatype": rec.get("datatype"), "value": rec.get("value"), "station": rec.get("station")},
                ))
        except Exception:
            logger.warning("NOAA CDO fetch failed")
        logger.info("NOAA Climate: ingested %d signals", len(signals))
        return signals


class NASAPowerIngester(BaseIngester):
    """NASA POWER — solar irradiance, temperature, wind from satellites. No key."""

    source_name = "nasa_power"
    BASE_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"

    def fetch(
        self,
        lat: float = 40.71,
        lon: float = -74.01,
        parameters: list[str] | None = None,
        start: str = "20250101",
        end: str = "20260101",
    ) -> list[Signal]:
        parameters = parameters or ["T2M", "T2M_MAX", "T2M_MIN", "ALLSKY_SFC_SW_DWN", "PRECTOTCORR", "WS10M"]
        signals: list[Signal] = []
        param_str = ",".join(parameters)
        try:
            url = (
                f"{self.BASE_URL}"
                f"?parameters={param_str}&community=RE"
                f"&longitude={lon}&latitude={lat}"
                f"&start={start}&end={end}&format=JSON"
            )
            data = self._get_json(url, timeout=30)
            props = data.get("properties", {}).get("parameter", {})
            # Get all dates from first parameter
            first_param = next(iter(props.values())) if props else {}
            for date_str in list(first_param.keys())[-60:]:  # last 60 days
                row = {p: props.get(p, {}).get(date_str) for p in parameters}
                yr = int(date_str[:4])
                mo = int(date_str[4:6])
                dy = int(date_str[6:8])
                signals.append(self._make_signal(
                    source="NASA_POWER",
                    title=f"NASA POWER — {date_str} — T={row.get('T2M', '')}°C",
                    content=json.dumps(row),
                    timestamp=datetime(yr, mo, dy),
                    meta={"lat": lat, "lon": lon, **row},
                ))
        except Exception:
            logger.warning("NASA POWER fetch failed")
        logger.info("NASA POWER: ingested %d signals", len(signals))
        return signals


class NOAACO2Ingester(BaseIngester):
    """NOAA Global Monitoring Lab — CO2 Keeling Curve. No key."""

    source_name = "noaa_co2"
    DATA_URL = "https://gml.noaa.gov/webdata/ccgg/trends/co2/co2_daily_mlo.csv"

    def fetch(self, last_n: int = 90) -> list[Signal]:
        signals: list[Signal] = []
        try:
            text = self._get_text(self.DATA_URL)
            lines = [ln for ln in text.strip().split("\n") if ln and not ln.startswith("#")]
            for line in lines[-last_n:]:
                parts = line.split(",")
                if len(parts) >= 2:
                    date_str = parts[0].strip()
                    co2_val = parts[1].strip()
                    ts = datetime.now()
                    with contextlib.suppress(ValueError):
                        ts = datetime.fromisoformat(date_str)
                    signals.append(self._make_signal(
                        source="NOAA_CO2",
                        title=f"CO2 — {date_str} — {co2_val} ppm",
                        content=json.dumps({"date": date_str, "co2_ppm": co2_val}),
                        timestamp=ts,
                        meta={"co2_ppm": co2_val},
                    ))
        except Exception:
            logger.warning("NOAA CO2 fetch failed")
        logger.info("NOAA CO2: ingested %d signals", len(signals))
        return signals


class GlobalForestWatchIngester(BaseIngester):
    """Global Forest Watch — deforestation alerts, tree cover loss."""

    source_name = "global_forest_watch"
    BASE_URL = "https://data-api.globalforestwatch.org"

    def fetch(self, iso: str = "BRA") -> list[Signal]:
        signals: list[Signal] = []
        try:
            url = f"{self.BASE_URL}/dataset/umd_tree_cover_loss/v1.11/query/iso?iso={iso}"
            data = self._get_json(url, timeout=30)
            for rec in data.get("data", [])[:50]:
                signals.append(self._make_signal(
                    source=f"GFW:{iso}",
                    title=f"Tree Cover Loss {iso} — {rec.get('umd_tree_cover_loss__year', '')}",
                    content=json.dumps(rec),
                    meta={"iso": iso, "year": rec.get("umd_tree_cover_loss__year"), "area_ha": rec.get("area__ha")},
                ))
        except Exception:
            logger.warning("Global Forest Watch fetch failed")
        logger.info("GFW: ingested %d signals", len(signals))
        return signals


class OpenAQIngester(BaseIngester):
    """OpenAQ — real-time air quality from 30,000+ stations worldwide."""

    source_name = "openaq"
    BASE_URL = "https://api.openaq.org/v3"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("OPENAQ_API_KEY", "")

    def fetch(
        self,
        countries: list[str] | None = None,
        parameter: str = "pm25",
        limit: int = 50,
    ) -> list[Signal]:
        countries = countries or ["US", "CN", "IN", "DE", "GB"]
        signals: list[Signal] = []
        headers: dict[str, str] = {}
        if self.api_key:
            headers["X-API-Key"] = self.api_key

        for country in countries:
            try:
                url = (
                    f"{self.BASE_URL}/locations"
                    f"?countries_id={country}&parameters_id=2&limit={limit}"
                )
                data = self._get_json(url, headers=headers)
                for loc in data.get("results", []):
                    sensors = loc.get("sensors", [])
                    latest = sensors[0].get("summary", {}).get("last", {}) if sensors else {}
                    signals.append(self._make_signal(
                        source=f"OpenAQ:{country}",
                        title=f"AQ {loc.get('name', '')} — PM2.5: {latest.get('value', '?')}",
                        content=json.dumps(loc),
                        meta={
                            "location": loc.get("name"),
                            "country": country,
                            "pm25": latest.get("value"),
                            "lat": loc.get("coordinates", {}).get("latitude"),
                            "lon": loc.get("coordinates", {}).get("longitude"),
                        },
                    ))
            except Exception:
                logger.warning("OpenAQ fetch failed for %s", country)
        logger.info("OpenAQ: ingested %d signals", len(signals))
        return signals
