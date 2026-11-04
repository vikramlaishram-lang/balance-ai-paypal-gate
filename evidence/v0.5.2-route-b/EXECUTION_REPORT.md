# Route B current-build execution report

Date: 2026-11-04

Decision: **PASS within the recorded local scope**

Live PayPal: **NO-GO / not invoked**

QF-01: **INCONCLUSIVE**

The recording used one genuine local `qwen3:8b` structured-proposal inference followed by the frozen v0.5.2 candidate's deterministic fictional-provider restart demonstration.

- Frozen candidate tree SHA-256: `7b7fd99e049fa26970e0753960098cf39fa484a1076acf20ec02c1bf2a61f5e5`
- Manifest files rechecked: 93/93
- Inference: exit 0 in 36.063 seconds
- Fixture runner: exit 0 in 5.032 seconds
- First Gate PID: 44164
- Recovered Gate PID: 5324
- Executor PID: 2624
- Mission: `4543f9e4-3e2e-4f12-bfc7-6a9215648261`
- Fictional order: `FIXTURE-ORDER-0001`
- Fictional capture dispatches: 1
- PayPal API calls: 0

The proposal reported `agent_provider=OLLAMA_LOCAL`, `agent_model=qwen3:8b`, amount `1.00`, currency `USD`, authority `NONE`, and effect `NONE`.

The fictional-provider run established `OUTCOME_UNKNOWN` before restart, recovery by a different Gate process, unchanged mission and order, capture retry `NOT_DISPATCHED`, GET-established `COMPLETED`, one fictional capture dispatch, a valid journal chain, and a matching terminal anchor.

The every-frame-verified 1080p recording is retained outside the repository. Its SHA-256 is `D3D89AF41C7C710A29411850B53A801F17ED7C6161ED970B57F7F5E91F970956`.

This is current-build local evidence with a deterministic fictional payment provider. It is not a PayPal Sandbox transaction, live qualification, production evidence, or a QF-01 PASS. Earlier failed recording attempts were retained and were not represented as successful footage.
