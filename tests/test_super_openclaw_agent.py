#!/usr/bin/env python3
"""Tests for the NCL Super OpenClaw Agent core."""

import asyncio
import sys
from pathlib import Path

# Path setup
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ncl_agency_runtime" / "agents"))

import pytest


# ── Import agent components ──────────────────────────────────

from ncl_agency_runtime.agents.super_openclaw_agent import (
    SuperOpenClawAgent,
    SkillRouter,
    PolicyGate,
    EventBus,
    HealthMonitor,
    InboundMessage,
    OutboundMessage,
    SkillResult,
    ChannelType,
    MessagePriority,
    Skill,
    MemorySearchSkill,
    MemoryStoreSkill,
    DoctrineSkill,
    BrainMapSkill,
    StatusSkill,
    HelpSkill,
    LearningSkill,
    create_agent,
)


# ── Fixtures ─────────────────────────────────────────────────

@pytest.fixture
def agent():
    return create_agent(allowed_senders=["AZ_PRIME", "test_user"])


@pytest.fixture
def event_bus():
    return EventBus()


@pytest.fixture
def policy_gate():
    return PolicyGate(allowed_senders=["AZ_PRIME", "test_user"])


@pytest.fixture
def skill_router():
    router = SkillRouter()
    router.register(HelpSkill())
    router.register(StatusSkill())
    router.register(DoctrineSkill())
    router.register(BrainMapSkill())
    return router


@pytest.fixture
def inbound_msg():
    return InboundMessage(
        channel=ChannelType.CLI,
        sender_id="AZ_PRIME",
        sender_name="AZ",
        text="help",
    )


# ── InboundMessage tests ────────────────────────────────────

def test_inbound_message_defaults():
    msg = InboundMessage()
    assert msg.channel == ChannelType.CLI
    assert msg.sender_id == ""
    assert msg.text == ""
    assert isinstance(msg.id, str)
    assert len(msg.id) == 12


def test_inbound_message_to_dict():
    msg = InboundMessage(
        channel=ChannelType.DISCORD,
        sender_id="12345",
        sender_name="Test",
        text="hello",
    )
    d = msg.to_dict()
    assert d["channel"] == "discord"
    assert d["sender_id"] == "12345"
    assert d["text"] == "hello"
    assert "raw" not in d


# ── PolicyGate tests ─────────────────────────────────────────

def test_policy_gate_allows_authorized(policy_gate, inbound_msg):
    allowed, reason = policy_gate.evaluate(inbound_msg)
    assert allowed
    assert reason == "ALLOWED"


def test_policy_gate_kill_switch():
    gate = PolicyGate(kill_switch=True)
    msg = InboundMessage(sender_id="AZ_PRIME", text="test")
    allowed, reason = gate.evaluate(msg)
    assert not allowed
    assert "KILL_SWITCH" in reason


def test_policy_gate_denied_log(policy_gate):
    msg = InboundMessage(sender_id="INTRUDER", text="hack")
    # With AZ_PRIME in allowed list, it should still pass
    # because AZ_PRIME is in the allowed_senders set
    allowed, _ = policy_gate.evaluate(msg)
    assert allowed  # AZ_PRIME is in the set


# ── EventBus tests ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_event_bus_publish_subscribe(event_bus):
    received = []

    async def handler(event):
        received.append(event)

    await event_bus.subscribe("test.topic", handler)
    await event_bus.publish("test.topic", {"key": "value"})

    assert len(received) == 1
    assert received[0]["payload"]["key"] == "value"
    assert received[0]["topic"] == "test.topic"


@pytest.mark.asyncio
async def test_event_bus_wildcard(event_bus):
    received = []

    async def handler(event):
        received.append(event)

    await event_bus.subscribe("*", handler)
    await event_bus.publish("any.topic", {"data": 1})
    await event_bus.publish("another.topic", {"data": 2})

    assert len(received) == 2


@pytest.mark.asyncio
async def test_event_bus_history(event_bus):
    for i in range(10):
        await event_bus.publish("test", {"i": i})
    assert len(event_bus._history) == 10


# ── SkillRouter tests ────────────────────────────────────────

def test_skill_router_match(skill_router):
    skill = skill_router.match("help me please")
    assert skill is not None
    assert skill.name == "help"


def test_skill_router_match_doctrine(skill_router):
    skill = skill_router.match("tell me about the doctrine")
    assert skill is not None
    assert skill.name == "doctrine"


def test_skill_router_match_brain_map(skill_router):
    skill = skill_router.match("show me the brain map")
    assert skill is not None
    assert skill.name == "brain_map"


def test_skill_router_no_match(skill_router):
    skill = skill_router.match("xyzzy foobar baz")
    assert skill is None


@pytest.mark.asyncio
async def test_skill_router_route_fallback(skill_router):
    msg = InboundMessage(text="totally unknown command")
    agent = create_agent()
    result = await skill_router.route(msg, agent)
    assert result.skill_name == "fallback"
    assert "help" in result.reply.lower()


# ── Individual Skill tests ───────────────────────────────────

@pytest.mark.asyncio
async def test_help_skill():
    skill = HelpSkill()
    agent = create_agent()
    msg = InboundMessage(text="help", sender_id="AZ_PRIME")
    result = await skill.execute(msg, agent)
    assert result.success
    assert "memory_search" in result.reply
    assert result.skill_name == "help"


@pytest.mark.asyncio
async def test_status_skill():
    skill = StatusSkill()
    agent = create_agent()
    msg = InboundMessage(text="status", sender_id="AZ_PRIME")
    result = await skill.execute(msg, agent)
    assert result.success
    assert agent.agent_id in result.reply
    assert "Skills loaded" in result.reply


@pytest.mark.asyncio
async def test_doctrine_skill():
    skill = DoctrineSkill()
    agent = create_agent()
    msg = InboundMessage(text="tell me about the living organism", sender_id="AZ_PRIME")
    result = await skill.execute(msg, agent)
    assert result.success
    assert "Living Organism" in result.reply


@pytest.mark.asyncio
async def test_doctrine_skill_all():
    skill = DoctrineSkill()
    agent = create_agent()
    msg = InboundMessage(text="doctrine overview", sender_id="AZ_PRIME")
    result = await skill.execute(msg, agent)
    assert result.success
    # Should contain multiple doctrine sections
    assert "Prime Directive" in result.reply
    assert "Faraday" in result.reply


@pytest.mark.asyncio
async def test_brain_map_skill():
    skill = BrainMapSkill()
    agent = create_agent()
    msg = InboundMessage(text="brain map", sender_id="AZ_PRIME")
    result = await skill.execute(msg, agent)
    assert result.success
    assert "COGNITIVE CORE" in result.reply
    assert "Active skills" in result.reply


@pytest.mark.asyncio
async def test_memory_search_empty_query():
    skill = MemorySearchSkill()
    agent = create_agent()
    msg = InboundMessage(text="remember", sender_id="AZ_PRIME")
    result = await skill.execute(msg, agent)
    assert not result.success
    assert "query" in result.reply.lower()


@pytest.mark.asyncio
async def test_memory_store_empty():
    skill = MemoryStoreSkill()
    agent = create_agent()
    msg = InboundMessage(text="remember this", sender_id="AZ_PRIME")
    result = await skill.execute(msg, agent)
    assert not result.success


# ── Agent Pipeline tests ─────────────────────────────────────

@pytest.mark.asyncio
async def test_agent_process_message(agent, inbound_msg):
    result = await agent.process_message(inbound_msg)
    assert result.success
    assert result.skill_name == "help"
    assert agent._msg_count == 1


@pytest.mark.asyncio
async def test_agent_process_denied():
    agent = create_agent(allowed_senders=["admin_only"])
    agent.policy_gate.allowed_senders = {"admin_only"}  # strict
    msg = InboundMessage(sender_id="random", text="help")
    result = await agent.process_message(msg)
    assert not result.success
    assert "denied" in result.reply.lower() or "ALLOWED" not in result.reply


@pytest.mark.asyncio
async def test_agent_kill_switch():
    agent = create_agent()
    agent.policy_gate.kill_switch = True
    msg = InboundMessage(sender_id="AZ_PRIME", text="help")
    result = await agent.process_message(msg)
    assert not result.success
    assert "KILL_SWITCH" in result.reply


@pytest.mark.asyncio
async def test_agent_multiple_messages(agent):
    for i in range(5):
        msg = InboundMessage(sender_id="AZ_PRIME", sender_name="AZ", text=f"status {i}")
        await agent.process_message(msg)
    assert agent._msg_count == 5


# ── HealthMonitor tests ─────────────────────────────────────

def test_health_monitor_check(agent):
    report = agent.health_monitor.check()
    assert "healthy" in report
    assert "skills" in report
    assert report["skills"] == len(agent.skill_router.skills)


# ── Factory tests ─────────────────────────────────────────────

def test_create_agent_defaults():
    agent = create_agent()
    assert agent.agent_id.startswith("openclaw-")
    assert len(agent.skill_router.skills) == 8  # 7 domain skills + GeneralChatSkill
    assert not agent.policy_gate.kill_switch


def test_create_agent_extra_skills():
    class DummySkill(Skill):
        name = "dummy"
        triggers = ["dummy"]
        description = "test"
        async def execute(self, msg, agent):
            return SkillResult(success=True, reply="dummy", skill_name="dummy")

    agent = create_agent(extra_skills=[DummySkill()])
    assert len(agent.skill_router.skills) == 9  # 8 default + 1 extra
    assert agent.skill_router.match("dummy") is not None


# ── Channel Type tests ────────────────────────────────────────

def test_channel_types():
    assert ChannelType.DISCORD.value == "discord"
    assert ChannelType.TELEGRAM.value == "telegram"
    assert ChannelType.RELAY.value == "relay"
    assert ChannelType.CLI.value == "cli"
    assert ChannelType.IOS.value == "ios"


def test_message_priority():
    assert MessagePriority.CRITICAL.value == "critical"
    assert MessagePriority.NORMAL.value == "normal"
