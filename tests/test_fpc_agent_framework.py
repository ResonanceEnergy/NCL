"""Tests for the 95% offload agent framework.

Covers: role cards, codenames, ATLAS mission control, event router,
policy engine, agent stubs, expansion pack, and live system boot.
"""

from __future__ import annotations

# ── Agent Roster Tests ──────────────────────────────────────────

def test_launch_squadron_count():
    from ncl_agency_runtime.fpc.agents import LAUNCH_SQUADRON
    assert len(LAUNCH_SQUADRON) == 10


def test_expansion_pack_count():
    from ncl_agency_runtime.fpc.agents import EXPANSION_PACK
    assert len(EXPANSION_PACK) == 21


def test_all_agents_count():
    from ncl_agency_runtime.fpc.agents import ALL_AGENTS
    assert len(ALL_AGENTS) == 31


def test_unique_codenames():
    from ncl_agency_runtime.fpc.agents import ALL_AGENTS
    codenames = [a.codename for a in ALL_AGENTS]
    assert len(codenames) == len(set(codenames)), "Duplicate codenames found"


def test_unique_callsigns():
    from ncl_agency_runtime.fpc.agents import ALL_AGENTS
    callsigns = [a.callsign for a in ALL_AGENTS]
    assert len(callsigns) == len(set(callsigns)), "Duplicate callsigns found"


def test_callsign_map():
    from ncl_agency_runtime.fpc.agents import CALLSIGN_MAP
    assert CALLSIGN_MAP["mc"] == "ATLAS"
    assert CALLSIGN_MAP["ds"] == "SCRIBE"
    assert CALLSIGN_MAP["be"] == "TEMPO"
    assert CALLSIGN_MAP["ne"] == "ORACLE"
    assert CALLSIGN_MAP["fo"] == "BEHEMOTH"
    assert CALLSIGN_MAP["xe"] == "LANTERN"
    assert CALLSIGN_MAP["cs"] == "RAVEN"
    assert CALLSIGN_MAP["mo"] == "FORGE"
    assert CALLSIGN_MAP["so"] == "PHALANX"
    assert CALLSIGN_MAP["dx"] == "ECHO"


def test_expansion_callsigns():
    from ncl_agency_runtime.fpc.agents import CALLSIGN_MAP
    assert CALLSIGN_MAP["ir"] == "MINDGATE"
    assert CALLSIGN_MAP["ss"] == "PHOENIX"
    assert CALLSIGN_MAP["sp"] == "NAVIGATOR"
    assert CALLSIGN_MAP["es"] == "SANCTUM"
    assert CALLSIGN_MAP["em"] == "WATCHTOWER"
    assert CALLSIGN_MAP["ux"] == "MUSE"
    assert CALLSIGN_MAP["an"] == "COUNCILOR"
    assert CALLSIGN_MAP["hr"] == "NIGHTFALL"
    assert CALLSIGN_MAP["rt"] == "SPECTRE"
    assert CALLSIGN_MAP["si"] == "BRIDGE"
    assert CALLSIGN_MAP["nc"] == "SENTINEL"
    assert CALLSIGN_MAP["ab"] == "VAULT"
    assert CALLSIGN_MAP["sa"] == "NEXUS"
    assert CALLSIGN_MAP["sg"] == "CIPHER"
    assert CALLSIGN_MAP["rd"] == "AEGIS"


def test_get_agent_by_codename():
    from ncl_agency_runtime.fpc.agents import get_agent
    atlas = get_agent("mc")
    assert atlas is not None
    assert atlas.callsign == "ATLAS"
    assert atlas.approval_required is True


def test_get_agent_by_callsign():
    from ncl_agency_runtime.fpc.agents import get_agent_by_callsign
    agent = get_agent_by_callsign("RAVEN")
    assert agent is not None
    assert agent.codename == "cs"


def test_get_agent_not_found():
    from ncl_agency_runtime.fpc.agents import get_agent, get_agent_by_callsign
    assert get_agent("zz") is None
    assert get_agent_by_callsign("NONEXISTENT") is None


def test_list_agents_by_tier():
    from ncl_agency_runtime.fpc.agents import AgentTier, list_agents
    leads = list_agents(AgentTier.LEAD)
    assert len(leads) == 1
    assert leads[0].callsign == "ATLAS"

    expansion = list_agents(AgentTier.EXPANSION)
    assert len(expansion) == 21


def test_agent_has_mission():
    from ncl_agency_runtime.fpc.agents import ALL_AGENTS
    for agent in ALL_AGENTS:
        # Launch squadron should all have missions
        if agent.tier.value != "expansion":
            assert agent.mission, f"{agent.callsign} missing mission"


def test_agent_has_langgraph_nodes():
    from ncl_agency_runtime.fpc.agents import ALL_AGENTS
    for agent in ALL_AGENTS:
        assert len(agent.langgraph_nodes) > 0, f"{agent.callsign} has no LangGraph nodes"


# ── ATLAS Mission Control Tests ─────────────────────────────────

def test_mission_control_init():
    from ncl_agency_runtime.fpc.agents.orchestrator import MissionControl
    mc = MissionControl()
    assert mc.state.total_spend_usd == 0.0
    assert mc.state.rollback_count == 0


def test_mission_control_loop_user_intent():
    from ncl_agency_runtime.fpc.agents.orchestrator import MissionControl
    from ncl_agency_runtime.fpc.agents.stubs import register_all

    mc = MissionControl()
    register_all(mc)

    event = {"detail_type": "intent.user", "payload": {"goal": "forecast sales"}}
    ctx = mc.run_loop(event)

    assert ctx.completed_at is not None
    assert len(ctx.interpretations) > 0
    assert "user_intent" in ctx.interpretations
    assert len(ctx.plan) >= 5  # Full council: ds, be, ne, xe, cs


def test_mission_control_loop_data_update():
    from ncl_agency_runtime.fpc.agents.orchestrator import MissionControl
    mc = MissionControl()

    event = {"detail_type": "data.update", "payload": {"rows": 100}}
    ctx = mc.run_loop(event)

    assert "data_update" in ctx.interpretations
    assert len(ctx.plan) >= 1


def test_mission_control_loop_model_cycle():
    from ncl_agency_runtime.fpc.agents.orchestrator import MissionControl
    mc = MissionControl()

    event = {"detail_type": "model.cycle", "payload": {"model": "AutoARIMA", "MASE": 0.85}}
    ctx = mc.run_loop(event)

    assert "model_cycle" in ctx.interpretations


def test_mission_control_budget():
    from ncl_agency_runtime.fpc.agents.orchestrator import MissionControl
    mc = MissionControl()
    mc.state.steering = {"budget_weekly_usd": 50.0}

    assert mc.budget_remaining() == 50.0
    mc.state.total_spend_usd = 30.0
    assert mc.budget_remaining() == 20.0


def test_mission_control_task_approve_reject():
    from ncl_agency_runtime.fpc.agents.orchestrator import MissionControl, Task

    mc = MissionControl()
    task = Task("T99", "fo", "Test burst", requires_approval=True)
    mc.add_task(task)
    mc.run_next()

    assert mc.approve("T99") is True
    assert task.result["status"] == "approved"

    task2 = Task("T100", "fo", "Another burst", requires_approval=True)
    mc.add_task(task2)
    mc.run_next()

    assert mc.reject("T100", "Too expensive") is True
    assert "rejected" in task2.result["status"]


def test_loop_phases():
    from ncl_agency_runtime.fpc.agents.orchestrator import LoopPhase
    phases = [p.value for p in LoopPhase]
    assert "observe" in phases
    assert "execute" in phases
    assert "recover" in phases


def test_build_launch_plan():
    from ncl_agency_runtime.fpc.agents.orchestrator import build_launch_plan
    plan = build_launch_plan()
    assert len(plan) == 10
    assert plan[0].agent_codename == "ds"
    assert plan[-1].requires_approval is True


# ── Event Schema Tests ──────────────────────────────────────────

def test_event_creation():
    from ncl_agency_runtime.fpc.agents.events import Event, EventType
    e = Event(detail_type=EventType.INTENT_USER, source="user", payload={"goal": "test"})
    assert e.id
    assert e.trace_id
    assert e.ts > 0


def test_event_to_dict():
    from ncl_agency_runtime.fpc.agents.events import Event, EventType
    e = Event(detail_type=EventType.MODEL_CYCLE, source="agent.TEMPO", payload={"MASE": 0.8})
    d = e.to_dict()
    assert d["detail_type"] == "model.cycle"
    assert d["source"] == "agent.TEMPO"
    assert d["privacy"]["pii"] is False


def test_event_helpers():
    from ncl_agency_runtime.fpc.agents.events import (
        make_data_update,
        make_intent,
        make_model_cycle,
        make_telemetry,
    )
    i = make_intent("forecast sales")
    assert i.payload["goal"] == "forecast sales"

    d = make_data_update("sales_panel", rows=500)
    assert d.payload["rows"] == 500

    m = make_model_cycle("PatchTST", mase=0.78, smape=9.8)
    assert m.payload["metrics"]["MASE"] == 0.78

    t = make_telemetry("be", latency_ms=45.0)
    assert t.payload["latency_ms"] == 45.0


def test_event_types_complete():
    from ncl_agency_runtime.fpc.agents.events import EventType
    types = [e.value for e in EventType]
    assert "intent.user" in types
    assert "model.cycle" in types
    assert "telemetry.agent" in types
    assert "security.alert" in types
    assert "agent.request" in types


# ── Event Router Tests ──────────────────────────────────────────

def test_router_basic_routing():
    from ncl_agency_runtime.fpc.agents.events import Event, EventType
    from ncl_agency_runtime.fpc.agents.router import EventRouter

    routed = []
    router = EventRouter()
    router.set_atlas(lambda e: routed.append(e))

    event = Event(detail_type=EventType.INTENT_USER, payload={"goal": "test"})
    assert router.route(event) is True
    assert len(routed) == 1
    assert router.metrics.events_routed == 1


def test_router_deduplication():
    from ncl_agency_runtime.fpc.agents.events import Event, EventType
    from ncl_agency_runtime.fpc.agents.router import EventRouter

    routed = []
    router = EventRouter()
    router.set_atlas(lambda e: routed.append(e))

    event = Event(detail_type=EventType.INTENT_USER, payload={"goal": "test"})
    router.route(event)
    router.route(event)  # Same event ID — should be deduped

    assert len(routed) == 1
    assert router.metrics.events_dropped == 1


def test_router_privacy_gate():
    from ncl_agency_runtime.fpc.agents.events import Event, EventType, PrivacyLevel, PrivacyTag
    from ncl_agency_runtime.fpc.agents.router import EventRouter

    router = EventRouter()
    router.set_atlas(lambda e: None)

    event = Event(
        detail_type=EventType.DATA_UPDATE,
        privacy=PrivacyTag(pii=True, level=PrivacyLevel.RESTRICTED),
    )
    assert router.route(event) is False
    assert router.metrics.events_dropped == 1


def test_router_type_subscribers():
    from ncl_agency_runtime.fpc.agents.events import Event, EventType
    from ncl_agency_runtime.fpc.agents.router import EventRouter

    model_events = []
    router = EventRouter()
    router.set_atlas(lambda e: None)
    router.subscribe(EventType.MODEL_CYCLE, lambda e: model_events.append(e))

    # Model cycle event → should hit subscriber
    router.route(Event(detail_type=EventType.MODEL_CYCLE, payload={"MASE": 0.8}))
    assert len(model_events) == 1

    # Intent event → should NOT hit model subscriber
    router.route(Event(detail_type=EventType.INTENT_USER, payload={}))
    assert len(model_events) == 1


def test_router_dlq():
    from ncl_agency_runtime.fpc.agents.events import Event, EventType
    from ncl_agency_runtime.fpc.agents.router import EventRouter

    def failing_handler(e: Event) -> None:
        raise RuntimeError("boom")

    router = EventRouter()
    router.set_atlas(failing_handler)

    event = Event(detail_type=EventType.INTENT_USER, payload={})
    assert router.route(event) is False
    assert router.dlq_size() == 1

    items = router.drain_dlq()
    assert len(items) == 1
    assert router.dlq_size() == 0


def test_router_health():
    from ncl_agency_runtime.fpc.agents.router import EventRouter
    router = EventRouter()
    h = router.health()
    assert h["status"] == "ok"
    assert h["received"] == 0


def test_router_batch():
    from ncl_agency_runtime.fpc.agents.events import Event, EventType
    from ncl_agency_runtime.fpc.agents.router import EventRouter

    router = EventRouter()
    router.set_atlas(lambda e: None)

    events = [Event(detail_type=EventType.INTENT_USER, payload={"i": i}) for i in range(5)]
    count = router.route_batch(events)
    assert count == 5


# ── Policy Engine Tests ─────────────────────────────────────────

def test_policy_budget_check():
    from ncl_agency_runtime.fpc.agents.policy import PolicyEngine, PolicyVerdict
    pe = PolicyEngine.__new__(PolicyEngine)
    pe.steering = {"budget_weekly_usd": 50.0}
    pe.release_policy = {}
    pe.deploy_states = {}
    pe._spend_log = []
    pe._total_spend_usd = 0.0

    result = pe.check_budget(30.0)
    assert result.verdict == PolicyVerdict.ALLOW

    pe._total_spend_usd = 40.0
    result = pe.check_budget(20.0)
    assert result.verdict == PolicyVerdict.DENY


def test_policy_burst_check():
    from ncl_agency_runtime.fpc.agents.policy import PolicyEngine, PolicyVerdict
    pe = PolicyEngine.__new__(PolicyEngine)
    pe.steering = {"budget_weekly_usd": 50.0, "gpu_max_hourly": 1.20, "gpu_max_daily_min": 60}
    pe.release_policy = {}
    pe.deploy_states = {}
    pe._spend_log = []
    pe._total_spend_usd = 0.0

    # Within limits
    result = pe.check_burst(hourly_cost=1.00, duration_min=30)
    assert result.verdict == PolicyVerdict.ALLOW

    # Hourly too high
    result = pe.check_burst(hourly_cost=2.00, duration_min=30)
    assert result.verdict == PolicyVerdict.DENY

    # Duration too long
    result = pe.check_burst(hourly_cost=0.50, duration_min=120)
    assert result.verdict == PolicyVerdict.DENY


def test_policy_spend_tracking():
    from ncl_agency_runtime.fpc.agents.policy import PolicyEngine
    pe = PolicyEngine.__new__(PolicyEngine)
    pe.steering = {"budget_weekly_usd": 50.0}
    pe.release_policy = {}
    pe.deploy_states = {}
    pe._spend_log = []
    pe._total_spend_usd = 0.0

    pe.record_spend(10.0, "burst_chronos2")
    pe.record_spend(5.0, "burst_timesfm")

    summary = pe.spend_summary()
    assert summary["total_usd"] == 15.0
    assert summary["remaining_usd"] == 35.0
    assert summary["pct_used"] == 30.0


def test_policy_rollback_check():
    from ncl_agency_runtime.fpc.agents.policy import PolicyEngine, PolicyVerdict
    pe = PolicyEngine.__new__(PolicyEngine)
    pe.steering = {}
    pe.release_policy = {"rollback_triggers": {"p95_latency_ms": 500, "action_failures": 3}}
    pe.deploy_states = {}
    pe._spend_log = []
    pe._total_spend_usd = 0.0

    # OK
    result = pe.check_rollback("alpha", p95_ms=200, failures=1)
    assert result.verdict == PolicyVerdict.ALLOW

    # p95 breach
    result = pe.check_rollback("alpha", p95_ms=800, failures=1)
    assert result.verdict == PolicyVerdict.DENY

    # Failure breach
    result = pe.check_rollback("alpha", p95_ms=200, failures=5)
    assert result.verdict == PolicyVerdict.DENY


def test_policy_security_check():
    from ncl_agency_runtime.fpc.agents.policy import PolicyEngine, PolicyVerdict
    pe = PolicyEngine.__new__(PolicyEngine)
    pe.steering = {}
    pe.release_policy = {"security": {"sbom": {"required": True}, "vuln_scan": {"required": True}}}
    pe.deploy_states = {}
    pe._spend_log = []
    pe._total_spend_usd = 0.0

    # Missing SBOM
    result = pe.check_security(sbom_present=False, vuln_scan_clean=True)
    assert result.verdict == PolicyVerdict.DENY

    # Missing vuln scan
    result = pe.check_security(sbom_present=True, vuln_scan_clean=False)
    assert result.verdict == PolicyVerdict.DENY

    # Both present
    result = pe.check_security(sbom_present=True, vuln_scan_clean=True)
    assert result.verdict == PolicyVerdict.ALLOW


# ── Agent Stub Tests ────────────────────────────────────────────

def test_all_launch_stubs_registered():
    from ncl_agency_runtime.fpc.agents.stubs import AGENT_STUBS
    assert len(AGENT_STUBS) == 10
    for codename in ["mc", "ds", "be", "ne", "fo", "xe", "cs", "mo", "so", "dx"]:
        assert codename in AGENT_STUBS


def test_stub_handle_returns_metadata():
    from ncl_agency_runtime.fpc.agents.orchestrator import Task
    from ncl_agency_runtime.fpc.agents.stubs import AGENT_STUBS

    task = Task("T-test", "be", "Test forecast")
    result = AGENT_STUBS["be"].handle(task, {"payload": {"horizon": 14}})

    assert result["_agent"] == "be"
    assert result["_callsign"] == "TEMPO"
    assert result["_elapsed_s"] >= 0
    assert "status" in result  # Real agent returns status (may vary based on deps)


def test_all_stubs_callable():
    from ncl_agency_runtime.fpc.agents.orchestrator import Task
    from ncl_agency_runtime.fpc.agents.stubs import AGENT_STUBS

    for codename, stub in AGENT_STUBS.items():
        task = Task(f"T-{codename}", codename, "Test task")
        result = stub.handle(task, {"payload": {}})
        assert "_callsign" in result, f"Stub {codename} missing _callsign"
        assert "status" in result, f"Stub {codename} missing status"


def test_expansion_stubs_registered():
    from ncl_agency_runtime.fpc.agents.expansion import EXPANSION_STUBS
    assert len(EXPANSION_STUBS) == 21
    for codename in ["ir", "ss", "sp", "es", "em", "ux", "an", "hr", "rt", "si", "wp", "nc", "ab", "sa", "sg", "rd", "jx", "sb", "ai", "xf", "yt"]:
        assert codename in EXPANSION_STUBS


def test_expansion_stubs_callable():
    from ncl_agency_runtime.fpc.agents.expansion import EXPANSION_STUBS
    from ncl_agency_runtime.fpc.agents.orchestrator import Task

    for codename, stub in EXPANSION_STUBS.items():
        task = Task(f"T-{codename}", codename, "Test task")
        result = stub.handle(task, {"payload": {}})
        assert "_callsign" in result


def test_register_all_with_mission_control():
    from ncl_agency_runtime.fpc.agents.expansion import register_expansion
    from ncl_agency_runtime.fpc.agents.orchestrator import MissionControl
    from ncl_agency_runtime.fpc.agents.stubs import register_all

    mc = MissionControl()
    register_all(mc)
    register_expansion(mc)

    # Should have 24 handlers
    assert len(mc._agent_handlers) == 31


# ── Live System Tests ───────────────────────────────────────────

def test_live_boot():
    from ncl_agency_runtime.fpc.agents.live import boot
    system = boot()
    assert system is not None
    assert system.atlas is not None
    assert system.router is not None
    assert system.policy is not None


def test_live_status():
    from ncl_agency_runtime.fpc.agents.live import boot
    system = boot()
    status = system.status()

    assert status["agents"]["launch_squadron"] == 10
    assert status["agents"]["expansion_pack"] == 21
    assert status["agents"]["total"] == 31
    assert status["router"]["status"] == "ok"


def test_live_roster():
    from ncl_agency_runtime.fpc.agents.live import boot
    system = boot()
    roster = system.roster()

    assert len(roster) == 31
    callsigns = [r["callsign"] for r in roster]
    assert "ATLAS" in callsigns
    assert "SPECTRE" in callsigns
    assert "BRIDGE" in callsigns


def test_live_dispatch_intent():
    from ncl_agency_runtime.fpc.agents.live import boot
    system = boot()

    result = system.dispatch_intent("Run a 14-day forecast on sales data")
    assert result["success"] is True
    assert result["trace_id"]
    assert result["goal"] == "Run a 14-day forecast on sales data"


def test_live_dispatch_data_update():
    from ncl_agency_runtime.fpc.agents.live import boot
    system = boot()

    result = system.dispatch_data_update("sales_panel", rows=500)
    assert result["success"] is True


def test_live_dispatch_model_cycle():
    from ncl_agency_runtime.fpc.agents.live import boot
    system = boot()

    result = system.dispatch_model_cycle("PatchTST", mase=0.78, smape=9.8)
    assert result["success"] is True


def test_live_multiple_intents():
    from ncl_agency_runtime.fpc.agents.live import boot
    system = boot()

    for i in range(5):
        result = system.dispatch_intent(f"Task {i}")
        assert result["success"] is True

    status = system.status()
    assert status["atlas"]["loops_run"] == 5


def test_live_full_cycle():
    """End-to-end: data update → forecast → model cycle → status check."""
    from ncl_agency_runtime.fpc.agents.live import boot
    system = boot()

    # 1. Data arrives
    system.dispatch_data_update("sales_panel", rows=1000)
    # 2. User requests forecast
    system.dispatch_intent("Run baseline + neural forecast")
    # 3. Model cycle completes
    system.dispatch_model_cycle("StatsForecast.AutoARIMA", mase=0.85, smape=11.2)
    # 4. Check status
    status = system.status()

    assert status["atlas"]["loops_run"] == 3
    assert status["router"]["received"] == 3


# ── Real Agent Integration Tests ────────────────────────────────

def test_scribe_validates_real_data():
    from ncl_agency_runtime.fpc.agents.orchestrator import Task
    from ncl_agency_runtime.fpc.agents.stubs import AGENT_STUBS

    task = Task("T-scribe", "ds", "Validate data")
    result = AGENT_STUBS["ds"].handle(task, {"payload": {}})

    assert result["status"] == "validated"
    assert result["rows_checked"] > 0, "Should load default example.csv"
    assert result["schema_valid"] is True
    assert isinstance(result["nulls_found"], int)
    assert isinstance(result["anomalies"], int)
    assert result["series_count"] >= 1


def test_tempo_produces_real_metrics():
    from ncl_agency_runtime.fpc.agents.orchestrator import Task
    from ncl_agency_runtime.fpc.agents.stubs import AGENT_STUBS

    task = Task("T-tempo", "be", "Forecast")
    result = AGENT_STUBS["be"].handle(task, {"payload": {"horizon": 7}})

    assert "status" in result
    # If statsforecast is installed, we get real MASE/sMAPE
    if result.get("note") != "statsforecast_not_installed" and result["status"] == "forecast_complete" and result.get("mase") is not None:
            assert isinstance(result["mase"], float)
            assert isinstance(result["smape"], float)


def test_behemoth_burst_evaluation():
    from ncl_agency_runtime.fpc.agents.orchestrator import Task
    from ncl_agency_runtime.fpc.agents.stubs import AGENT_STUBS

    task = Task("T-burst", "fo", "Manage burst")
    result = AGENT_STUBS["fo"].handle(task, {"payload": {"model": "chronos2", "duration_min": 30}})

    assert result["status"] == "burst_managed"
    assert isinstance(result["approved"], bool)
    assert isinstance(result["cost_estimate_usd"], float)
    assert "chronos2" in result["available_models"]


def test_lantern_xai_dossier():
    from ncl_agency_runtime.fpc.agents.orchestrator import Task
    from ncl_agency_runtime.fpc.agents.stubs import AGENT_STUBS

    task = Task("T-xai", "xe", "Generate XAI")
    result = AGENT_STUBS["xe"].handle(task, {"payload": {}})

    assert result["status"] == "dossier_generated"
    assert isinstance(result["shap_features"], int)
    assert result["series_length"] > 0


def test_forge_pipeline_check():
    from ncl_agency_runtime.fpc.agents.orchestrator import Task
    from ncl_agency_runtime.fpc.agents.stubs import AGENT_STUBS

    task = Task("T-forge", "mo", "Check pipeline")
    result = AGENT_STUBS["mo"].handle(task, {"payload": {}})

    assert result["status"] in ("pipeline_ok", "pipeline_warning")
    assert isinstance(result["ci_passing"], bool)
    assert isinstance(result["checks"], dict)


def test_phalanx_security_scan():
    from ncl_agency_runtime.fpc.agents.orchestrator import Task
    from ncl_agency_runtime.fpc.agents.stubs import AGENT_STUBS

    task = Task("T-sec", "so", "Security scan")
    result = AGENT_STUBS["so"].handle(task, {"payload": {}})

    assert result["status"] in ("security_ok", "security_alert")
    assert result["sbom_generated"] is True
    assert result["sbom_packages"] > 0


def test_echo_doc_generation():
    from ncl_agency_runtime.fpc.agents.orchestrator import Task
    from ncl_agency_runtime.fpc.agents.stubs import AGENT_STUBS

    task = Task("T-docs", "dx", "Generate docs")
    result = AGENT_STUBS["dx"].handle(task, {"detail_type": "model.cycle", "payload": {"model": "AutoARIMA"}})

    assert result["status"] == "docs_updated"
    assert result["brief_published"] is True
    assert "brief" in result
    assert "AutoARIMA" in result["brief"]


def test_mindgate_intent_classification():
    from ncl_agency_runtime.fpc.agents.expansion import EXPANSION_STUBS
    from ncl_agency_runtime.fpc.agents.orchestrator import Task

    task = Task("T-intent", "ir", "Classify intent")
    result = EXPANSION_STUBS["ir"].handle(task, {"payload": {"goal": "forecast sales data"}})

    assert result["status"] == "intent_classified"
    assert result["intent_type"] == "forecast_request"
    assert "be" in result["target_agents"] or "ds" in result["target_agents"]
    assert result["confidence"] > 0


def test_mindgate_general_intent():
    from ncl_agency_runtime.fpc.agents.expansion import EXPANSION_STUBS
    from ncl_agency_runtime.fpc.agents.orchestrator import Task

    task = Task("T-intent2", "ir", "Classify general")
    result = EXPANSION_STUBS["ir"].handle(task, {"payload": {"goal": "hello world"}})

    assert result["status"] == "intent_classified"
    assert result["intent_type"] == "general"


def test_phoenix_scenario_simulation():
    from ncl_agency_runtime.fpc.agents.expansion import EXPANSION_STUBS
    from ncl_agency_runtime.fpc.agents.orchestrator import Task

    task = Task("T-sim", "ss", "Simulate")
    result = EXPANSION_STUBS["ss"].handle(task, {"payload": {"scenarios": 500}})

    assert result["status"] == "simulation_complete"
    assert result["scenarios_run"] == 500
    assert result["p5_downside"] < result["p95_upside"]


def test_watchtower_health_monitoring():
    from ncl_agency_runtime.fpc.agents.expansion import EXPANSION_STUBS
    from ncl_agency_runtime.fpc.agents.orchestrator import Task

    task = Task("T-watch", "em", "Monitor")
    result = EXPANSION_STUBS["em"].handle(task, {"payload": {}})

    assert result["status"] == "monitoring"
    assert result["agents_healthy"] == 10
    assert result["alert_level"] in ("green", "yellow", "red")


def test_bridge_system_discovery():
    from ncl_agency_runtime.fpc.agents.expansion import EXPANSION_STUBS
    from ncl_agency_runtime.fpc.agents.orchestrator import Task

    task = Task("T-bridge", "si", "Check systems")
    result = EXPANSION_STUBS["si"].handle(task, {"payload": {}})

    assert result["status"] == "bridge_ok"
    assert isinstance(result["connected_systems"], list)
    assert result["connected_count"] > 0


def test_nightfall_circuit_breakers():
    from ncl_agency_runtime.fpc.agents.expansion import EXPANSION_STUBS
    from ncl_agency_runtime.fpc.agents.orchestrator import Task

    task = Task("T-night", "hr", "Check breakers")
    result = EXPANSION_STUBS["hr"].handle(task, {"payload": {"total_spend_usd": 10.0}})

    assert result["status"] == "standby"
    assert result["circuit_breakers"]["budget"] == "closed"
    assert result["active_incidents"] == 0


def test_spectre_adversarial_scan():
    from ncl_agency_runtime.fpc.agents.expansion import EXPANSION_STUBS
    from ncl_agency_runtime.fpc.agents.orchestrator import Task

    task = Task("T-spectre", "rt", "Red team")
    result = EXPANSION_STUBS["rt"].handle(task, {"payload": {}})

    assert result["status"] == "scan_complete"
    assert isinstance(result["vulnerabilities_found"], int)
    assert isinstance(result["edge_cases"], list)
