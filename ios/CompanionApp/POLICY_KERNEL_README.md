PolicyKernel — README (starter)

Purpose
- Explain the PolicyKernel API, where to add tests, and how to wire it into the ActionRouter.

Key files
- PolicyKernel.swift — pure logic; no network IO; unit-test heavy
- ActionRouter.swift — execution entry point that calls PolicyKernel
- Tests/* — add PolicyKernel unit tests here (deny/no-provenance, killswitch, council gating)

Developer notes
- Keep PolicyKernel deterministic and pure so tests can be run offline in CI.
- Any change to PolicyKernel must include unit tests and a CI policy-gate update.

Quick test list (priorities)
- testAuthorize_deniesExecuteWhenKillSwitchEngaged
- testAuthorize_deniesExecuteWithoutProvenance
- testAuthorize_requestsCouncilWhenRiskTierHigh
- testAuthorize_requiresConsentForSensitive

How to wire into the app
1. Construct KillSwitchService & ModalityRegistry implementations.
2. Instantiate PolicyKernel(killSwitch:..., modalityRegistry:...)
3. Inject into ActionRouter during app startup (AppDelegate / CompanionApp.swift)

CI Gate
- Add PolicyKernel unit tests to the PR pipeline. PolicyKernel regressions must block merge.

