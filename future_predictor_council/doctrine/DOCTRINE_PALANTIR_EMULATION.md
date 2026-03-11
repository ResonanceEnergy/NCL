# Palantir Emulation Doctrine — 200 Insights across 20 Clusters

> Distilled from Palantir's AIP, Foundry, Apollo, Gotham, OSDK, and public disclosures.
> Purpose: Extract emulatable patterns for the Future Predictor Council.

---

## Cluster 1 — AIP (Agentic Intelligence Platform)

1. **Agent layer is model-agnostic** — swap LLMs without rewriting business logic
2. **Logic → Agent → Eval** pipeline enforces structured reasoning before action
3. **AIP Assist** wraps natural language → ontology queries so non-technical users can query
4. **Agent Studio** provides visual flow builder for agent graphs (nodes = tools/steps)
5. **Sandboxed execution** — agents run in isolated containers, no ambient credential access
6. **Observability-first** — every agent step emits structured traces (span-level)
7. **Multi-model routing** — different steps can call different models (cost/quality tradeoff)
8. **Human-in-the-loop gates** before any "kinetic" action (write, approve, deploy)
9. **Prompt versioning** — prompts are first-class versioned artifacts, not inline strings
10. **Eval harness runs on every PR** — no prompt change ships without regression check

## Cluster 2 — Ontology (Digital Twin)

11. **Objects = digital twins** of real-world entities (assets, events, people, sensors)
12. **Links = relationships** between objects (typed, directional, with cardinality)
13. **Interfaces** define abstract contracts objects must satisfy (polymorphism for data)
14. **Actions** are governed mutations — every write goes through validation + approval
15. **Functions** are serverless compute attached to objects (TypeScript/Python)
16. **MMDP (Multi-Modal Data Pipeline)** — batch, streaming, CDC all feed the same ontology
17. **Object sets** are first-class queryable collections with permission scoping
18. **Versioned schemas** — ontology types evolve without breaking downstream consumers
19. **Semantic layer** — ontology IS the semantic layer (no separate BI metadata store)
20. **Composability** — objects compose into higher-order objects (e.g., Mission = n Tasks)

## Cluster 3 — OSDK (Ontology SDK)

21. **Typed client generation** — TS/Python/Java clients auto-generated from ontology schema
22. **Scope-limited tokens** — API tokens grant access only to specific object sets / actions
23. **Developer Console** — web UI for testing queries, inspecting objects, debugging
24. **Automatic pagination** — SDK handles large result sets transparently
25. **Webhook registration** — subscribe to ontology change events for reactive flows
26. **Local dev mode** — run against a local mock ontology for fast iteration
27. **Rate limiting per scope** — different token scopes get different QPS budgets
28. **SDK versioning** — breaking changes are versioned, old clients get deprecation window
29. **Audit trail** — every SDK call is logged with caller identity and timestamp
30. **Code samples** — Developer Console generates copy-paste code for each operation

## Cluster 4 — Scenarios / Vertex (What-If)

31. **Scenarios = branched ontology** — create a "what-if" fork of reality
32. **Model + Action composition** — chain forecast → action → forecast in a scenario
33. **Writeback previews** — see the effect of an action before committing
34. **Template scenarios** — save reusable scenario patterns (e.g., "price increase +5%")
35. **Multi-user scenarios** — collaborative what-if with merge/conflict resolution
36. **Time-travel** — scenarios can be replayed from any historical snapshot
37. **Approval gates** on scenario promotion — what-if → committed requires sign-off
38. **Cost estimation** — scenario runner estimates compute/API cost before execution
39. **Audit trail** — every scenario action is immutably logged
40. **Diff view** — compare scenario outcomes against baseline reality

## Cluster 5 — Platform Overview

41. **AI Mesh** — unified compute fabric across on-prem, cloud, edge, air-gapped
42. **Bootcamps as GTM** — 5-day hands-on builds convert prospects to paying customers
43. **Real-time ops** — streaming data + live dashboards for operational decision-making
44. **Foundry = the OS** — not a product, an operating system for the enterprise
45. **Platform → use-case, not use-case → platform** — build infra first, then applications
46. **Data → Information → Decision → Action** pipeline is the core value chain
47. **Network effects** — more objects + links → more valuable the ontology becomes
48. **Self-serve analytics** — non-engineers can build dashboards, queries, actions
49. **Compliance by construction** — access control and audit baked into every layer
50. **Ecosystem play** — OSDK lets third parties build on top of the ontology

## Cluster 6 — Apollo (Continuous Deployment)

51. **Multi-cloud / hybrid / air-gapped** — one CD system for all environments
52. **Constraint-based deployment** — declare constraints (soak time, health checks), system plans rollout
53. **Channels** — alpha (10%) → beta (30%) → stable (100%) progression
54. **Soak times** — mandatory wait periods between channel promotions
55. **Automatic rollback** — triggered by KPI breach (error rate, latency, business metric)
56. **Everfox CDS integration** — cross-domain solution for air-gapped networks
57. **Artifact provenance** — every deployment artifact has a signed chain of custody
58. **SBOM generation** — every release includes a Software Bill of Materials
59. **Vulnerability scanning** — pre-deploy vuln check gates promotion
60. **Blue-green + canary** — deploy strategies configurable per service

## Cluster 7 — Gotham (Government Intel)

61. **Data fusion** — combine SIGINT, HUMINT, OSINT, GEOINT into unified graph
62. **HITL targeting** — human always in the loop for lethal decisions
63. **Graph analytics** — link analysis, community detection, influence mapping
64. **Temporal analysis** — event timelines, pattern-of-life detection
65. **Geospatial** — map overlays, area-of-interest monitoring, proximity queries
66. **Classification handling** — data marked at object level, access enforced by clearance
67. **Sensor integration** — real-time feeds from satellites, drones, ground sensors
68. **Mission planning** — collaborative tools for operational planning
69. **After-action review** — structured replay and analysis of completed missions
70. **Interop with allied systems** — standardized data formats for coalition sharing

## Cluster 8 — AIP Security

71. **Reasoning / Executor / Memory isolation** — three separate security domains
72. **No-retention mode** — model sees data but doesn't retain it post-inference
73. **AppSec gates** — security review required before agent deployment
74. **Observability** — real-time monitoring of all agent actions and model calls
75. **Prompt injection detection** — input sanitization + output validation
76. **Memory scoping** — agents can only access memories within their permission scope
77. **Credential isolation** — agents get scoped tokens, never raw credentials
78. **Output filtering** — sensitive data redacted before user-facing display
79. **Audit logs** — immutable, tamper-evident logs of all security-relevant events
80. **Threat modeling** — required before any new agent capability is enabled

## Cluster 9 — Bootcamps

81. **5-day structure** — Day 1 Scope, Day 2 Build, Day 3 Eval, Day 4 Deploy, Day 5 Train
82. **Co-build model** — Palantir engineers work alongside customer engineers
83. **Use-case driven** — start from a real business problem, not generic training
84. **Production by Friday** — goal is a working system by end of week
85. **TCV flywheel** — bootcamp → production → expansion → more bootcamps
86. **Hands-on over slides** — 80% hands-on, 20% instruction
87. **Executive sponsor** — C-level attends Day 1 scoping and Day 5 review
88. **Success criteria defined upfront** — measurable KPIs agreed on Day 1
89. **Post-bootcamp support** — 30-day hypercare period after bootcamp
90. **Reusable templates** — bootcamp playbooks are templatized for different verticals

## Cluster 10 — Observability / Evals

91. **AIP Evals** — automated evaluation of agent performance on golden datasets
92. **p95 / failure monitoring** — real-time alerting on latency and error rates
93. **Data Health** — data quality scoring across all ontology objects
94. **Flow Capture** — record and replay agent flows for debugging
95. **A/B testing** — traffic splitting for comparing agent versions
96. **Regression detection** — automatic comparison against baseline performance
97. **Custom metrics** — define domain-specific metrics (e.g., forecast accuracy)
98. **Dashboard templates** — pre-built observability dashboards for common patterns
99. **Alerting rules** — configurable thresholds with escalation chains
100. **SLO tracking** — service-level objectives measured and reported continuously

## Cluster 11 — Model Management

101. **Multi-LLM support** — GPT-4, Claude, Llama, Mistral, Gemini all available
102. **No-training policy** — inference only, no fine-tuning with customer data
103. **Model version control** — pin specific model versions for reproducibility
104. **Sandboxed inference** — models run in isolated containers with resource limits
105. **A/B model testing** — compare model versions on the same traffic
106. **Fallback chains** — primary model fails → secondary model → deterministic fallback
107. **Token budgeting** — per-agent, per-day token consumption limits
108. **Model cards** — documentation of model capabilities, limitations, biases
109. **Latency optimization** — model routing considers latency requirements
110. **Cost dashboards** — real-time model inference cost tracking per agent/team

## Cluster 12 — TITAN ($178.4M DoD Contract)

111. **10 AI ground systems** — independent deployable AI nodes
112. **Sensor-to-shooter fusion** — real-time sensor data → actionable targeting
113. **DDIL resilience** — works in Denied, Disrupted, Intermittent, Limited environments
114. **Edge inference** — models run on tactical hardware, not cloud
115. **Mesh networking** — nodes communicate peer-to-peer when backbone is down
116. **Rapid deployment** — containerized for quick field deployment
117. **Multi-sensor integration** — radar, EO/IR, SIGINT, COMINT fused
118. **Human-on-the-loop** — AI recommends, human decides on high-stakes actions
119. **Real-time C2** — command and control at mission speed
120. **Interop** — works with existing DoD systems (Link 16, TAK, etc.)

## Cluster 13 — NHS FDP (£330M Healthcare)

121. **Federated Data Platform** — data stays in NHS trusts, platform queries in-place
122. **Privacy by design** — pseudonymization, access controls, consent management
123. **Social license** — public trust requires transparency about data use
124. **Clinical pathways** — data-driven optimization of patient flow
125. **Operational dashboards** — real-time bed occupancy, wait times, staff allocation
126. **Research enablement** — anonymized data available for medical research
127. **Audit trail** — every data access logged and reviewable
128. **Data quality scoring** — flag inconsistencies across trusts
129. **Ethical review** — use cases require ethics board approval
130. **Scalable architecture** — handles 55M+ patient records across 150+ trusts

## Cluster 14 — Financials

131. **Q4-2025: +70% year-over-year revenue growth** — accelerating, not decelerating
132. **GAAP operating margin: 43%** — software gross margins at scale
133. **Rule of 40 = 127%** — revenue growth + profit margin vastly exceeds benchmark
134. **Commercial revenue growing faster than government** — diversified customer base
135. **Net dollar retention > 120%** — existing customers spend more over time
136. **Remaining deal value (RDV) growing** — backlog provides revenue visibility
137. **Customer count growing** — land-and-expand working across verticals
138. **AIP driving acceleration** — AI use cases increasing average deal size
139. **Profitability without revenue sacrifice** — margin expansion + growth simultaneously
140. **Cash flow positive** — self-funding growth without external capital needs

## Cluster 15 — Product Security

141. **Threat modeling** — STRIDE analysis for every new feature
142. **AppSec gates** — automated security checks in deployment pipeline
143. **Supply chain security** — SBOM, dependency scanning, provenance verification
144. **Provenance verification** — signed artifacts with attestation chains
145. **Penetration testing** — regular third-party security assessments
146. **Bug bounty** — coordinated vulnerability disclosure program
147. **Security training** — mandatory annual training for all engineers
148. **Incident response** — documented playbooks for security incident handling
149. **Data encryption** — at-rest and in-transit encryption for all data
150. **Zero-trust networking** — no implicit trust between services

## Cluster 16 — Data / Logic / Action Patterns

151. **Action validations** — every mutation passes through type-safe validation
152. **Functions** — serverless compute (TS/Python) triggered by data events or user actions
153. **Kinetic elements** — actions that affect the real world (orders, deployments, alerts)
154. **Governed writebacks** — every write is audited, approved, and reversible
155. **Idempotent actions** — safe to retry without side effects
156. **Action templates** — reusable action patterns (e.g., "approve order", "escalate case")
157. **Batch actions** — apply action to a set of objects atomically
158. **Conditional logic** — actions can have preconditions and post-conditions
159. **Rollback support** — compensating actions for undoing mutations
160. **Event sourcing** — action history is the source of truth, not current state

## Cluster 17 — Interop & Runtime

161. **Batch / streaming / CDC** — all three ingestion modes supported
162. **Sandboxed applications** — customer-built apps run in isolated environments
163. **Service mesh** — internal communication via service mesh (mTLS, observability)
164. **OSDK** — standardized API layer for all external integrations
165. **Plugin system** — extend platform with custom plugins (data connectors, actions)
166. **Webhook support** — push notifications for ontology change events
167. **REST + GraphQL** — multiple API styles for different consumer needs
168. **gRPC** — high-performance internal communication
169. **Event bus** — pub/sub for asynchronous cross-service communication
170. **API versioning** — backward-compatible API evolution with deprecation policy

## Cluster 18 — Edge & DDIL

171. **Air-gapped deployment** — full platform runs without internet connectivity
172. **BTS (Behind the Shield)** — classified network deployments
173. **Everfox CDS** — cross-domain solution for data movement between classification levels
174. **TITAN offline inference** — tactical AI runs on edge hardware
175. **Data synchronization** — eventual consistency when connectivity restored
176. **Compact packaging** — minimal footprint for edge deployment
177. **Local-first** — edge sites operate independently, sync when connected
178. **Update bundles** — signed update packages for air-gapped environments
179. **Mesh networking** — peer-to-peer data sharing between edge nodes
180. **Graceful degradation** — reduced functionality when disconnected, not failure

## Cluster 19 — Adoption Motions

181. **Bootcamp → production** — fastest path to value (5 days)
182. **Architecture documentation** — detailed system architecture provided to customer
183. **Feedback loops** — structured user feedback → product improvement cycle
184. **Champion development** — identify and enable internal customer champions
185. **Use-case library** — catalog of proven use cases by vertical
186. **Community of practice** — cross-customer knowledge sharing forums
187. **Maturity model** — assess and track customer platform adoption maturity
188. **Success metrics** — defined, tracked, and reported KPIs for each deployment
189. **Executive alignment** — regular strategic reviews with customer leadership
190. **Self-service enablement** — documentation and tooling for customer independence

## Cluster 20 — Narrative Cohesion

191. **AIP + Foundry + Apollo = one OS** — unified narrative, not separate products
192. **Ontology as language** — ontology is how the organization speaks about its data
193. **Platform, not product** — sell capabilities, not features
194. **Data-driven transformation** — technology enables organizational change
195. **Mission focus** — everything tied back to a customer mission or outcome
196. **Trust as competitive moat** — security and compliance as selling points
197. **Long-term partnerships** — multi-year contracts with expansion built in
198. **Vertical expertise** — deep domain knowledge in defense, healthcare, finance, energy
199. **Developer ecosystem** — OSDK enables third-party app development
200. **Compounding value** — more data + more users + more models = exponentially more value

---

## Emulation Matrix — Future Predictor Council

| Palantir Pattern | Our Emulation | Priority |
|---|---|---|
| Ontology (digital twin) | Panel data schema + object registry | P0 |
| Agent Studio (visual flows) | LangGraph orchestrator graph | P1 |
| AIP Evals | Rolling backtest + golden tasks | P0 |
| Apollo channels | Alpha→Beta→Stable release policy | P1 |
| Scenarios (what-if) | DoWhy + EconML causal panels | P0 |
| OSDK typed clients | FastAPI + typed Pydantic models | P1 |
| Bootcamps (5-day) | Arena Bootcamp kit | P1 |
| Air-gapped | Offline-first, one-drop bundles | P2 |
| Observability | Structured traces + metrics dashboard | P1 |
| HITL gates | 5% steering knobs + approval gates | P0 |
| Multi-model routing | Model council with weighted ensemble | P0 |
| Cost dashboards | Burst helper with budget caps | P1 |
| Prompt versioning | Config-driven, version-controlled | P2 |
| Threat modeling | Security officer agent + SBOM/Trivy | P2 |
| Data Health | Data steward agent + validation | P1 |

---

*Doctrine version: 1.0 — derived from public Palantir disclosures, earnings calls, documentation, and community analysis.*
