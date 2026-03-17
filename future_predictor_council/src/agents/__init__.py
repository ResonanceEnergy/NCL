"""20-Agent Roster — Launch Squadron (10) + Expansion Pack (10).

Each agent has a callsign codename, mission, capabilities, IO contracts,
guardrails, metrics, failure modes, and LangGraph node hooks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


# ── Enums ───────────────────────────────────────────────────────
class AgentTier(StrEnum):
    LEAD = "lead"
    CORE = "core"
    OPS = "ops"
    EXPANSION = "expansion"


class AgentStatus(StrEnum):
    IDLE = "idle"
    ACTIVE = "active"
    BLOCKED = "blocked"
    ERROR = "error"
    OFFLINE = "offline"


# ── Role Card ───────────────────────────────────────────────────
@dataclass
class AgentRole:
    """Full role card for an autonomous agent."""

    name: str
    codename: str
    callsign: str  # cool codename
    tier: AgentTier
    mission: str = ""
    responsibilities: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    guardrails: list[str] = field(default_factory=list)
    metrics: list[str] = field(default_factory=list)
    failure_modes: list[str] = field(default_factory=list)
    langgraph_nodes: list[str] = field(default_factory=list)
    approval_required: bool = False
    status: AgentStatus = AgentStatus.IDLE


# ── Launch Squadron (10 Agents) ─────────────────────────────────
LAUNCH_SQUADRON: list[AgentRole] = [
    # 1 ─ ATLAS — Mission Control
    AgentRole(
        name="Mission Control",
        codename="mc",
        callsign="ATLAS",
        tier=AgentTier.LEAD,
        mission=(
            "Orchestrate the entire system; route intents/events; "
            "enforce policy; approve actions; handle errors/rollbacks."
        ),
        responsibilities=[
            "Intent → plan → act routing; cross-agent coordination",
            "Gatekeeper for ReleasePolicy channels (alpha/beta/stable)",
            "Live cost governance vs weekly GPU/RAM budgets",
            "Escalate blockers to human operator",
        ],
        capabilities=[
            "State machine: OBSERVE → INTERPRET → PLAN → PROPOSE → POLICY_CHECK → EXECUTE → EVAL_LEARN",
            "Multi-agent task dispatch via LangGraph supervisor",
            "Human-in-the-loop 5% steering decisions",
            "Automatic rollback on p95 / failure threshold breach",
        ],
        tools=["langgraph", "task_tracker", "notification", "policy_engine"],
        inputs=["intents (user/system)", "events stream", "model telemetry", "policy state"],
        outputs=[
            "routed tasks to agents", "action proposals for approval",
            "deploy/rollback commands", "council briefs",
        ],
        guardrails=[
            "Policy enforcement per ReleasePolicy.yaml",
            "Human approval on high-risk", "Cost caps enforced",
        ],
        metrics=[
            "end-to-end action success rate", "time-to-decision",
            "rollback rate (p95)", "budget adherence",
        ],
        failure_modes=[
            "Auto-retry w/ exponential backoff",
            "Deterministic fallback paths",
            "Human escalation", "Blue/green rollback",
        ],
        langgraph_nodes=[
            "mission_control", "observe", "interpret", "plan",
            "propose_actions", "policy_check", "execute",
            "eval_learn", "recover",
        ],
        approval_required=True,
    ),
    # 2 ─ SCRIBE — Data Steward
    AgentRole(
        name="Data Steward",
        codename="ds",
        callsign="SCRIBE",
        tier=AgentTier.CORE,
        mission="Own ontology, data contracts, quality, and access. Feed trusted data to forecasters/causal/XAI.",
        responsibilities=[
            "Ingest and validate panel data (unique_id, ds, y)",
            "Schema/lineage/provenance checks",
            "PII minimization and policy labels",
            "Generate synthetic test datasets",
        ],
        capabilities=[
            "Data quality validation gates pre-training",
            "Anomaly detection on incoming streams",
            "Feature store publish/subscribe",
            "Air-gap data packaging",
        ],
        tools=["pandas", "great_expectations", "schema_validator"],
        inputs=["raw events", "datasets", "metadata"],
        outputs=["clean feature sets", "data health signals to ATLAS", "documentation for ECHO"],
        guardrails=["Security/privacy policies", "Air-gap packaging when required"],
        metrics=["data freshness", "coverage", "null/anomaly rates", "audit pass/fail"],
        failure_modes=["Quarantine + roll to last-known-good feature store", "Alert ATLAS"],
        langgraph_nodes=["validate_data", "build_features", "publish_features"],
    ),
    # 3 ─ TEMPO — Baseline Forecaster
    AgentRole(
        name="Baselines Engineer",
        codename="be",
        callsign="TEMPO",
        tier=AgentTier.CORE,
        mission="Produce strong classical baselines; set the beat. Primary metric: MASE, secondary: sMAPE.",
        responsibilities=[
            "Implement StatsForecast (AutoARIMA, ETS, Theta)",
            "Implement Silverkite (Greykite) for changepoints",
            "Run initial backtests and set MASE baselines",
            "Tune hyperparameters via grid/random search",
        ],
        capabilities=[
            "Univariate/multivariate baselines",
            "Confidence bands and prediction intervals",
            "Seasonality and holiday handling",
            "Changepoint detection",
        ],
        tools=["statsforecast", "greykite", "optuna"],
        inputs=["clean feature sets from SCRIBE"],
        outputs=["baseline forecasts + errors to council"],
        guardrails=["Never auto-deploy changes", "Used as control arm and sanity check"],
        metrics=["MASE", "sMAPE vs last cycle"],
        failure_modes=["If neural/ensemble fails, ATLAS can revert to TEMPO outputs for actions"],
        langgraph_nodes=["baseline_forecast"],
    ),
    # 4 ─ ORACLE — Neural Forecaster
    AgentRole(
        name="Neural Engineer",
        codename="ne",
        callsign="ORACLE",
        tier=AgentTier.CORE,
        mission="Higher-accuracy modeling with deep learning, under strict cost caps.",
        responsibilities=[
            "Implement PatchTST and TFT via NeuralForecast",
            "Manage training loops on CPU (local) and GPU (burst)",
            "Track experiments via MLflow or W&B",
            "Hyperparameter optimization with Optuna",
        ],
        capabilities=[
            "Quantile forecasts with uncertainty-aware outputs",
            "Cold-start smoothing",
            "Transfer learning from pre-trained weights",
            "Early stopping and learning rate scheduling",
        ],
        tools=["neuralforecast", "pytorch", "optuna", "mlflow"],
        inputs=["feature sets from SCRIBE"],
        outputs=["forecasts + embeddings + uncertainty to council"],
        guardrails=["GPU <= $1.20/hr and <= 60 min/day", "RAM <= $0.80/hr via burst helper"],
        metrics=["MASE/sMAPE deltas vs TEMPO", "cost per training minute", "p95 latency"],
        failure_modes=["Drop to smaller context/shorter horizon", "Fall back to TEMPO"],
        langgraph_nodes=["neural_forecast"],
    ),
    # 5 ─ BEHEMOTH — Foundation Ops
    AgentRole(
        name="Foundation Ops",
        codename="fo",
        callsign="BEHEMOTH",
        tier=AgentTier.CORE,
        mission=(
            "Provision and control foundation model bursts "
            "(Chronos-2 on A10G; TimesFM >= 64 GB RAM) under budget caps."
        ),
        responsibilities=[
            "Deploy TimesFM 2.5 to cloud burst instances (>=64 GB RAM)",
            "Deploy Chronos-2 to A10G GPU instances",
            "Manage cost caps ($50/week, $1.20/hr GPU max)",
            "Cache inference results for offline replay",
        ],
        capabilities=[
            "Spin-up/spin-down GPU/Hi-RAM runners",
            "Monitor spend in real-time",
            "Pin model versions and cache results",
            "Budget forecasting",
        ],
        tools=["timesfm", "chronos", "aws_ec2", "cost_monitor"],
        inputs=["requests from ORACLE/FORGE"],
        outputs=["session handles", "cost telemetry"],
        guardrails=["Weekly $50 budget", "Deny if cap hit", "Prefer local inference where viable"],
        metrics=["utilization", "$/effective forecast", "uptime"],
        failure_modes=["Switch to CPU/cheaper tier", "Queue burst for next window"],
        langgraph_nodes=["foundation_burst_manager"],
        approval_required=True,
    ),
    # 6 ─ LANTERN — XAI / Interpretability
    AgentRole(
        name="XAI Engineer",
        codename="xe",
        callsign="LANTERN",
        tier=AgentTier.CORE,
        mission="Turn models into evidence. Generate XAI dossiers for every cycle and action.",
        responsibilities=[
            "Build SHAP global/local feature importance panels",
            "Implement TimeSHAP sequential attribution for neural models",
            "Generate human-readable explanation dossiers",
            "Validate explanations against domain knowledge",
        ],
        capabilities=[
            "Feature attribution (SHAP, TimeSHAP)",
            "Error analysis and residual decomposition",
            "'What changed this cycle' summaries",
            "Automated explanation quality scoring",
        ],
        tools=["shap", "timeshap", "matplotlib"],
        inputs=["forecasts", "residuals", "model internals"],
        outputs=["XAI dossiers to council/ECHO", "reason codes to ATLAS"],
        guardrails=["No action without explanation when risk > threshold"],
        metrics=["coverage of explanations", "human readability scores", "time-to-understand"],
        failure_modes=["If explainability fails, action gates hold"],
        langgraph_nodes=["xai_report"],
    ),
    # 7 ─ RAVEN — Causal Inference
    AgentRole(
        name="Causal Scientist",
        codename="cs",
        callsign="RAVEN",
        tier=AgentTier.CORE,
        mission="Identify interventions (price, promo) and run counterfactuals/what-ifs.",
        responsibilities=[
            "Build DoWhy causal DAGs for treatment → outcome",
            "Estimate ATE/CATE via EconML (DML, Causal Forest)",
            "Run refutation tests (placebo, subset, random cause)",
            "Power what-if scenario simulations",
        ],
        capabilities=[
            "Uplift estimates and treatment effect heterogeneity",
            "Policy simulation with confidence intervals",
            "Automated refutation battery",
            "Counterfactual scenario generation",
        ],
        tools=["dowhy", "econml", "networkx"],
        inputs=["forecasts/features from council"],
        outputs=["action candidates w/ expected causal lift"],
        guardrails=["Only propose under data sufficiency and overlap tests", "Confidence thresholds"],
        metrics=["uplift accuracy post-action", "counterfactual regret"],
        failure_modes=["If causal validity weak, downgrade to correlation-informed suggestion flagged 'exploratory'"],
        langgraph_nodes=["causal_what_if"],
    ),
    # 8 ─ FORGE — MLOps / Pipeline
    AgentRole(
        name="MLOps Engineer",
        codename="mo",
        callsign="FORGE",
        tier=AgentTier.OPS,
        mission="Build, deploy, promote, roll back. Automate with policy and SBOM/vuln gates.",
        responsibilities=[
            "CI/CD pipeline (GitHub Actions, micro-backtest)",
            "Model registry and artifact versioning",
            "Apollo-lite release channels (alpha → beta → stable)",
            "Monitoring dashboards and drift detection",
        ],
        capabilities=[
            "Blue/green deployments",
            "Soak-hour management and channel promotions",
            "Air-gap package creation",
            "Automated drift detection and retrain triggers",
        ],
        tools=["github_actions", "mlflow", "docker", "prometheus"],
        inputs=["artifacts + ReleasePolicy"],
        outputs=["deployment status", "rollback events"],
        guardrails=["p95 thresholds", "Action failure triggers", "Approvals before promote"],
        metrics=["deployment success rate", "MTTR", "rollback frequency"],
        failure_modes=["Auto-rollback on policy breach", "Freeze promotions"],
        langgraph_nodes=["build_artifacts", "deploy_candidate", "promote_channel", "rollback"],
    ),
    # 9 ─ PHALANX — Security & Privacy
    AgentRole(
        name="Security Officer",
        codename="so",
        callsign="PHALANX",
        tier=AgentTier.OPS,
        mission="Enforce least privilege, threat model checks, privacy controls; handle SBOM + vuln scans.",
        responsibilities=[
            "SBOM generation (Syft) and vulnerability scanning (Trivy)",
            "Air-gap bundle packaging for offline deployment",
            "Secrets management and credential rotation",
            "Audit trail for all model predictions and actions",
        ],
        capabilities=[
            "Policy checks on every action and deploy intent",
            "API key vaulting and rotation schedules",
            "Anomaly detection on agent behavior",
            "Air-gap bundle signing",
        ],
        tools=["syft", "trivy", "vault", "audit_logger"],
        inputs=["actions", "deploy intents"],
        outputs=["allow/deny decisions", "alerts", "signed bundles"],
        guardrails=["Mandatory scan gates before deploy", "Deny unvetted actions"],
        metrics=["detections", "false positive rate", "mean time to contain"],
        failure_modes=["Block and alert ATLAS", "Quarantine artifacts"],
        langgraph_nodes=["security_gate"],
    ),
    # 10 ─ ECHO — Documentation & DevEx
    AgentRole(
        name="DX Docs",
        codename="dx",
        callsign="ECHO",
        tier=AgentTier.OPS,
        mission="Keep humans in sync; convert council outputs to briefs; maintain playbooks and bootcamp materials.",
        responsibilities=[
            "Write and maintain developer documentation",
            "Create onboarding guides and bootcamp materials",
            "Generate API reference from docstrings",
            "Maintain CHANGELOG and release notes",
        ],
        capabilities=[
            "Summarize council cycles into human-readable briefs",
            "'What changed this cycle' reports",
            "Runbook and playbook generation",
            "Arena Bootcamp kit packaging",
        ],
        tools=["mkdocs", "sphinx", "markdown"],
        inputs=["XAI dossiers", "metrics", "policy changes"],
        outputs=["docs", "dashboards", "PR templates"],
        guardrails=["Only publish signed/approved materials", "Align with ReleasePolicy"],
        metrics=["doc freshness", "dev onboarding time", "incident comprehension"],
        failure_modes=["Minimal status bulletin if automation fails"],
        langgraph_nodes=["publish_docs", "bootcamp_packager"],
    ),
]


# ── Expansion Pack (10 Agents) ──────────────────────────────────
EXPANSION_PACK: list[AgentRole] = [
    # 11 ─ MINDGATE — Intent Router
    AgentRole(
        name="Intent Router",
        codename="ir",
        callsign="MINDGATE",
        tier=AgentTier.EXPANSION,
        mission=(
            "Parse and classify natural-language intents from users "
            "and external systems into structured action requests."
        ),
        capabilities=[
            "NLU classification", "Intent disambiguation",
            "Context tracking", "Priority scoring",
        ],
        inputs=["raw user messages", "API requests", "webhook payloads"],
        outputs=["structured intents to ATLAS"],
        langgraph_nodes=["intent_parse", "intent_classify"],
    ),
    # 12 ─ PHOENIX — Scenario Simulation
    AgentRole(
        name="Scenario Simulator",
        codename="ss",
        callsign="PHOENIX",
        tier=AgentTier.EXPANSION,
        mission="Run Monte Carlo and what-if scenario simulations across council forecasts and causal models.",
        capabilities=["Monte Carlo paths", "Stress-test generation", "Sensitivity sweeps", "Scenario comparison"],
        inputs=["forecasts", "causal DAGs", "parameter ranges"],
        outputs=["scenario reports", "risk distributions"],
        langgraph_nodes=["scenario_simulate"],
    ),
    # 13 ─ NAVIGATOR — Strategy Planner
    AgentRole(
        name="Strategy Planner",
        codename="sp",
        callsign="NAVIGATOR",
        tier=AgentTier.EXPANSION,
        mission="Synthesize council evidence into strategic recommendations and long-horizon plans.",
        capabilities=["Multi-objective optimization", "Resource allocation", "Timeline planning", "Trade-off analysis"],
        inputs=["council forecasts", "XAI dossiers", "causal effects", "scenario reports"],
        outputs=["strategic plans", "priority-ranked actions"],
        langgraph_nodes=["strategy_plan"],
    ),
    # 14 ─ SANCTUM — Ethics & Safety Council
    AgentRole(
        name="Ethics & Safety",
        codename="es",
        callsign="SANCTUM",
        tier=AgentTier.EXPANSION,
        mission="Review all high-impact decisions for ethical, safety, and fairness constraints before execution.",
        capabilities=["Bias detection", "Fairness checks", "Impact assessment", "Ethical guardrail enforcement"],
        inputs=["action proposals from ATLAS", "XAI dossiers"],
        outputs=["approve/flag/block decisions", "fairness reports"],
        guardrails=["Block actions that fail fairness thresholds"],
        langgraph_nodes=["ethics_review"],
        approval_required=True,
    ),
    # 15 ─ WATCHTOWER — Real-Time Event Monitor
    AgentRole(
        name="Event Monitor",
        codename="em",
        callsign="WATCHTOWER",
        tier=AgentTier.EXPANSION,
        mission="Continuously monitor telemetry, events, and agent health; trigger alerts and auto-responses.",
        capabilities=["Stream processing", "Anomaly detection", "Alert routing", "Health dashboards"],
        inputs=["telemetry streams", "agent heartbeats", "system logs"],
        outputs=["alerts to ATLAS", "health status", "drift signals"],
        langgraph_nodes=["monitor_stream", "anomaly_detect"],
    ),
    # 16 ─ MUSE — Human Interaction / UX
    AgentRole(
        name="Human UX",
        codename="ux",
        callsign="MUSE",
        tier=AgentTier.EXPANSION,
        mission=(
            "Present information to humans in optimal formats; "
            "manage approval UIs and feedback loops."
        ),
        capabilities=[
            "Dashboard generation", "Natural-language summaries",
            "Approval UI management", "Feedback collection",
        ],
        inputs=["council briefs", "action proposals", "XAI dossiers"],
        outputs=["rendered dashboards", "approval requests", "feedback signals"],
        langgraph_nodes=["render_ui", "collect_feedback"],
    ),
    # 17 ─ COUNCILOR — Multi-Agent Negotiation
    AgentRole(
        name="Agent Negotiator",
        codename="an",
        callsign="COUNCILOR",
        tier=AgentTier.EXPANSION,
        mission=(
            "Resolve conflicts between agents when multiple strategies "
            "or actions compete for resources or priority."
        ),
        capabilities=[
            "Conflict resolution", "Resource arbitration",
            "Voting protocols", "Consensus building",
        ],
        inputs=["competing proposals from agents"],
        outputs=["negotiated decisions", "resource allocations"],
        langgraph_nodes=["negotiate", "arbitrate"],
    ),
    # 18 ─ NIGHTFALL — High-Risk Intervention
    AgentRole(
        name="High-Risk Intervention",
        codename="hr",
        callsign="NIGHTFALL",
        tier=AgentTier.EXPANSION,
        mission=(
            "Handle critical situations: system failures, budget breaches, "
            "security incidents, emergency rollbacks."
        ),
        capabilities=[
            "Emergency response", "Circuit breakers",
            "Incident triage", "War-room coordination",
        ],
        inputs=["critical alerts from WATCHTOWER/PHALANX", "failure events"],
        outputs=["emergency actions", "incident reports"],
        guardrails=["Always logs full trace", "Human notified within 60s"],
        langgraph_nodes=["emergency_respond", "circuit_break"],
        approval_required=True,
    ),
    # 19 ─ SPECTRE — Red Team / Adversarial
    AgentRole(
        name="Red Team",
        codename="rt",
        callsign="SPECTRE",
        tier=AgentTier.EXPANSION,
        mission="Proactively test the system with adversarial scenarios, edge cases, and chaos engineering.",
        capabilities=["Adversarial input generation", "Chaos injection", "Edge-case discovery", "Security pen-testing"],
        inputs=["system state", "model artifacts"],
        outputs=["vulnerability reports", "stress-test results"],
        guardrails=["Sandboxed execution only", "No production mutations"],
        langgraph_nodes=["adversarial_test", "chaos_inject"],
    ),
    # 20 ─ BRIDGE — Cross-System Integration
    AgentRole(
        name="System Integrator",
        codename="si",
        callsign="BRIDGE",
        tier=AgentTier.EXPANSION,
        mission="Connect the council to external systems: NCL memory, GBX, Crimson Compass, APIs, databases.",
        capabilities=["API adapter management", "Protocol bridging", "Data format translation", "Webhook management"],
        inputs=["external system events", "integration requests"],
        outputs=["translated events", "writeback confirmations"],
        langgraph_nodes=["bridge_ingest", "bridge_writeback"],
    ),
    # 21 ─ WOLFRAM — Computational Universe Physics Engine
    AgentRole(
        name="Computational Universe",
        codename="wp",
        callsign="WOLFRAM",
        tier=AgentTier.EXPANSION,
        mission=(
            "Run the Wolfram Physics framework: hypergraph state tracking, "
            "multiway branching, causal graphs, branchial distance, "
            "computational irreducibility detection, and ruliad exploration."
        ),
        capabilities=[
            "Hypergraph state evolution",
            "Multiway prediction branching",
            "Causal graph construction and invariance scoring",
            "Branchial distance and entanglement measurement",
            "Computational irreducibility detection",
            "Ruliad configuration-space exploration",
            "Observer projection (branch collapse to classical forecast)",
        ],
        inputs=["model predictions", "agent events", "series data", "configuration space"],
        outputs=[
            "multiway branchial graph", "causal invariance score",
            "irreducibility assessment", "ruliad exploration summary",
            "observer projection (consensus forecast)",
        ],
        langgraph_nodes=["wolfram_observe", "wolfram_branch", "wolfram_collapse"],
    ),
    # 22 ─ SENTINEL — NCC Doctrine Enforcer
    AgentRole(
        name="NCC Doctrine Enforcer",
        codename="nc",
        callsign="SENTINEL",
        tier=AgentTier.EXPANSION,
        mission=(
            "Enforce NCC governance doctrine: Three Pillars compliance scoring, "
            "Faraday Fortress security validation, Doctrine-Lock rules, "
            "and PDCA audit loops."
        ),
        capabilities=[
            "Three Pillars scoring (Art of War, 48 Laws, 7 Habits)",
            "Faraday Fortress layer validation",
            "Doctrine-Lock enforcement (ZERO CLOUD DATA)",
            "PDCA audit cycles (Plan-Do-Check-Act)",
            "Governance resonance computation",
        ],
        inputs=["operational context", "agent states", "system metrics"],
        outputs=["doctrine compliance report", "pillar scores", "PDCA findings"],
        guardrails=["Doctrine-Lock violations halt operations", "Evidence-based audit only"],
        langgraph_nodes=["doctrine_check", "pillar_score", "pdca_audit"],
    ),
    # 23 ─ VAULT — AAC Asset Bridge
    AgentRole(
        name="AAC Asset Bridge",
        codename="ab",
        callsign="VAULT",
        tier=AgentTier.EXPANSION,
        mission=(
            "Connect the council to the Autonomous Asset Collective (AAC): "
            "portfolio snapshots, strategy performance reports, trading signal relay, "
            "and exchange connector status."
        ),
        capabilities=[
            "AAC discovery and connectivity",
            "Portfolio snapshot retrieval",
            "Strategy performance reporting",
            "Trading signal relay to council",
            "Exchange connector status monitoring",
        ],
        inputs=["AAC portfolio data", "trading signals", "strategy metrics"],
        outputs=["portfolio snapshots", "strategy reports", "signal relay confirmations"],
        guardrails=["Read-only access to AAC", "No direct trading execution"],
        langgraph_nodes=["aac_snapshot", "aac_strategy", "aac_signal"],
    ),
    # 24 ─ NEXUS — BRS Orchestrator
    AgentRole(
        name="BRS Orchestrator",
        codename="sa",
        callsign="NEXUS",
        tier=AgentTier.EXPANSION,
        mission=(
            "Connect the council to BRS (Bit Rage Systems): multi-agent dispatch, "
            "RBAC policy coordination, workflow composition, and capability bridging."
        ),
        capabilities=[
            "BRS discovery and connectivity",
            "Multi-agent workflow dispatch",
            "RBAC policy coordination",
            "Workflow status monitoring",
            "Capability bridging across platforms",
        ],
        inputs=["workflow requests", "agent dispatch orders", "RBAC queries"],
        outputs=["dispatch confirmations", "workflow status", "RBAC verdicts"],
        guardrails=["Council trust boundary enforced", "No unauthorized escalation"],
        langgraph_nodes=["agency_dispatch", "agency_workflow", "agency_rbac"],
    ),
    # 25 ─ CIPHER — SIGINT Intelligence & Fusion Analyst
    AgentRole(
        name="SIGINT Intelligence Analyst",
        codename="sg",
        callsign="CIPHER",
        tier=AgentTier.EXPANSION,
        mission=(
            "Apply Unit 8200's TCPED intelligence cycle and multi-source fusion "
            "to the council's data pipeline: collect, process, exploit, fuse, "
            "and disseminate intelligence with compartmentalized access control."
        ),
        capabilities=[
            "TCPED intelligence collection cycle",
            "Multi-source fusion (SIGINT/COMINT/ELINT/CYBINT/OSINT/HUMINT)",
            "Cross-discipline correlation and anomaly detection",
            "Compartmentalized dissemination with need-to-know",
            "Zero-day proactive vulnerability scanning",
        ],
        inputs=["raw data streams", "channel signals", "telemetry feeds"],
        outputs=["intelligence reports", "fusion pictures", "anomaly alerts"],
        guardrails=["Compartmentalization enforced", "Need-to-know access only"],
        langgraph_nodes=["sigint_collect", "sigint_fuse", "sigint_disseminate"],
    ),
    # 26 ─ AEGIS — Red Team & Adversarial Defense Shield
    AgentRole(
        name="Red Team Defense Shield",
        codename="rd",
        callsign="AEGIS",
        tier=AgentTier.EXPANSION,
        mission=(
            "Apply Unit 8200's red team / blue team methodology to continuously "
            "validate predictions, probe for vulnerabilities, stress test models, "
            "and activate defensive countermeasures against adversarial threats."
        ),
        capabilities=[
            "Red team adversarial probing (noise, drift, boundary, replay)",
            "Blue team defensive countermeasures",
            "Zero-day prediction vulnerability scanning",
            "Stress testing with escalating noise injection",
            "CIOV threat matrix assessment",
        ],
        inputs=["predictions", "model outputs", "threat indicators"],
        outputs=["probe results", "vulnerability findings", "defense actions"],
        guardrails=["Red team scoped to internal systems only", "No external attacks"],
        langgraph_nodes=["redteam_probe", "blueteam_defend", "threat_assess"],
    ),
    # 27 ─ MANDARIN — Geopolitical Intelligence Advisor
    AgentRole(
        name="Geopolitical Intelligence Advisor",
        codename="jx",
        callsign="MANDARIN",
        tier=AgentTier.EXPANSION,
        mission=(
            "Integrate Jiang Xueqin's geopolitical analysis framework: innovation-over-imitation, "
            "education-as-predictor, bridge-perspectives, structural-over-surface, "
            "data-driven narrative, and long-horizon thinking. Provides ongoing signal "
            "collection, multi-lens strategic assessment, and trusted advisory output."
        ),
        capabilities=[
            "Geopolitical signal collection and credibility scoring",
            "Six-lens strategic assessment (innovation, education, competition, trade, tech sovereignty, diplomacy)",
            "Narrative engine with Eastern-Western perspective bridging",
            "Ongoing data pipeline with trend tracking",
            "Trusted advisory board consultations",
            "Jiang Xueqin lesson scoring and compliance",
        ],
        inputs=["geopolitical signals", "news feeds", "trade data", "education statistics"],
        outputs=["strategic assessments", "advisory notes", "trend reports", "narrative analyses"],
        guardrails=["Structural analysis over surface commentary", "Source credibility verification required"],
        langgraph_nodes=["geopol_collect", "geopol_assess", "geopol_advise"],
    ),
    # 28 ─ CORTEX — Second Brain Knowledge Engine
    AgentRole(
        name="Second Brain Knowledge Engine",
        codename="sb",
        callsign="CORTEX",
        tier=AgentTier.EXPANSION,
        mission=(
            "Implement Tiago Forte's Second Brain methodology as a knowledge "
            "amplification layer: PARA organization, CODE workflow pipeline, "
            "Progressive Summarization, Intermediate Packets, Just-In-Time "
            "retrieval, and associative connection graphs for cross-domain insight."
        ),
        capabilities=[
            "PARA knowledge organization (Projects/Areas/Resources/Archives)",
            "CODE workflow pipeline (Capture/Organize/Distill/Express)",
            "5-layer Progressive Summarization (raw to remix)",
            "Intermediate Packet creation and reuse tracking",
            "Just-In-Time retrieval (keyword/semantic/temporal/associative/contextual)",
            "Connection graph for associative knowledge discovery",
            "Twelve Favorite Problems methodology testing",
            "Knowledge maintenance cycles and methodology scoring",
        ],
        inputs=["raw knowledge", "signals from other agents", "query contexts"],
        outputs=["distilled notes", "intermediate packets", "expression outputs", "retrieval results"],
        guardrails=["Source attribution required", "No knowledge deletion without archive"],
        langgraph_nodes=["brain_capture", "brain_distill", "brain_express"],
    ),
    # 29 ─ BEACON — AI Daily Brief & Exponential Intelligence
    AgentRole(
        name="AI Daily Brief & Exponential Intelligence",
        codename="ai",
        callsign="BEACON",
        tier=AgentTier.EXPANSION,
        mission=(
            "Integrate NLW's AI Daily Brief intelligence (policy, safety, industry, "
            "models, regulation) with Peter H. Diamandis's exponential frameworks "
            "(6 D's, abundance, convergence, metatrends, moonshots, MTP). Provides "
            "daily AI briefings, exponential signal tracking, convergence detection, "
            "abundance scoring, and lessons-learned compliance."
        ),
        capabilities=[
            "AI Daily Brief signal ingestion and classification (NLW taxonomy)",
            "Exponential tracking via 6 D's pipeline (Diamandis framework)",
            "Technology convergence detection and multiplier scoring",
            "Abundance assessment across 8 domains",
            "Metatrend registration and momentum tracking",
            "Moonshot idea generation with MTP alignment scoring",
            "Daily digest generation combining both channels",
            "Integrated lessons scoring (5 NLW + 7 Diamandis lessons)",
        ],
        inputs=["AI news signals", "technology data", "market trends", "exponential indicators"],
        outputs=["daily briefings", "exponential signals", "convergence events", "abundance reports", "moonshot ideas"],
        guardrails=["Source attribution required", "Evidence-based scoring only"],
        langgraph_nodes=["brief_ingest", "brief_exponential", "brief_digest"],
    ),
    # 30 ─ HERALD — X (Twitter) Intelligence & Feed Router
    AgentRole(
        name="X Intelligence & Feed Router",
        codename="xf",
        callsign="HERALD",
        tier=AgentTier.EXPANSION,
        mission=(
            "Ingest X (Twitter) account feed—timeline, likes, reposts, bookmarks—"
            "classify each item by content domain (AI, finance, geopolitics, security, "
            "etc.), filter by signal quality, and route intelligence to the appropriate "
            "NCL agent, division, and NCC Triad pillar for downstream processing."
        ),
        capabilities=[
            "X feed ingestion with deduplication (timeline, likes, reposts)",
            "Multi-domain content classification (12 domains)",
            "Urgency and signal quality assessment",
            "Intelligent routing to 30 agents across 9 divisions",
            "NCC Triad pillar targeting (NCL, AAC, BRS)",
            "Quality filtering with configurable thresholds",
            "Feed digest generation with routing analytics",
            "Per-agent dispatch queue management",
        ],
        inputs=["X feed data", "likes", "reposts", "bookmarks", "timeline posts"],
        outputs=["classified posts", "agent dispatches", "feed digests", "routing summaries"],
        guardrails=["Noise filtering required", "Privacy-tag all personal content"],
        langgraph_nodes=["xfeed_ingest", "xfeed_classify", "xfeed_route"],
    ),
    # 31 ─ CATALYST — YouTube Intelligence & AI Tool Discovery + Strategic AI News
    AgentRole(
        name="YouTube Intelligence & Strategic AI News",
        codename="yt",
        callsign="CATALYST",
        tier=AgentTier.EXPANSION,
        mission=(
            "Dual-pipeline YouTube intelligence agent. "
            "Pipeline 1 (TIAIFT): Ingest video data from 'There Is An AI For That' "
            "channel, extract tool mentions, classify by AI tool category, score impact, "
            "track trends, and route to NCL agents. "
            "Pipeline 2 (AI Upload): Ingest strategic AI news from 'AI Upload' channel, "
            "analyze content type (model releases, company news, safety, geopolitics, "
            "AGI progress), extract named entities (companies, models, researchers), "
            "detect strategic signals, track evolving narratives, and generate "
            "intelligence briefs for downstream NCL decision-making."
        ),
        capabilities=[
            "YouTube video ingestion with deduplication (TIAIFT + AI Upload)",
            "AI tool extraction from titles, descriptions, tags, transcripts",
            "15-category tool classification (text/image/video/audio/code/...)",
            "Impact scoring (paradigm-shift / high / moderate / low / noise)",
            "Intelligent routing to 31 agents across 8 divisions",
            "AI tool trend tracking with frequency and recency analysis",
            "NCC Triad pillar targeting (NCL Brain, AAC Bank, BRS)",
            "Video digest generation with category and impact breakdowns",
            "AI Upload content analysis (10 types: model/company/safety/geo/AGI/...)",
            "Named entity extraction (24 companies, 25 models, 14 researchers)",
            "Strategic signal detection (8 types: capability leap, competitive shift, ...)",
            "Narrative thread tracking across videos",
            "Urgency-level assessment (flash/priority/standard/archive)",
            "Intelligence brief generation with signal & entity breakdowns",
        ],
        inputs=["YouTube video metadata", "transcripts", "engagement data", "channel feeds"],
        outputs=["classified videos", "tool extractions", "trend reports", "agent dispatches",
                 "video digests", "strategic signals", "intelligence briefs", "narrative reports"],
        guardrails=["Impact filtering required", "Source attribution to channel"],
        langgraph_nodes=["yt_ingest", "yt_classify", "yt_route",
                         "au_ingest", "au_analyze", "au_signal"],
    ),
]


# ── Full Roster ─────────────────────────────────────────────────
ALL_AGENTS: list[AgentRole] = LAUNCH_SQUADRON + EXPANSION_PACK

# Codename → callsign lookup
CALLSIGN_MAP: dict[str, str] = {a.codename: a.callsign for a in ALL_AGENTS}


def get_agent(codename: str) -> AgentRole | None:
    """Find agent by codename."""
    for agent in ALL_AGENTS:
        if agent.codename == codename:
            return agent
    return None


def get_agent_by_callsign(callsign: str) -> AgentRole | None:
    """Find agent by callsign (e.g. 'ATLAS')."""
    callsign_upper = callsign.upper()
    for agent in ALL_AGENTS:
        if agent.callsign == callsign_upper:
            return agent
    return None


def list_agents(tier: AgentTier | None = None) -> list[AgentRole]:
    """List agents, optionally filtered by tier."""
    if tier is None:
        return ALL_AGENTS
    return [a for a in ALL_AGENTS if a.tier == tier]


def active_agents() -> list[AgentRole]:
    """Return agents currently in ACTIVE status."""
    return [a for a in ALL_AGENTS if a.status == AgentStatus.ACTIVE]
