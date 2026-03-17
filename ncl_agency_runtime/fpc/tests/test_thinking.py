#!/usr/bin/env python3
"""Tests for ICM Thinking Layer integration (ICM + OpenClaw + Ralphy)."""

import json
import tempfile
from pathlib import Path

# ── ICM Pipeline ─────────────────────────────────────────────────────────────


class TestICMPipeline:
    def _make_workspace(self, tmp: Path):
        """Create a minimal ICM workspace for testing."""
        stages_dir = tmp / "stages"
        for stage in ["01-data-ingestion", "02-forecasting", "03-council-deliberation",
                       "04-consensus", "05-delivery"]:
            s = stages_dir / stage
            s.mkdir(parents=True, exist_ok=True)
            (s / "output").mkdir(exist_ok=True)
            (s / "CONTEXT.md").write_text(
                f"# Stage: {stage}\n\n## Inputs\n| Item | Source |\n|---|---|\n"
                f"| data | previous |\n\n## Process\n1. Execute\n\n"
                f"## Outputs\n| Artifact | Format |\n|---|---|\n| result | JSON |\n\n"
                f"## Audit\n| Check | Rule |\n|---|---|\n| valid | must pass |\n",
                encoding="utf-8",
            )
        return tmp

    def test_pipeline_init(self):
        from ncl_agency_runtime.fpc.icm_pipeline import ICMPipeline
        with tempfile.TemporaryDirectory() as tmp:
            ws = self._make_workspace(Path(tmp))
            pipeline = ICMPipeline(workspace_root=ws)
            assert pipeline.workspace_root == ws

    def test_pipeline_status(self):
        from ncl_agency_runtime.fpc.icm_pipeline import ICMPipeline
        with tempfile.TemporaryDirectory() as tmp:
            ws = self._make_workspace(Path(tmp))
            pipeline = ICMPipeline(workspace_root=ws)
            status = pipeline.pipeline_status()
            assert "01-data-ingestion" in status
            assert "05-delivery" in status

    def test_stage_contract_parsing(self):
        from ncl_agency_runtime.fpc.icm_pipeline import ICMPipeline
        with tempfile.TemporaryDirectory() as tmp:
            ws = self._make_workspace(Path(tmp))
            pipeline = ICMPipeline(workspace_root=ws)
            contract = pipeline.get_stage_contract("01-data-ingestion")
            assert contract is not None
            assert contract.stage_name == "01-data-ingestion"
            assert len(contract.inputs) >= 1
            assert len(contract.outputs) >= 1
            assert len(contract.process_steps) >= 1

    def test_stage_result_dataclass(self):
        from ncl_agency_runtime.fpc.icm_pipeline import StageResult
        result = StageResult(stage="01-data-ingestion", status="completed")
        assert result.stage == "01-data-ingestion"
        assert result.status == "completed"
        assert result.audit_passed is True
        assert result.timestamp  # auto-filled

    def test_pipeline_run_dataclass(self):
        from ncl_agency_runtime.fpc.icm_pipeline import PipelineRun
        run = PipelineRun(run_id="", topic="test", horizon="1-3 months")
        assert run.run_id.startswith("run_")
        assert run.topic == "test"
        assert run.started_at

    def test_parse_table(self):
        from ncl_agency_runtime.fpc.icm_pipeline import ICMPipeline
        content = "## Inputs\n| Item | Source |\n|---|---|\n| data | api |\n| news | rss |\n## Process\n"
        rows = ICMPipeline._parse_table(content, "Inputs")
        assert len(rows) == 2
        assert rows[0]["Item"] == "data"
        assert rows[1]["Source"] == "rss"

    def test_parse_numbered_list(self):
        from ncl_agency_runtime.fpc.icm_pipeline import ICMPipeline
        content = "## Process\n1. Fetch data\n2. Validate\n3. Transform\n## Outputs\n"
        items = ICMPipeline._parse_numbered_list(content, "Process")
        assert len(items) == 3
        assert items[0] == "Fetch data"


# ── OpenClaw Gateway ─────────────────────────────────────────────────────────


class TestOpenClawGateway:
    def test_gateway_init(self):
        from ncl_agency_runtime.fpc.openclaw_gateway import OpenClawGateway
        gw = OpenClawGateway()
        assert gw.gateway_url == "http://127.0.0.1:18789"
        assert not gw.is_connected

    def test_gateway_status(self):
        from ncl_agency_runtime.fpc.openclaw_gateway import OpenClawGateway
        gw = OpenClawGateway()
        status = gw.get_gateway_status()
        assert "gateway_url" in status
        assert "hooks_registered" in status
        assert "before_prompt_build" in status["hooks_registered"]

    def test_message_protocol(self):
        from ncl_agency_runtime.fpc.openclaw_gateway import OpenClawMessage
        msg = OpenClawMessage(type="prediction", payload={"direction": "bullish"})
        assert msg.type == "prediction"
        j = json.loads(msg.to_json())
        assert j["type"] == "prediction"
        assert j["payload"]["direction"] == "bullish"
        assert "timestamp" in j

    def test_hook_registration(self):
        from ncl_agency_runtime.fpc.openclaw_gateway import OpenClawGateway, PluginHook
        gw = OpenClawGateway()
        called = []
        gw.register_hook(PluginHook(
            hook_name="test_hook",
            callback=lambda ctx: called.append(True) or {},
            priority=10,
        ))
        gw.fire_hook("test_hook", {})
        assert len(called) == 1

    def test_hook_priority_order(self):
        from ncl_agency_runtime.fpc.openclaw_gateway import OpenClawGateway, PluginHook
        gw = OpenClawGateway()
        order = []
        gw.register_hook(PluginHook("order_test", lambda c: order.append("B"), priority=200))
        gw.register_hook(PluginHook("order_test", lambda c: order.append("A"), priority=100))
        gw.fire_hook("order_test", {})
        assert order == ["A", "B"]

    def test_cron_job(self):
        from ncl_agency_runtime.fpc.openclaw_gateway import CronJob, OpenClawGateway
        gw = OpenClawGateway()
        gw.add_cron_job(CronJob(schedule="0 8 * * 1-5", topic="market update"))
        jobs = gw.list_cron_jobs()
        assert len(jobs) == 1
        assert jobs[0]["topic"] == "market update"

    def test_webhook_trigger(self):
        from ncl_agency_runtime.fpc.openclaw_gateway import OpenClawGateway, WebhookTrigger
        gw = OpenClawGateway()
        gw.add_webhook_trigger(WebhookTrigger(
            event_type="price_alert",
            topic_template="Price alert for {symbol}",
        ))
        result = gw.handle_webhook("price_alert", {"symbol": "BTC"})
        assert result is not None
        assert result["topic"] == "Price alert for BTC"

    def test_webhook_no_match(self):
        from ncl_agency_runtime.fpc.openclaw_gateway import OpenClawGateway
        gw = OpenClawGateway()
        result = gw.handle_webhook("unknown_event", {})
        assert result is None

    def test_channel_configuration(self):
        from ncl_agency_runtime.fpc.openclaw_gateway import OpenClawGateway
        gw = OpenClawGateway()
        gw.configure_channel("file", {"output_dir": "reports"})
        assert "file" in gw._channels

    def test_domain_context_injection(self):
        from ncl_agency_runtime.fpc.openclaw_gateway import OpenClawGateway
        context = {"topic": "crypto market analysis"}
        result = OpenClawGateway._inject_domain_context(context)
        assert "suggested_sources" in result
        assert "coindesk" in result["suggested_sources"]

    def test_tool_audit_hook(self):
        from ncl_agency_runtime.fpc.openclaw_gateway import OpenClawGateway
        # Passing case
        ctx = {"tool_result": {"data": [1, 2, 3]}}
        result = OpenClawGateway._audit_tool_result(ctx)
        assert result["tool_audit"] == "passed"

        # Failing case
        ctx = {"tool_result": {"error": "timeout"}}
        result = OpenClawGateway._audit_tool_result(ctx)
        assert result["tool_audit"] == "failed"

    def test_file_delivery(self):
        from ncl_agency_runtime.fpc.openclaw_gateway import OpenClawGateway
        with tempfile.TemporaryDirectory() as tmp:
            gw = OpenClawGateway()
            gw.configure_channel("file", {"output_dir": tmp})
            results = gw.deliver_prediction(
                {"direction": "bullish", "confidence": 0.8},
                channels=["file"],
            )
            assert results["file"].endswith(".json")
            # Verify file was actually written
            written = Path(results["file"])
            assert written.exists()
            data = json.loads(written.read_text(encoding="utf-8"))
            assert data["direction"] == "bullish"


# ── Ralphy Evolution ─────────────────────────────────────────────────────────


class TestRalphyEvolution:
    def test_evolution_init(self):
        from ncl_agency_runtime.fpc.ralphy_evolution import RalphyEvolution
        with tempfile.TemporaryDirectory() as tmp:
            evo = RalphyEvolution(state_dir=Path(tmp))
            assert evo.state_dir == Path(tmp)

    def test_evolution_status(self):
        from ncl_agency_runtime.fpc.ralphy_evolution import RalphyEvolution
        with tempfile.TemporaryDirectory() as tmp:
            evo = RalphyEvolution(state_dir=Path(tmp))
            status = evo.get_evolution_status()
            assert "total_tasks" in status
            assert status["total_tasks"] == 0

    def test_evolution_task_creation(self):
        from ncl_agency_runtime.fpc.ralphy_evolution import EvolutionTask
        task = EvolutionTask(
            id="", category="strategy",
            title="Add XGBoost strategy",
            description="Implement XGBoost-based forecasting",
        )
        assert task.id.startswith("evo_")
        assert task.status == "queued"
        assert task.category == "strategy"

    def test_analyze_generates_tasks(self):
        from ncl_agency_runtime.fpc.ralphy_evolution import RalphyEvolution
        with tempfile.TemporaryDirectory() as tmp:
            evo = RalphyEvolution(state_dir=Path(tmp))
            report = evo.analyze()
            assert report.timestamp
            # Should identify at least the "insufficient history" weakness
            assert len(report.weaknesses) >= 1 or len(report.strengths) >= 1
            assert len(report.recommendations) >= 1

    def test_task_persistence(self):
        from ncl_agency_runtime.fpc.ralphy_evolution import EvolutionTask, RalphyEvolution
        with tempfile.TemporaryDirectory() as tmp:
            evo = RalphyEvolution(state_dir=Path(tmp))
            evo._tasks.append(EvolutionTask(
                id="test_1", category="coverage",
                title="Test task", description="Test",
            ))
            evo._save_tasks()

            # Reload
            evo2 = RalphyEvolution(state_dir=Path(tmp))
            assert len(evo2._tasks) == 1
            assert evo2._tasks[0].id == "test_1"

    def test_complete_task(self):
        from ncl_agency_runtime.fpc.ralphy_evolution import EvolutionTask, RalphyEvolution
        with tempfile.TemporaryDirectory() as tmp:
            evo = RalphyEvolution(state_dir=Path(tmp))
            evo._tasks.append(EvolutionTask(
                id="test_done", category="calibration",
                title="Recalibrate", description="Fix weights",
            ))
            evo.complete_task("test_done", "Weights adjusted", {"accuracy": 0.75})
            task = evo._tasks[0]
            assert task.status == "completed"
            assert task.result == "Weights adjusted"
            assert task.metrics_after == {"accuracy": 0.75}

    def test_recalibrate_weights(self):
        from ncl_agency_runtime.fpc.ralphy_evolution import RalphyEvolution
        with tempfile.TemporaryDirectory() as tmp:
            evo = RalphyEvolution(state_dir=Path(tmp))
            weights = evo.recalibrate_weights()
            # Default weights (not enough history to recalibrate)
            assert abs(sum(weights.values()) - 1.0) < 0.01
            assert "Trend Analyzer" in weights
            assert "Risk Assessor" in weights

    def test_get_tasks_filtered(self):
        from ncl_agency_runtime.fpc.ralphy_evolution import EvolutionTask, RalphyEvolution
        with tempfile.TemporaryDirectory() as tmp:
            evo = RalphyEvolution(state_dir=Path(tmp))
            evo._tasks = [
                EvolutionTask(id="t1", category="strategy", title="A", description="", status="queued"),
                EvolutionTask(id="t2", category="coverage", title="B", description="", status="completed"),
                EvolutionTask(id="t3", category="strategy", title="C", description="", status="queued"),
            ]
            queued = evo.get_tasks(status="queued")
            assert len(queued) == 2
            strat = evo.get_tasks(category="strategy")
            assert len(strat) == 2

    def test_weakness_to_task_mapping(self):
        from ncl_agency_runtime.fpc.ralphy_evolution import RalphyEvolution
        with tempfile.TemporaryDirectory() as tmp:
            evo = RalphyEvolution(state_dir=Path(tmp))
            task = evo._weakness_to_task("Prediction accuracy is critically low at 30%")
            assert task is not None
            assert task.category == "calibration"
            assert task.priority == 10  # Critical = highest priority


# ── Thinking Layer (Orchestrator) ────────────────────────────────────────────


class TestThinkingLayer:
    def test_thinking_init(self):
        from ncl_agency_runtime.fpc.thinking import ThinkingLayer
        thinking = ThinkingLayer(config={
            "workspace_root": "workspace",
            "gateway_url": "http://127.0.0.1:18789",
            "evolution_dir": "state/evolution",
            "channels": {"file": {"output_dir": "reports"}},
        })
        assert thinking.icm is not None
        assert thinking.gateway is not None
        assert thinking.evolution is not None

    def test_thinking_status(self):
        from ncl_agency_runtime.fpc.thinking import ThinkingLayer
        thinking = ThinkingLayer()
        status = thinking.status()
        assert "icm_pipeline" in status
        assert "gateway" in status
        assert "evolution" in status

    def test_schedule_prediction(self):
        from ncl_agency_runtime.fpc.thinking import ThinkingLayer
        thinking = ThinkingLayer()
        thinking.schedule_prediction("0 8 * * 1-5", "daily market scan")
        jobs = thinking.gateway.list_cron_jobs()
        assert len(jobs) == 1
        assert jobs[0]["topic"] == "daily market scan"

    def test_add_trigger(self):
        from ncl_agency_runtime.fpc.thinking import ThinkingLayer
        thinking = ThinkingLayer()
        thinking.add_trigger("price_alert", "Alert: {symbol} moved")
        result = thinking.gateway.handle_webhook("price_alert", {"symbol": "ETH"})
        assert result["topic"] == "Alert: ETH moved"

    def test_handle_event_no_match(self):
        from ncl_agency_runtime.fpc.thinking import ThinkingLayer
        thinking = ThinkingLayer()
        result = thinking.handle_event("unknown", {})
        assert result is None


# ── Council integration ──────────────────────────────────────────────────────


class TestCouncilThinking:
    def test_council_has_think_method(self):
        from ncl_agency_runtime.fpc.heuristic_council import FuturePredictorCouncil
        council = FuturePredictorCouncil()
        assert hasattr(council, "think")

    def test_council_status_includes_thinking(self):
        from ncl_agency_runtime.fpc.heuristic_council import FuturePredictorCouncil
        council = FuturePredictorCouncil()
        status = council.get_council_status()
        assert "thinking_layer" in status

    def test_version_bump(self):
        from ncl_agency_runtime.fpc import __version__
        assert __version__ == "0.6.0"
