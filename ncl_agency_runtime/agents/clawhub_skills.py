"""ClawHub-powered skills for the NCL SuperOpenClawAgent.

These skills bridge ClawHub's 22,857+ skill registry into the NCL
Living Organism architecture.  Each skill wraps ClawHub client calls
and skill-router patterns so they integrate seamlessly as NCL Muscles.

Skill hierarchy:
    Skill (ABC)  ← super_openclaw_agent.py
    └── ClawHubSearchSkill       — discover skills in the registry
    └── ClawHubStatusSkill       — show installed / curated skill status
    └── ClawHubSummarizeSkill    — URL / file / PDF / YouTube summarization
    └── ClawHubWebSearchSkill    — multi-engine web search
    └── ClawHubBrowserSkill      — headless browser automation
    └── ClawHubOntologySkill     — typed knowledge graph ops
    └── ClawHubWeatherSkill      — weather forecasts
    └── ClawHubSkillVetterSkill  — security vetting for skills
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any, ClassVar

from ncl_agency_runtime.agents.super_openclaw_agent import (
    InboundMessage,
    Skill,
    SkillResult,
)
from ncl_agency_runtime.tools.clawhub_client import ClawHubClient
from ncl_agency_runtime.tools.clawhub_registry import (
    CURATED_SKILLS,
    get_mapping_by_slug,
    get_mappings_by_layer,
    get_mappings_by_priority,
    summary as registry_summary,
)

if TYPE_CHECKING:
    from ncl_agency_runtime.agents.super_openclaw_agent import SuperOpenClawAgent

LOG = logging.getLogger(__name__)


def _strip_triggers(text: str, triggers: list[str]) -> str:
    """Remove trigger prefixes from user text to extract the query."""
    lower = text.lower()
    for trigger in sorted(triggers, key=len, reverse=True):
        if lower.startswith(trigger):
            return text[len(trigger):].strip()
    # Fallback: remove trigger anywhere
    for trigger in triggers:
        lower = lower.replace(trigger, "")
    return lower.strip()


# ═══════════════════════════════════════════════════════════════
#  Discovery & Registry Skills
# ═══════════════════════════════════════════════════════════════

class ClawHubSearchSkill(Skill):
    """Search ClawHub's registry for agent skills."""

    name = "clawhub_search"
    triggers: ClassVar[list[str]] = [
        "find skill", "clawhub search", "skill search",
        "search clawhub", "what skills exist", "skill for",
        "clawhub find",
    ]
    description = "Search ClawHub's 22,857+ skill registry for agent capabilities."

    def __init__(self) -> None:
        self._client = ClawHubClient()

    async def execute(self, msg: InboundMessage, agent: SuperOpenClawAgent) -> SkillResult:
        t0 = time.monotonic()
        query = _strip_triggers(msg.text, self.triggers)
        if not query:
            return SkillResult(
                success=False,
                reply="Please specify what kind of skill you're looking for.\n"
                      "Example: *find skill web scraping*",
                skill_name=self.name,
            )

        if not self._client.is_available():
            # Fall back to curated registry
            return self._search_curated(query, t0)

        results = self._client.search(query, limit=8)
        if not results:
            return self._search_curated(query, t0)

        lines = [f"**ClawHub Skills** matching *{query}*:\n"]
        for i, skill in enumerate(results, 1):
            stars = f"⭐ {skill.stars}" if skill.stars else ""
            installs = f"📦 {skill.installs:,}" if skill.installs else ""
            curated = get_mapping_by_slug(skill.slug)
            badge = " 🟢 NCL-curated" if curated else ""
            lines.append(
                f"{i}. **{skill.name}** (`{skill.slug}`) "
                f"{stars} {installs}{badge}\n"
                f"   {skill.description[:120]}"
            )

        elapsed = (time.monotonic() - t0) * 1000
        return SkillResult(
            success=True,
            reply="\n".join(lines),
            data={"results": [{"slug": r.slug, "name": r.name} for r in results]},
            skill_name=self.name,
            execution_ms=elapsed,
        )

    def _search_curated(self, query: str, t0: float) -> SkillResult:
        """Search the local curated registry when online search unavailable."""
        query_lower = query.lower()
        matches = [
            m for m in CURATED_SKILLS
            if query_lower in m.ncl_description.lower()
            or query_lower in " ".join(m.tags).lower()
            or query_lower in m.ncl_skill_name.lower()
        ]
        if not matches:
            elapsed = (time.monotonic() - t0) * 1000
            return SkillResult(
                success=True,
                reply=f"No skills found matching *{query}* in local registry.",
                skill_name=self.name,
                execution_ms=elapsed,
            )

        lines = [f"**Curated Skills** matching *{query}* (offline):\n"]
        for i, m in enumerate(matches, 1):
            lines.append(
                f"{i}. **{m.ncl_skill_name}** (`{m.slug}`) "
                f"[{m.ncl_layer}/{m.ncl_pillar}]\n"
                f"   {m.ncl_description}"
            )
        elapsed = (time.monotonic() - t0) * 1000
        return SkillResult(
            success=True,
            reply="\n".join(lines),
            skill_name=self.name,
            execution_ms=elapsed,
        )


class ClawHubStatusSkill(Skill):
    """Show status of ClawHub skill integration."""

    name = "clawhub_status"
    triggers: ClassVar[list[str]] = [
        "clawhub status", "installed skills", "clawhub info",
        "skill status", "clawhub registry",
    ]
    description = "Show ClawHub integration status — curated skills, installed skills, registry health."

    async def execute(self, msg: InboundMessage, agent: SuperOpenClawAgent) -> SkillResult:
        t0 = time.monotonic()
        s = registry_summary()

        lines = [
            "**ClawHub Integration Status**\n",
            f"Total curated skills: **{s['total_curated']}**",
            f"Installed: **{s['installed']}**\n",
            "**By NCL Pillar:**",
        ]
        for pillar, count in sorted(s["by_pillar"].items()):
            lines.append(f"  • {pillar}: {count}")

        lines.append("\n**By Organism Layer:**")
        for layer, count in sorted(s["by_layer"].items()):
            lines.append(f"  • {layer}: {count}")

        lines.append("\n**By Priority:**")
        for p, count in sorted(s["by_priority"].items()):
            label = {1: "Critical", 2: "Important", 3: "Nice-to-have"}.get(p, str(p))
            lines.append(f"  • P{p} ({label}): {count}")

        # Check API connectivity
        client = ClawHubClient()
        api_ok = client.is_available()
        lines.append(f"\nClawHub API: {'🟢 Connected' if api_ok else '🔴 Offline'}")

        elapsed = (time.monotonic() - t0) * 1000
        return SkillResult(
            success=True,
            reply="\n".join(lines),
            data=s,
            skill_name=self.name,
            execution_ms=elapsed,
        )


# ═══════════════════════════════════════════════════════════════
#  Content & Research Skills
# ═══════════════════════════════════════════════════════════════

class ClawHubSummarizeSkill(Skill):
    """Summarize URLs, files, PDFs, YouTube videos via ClawHub summarize skill."""

    name = "clawhub_summarize"
    triggers: ClassVar[list[str]] = [
        "summarize url", "summarize file", "summarize pdf",
        "tldr", "summarize this", "digest this",
        "summarize link", "summarize page",
    ]
    description = "Summarize URLs, PDFs, YouTube videos, and files using the ClawHub summarize skill."

    def __init__(self) -> None:
        self._client = ClawHubClient()

    async def execute(self, msg: InboundMessage, agent: SuperOpenClawAgent) -> SkillResult:
        t0 = time.monotonic()
        target = _strip_triggers(msg.text, self.triggers)
        if not target:
            return SkillResult(
                success=False,
                reply="Please provide a URL or file to summarize.\n"
                      "Example: *summarize url https://example.com/article*",
                skill_name=self.name,
            )

        # Try to get the summarize skill README for instructions
        readme = self._client.get_skill_readme("steipete", "summarize")
        if readme:
            # Summarize skill is CLI-based; provide guidance
            reply = (
                f"**Summarize:** *{target}*\n\n"
                f"ClawHub `steipete/summarize` skill can process this.\n"
                f"Install: `npx clawhub@latest install steipete/summarize`\n"
                f"Usage: `summarize {target}`\n\n"
                f"The skill supports URLs, PDFs, images, audio, YouTube, "
                f"and local files with configurable output length."
            )
        else:
            reply = (
                f"**Summarize:** *{target}*\n\n"
                f"The ClawHub summarize skill (`steipete/summarize`) handles "
                f"URL/PDF/YouTube/file summarization.\n"
                f"Install: `npx clawhub@latest install steipete/summarize`"
            )

        elapsed = (time.monotonic() - t0) * 1000
        return SkillResult(
            success=True,
            reply=reply,
            data={"target": target, "skill_slug": "steipete/summarize"},
            skill_name=self.name,
            execution_ms=elapsed,
        )


class ClawHubWebSearchSkill(Skill):
    """Search the web via ClawHub's multi-search-engine skill."""

    name = "clawhub_web_search"
    triggers: ClassVar[list[str]] = [
        "web search", "search the web", "google it",
        "brave search", "search online", "find online",
    ]
    description = "Search the web using 17+ search engines via ClawHub's multi-search skill."

    def __init__(self) -> None:
        self._client = ClawHubClient()

    async def execute(self, msg: InboundMessage, agent: SuperOpenClawAgent) -> SkillResult:
        t0 = time.monotonic()
        query = _strip_triggers(msg.text, self.triggers)
        if not query:
            return SkillResult(
                success=False,
                reply="Please provide a search query.\n"
                      "Example: *web search python async patterns*",
                skill_name=self.name,
            )

        # Look up the skill in ClawHub
        skill_info = self._client.get_skill("gpyAngyoujun", "multi-search-engine")
        if skill_info:
            reply = (
                f"**Web Search:** *{query}*\n\n"
                f"ClawHub `gpyAngyoujun/multi-search-engine` can run this across "
                f"17 engines (Google, Bing, DuckDuckGo, Baidu, etc.).\n"
                f"Install: `npx clawhub@latest install gpyAngyoujun/multi-search-engine`\n"
                f"Usage: `search_multi \"{query}\"`"
            )
        else:
            reply = (
                f"**Web Search:** *{query}*\n\n"
                f"Alternative: `steipete/brave-search` for Brave Search API.\n"
                f"Install: `npx clawhub@latest install steipete/brave-search`"
            )

        elapsed = (time.monotonic() - t0) * 1000
        return SkillResult(
            success=True,
            reply=reply,
            data={"query": query},
            skill_name=self.name,
            execution_ms=elapsed,
        )


# ═══════════════════════════════════════════════════════════════
#  Senses Layer Skills
# ═══════════════════════════════════════════════════════════════

class ClawHubBrowserSkill(Skill):
    """Headless browser automation via ClawHub's agent-browser skill."""

    name = "clawhub_browser"
    triggers: ClassVar[list[str]] = [
        "browse page", "open browser", "scrape page",
        "fill form", "click button", "browser action",
        "visit page", "navigate to",
    ]
    description = "Headless browser automation — navigate, click, type, screenshot, extract."

    async def execute(self, msg: InboundMessage, agent: SuperOpenClawAgent) -> SkillResult:
        t0 = time.monotonic()
        target = _strip_triggers(msg.text, self.triggers)
        if not target:
            return SkillResult(
                success=False,
                reply="Please provide a URL or browser action.\n"
                      "Example: *browse page https://example.com*",
                skill_name=self.name,
            )

        reply = (
            f"**Browser Action:** *{target}*\n\n"
            f"ClawHub `TheSethRose/agent-browser` provides headless Rust browser.\n"
            f"Capabilities: navigate, click, type, screenshot, extract content.\n"
            f"Install: `npx clawhub@latest install TheSethRose/agent-browser`"
        )

        elapsed = (time.monotonic() - t0) * 1000
        return SkillResult(
            success=True,
            reply=reply,
            data={"target": target, "skill_slug": "TheSethRose/agent-browser"},
            skill_name=self.name,
            execution_ms=elapsed,
        )


class ClawHubWeatherSkill(Skill):
    """Weather forecasts via ClawHub's weather skill (no API key needed)."""

    name = "clawhub_weather"
    triggers: ClassVar[list[str]] = [
        "weather", "forecast weather", "temperature",
        "weather today", "rain today", "weather in",
    ]
    description = "Current weather and forecasts — no API key required."

    async def execute(self, msg: InboundMessage, agent: SuperOpenClawAgent) -> SkillResult:
        t0 = time.monotonic()
        location = _strip_triggers(msg.text, self.triggers)
        if not location:
            location = "current location"

        reply = (
            f"**Weather:** *{location}*\n\n"
            f"ClawHub `steipete/weather` provides forecasts with no API key.\n"
            f"Install: `npx clawhub@latest install steipete/weather`\n"
            f"Usage: `weather {location}`"
        )

        elapsed = (time.monotonic() - t0) * 1000
        return SkillResult(
            success=True,
            reply=reply,
            data={"location": location, "skill_slug": "steipete/weather"},
            skill_name=self.name,
            execution_ms=elapsed,
        )


# ═══════════════════════════════════════════════════════════════
#  Memory & Knowledge Skills
# ═══════════════════════════════════════════════════════════════

class ClawHubOntologySkill(Skill):
    """Typed knowledge graph via ClawHub's ontology skill."""

    name = "clawhub_ontology"
    triggers: ClassVar[list[str]] = [
        "knowledge graph", "ontology", "create entity",
        "link entities", "query graph", "entity search",
    ]
    description = "Typed knowledge graph for structured agent memory — entities, relations, queries."

    async def execute(self, msg: InboundMessage, agent: SuperOpenClawAgent) -> SkillResult:
        t0 = time.monotonic()
        action = _strip_triggers(msg.text, self.triggers)
        if not action:
            return SkillResult(
                success=False,
                reply="Please specify a knowledge graph operation.\n"
                      "Examples:\n"
                      "  • *create entity Person: John Doe*\n"
                      "  • *link entities John → works_at → Acme*\n"
                      "  • *query graph Person where name=John*",
                skill_name=self.name,
            )

        reply = (
            f"**Knowledge Graph:** *{action}*\n\n"
            f"ClawHub `oswalpalash/ontology` provides a typed knowledge graph.\n"
            f"Features: entity types, relationships, composable queries, memory integration.\n"
            f"Install: `npx clawhub@latest install oswalpalash/ontology`"
        )

        elapsed = (time.monotonic() - t0) * 1000
        return SkillResult(
            success=True,
            reply=reply,
            data={"action": action, "skill_slug": "oswalpalash/ontology"},
            skill_name=self.name,
            execution_ms=elapsed,
        )


# ═══════════════════════════════════════════════════════════════
#  Immune Layer Skills
# ═══════════════════════════════════════════════════════════════

class ClawHubSkillVetterSkill(Skill):
    """Security-first skill vetting via ClawHub's skill-vetter."""

    name = "clawhub_skill_vetter"
    triggers: ClassVar[list[str]] = [
        "vet skill", "check skill security", "skill audit",
        "is this skill safe", "vetter", "audit skill",
    ]
    description = "Security-first skill vetting — red flags, permission scope, suspicious patterns."

    def __init__(self) -> None:
        self._client = ClawHubClient()

    async def execute(self, msg: InboundMessage, agent: SuperOpenClawAgent) -> SkillResult:
        t0 = time.monotonic()
        target = _strip_triggers(msg.text, self.triggers)
        if not target:
            return SkillResult(
                success=False,
                reply="Please specify a skill to vet.\n"
                      "Example: *vet skill steipete/summarize*",
                skill_name=self.name,
            )

        # Try to look up the skill
        parts = target.split("/", 1)
        if len(parts) == 2:
            owner, slug = parts
            skill_info = self._client.get_skill(owner.strip(), slug.strip())
            if skill_info:
                reply = (
                    f"**Skill Vetting:** `{target}`\n\n"
                    f"Name: {skill_info.name}\n"
                    f"Owner: {skill_info.owner}\n"
                    f"Stars: {skill_info.stars} | Installs: {skill_info.installs:,}\n"
                    f"Tags: {', '.join(skill_info.tags)}\n\n"
                    f"For deep security scan, use:\n"
                    f"`npx clawhub@latest install spclaudehome/skill-vetter`\n"
                    f"Then: `vet {target}`"
                )
            else:
                reply = (
                    f"**Skill Vetting:** `{target}`\n\n"
                    f"Could not retrieve skill metadata.\n"
                    f"For deep security scan:\n"
                    f"`npx clawhub@latest install spclaudehome/skill-vetter`\n"
                    f"Then: `vet {target}`"
                )
        else:
            reply = (
                f"**Skill Vetting:** *{target}*\n\n"
                f"Please provide skill in `owner/slug` format.\n"
                f"Example: *vet skill steipete/summarize*\n\n"
                f"For deep security scanning:\n"
                f"`npx clawhub@latest install spclaudehome/skill-vetter`"
            )

        elapsed = (time.monotonic() - t0) * 1000
        return SkillResult(
            success=True,
            reply=reply,
            data={"target": target, "skill_slug": "spclaudehome/skill-vetter"},
            skill_name=self.name,
            execution_ms=elapsed,
        )


# ═══════════════════════════════════════════════════════════════
#  Convenience: All ClawHub Skills
# ═══════════════════════════════════════════════════════════════

ALL_CLAWHUB_SKILLS: list[type[Skill]] = [
    ClawHubSearchSkill,
    ClawHubStatusSkill,
    ClawHubSummarizeSkill,
    ClawHubWebSearchSkill,
    ClawHubBrowserSkill,
    ClawHubWeatherSkill,
    ClawHubOntologySkill,
    ClawHubSkillVetterSkill,
]


def create_clawhub_skills() -> list[Skill]:
    """Instantiate all ClawHub skills ready for registration."""
    return [cls() for cls in ALL_CLAWHUB_SKILLS]
