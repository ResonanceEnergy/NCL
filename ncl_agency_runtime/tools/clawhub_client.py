"""ClawHub API client for NCL.

Queries the ClawHub skill registry (clawhub.ai) to discover, search,
and retrieve agent skills.  Uses the Convex-backed public API.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

LOG = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "https://clawhub.ai"
_DEFAULT_TIMEOUT = 15  # seconds


@dataclass
class ClawHubSkillInfo:
    """Metadata for a single ClawHub skill."""

    slug: str
    name: str = ""
    owner: str = ""
    description: str = ""
    stars: int = 0
    installs: int = 0
    versions: int = 1
    tags: list[str] = field(default_factory=list)
    url: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ClawHubSkillInfo:
        slug = data.get("slug", data.get("name", ""))
        owner = data.get("owner", data.get("author", ""))
        raw_versions = data.get("versions", data.get("versionCount", 1))
        if isinstance(raw_versions, list):
            version_count = len(raw_versions)
        else:
            version_count = int(raw_versions)
        return cls(
            slug=slug,
            name=data.get("name", slug),
            owner=owner,
            description=data.get("description", ""),
            stars=int(data.get("stars", data.get("starCount", 0))),
            installs=int(data.get("installs", data.get("installCount", 0))),
            versions=version_count,
            tags=data.get("tags", []),
            url=data.get("url", f"{_DEFAULT_BASE_URL}/skills/{slug}"),
        )


class ClawHubClient:
    """HTTP client for the ClawHub skill registry.

    Reads ``OPENCLAW_API_KEY`` from environment or from the NCL ``.env``
    file for authenticated operations (publish, sync).  Read-only
    operations (search, list, inspect) work without authentication.
    """

    def __init__(
        self,
        base_url: str = _DEFAULT_BASE_URL,
        api_key: str | None = None,
        timeout: int = _DEFAULT_TIMEOUT,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or self._load_api_key()
        self.timeout = timeout

    # ── API key resolution ────────────────────────────────────

    @staticmethod
    def _load_api_key() -> str | None:
        key = os.environ.get("OPENCLAW_API_KEY")
        if key:
            return key
        env_path = Path(__file__).resolve().parent.parent.parent / ".env"
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("OPENCLAW_API_KEY="):
                    return line.split("=", 1)[1].strip()
        return None

    # ── HTTP helpers ──────────────────────────────────────────

    def _headers(self, authenticated: bool = False) -> dict[str, str]:
        headers: dict[str, str] = {
            "User-Agent": "NCL/3.0 ClawHubClient",
            "Accept": "application/json",
        }
        if authenticated and self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _get(self, path: str, *, authenticated: bool = False) -> Any:
        url = f"{self.base_url}{path}"
        req = urllib.request.Request(url, headers=self._headers(authenticated))
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            LOG.error("ClawHub API error %s %s: %s", exc.code, url, exc.reason)
            return None
        except urllib.error.URLError as exc:
            LOG.error("ClawHub connection error %s: %s", url, exc.reason)
            return None

    def _post(self, path: str, body: dict[str, Any]) -> Any:
        url = f"{self.base_url}{path}"
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={**self._headers(authenticated=True), "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            LOG.error("ClawHub POST error %s %s: %s", exc.code, url, exc.reason)
            return None
        except urllib.error.URLError as exc:
            LOG.error("ClawHub POST connection error %s: %s", url, exc.reason)
            return None

    # ── Public API ────────────────────────────────────────────

    def search(self, query: str, limit: int = 20) -> list[ClawHubSkillInfo]:
        """Search ClawHub for skills matching *query*."""
        data = self._get(f"/api/skills/search?q={urllib.request.quote(query)}&limit={limit}")
        if not data:
            LOG.warning("ClawHub search returned no results for: %s", query)
            return []
        skills_list: list[dict] = []
        if isinstance(data, list):
            skills_list = data
        elif isinstance(data, dict):
            skills_list = data.get("skills", data.get("results", []))
        if not skills_list:
            LOG.warning("ClawHub search returned no results for: %s", query)
            return []
        return [ClawHubSkillInfo.from_dict(s) for s in skills_list]

    def get_skill(self, owner: str, slug: str) -> ClawHubSkillInfo | None:
        """Get metadata for a specific skill."""
        data = self._get(f"/api/skills/{owner}/{slug}")
        if not data:
            return None
        return ClawHubSkillInfo.from_dict(data)

    def get_skill_readme(self, owner: str, slug: str) -> str | None:
        """Fetch the SKILL.md content for a skill."""
        data = self._get(f"/api/skills/{owner}/{slug}/readme")
        if isinstance(data, dict):
            return data.get("content", data.get("readme", ""))
        if isinstance(data, str):
            return data
        return None

    def whoami(self) -> dict[str, Any] | None:
        """Check current authenticated user."""
        return self._get("/api/auth/whoami", authenticated=True)

    def is_available(self) -> bool:
        """Quick connectivity check."""
        try:
            result = self._get("/api/health")
            return result is not None
        except Exception:
            return False
