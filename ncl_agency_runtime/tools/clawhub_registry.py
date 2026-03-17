"""ClawHub Skill Registry for NCL.

Curates the mapping between ClawHub skills and NCL domains/pillars.
Tracks which skills are relevant, installed, and how they map to
the NCL Living Organism architecture.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

LOG = logging.getLogger(__name__)

_REGISTRY_PATH = Path(__file__).resolve().parent.parent.parent / "_config" / "clawhub_skills.json"


@dataclass
class SkillMapping:
    """Maps a ClawHub skill to NCL architecture."""

    slug: str                       # e.g. "steipete/summarize"
    ncl_skill_name: str             # Name used inside NCL skill router
    ncl_triggers: list[str]         # Trigger keywords for NCL routing
    ncl_description: str            # Human-readable purpose within NCL
    ncl_pillar: str                 # NCL_BRAIN | AAC_BANK | BIT_RAGE_SYSTEMS | NCC_COMMAND
    ncl_division: str               # INTELLIGENCE | OPERATIONS | RESEARCH | etc.
    ncl_layer: str                  # Which Living Organism layer: brain | muscles | senses | memory | immune
    priority: int = 1               # 1=critical, 2=important, 3=nice-to-have
    installed: bool = False
    tags: list[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════
#  CURATED SKILL MAPPINGS — ClawHub → NCL
#  Selected from 22,857+ skills for relevance to NCL architecture
# ═══════════════════════════════════════════════════════════════

CURATED_SKILLS: list[SkillMapping] = [
    # ─── BRAIN Layer (Intelligence & Research) ─────────────────
    SkillMapping(
        slug="steipete/summarize",
        ncl_skill_name="clawhub_summarize",
        ncl_triggers=["summarize url", "summarize file", "summarize pdf",
                       "tldr", "summarize this", "digest this"],
        ncl_description="Summarize URLs, PDFs, images, audio, YouTube via summarize CLI",
        ncl_pillar="NCL_BRAIN", ncl_division="INTELLIGENCE", ncl_layer="brain",
        priority=1, tags=["content", "digest", "research"],
    ),
    SkillMapping(
        slug="steipete/github",
        ncl_skill_name="clawhub_github",
        ncl_triggers=["github issue", "github pr", "gh search", "github repo",
                       "github run", "check ci"],
        ncl_description="GitHub CLI integration — issues, PRs, CI runs, API queries",
        ncl_pillar="NCL_BRAIN", ncl_division="INTELLIGENCE", ncl_layer="brain",
        priority=1, tags=["github", "devops", "ci"],
    ),
    SkillMapping(
        slug="oswalpalash/ontology",
        ncl_skill_name="clawhub_ontology",
        ncl_triggers=["knowledge graph", "ontology", "create entity",
                       "link entities", "query graph", "entity search"],
        ncl_description="Typed knowledge graph for structured agent memory and composable skills",
        ncl_pillar="NCL_BRAIN", ncl_division="RESEARCH", ncl_layer="memory",
        priority=1, tags=["knowledge", "graph", "memory", "entities"],
    ),
    SkillMapping(
        slug="gpyAngyoujun/multi-search-engine",
        ncl_skill_name="clawhub_multi_search",
        ncl_triggers=["web search", "search engine", "search the web",
                       "look up", "find online", "google it"],
        ncl_description="Multi search engine (17 engines, 8 CN + 9 Global) with advanced operators",
        ncl_pillar="NCL_BRAIN", ncl_division="INTELLIGENCE", ncl_layer="senses",
        priority=1, tags=["search", "web", "research"],
    ),
    SkillMapping(
        slug="steipete/brave-search",
        ncl_skill_name="clawhub_brave_search",
        ncl_triggers=["brave search", "search brave", "brave lookup"],
        ncl_description="Web search and content extraction via Brave Search API",
        ncl_pillar="NCL_BRAIN", ncl_division="INTELLIGENCE", ncl_layer="senses",
        priority=2, tags=["search", "web", "privacy"],
    ),

    # ─── SENSES Layer (Data Ingestion & Monitoring) ────────────
    SkillMapping(
        slug="TheSethRose/agent-browser",
        ncl_skill_name="clawhub_browser",
        ncl_triggers=["browse page", "open browser", "scrape page",
                       "fill form", "click button", "browser action"],
        ncl_description="Headless browser automation — navigate, click, type, snapshot",
        ncl_pillar="NCL_BRAIN", ncl_division="OPERATIONS", ncl_layer="senses",
        priority=1, tags=["browser", "automation", "scraping"],
    ),
    SkillMapping(
        slug="steipete/weather",
        ncl_skill_name="clawhub_weather",
        ncl_triggers=["weather", "forecast weather", "temperature",
                       "weather today", "rain today"],
        ncl_description="Current weather and forecasts (no API key required)",
        ncl_pillar="NCL_BRAIN", ncl_division="OPERATIONS", ncl_layer="senses",
        priority=2, tags=["weather", "data", "environment"],
    ),

    # ─── MUSCLES Layer (Actions & Productivity) ────────────────
    SkillMapping(
        slug="steipete/gog",
        ncl_skill_name="clawhub_google_workspace",
        ncl_triggers=["gmail", "google calendar", "google drive",
                       "google sheets", "google docs", "google contacts"],
        ncl_description="Google Workspace CLI — Gmail, Calendar, Drive, Contacts, Sheets, Docs",
        ncl_pillar="BIT_RAGE_SYSTEMS", ncl_division="OPERATIONS", ncl_layer="muscles",
        priority=1, tags=["google", "email", "calendar", "productivity"],
    ),
    SkillMapping(
        slug="steipete/notion",
        ncl_skill_name="clawhub_notion",
        ncl_triggers=["notion page", "notion database", "create notion",
                       "notion query", "notion update"],
        ncl_description="Notion API for creating and managing pages, databases, and blocks",
        ncl_pillar="NCL_BRAIN", ncl_division="KNOWLEDGE", ncl_layer="muscles",
        priority=2, tags=["notion", "notes", "knowledge"],
    ),
    SkillMapping(
        slug="steipete/obsidian",
        ncl_skill_name="clawhub_obsidian",
        ncl_triggers=["obsidian note", "obsidian vault", "obsidian search",
                       "open obsidian", "obsidian create"],
        ncl_description="Work with Obsidian vaults (plain Markdown notes) and automate via obsidian-cli",
        ncl_pillar="NCL_BRAIN", ncl_division="KNOWLEDGE", ncl_layer="memory",
        priority=2, tags=["obsidian", "notes", "knowledge", "markdown"],
    ),
    SkillMapping(
        slug="steipete/nano-pdf",
        ncl_skill_name="clawhub_pdf",
        ncl_triggers=["edit pdf", "create pdf", "pdf edit",
                       "merge pdf", "extract pdf"],
        ncl_description="Edit PDFs with natural-language instructions using nano-pdf CLI",
        ncl_pillar="BIT_RAGE_SYSTEMS", ncl_division="OPERATIONS", ncl_layer="muscles",
        priority=2, tags=["pdf", "documents"],
    ),
    SkillMapping(
        slug="steipete/nano-banana-pro",
        ncl_skill_name="clawhub_image_gen",
        ncl_triggers=["generate image", "create image", "edit image",
                       "make picture", "image generation"],
        ncl_description="Generate/edit images with Gemini 3 Pro (text-to-image + image-to-image)",
        ncl_pillar="BIT_RAGE_SYSTEMS", ncl_division="CREATIVE", ncl_layer="muscles",
        priority=3, tags=["image", "creative", "ai"],
    ),

    # ─── IMMUNE Layer (Security & Vetting) ─────────────────────
    SkillMapping(
        slug="spclaudehome/skill-vetter",
        ncl_skill_name="clawhub_skill_vetter",
        ncl_triggers=["vet skill", "check skill security", "skill audit",
                       "is this skill safe", "vetter"],
        ncl_description="Security-first skill vetting — red flags, permission scope, suspicious patterns",
        ncl_pillar="NCC_COMMAND", ncl_division="GOVERNANCE", ncl_layer="immune",
        priority=1, tags=["security", "vetting", "audit"],
    ),

    # ─── REGENERATION Layer (Self-Improvement) ─────────────────
    SkillMapping(
        slug="halthelobster/proactive-agent",
        ncl_skill_name="clawhub_proactive",
        ncl_triggers=["proactive mode", "anticipate needs", "autonomous cron",
                       "proactive check", "hal stack"],
        ncl_description="Transform from task-follower to proactive partner — WAL Protocol, Working Buffer, Autonomous Crons",
        ncl_pillar="NCL_BRAIN", ncl_division="OPERATIONS", ncl_layer="regeneration",
        priority=1, tags=["proactive", "autonomous", "cron"],
    ),
    SkillMapping(
        slug="ivangdavila/self-improving",
        ncl_skill_name="clawhub_self_improving",
        ncl_triggers=["self improve", "self reflect", "self critique",
                       "learn from mistakes", "self evaluation"],
        ncl_description="Self-reflection + self-criticism + self-learning + self-organizing memory",
        ncl_pillar="NCL_BRAIN", ncl_division="RESEARCH", ncl_layer="regeneration",
        priority=2, tags=["learning", "self-improvement", "reflection"],
    ),
    SkillMapping(
        slug="JimLiuxinghai/find-skills",
        ncl_skill_name="clawhub_find_skills",
        ncl_triggers=["find skill", "search skills", "clawhub search",
                       "what skills exist", "skill for"],
        ncl_description="Discover and install agent skills from ClawHub registry",
        ncl_pillar="NCL_BRAIN", ncl_division="INTELLIGENCE", ncl_layer="brain",
        priority=1, tags=["discovery", "skills", "clawhub"],
    ),

    # ─── OPERATIONS Layer (Automation & Workflows) ─────────────
    SkillMapping(
        slug="JK-0001/automation-workflows",
        ncl_skill_name="clawhub_automation",
        ncl_triggers=["automate", "automation workflow", "create workflow",
                       "zapier", "make.com", "n8n"],
        ncl_description="Design and implement automation workflows — Zapier, Make, n8n integration",
        ncl_pillar="BIT_RAGE_SYSTEMS", ncl_division="OPERATIONS", ncl_layer="muscles",
        priority=2, tags=["automation", "workflow", "integration"],
    ),
    SkillMapping(
        slug="byungkyu/api-gateway",
        ncl_skill_name="clawhub_api_gateway",
        ncl_triggers=["connect api", "api gateway", "oauth connect",
                       "airtable", "hubspot", "slack api"],
        ncl_description="Connect to 100+ APIs (Google, Microsoft, GitHub, Slack, etc.) with managed OAuth",
        ncl_pillar="BIT_RAGE_SYSTEMS", ncl_division="OPERATIONS", ncl_layer="senses",
        priority=1, tags=["api", "oauth", "integration"],
    ),
    SkillMapping(
        slug="steipete/mcporter",
        ncl_skill_name="clawhub_mcp",
        ncl_triggers=["mcp server", "mcp tool", "list mcp", "call mcp",
                       "model context protocol"],
        ncl_description="List, configure, auth, and call MCP servers/tools directly",
        ncl_pillar="NCL_BRAIN", ncl_division="OPERATIONS", ncl_layer="muscles",
        priority=2, tags=["mcp", "protocol", "tools"],
    ),

    # ─── CONTENT Layer (Writing & Communication) ───────────────
    SkillMapping(
        slug="biostartechnology/humanizer",
        ncl_skill_name="clawhub_humanizer",
        ncl_triggers=["humanize text", "make natural", "remove ai writing",
                       "humanize", "rewrite naturally"],
        ncl_description="Remove signs of AI-generated writing — make text sound natural and human",
        ncl_pillar="BIT_RAGE_SYSTEMS", ncl_division="COMMUNICATIONS", ncl_layer="muscles",
        priority=2, tags=["writing", "content", "humanize"],
    ),
    SkillMapping(
        slug="chindden/skill-creator",
        ncl_skill_name="clawhub_skill_creator",
        ncl_triggers=["create skill", "build skill", "new skill",
                       "skill creator", "make a skill"],
        ncl_description="Guide for creating effective ClawHub skills — templates, workflows, best practices",
        ncl_pillar="NCL_BRAIN", ncl_division="INNOVATION", ncl_layer="brain",
        priority=2, tags=["meta", "skills", "creation"],
    ),

    # ─── AUDIO/MEDIA Layer ─────────────────────────────────────
    SkillMapping(
        slug="steipete/openai-whisper",
        ncl_skill_name="clawhub_whisper",
        ncl_triggers=["transcribe audio", "speech to text", "whisper",
                       "transcribe", "audio to text"],
        ncl_description="Local speech-to-text with Whisper CLI (no API key required)",
        ncl_pillar="NCL_BRAIN", ncl_division="INTELLIGENCE", ncl_layer="senses",
        priority=2, tags=["audio", "transcription", "speech"],
    ),
    SkillMapping(
        slug="steipete/sonoscli",
        ncl_skill_name="clawhub_sonos",
        ncl_triggers=["sonos", "play music", "speaker control",
                       "play sonos", "sonos volume"],
        ncl_description="Control Sonos speakers — discover, play, volume, group",
        ncl_pillar="BIT_RAGE_SYSTEMS", ncl_division="OPERATIONS", ncl_layer="muscles",
        priority=3, tags=["audio", "speakers", "smart-home"],
    ),

    # ─── AUTO-UPDATER ──────────────────────────────────────────
    SkillMapping(
        slug="maximeprades/auto-updater",
        ncl_skill_name="clawhub_auto_updater",
        ncl_triggers=["update skills", "auto update", "check updates",
                       "update clawhub"],
        ncl_description="Auto-update installed skills daily via cron — summary of changes",
        ncl_pillar="NCC_COMMAND", ncl_division="GOVERNANCE", ncl_layer="regeneration",
        priority=2, tags=["updates", "maintenance", "cron"],
    ),
]


# ═══════════════════════════════════════════════════════════════
#  Registry Operations
# ═══════════════════════════════════════════════════════════════

def get_all_mappings() -> list[SkillMapping]:
    """Return all curated skill mappings."""
    return list(CURATED_SKILLS)


def get_mappings_by_pillar(pillar: str) -> list[SkillMapping]:
    """Return mappings filtered by NCL pillar."""
    return [m for m in CURATED_SKILLS if m.ncl_pillar == pillar]


def get_mappings_by_layer(layer: str) -> list[SkillMapping]:
    """Return mappings filtered by NCL organism layer."""
    return [m for m in CURATED_SKILLS if m.ncl_layer == layer]


def get_mappings_by_priority(max_priority: int = 2) -> list[SkillMapping]:
    """Return mappings at or above priority threshold (1 = highest)."""
    return [m for m in CURATED_SKILLS if m.priority <= max_priority]


def get_mapping_by_slug(slug: str) -> SkillMapping | None:
    """Look up a mapping by ClawHub slug."""
    for m in CURATED_SKILLS:
        if m.slug == slug:
            return m
    return None


def get_mapping_by_skill_name(name: str) -> SkillMapping | None:
    """Look up a mapping by NCL skill name."""
    for m in CURATED_SKILLS:
        if m.ncl_skill_name == name:
            return m
    return None


def save_registry(path: Path | None = None) -> None:
    """Persist the current registry state to disk."""
    target = path or _REGISTRY_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "version": "1.0.0",
        "description": "NCL ↔ ClawHub skill mappings — curated from 22,857+ skills",
        "skills": [
            {
                "slug": m.slug,
                "ncl_skill_name": m.ncl_skill_name,
                "ncl_triggers": m.ncl_triggers,
                "ncl_description": m.ncl_description,
                "ncl_pillar": m.ncl_pillar,
                "ncl_division": m.ncl_division,
                "ncl_layer": m.ncl_layer,
                "priority": m.priority,
                "installed": m.installed,
                "tags": m.tags,
            }
            for m in CURATED_SKILLS
        ],
    }
    target.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    LOG.info("ClawHub registry saved to %s (%d skills)", target, len(CURATED_SKILLS))


def load_registry(path: Path | None = None) -> list[SkillMapping]:
    """Load registry state from disk, merging installed status."""
    target = path or _REGISTRY_PATH
    if not target.exists():
        return get_all_mappings()
    data: dict[str, Any] = json.loads(target.read_text(encoding="utf-8"))
    disk_skills: dict[str, dict] = {s["slug"]: s for s in data.get("skills", [])}
    for m in CURATED_SKILLS:
        if m.slug in disk_skills:
            m.installed = disk_skills[m.slug].get("installed", False)
    return get_all_mappings()


def summary() -> dict[str, Any]:
    """High-level registry summary."""
    total = len(CURATED_SKILLS)
    by_pillar: dict[str, int] = {}
    by_layer: dict[str, int] = {}
    by_priority: dict[int, int] = {}
    installed = 0
    for m in CURATED_SKILLS:
        by_pillar[m.ncl_pillar] = by_pillar.get(m.ncl_pillar, 0) + 1
        by_layer[m.ncl_layer] = by_layer.get(m.ncl_layer, 0) + 1
        by_priority[m.priority] = by_priority.get(m.priority, 0) + 1
        if m.installed:
            installed += 1
    return {
        "total_curated": total,
        "installed": installed,
        "by_pillar": by_pillar,
        "by_layer": by_layer,
        "by_priority": by_priority,
    }
