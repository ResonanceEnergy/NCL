"""Base ingester class — all data source ingesters inherit from this."""

import json
import logging
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any

from ..ingestion import Signal

logger = logging.getLogger(__name__)

# Shared timeout for all HTTP requests
_TIMEOUT = 20


class BaseIngester:
    """Common HTTP helpers for all ingesters."""

    source_name: str = "base"

    def _get_json(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: int = _TIMEOUT,
    ) -> Any:
        hdrs = {"User-Agent": "FPC/0.4", "Accept": "application/json"}
        if headers:
            hdrs.update(headers)
        req = urllib.request.Request(url, headers=hdrs)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())

    def _get_text(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: int = _TIMEOUT,
    ) -> str:
        hdrs = {"User-Agent": "FPC/0.4"}
        if headers:
            hdrs.update(headers)
        req = urllib.request.Request(url, headers=hdrs)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode()

    def _make_signal(
        self,
        source: str,
        title: str,
        content: str,
        url: str = "",
        timestamp: datetime | None = None,
        meta: dict | None = None,
    ) -> Signal:
        return Signal(
            source=source,
            title=title[:200],
            content=content[:4000],
            url=url,
            timestamp=timestamp or datetime.now(),
            meta=meta or {},
        )

    def fetch(self, **kwargs: Any) -> list[Signal]:
        raise NotImplementedError
