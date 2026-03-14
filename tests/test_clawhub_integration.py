#!/usr/bin/env python3
"""Tests for the ClawHub integration layer.

Covers:
    - ClawHub client (mocked HTTP)
    - ClawHub skill registry (curated mappings)
    - ClawHub NCL skills (routing, execution)
    - Integration with SuperOpenClawAgent
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Path setup
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ncl_agency_runtime" / "agents"))

import pytest

from ncl_agency_runtime.agents.super_openclaw_agent import (
    ChannelType,
    InboundMessage,
    Skill,
    SkillResult,
    SkillRouter,
    create_agent,
)
from ncl_agency_runtime.agents.clawhub_skills import (
    ALL_CLAWHUB_SKILLS,
    ClawHubBrowserSkill,
    ClawHubOntologySkill,
    ClawHubSearchSkill,
    ClawHubSkillVetterSkill,
    ClawHubStatusSkill,
    ClawHubSummarizeSkill,
    ClawHubWeatherSkill,
    ClawHubWebSearchSkill,
    create_clawhub_skills,
)
from ncl_agency_runtime.tools.clawhub_client import ClawHubClient, ClawHubSkillInfo
from ncl_agency_runtime.tools.clawhub_registry import (
    CURATED_SKILLS,
    get_all_mappings,
    get_mapping_by_slug,
    get_mapping_by_skill_name,
    get_mappings_by_layer,
    get_mappings_by_pillar,
    get_mappings_by_priority,
    summary,
)


# ══════════════════════════════════════════════════════════════
#  Fixtures
# ══════════════════════════════════════════════════════════════

@pytest.fixture
def agent():
    return create_agent(allowed_senders=["AZ_PRIME", "test_user"])


@pytest.fixture
def inbound_msg():
    return InboundMessage(
        channel=ChannelType.CLI,
        sender_id="AZ_PRIME",
        sender_name="AZ",
        text="find skill web scraping",
    )


@pytest.fixture
def skill_router():
    router = SkillRouter()
    for skill in create_clawhub_skills():
        router.register(skill)
    return router


# ══════════════════════════════════════════════════════════════
#  ClawHub Client Tests
# ══════════════════════════════════════════════════════════════

class TestClawHubClient:
    """Test ClawHubClient HTTP interactions (mocked)."""

    def test_client_creation(self):
        client = ClawHubClient()
        assert client.base_url == "https://clawhub.ai"

    @patch("ncl_agency_runtime.tools.clawhub_client.ClawHubClient._get")
    def test_search(self, mock_get):
        mock_get.return_value = {
            "skills": [
                {
                    "slug": "owner/test-skill",
                    "name": "Test Skill",
                    "owner": "owner",
                    "description": "A test skill",
                    "stars": 100,
                    "installs": 5000,
                    "versions": ["1.0.0"],
                    "tags": ["test"],
                },
            ]
        }
        client = ClawHubClient()
        results = client.search("test", limit=5)
        assert len(results) == 1
        assert results[0].slug == "owner/test-skill"
        assert results[0].name == "Test Skill"
        assert results[0].stars == 100

    @patch("ncl_agency_runtime.tools.clawhub_client.ClawHubClient._get")
    def test_get_skill(self, mock_get):
        mock_get.return_value = {
            "slug": "steipete/summarize",
            "name": "Summarize",
            "owner": "steipete",
            "description": "Summarize anything",
            "stars": 579,
            "installs": 152000,
            "versions": ["2.1.0"],
            "tags": ["content", "summary"],
        }
        client = ClawHubClient()
        info = client.get_skill("steipete", "summarize")
        assert info is not None
        assert info.slug == "steipete/summarize"
        assert info.installs == 152000

    @patch("ncl_agency_runtime.tools.clawhub_client.ClawHubClient._get")
    def test_get_skill_not_found(self, mock_get):
        mock_get.return_value = None
        client = ClawHubClient()
        info = client.get_skill("nonexistent", "skill")
        assert info is None

    @patch("ncl_agency_runtime.tools.clawhub_client.ClawHubClient._get")
    def test_is_available(self, mock_get):
        mock_get.return_value = {"status": "ok"}
        client = ClawHubClient()
        assert client.is_available()

    @patch("ncl_agency_runtime.tools.clawhub_client.ClawHubClient._get")
    def test_is_unavailable(self, mock_get):
        mock_get.return_value = None
        client = ClawHubClient()
        assert not client.is_available()

    def test_skill_info_from_dict(self):
        data = {
            "slug": "owner/skill",
            "name": "Test",
            "owner": "owner",
            "description": "Desc",
            "stars": 10,
            "installs": 100,
            "versions": ["1.0"],
            "tags": ["a", "b"],
        }
        info = ClawHubSkillInfo.from_dict(data)
        assert info.slug == "owner/skill"
        assert info.tags == ["a", "b"]
        assert info.url == "https://clawhub.ai/skills/owner/skill"

    def test_skill_info_from_dict_defaults(self):
        info = ClawHubSkillInfo.from_dict({"slug": "x/y"})
        assert info.name == "x/y"  # defaults to slug when name not provided
        assert info.stars == 0
        assert info.installs == 0
        assert info.tags == []


# ══════════════════════════════════════════════════════════════
#  ClawHub Registry Tests
# ══════════════════════════════════════════════════════════════

class TestClawHubRegistry:
    """Test the curated skill registry."""

    def test_curated_skills_count(self):
        assert len(CURATED_SKILLS) == 24

    def test_all_mappings_returns_copy(self):
        mappings = get_all_mappings()
        assert len(mappings) == len(CURATED_SKILLS)
        assert mappings is not CURATED_SKILLS

    def test_mappings_by_pillar(self):
        ncl_brain = get_mappings_by_pillar("NCL_BRAIN")
        assert len(ncl_brain) > 0
        for m in ncl_brain:
            assert m.ncl_pillar == "NCL_BRAIN"

    def test_mappings_by_layer(self):
        brain_layer = get_mappings_by_layer("brain")
        assert len(brain_layer) > 0
        for m in brain_layer:
            assert m.ncl_layer == "brain"

    def test_mappings_by_priority(self):
        critical = get_mappings_by_priority(1)
        assert len(critical) > 0
        for m in critical:
            assert m.priority == 1

    def test_get_mapping_by_slug(self):
        m = get_mapping_by_slug("steipete/summarize")
        assert m is not None
        assert m.ncl_skill_name == "clawhub_summarize"

    def test_get_mapping_by_slug_not_found(self):
        m = get_mapping_by_slug("nonexistent/skill")
        assert m is None

    def test_get_mapping_by_skill_name(self):
        m = get_mapping_by_skill_name("clawhub_search")
        assert m is None  # clawhub_search is not the curated name

        m = get_mapping_by_skill_name("clawhub_find_skills")
        assert m is not None
        assert m.slug == "JimLiuxinghai/find-skills"

    def test_summary(self):
        s = summary()
        assert s["total_curated"] == 24
        assert "by_pillar" in s
        assert "by_layer" in s
        assert "by_priority" in s
        assert isinstance(s["installed"], int)

    def test_all_skills_have_required_fields(self):
        for m in CURATED_SKILLS:
            assert m.slug, f"Missing slug"
            assert m.ncl_skill_name, f"Missing ncl_skill_name for {m.slug}"
            assert m.ncl_triggers, f"Missing triggers for {m.slug}"
            assert m.ncl_description, f"Missing description for {m.slug}"
            assert m.ncl_pillar, f"Missing pillar for {m.slug}"
            assert m.ncl_layer, f"Missing layer for {m.slug}"
            assert m.priority in (1, 2, 3), f"Invalid priority for {m.slug}"

    def test_no_duplicate_slugs(self):
        slugs = [m.slug for m in CURATED_SKILLS]
        assert len(slugs) == len(set(slugs)), "Duplicate slugs in registry"

    def test_no_duplicate_skill_names(self):
        names = [m.ncl_skill_name for m in CURATED_SKILLS]
        assert len(names) == len(set(names)), "Duplicate skill names in registry"


# ══════════════════════════════════════════════════════════════
#  ClawHub Skills Tests
# ══════════════════════════════════════════════════════════════

class TestClawHubSkills:
    """Test ClawHub NCL skill implementations."""

    def test_all_skills_count(self):
        assert len(ALL_CLAWHUB_SKILLS) == 8

    def test_create_clawhub_skills(self):
        skills = create_clawhub_skills()
        assert len(skills) == 8
        for skill in skills:
            assert isinstance(skill, Skill)
            assert skill.name
            assert skill.triggers
            assert skill.description

    def test_skill_names_unique(self):
        skills = create_clawhub_skills()
        names = [s.name for s in skills]
        assert len(names) == len(set(names))

    def test_search_skill_triggers(self):
        skill = ClawHubSearchSkill()
        assert "find skill" in skill.triggers
        assert "clawhub search" in skill.triggers

    def test_status_skill_triggers(self):
        skill = ClawHubStatusSkill()
        assert "clawhub status" in skill.triggers
        assert "installed skills" in skill.triggers

    def test_summarize_skill_triggers(self):
        skill = ClawHubSummarizeSkill()
        assert "summarize url" in skill.triggers
        assert "tldr" in skill.triggers

    def test_browser_skill_triggers(self):
        skill = ClawHubBrowserSkill()
        assert "browse page" in skill.triggers
        assert "scrape page" in skill.triggers

    def test_weather_skill_triggers(self):
        skill = ClawHubWeatherSkill()
        assert "weather" in skill.triggers

    def test_ontology_skill_triggers(self):
        skill = ClawHubOntologySkill()
        assert "knowledge graph" in skill.triggers
        assert "ontology" in skill.triggers

    def test_vetter_skill_triggers(self):
        skill = ClawHubSkillVetterSkill()
        assert "vet skill" in skill.triggers

    def test_web_search_skill_triggers(self):
        skill = ClawHubWebSearchSkill()
        assert "web search" in skill.triggers


# ══════════════════════════════════════════════════════════════
#  Skill Routing Tests
# ══════════════════════════════════════════════════════════════

class TestClawHubSkillRouting:
    """Test ClawHub skills integrate with SkillRouter."""

    def test_router_registers_clawhub_skills(self, skill_router):
        assert len(skill_router.skills) == 8

    def test_router_matches_find_skill(self, skill_router):
        skill = skill_router.match("find skill web scraping")
        assert skill is not None
        assert skill.name == "clawhub_search"

    def test_router_matches_clawhub_search(self, skill_router):
        skill = skill_router.match("clawhub search browser automation")
        assert skill is not None
        assert skill.name == "clawhub_search"

    def test_router_matches_clawhub_status(self, skill_router):
        skill = skill_router.match("clawhub status")
        assert skill is not None
        assert skill.name == "clawhub_status"

    def test_router_matches_summarize(self, skill_router):
        skill = skill_router.match("summarize url https://example.com")
        assert skill is not None
        assert skill.name == "clawhub_summarize"

    def test_router_matches_web_search(self, skill_router):
        skill = skill_router.match("web search python patterns")
        assert skill is not None
        assert skill.name == "clawhub_web_search"

    def test_router_matches_browser(self, skill_router):
        skill = skill_router.match("browse page https://example.com")
        assert skill is not None
        assert skill.name == "clawhub_browser"

    def test_router_matches_weather(self, skill_router):
        skill = skill_router.match("weather in montevideo")
        assert skill is not None
        assert skill.name == "clawhub_weather"

    def test_router_matches_ontology(self, skill_router):
        skill = skill_router.match("knowledge graph create entity")
        assert skill is not None
        assert skill.name == "clawhub_ontology"

    def test_router_matches_vetter(self, skill_router):
        skill = skill_router.match("vet skill steipete/summarize")
        assert skill is not None
        assert skill.name == "clawhub_skill_vetter"


# ══════════════════════════════════════════════════════════════
#  Skill Execution Tests (async)
# ══════════════════════════════════════════════════════════════

class TestClawHubSkillExecution:
    """Test ClawHub skill execution (mocked network)."""

    @pytest.mark.asyncio
    async def test_search_skill_empty_query(self, agent):
        msg = InboundMessage(
            channel=ChannelType.CLI,
            sender_id="AZ_PRIME",
            text="find skill",
        )
        skill = ClawHubSearchSkill()
        result = await skill.execute(msg, agent)
        assert not result.success
        assert "specify" in result.reply.lower()

    @pytest.mark.asyncio
    async def test_search_skill_curated_fallback(self, agent):
        skill = ClawHubSearchSkill()
        # Mock client as unavailable so it falls back to curated
        skill._client = MagicMock()
        skill._client.is_available.return_value = False
        msg = InboundMessage(
            channel=ChannelType.CLI,
            sender_id="AZ_PRIME",
            text="find skill browser",
        )
        result = await skill.execute(msg, agent)
        assert result.success
        assert "browser" in result.reply.lower() or "Curated" in result.reply

    @pytest.mark.asyncio
    async def test_status_skill(self, agent):
        skill = ClawHubStatusSkill()
        msg = InboundMessage(
            channel=ChannelType.CLI,
            sender_id="AZ_PRIME",
            text="clawhub status",
        )
        result = await skill.execute(msg, agent)
        assert result.success
        assert "ClawHub Integration Status" in result.reply
        assert result.data["total_curated"] == 24

    @pytest.mark.asyncio
    async def test_summarize_skill_empty(self, agent):
        skill = ClawHubSummarizeSkill()
        skill._client = MagicMock()
        msg = InboundMessage(
            channel=ChannelType.CLI,
            sender_id="AZ_PRIME",
            text="summarize url",
        )
        result = await skill.execute(msg, agent)
        assert not result.success

    @pytest.mark.asyncio
    async def test_summarize_skill_with_target(self, agent):
        skill = ClawHubSummarizeSkill()
        skill._client = MagicMock()
        skill._client.get_skill_readme.return_value = None
        msg = InboundMessage(
            channel=ChannelType.CLI,
            sender_id="AZ_PRIME",
            text="summarize url https://example.com/article",
        )
        result = await skill.execute(msg, agent)
        assert result.success
        assert "steipete/summarize" in result.reply

    @pytest.mark.asyncio
    async def test_weather_skill(self, agent):
        skill = ClawHubWeatherSkill()
        msg = InboundMessage(
            channel=ChannelType.CLI,
            sender_id="AZ_PRIME",
            text="weather in Paris",
        )
        result = await skill.execute(msg, agent)
        assert result.success
        assert "Paris" in result.reply or "weather" in result.reply.lower()

    @pytest.mark.asyncio
    async def test_browser_skill_empty(self, agent):
        skill = ClawHubBrowserSkill()
        msg = InboundMessage(
            channel=ChannelType.CLI,
            sender_id="AZ_PRIME",
            text="browse page",
        )
        result = await skill.execute(msg, agent)
        assert not result.success

    @pytest.mark.asyncio
    async def test_browser_skill_with_url(self, agent):
        skill = ClawHubBrowserSkill()
        msg = InboundMessage(
            channel=ChannelType.CLI,
            sender_id="AZ_PRIME",
            text="browse page https://example.com",
        )
        result = await skill.execute(msg, agent)
        assert result.success
        assert "agent-browser" in result.reply

    @pytest.mark.asyncio
    async def test_ontology_skill_empty(self, agent):
        skill = ClawHubOntologySkill()
        msg = InboundMessage(
            channel=ChannelType.CLI,
            sender_id="AZ_PRIME",
            text="knowledge graph",
        )
        result = await skill.execute(msg, agent)
        assert not result.success

    @pytest.mark.asyncio
    async def test_vetter_skill_with_slug(self, agent):
        skill = ClawHubSkillVetterSkill()
        skill._client = MagicMock()
        skill._client.get_skill.return_value = ClawHubSkillInfo(
            slug="steipete/summarize",
            name="Summarize",
            owner="steipete",
            description="Summarize anything",
            stars=579,
            installs=152000,
        )
        msg = InboundMessage(
            channel=ChannelType.CLI,
            sender_id="AZ_PRIME",
            text="vet skill steipete/summarize",
        )
        result = await skill.execute(msg, agent)
        assert result.success
        assert "579" in result.reply
        assert "152,000" in result.reply


# ══════════════════════════════════════════════════════════════
#  Agent Integration Tests
# ══════════════════════════════════════════════════════════════

class TestClawHubAgentIntegration:
    """Test ClawHub skills are properly wired into the agent."""

    def test_agent_has_clawhub_skills(self, agent):
        """Agent should have ClawHub skills registered."""
        skill_names = [s.name for s in agent.skill_router.skills]
        assert "clawhub_search" in skill_names
        assert "clawhub_status" in skill_names
        assert "clawhub_summarize" in skill_names
        assert "clawhub_web_search" in skill_names
        assert "clawhub_browser" in skill_names
        assert "clawhub_weather" in skill_names
        assert "clawhub_ontology" in skill_names
        assert "clawhub_skill_vetter" in skill_names

    def test_agent_total_skills_with_clawhub(self, agent):
        """Agent should have 22 total skills (14 base + 8 ClawHub)."""
        assert len(agent.skill_router.skills) == 22

    def test_agent_routes_clawhub_search(self, agent):
        skill = agent.skill_router.match("find skill browser")
        assert skill is not None
        assert skill.name == "clawhub_search"

    def test_agent_routes_clawhub_status(self, agent):
        skill = agent.skill_router.match("clawhub status")
        assert skill is not None
        assert skill.name == "clawhub_status"

    @pytest.mark.asyncio
    async def test_agent_process_clawhub_message(self, agent):
        """Full pipeline: message → policy → route → ClawHub skill → result."""
        msg = InboundMessage(
            channel=ChannelType.CLI,
            sender_id="AZ_PRIME",
            sender_name="AZ",
            text="clawhub status",
        )
        result = await agent.process_message(msg)
        assert result.success
        assert result.skill_name == "clawhub_status"
        assert "Integration Status" in result.reply


# ══════════════════════════════════════════════════════════════
#  Config Tests
# ══════════════════════════════════════════════════════════════

class TestClawHubConfig:
    """Test ClawHub config integration."""

    def test_config_has_clawhub_section(self, agent):
        """Agent config should include the clawhub section."""
        assert "clawhub" in agent.config
        assert agent.config["clawhub"]["enabled"] is True

    def test_config_skills_by_layer(self, agent):
        layers = agent.config["clawhub"]["skills_by_layer"]
        assert "brain" in layers
        assert "senses" in layers
        assert "muscles" in layers
        assert "immune" in layers
        assert "regeneration" in layers
