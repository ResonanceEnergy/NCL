"""Governance, geopolitical risk, space weather & transport ingesters.

APIs: GDELT, ACLED (stub), V-Dem (stub), Fragile States (stub),
      Transparency Intl CPI (stub), NASA DONKI, NOAA Space Weather, OpenSky.
"""

import contextlib
import json
import logging
import os
from datetime import datetime, timedelta
from typing import ClassVar

from ..ingestion import Signal
from .base import BaseIngester

logger = logging.getLogger(__name__)


# ─── Geopolitical ────────────────────────────────────────────────────────────

class GDELTIngester(BaseIngester):
    """GDELT Project — global events, media tone, conflict monitoring. No key."""

    source_name = "gdelt"
    BASE_URL = "https://api.gdeltproject.org/api/v2"

    def fetch(
        self,
        queries: list[str] | None = None,
        mode: str = "ArtList",
        max_records: int = 25,
        timespan: str = "7d",
    ) -> list[Signal]:
        queries = queries or [
            "climate disaster",
            "military conflict",
            "pandemic outbreak",
            "economic crisis",
            "energy supply disruption",
        ]
        signals: list[Signal] = []
        for q in queries:
            try:
                import urllib.parse
                url = (
                    f"{self.BASE_URL}/doc/doc"
                    f"?query={urllib.parse.quote(q)}"
                    f"&mode={mode}&maxrecords={max_records}"
                    f"&timespan={timespan}&format=json"
                )
                data = self._get_json(url)
                articles = data.get("articles", [])
                for art in articles:
                    ts = datetime.now()
                    if art.get("seendate"):
                        try:
                            d = art["seendate"]
                            ts = datetime(int(d[:4]), int(d[4:6]), int(d[6:8]),
                                          int(d[8:10]) if len(d) > 8 else 0,
                                          int(d[10:12]) if len(d) > 10 else 0)
                        except (ValueError, IndexError):
                            pass
                    signals.append(self._make_signal(
                        source=f"GDELT:{q[:15]}",
                        title=art.get("title", ""),
                        content=art.get("title", ""),
                        url=art.get("url", ""),
                        timestamp=ts,
                        meta={
                            "query": q,
                            "domain": art.get("domain"),
                            "language": art.get("language"),
                            "tone": art.get("tone"),
                            "source_country": art.get("sourcecountry"),
                        },
                    ))
            except Exception:
                logger.warning("GDELT fetch failed for '%s'", q)
        logger.info("GDELT: ingested %d signals", len(signals))
        return signals


class ACLEDIngester(BaseIngester):
    """ACLED — political violence & protests events."""

    source_name = "acled"
    BASE_URL = "https://api.acleddata.com/acled/read"

    def __init__(self, api_key: str | None = None, email: str | None = None):
        self.api_key = api_key or os.environ.get("ACLED_API_KEY", "")
        self.email = email or os.environ.get("ACLED_EMAIL", "")

    def fetch(self, limit: int = 50) -> list[Signal]:
        if not self.api_key or not self.email:
            logger.warning("ACLED_API_KEY/EMAIL not set — skipping")
            return []

        signals: list[Signal] = []
        try:
            url = (
                f"{self.BASE_URL}"
                f"?key={self.api_key}&email={self.email}"
                f"&limit={limit}&page=1"
            )
            data = self._get_json(url)
            for rec in data.get("data", []):
                ts = datetime.now()
                if rec.get("event_date"):
                    with contextlib.suppress(ValueError):
                        ts = datetime.fromisoformat(rec["event_date"])
                signals.append(self._make_signal(
                    source="ACLED",
                    title=f"{rec.get('event_type', '')} — {rec.get('country', '')} — {rec.get('event_date', '')}",
                    content=json.dumps(rec),
                    timestamp=ts,
                    meta={
                        "event_type": rec.get("event_type"),
                        "country": rec.get("country"),
                        "fatalities": rec.get("fatalities"),
                        "actor1": rec.get("actor1"),
                        "lat": rec.get("latitude"),
                        "lon": rec.get("longitude"),
                    },
                ))
        except Exception:
            logger.warning("ACLED fetch failed")
        logger.info("ACLED: ingested %d signals", len(signals))
        return signals


class UNComtradeIngester(BaseIngester):
    """UN Comtrade — international trade statistics."""

    source_name = "un_comtrade"
    BASE_URL = "https://comtradeapi.un.org/data/v1/get/C/A"

    def fetch(
        self,
        reporter: str = "842",   # USA
        partner: str = "156",    # China
        period: str = "2024",
        flow: str = "M",         # imports
    ) -> list[Signal]:
        signals: list[Signal] = []
        try:
            url = (
                f"{self.BASE_URL}"
                f"?reporterCode={reporter}&partnerCode={partner}"
                f"&period={period}&flowCode={flow}&cmdCode=TOTAL"
            )
            data = self._get_json(url)
            for rec in data.get("data", [])[:50]:
                signals.append(self._make_signal(
                    source="UNComtrade",
                    title=f"Trade {rec.get('reporterDesc', '')} ← {rec.get('partnerDesc', '')} — ${rec.get('primaryValue', 0):,.0f}",
                    content=json.dumps(rec),
                    meta={
                        "reporter": rec.get("reporterDesc"),
                        "partner": rec.get("partnerDesc"),
                        "value": rec.get("primaryValue"),
                        "flow": rec.get("flowDesc"),
                    },
                ))
        except Exception:
            logger.warning("UN Comtrade fetch failed")
        logger.info("UN Comtrade: ingested %d signals", len(signals))
        return signals


# ─── Space Weather ───────────────────────────────────────────────────────────

class NASADONKIIngester(BaseIngester):
    """NASA DONKI — coronal mass ejections, solar flares, geomagnetic storms."""

    source_name = "nasa_donki"
    BASE_URL = "https://api.nasa.gov/DONKI"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("NASA_API_KEY", "DEMO_KEY")

    def fetch(self, days_back: int = 30) -> list[Signal]:
        signals: list[Signal] = []
        start = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
        end = datetime.now().strftime("%Y-%m-%d")

        endpoints = {
            "CME": "CME",
            "FLR": "FLR",
            "GST": "GST",
            "SEP": "SEP",
        }

        for name, ep in endpoints.items():
            try:
                url = (
                    f"{self.BASE_URL}/{ep}"
                    f"?startDate={start}&endDate={end}&api_key={self.api_key}"
                )
                data = self._get_json(url)
                for event in (data if isinstance(data, list) else []):
                    ts = datetime.now()
                    time_key = "startTime" if "startTime" in event else "eventTime"
                    if event.get(time_key):
                        with contextlib.suppress(ValueError):
                            ts = datetime.fromisoformat(event[time_key][:19].replace("Z", ""))
                    signals.append(self._make_signal(
                        source=f"NASA_DONKI:{name}",
                        title=f"Space Weather {name} — {event.get(time_key, '')}",
                        content=json.dumps(event),
                        timestamp=ts,
                        meta={
                            "event_type": name,
                            "activity_id": event.get("activityID"),
                        },
                    ))
            except Exception:
                logger.warning("NASA DONKI fetch failed for %s", name)
        logger.info("NASA DONKI: ingested %d signals", len(signals))
        return signals


class NOAASpaceWeatherIngester(BaseIngester):
    """NOAA Space Weather Prediction Center — solar wind, Kp index. No key."""

    source_name = "noaa_space_weather"
    BASE_URL = "https://services.swpc.noaa.gov/json"

    def fetch(self) -> list[Signal]:
        signals: list[Signal] = []
        feeds = {
            "planetary_k_index": "/planetary_k_index_1m.json",
            "solar_wind_mag": "/rtsw/rtsw_mag_1m.json",
            "sunspot_number": "/solar-cycle/observed-solar-cycle-indices.json",
        }

        for name, path in feeds.items():
            try:
                url = f"{self.BASE_URL}{path}"
                data = self._get_json(url)
                entries = data if isinstance(data, list) else []
                for entry in entries[-30:]:
                    ts = datetime.now()
                    time_tag = entry.get("time_tag", entry.get("time-tag", ""))
                    if time_tag:
                        with contextlib.suppress(ValueError):
                            ts = datetime.fromisoformat(time_tag[:19])
                    signals.append(self._make_signal(
                        source=f"NOAA_SW:{name}",
                        title=f"Space Weather {name} — {time_tag}",
                        content=json.dumps(entry),
                        timestamp=ts,
                        meta={"feed": name, **{k: v for k, v in entry.items() if isinstance(v, (int, float, str))}},
                    ))
            except Exception:
                logger.warning("NOAA Space Weather fetch failed for %s", name)
        logger.info("NOAA Space Weather: ingested %d signals", len(signals))
        return signals


# ─── Transportation ──────────────────────────────────────────────────────────

class OpenSkyIngester(BaseIngester):
    """OpenSky Network — real-time flight tracking. Free, registration optional."""

    source_name = "opensky"
    BASE_URL = "https://opensky-network.org/api"

    def fetch(
        self,
        bounding_box: dict[str, float] | None = None,
    ) -> list[Signal]:
        signals: list[Signal] = []
        # Default: continental US bounding box
        bbox = bounding_box or {"lamin": 25, "lomin": -130, "lamax": 50, "lomax": -60}

        try:
            url = (
                f"{self.BASE_URL}/states/all"
                f"?lamin={bbox['lamin']}&lomin={bbox['lomin']}"
                f"&lamax={bbox['lamax']}&lomax={bbox['lomax']}"
            )
            data = self._get_json(url, timeout=30)
            states = data.get("states", [])
            # Summarize rather than creating per-aircraft signals
            signals.append(self._make_signal(
                source="OpenSky:summary",
                title=f"OpenSky — {len(states)} aircraft in flight",
                content=json.dumps({
                    "aircraft_count": len(states),
                    "timestamp": data.get("time"),
                    "bounding_box": bbox,
                }),
                meta={"aircraft_count": len(states), "region": "continental_US"},
            ))

            # Top origins by callsign prefix (country proxy)
            origin_counts: dict[str, int] = {}
            for s in states:
                if s and len(s) > 2 and s[2]:
                    country = str(s[2]).strip()
                    origin_counts[country] = origin_counts.get(country, 0) + 1
            for country, count in sorted(origin_counts.items(), key=lambda x: -x[1])[:10]:
                signals.append(self._make_signal(
                    source=f"OpenSky:origin:{country}",
                    title=f"OpenSky — {country}: {count} aircraft",
                    content=json.dumps({"origin_country": country, "count": count}),
                    meta={"origin_country": country, "count": count},
                ))
        except Exception:
            logger.warning("OpenSky fetch failed")
        logger.info("OpenSky: ingested %d signals", len(signals))
        return signals


# ─── Energy ──────────────────────────────────────────────────────────────────

class EIAIngester(BaseIngester):
    """EIA (Energy Information Administration) — oil, gas, electricity."""

    source_name = "eia"
    BASE_URL = "https://api.eia.gov/v2"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("EIA_API_KEY", "")

    DEFAULT_SERIES: ClassVar[list[tuple[str, dict[str, str]]]] = [
        ("petroleum/pri/spt/data", {"product": "EPCBRENT", "frequency": "weekly"}),
        ("natural-gas/pri/sum/data", {"frequency": "monthly"}),
        ("electricity/retail-sales/data", {"frequency": "monthly"}),
    ]

    def fetch(self) -> list[Signal]:
        if not self.api_key:
            logger.warning("EIA_API_KEY not set — skipping")
            return []

        signals: list[Signal] = []
        for path, params in self.DEFAULT_SERIES:
            try:
                qs = "&".join(f"data[{k}]={v}" if k != "frequency" else f"frequency={v}"
                              for k, v in params.items())
                url = f"{self.BASE_URL}/{path}?api_key={self.api_key}&{qs}&length=50"
                data = self._get_json(url)
                resp = data.get("response", {})
                for rec in resp.get("data", []):
                    ts = datetime.now()
                    if rec.get("period"):
                        with contextlib.suppress(ValueError):
                            ts = datetime.fromisoformat(rec["period"][:10])
                    signals.append(self._make_signal(
                        source=f"EIA:{path.split('/')[0]}",
                        title=f"EIA {rec.get('seriesDescription', path)} — {rec.get('period', '')}",
                        content=json.dumps(rec),
                        timestamp=ts,
                        meta={"series": path, "value": rec.get("value"), "period": rec.get("period")},
                    ))
            except Exception:
                logger.warning("EIA fetch failed for %s", path)
        logger.info("EIA: ingested %d signals", len(signals))
        return signals


class GitHubDevActivityIngester(BaseIngester):
    """GitHub API — developer activity for crypto/tech projects."""

    source_name = "github_dev"
    BASE_URL = "https://api.github.com"

    DEFAULT_REPOS: ClassVar[list[str]] = [
        "bitcoin/bitcoin",
        "ethereum/go-ethereum",
        "solana-labs/solana",
        "openai/openai-python",
        "tensorflow/tensorflow",
    ]

    def __init__(self, token: str | None = None):
        self.token = token or os.environ.get("GITHUB_TOKEN", "")

    def fetch(
        self,
        repos: list[str] | None = None,
    ) -> list[Signal]:
        repos = repos or self.DEFAULT_REPOS
        signals: list[Signal] = []
        headers: dict[str, str] = {}
        if self.token:
            headers["Authorization"] = f"token {self.token}"

        for repo in repos:
            try:
                # Repo info
                data = self._get_json(f"{self.BASE_URL}/repos/{repo}", headers=headers)
                signals.append(self._make_signal(
                    source=f"GitHub:{repo}",
                    title=f"GitHub {repo} — ★{data.get('stargazers_count', 0)} — forks {data.get('forks_count', 0)}",
                    content=json.dumps({
                        "stars": data.get("stargazers_count"),
                        "forks": data.get("forks_count"),
                        "open_issues": data.get("open_issues_count"),
                        "watchers": data.get("watchers_count"),
                        "language": data.get("language"),
                        "updated_at": data.get("updated_at"),
                        "pushed_at": data.get("pushed_at"),
                    }),
                    url=data.get("html_url", ""),
                    meta={
                        "repo": repo,
                        "stars": data.get("stargazers_count"),
                        "forks": data.get("forks_count"),
                        "language": data.get("language"),
                    },
                ))

                # Recent commit activity (last 4 weeks)
                commits = self._get_json(
                    f"{self.BASE_URL}/repos/{repo}/stats/commit_activity",
                    headers=headers,
                )
                if isinstance(commits, list):
                    for week in commits[-4:]:
                        ts = datetime.fromtimestamp(week.get("week", 0))
                        signals.append(self._make_signal(
                            source=f"GitHub:{repo}:commits",
                            title=f"GitHub {repo} — {week.get('total', 0)} commits (week of {ts.date()})",
                            content=json.dumps(week),
                            timestamp=ts,
                            meta={"repo": repo, "total_commits": week.get("total")},
                        ))
            except Exception:
                logger.warning("GitHub fetch failed for %s", repo)
        logger.info("GitHub: ingested %d signals", len(signals))
        return signals
