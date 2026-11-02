# Balance Gate v0.2 verification report — 25 October 2026

## Reference inspection

The build began with a read-only inspection of these adjacent Balance artifacts:

- Productization Blueprint v0.1
- OpenAPI v0.2
- contract-to-test conformance matrix v0.1
- P1 contract closure matrix v0.2
- P1 specification freeze and approval record
- CANDIDATE01/QUAL01 package boundary and binding records

The milestone adopts the relevant separation of proposal, approval, dispatch receipt, observation, reconciliation, and completion. It is a separate hackathon candidate and does not claim conformance certification for the full OpenAPI surface.

## Automated result

Command:

```powershell
python -I -B run_tests.py
```

Final result for the current Gate/Executor suite: **27 tests passed, 0 failed**.

Archived v0.1 regression checks remain in the source tree for provenance but are deliberately
excluded by `run_tests.py`; their capture-retry policy is superseded by the permanently latched
v0.2 Gate barrier.

The expanded suite includes deterministic coverage for structured local-model output, pure/read-only typed MCP tools, policy admission, signed act-digest approval, short-lived execution tokens, request-body mismatch refusal, immutable event rows, provider time evidence, governed-versus-naive contrast, mutation conformance, reconciliation outcomes, and capture concurrency.

Covered behaviors include:

- proposal causes no PayPal effect;
- admissibility and decision are separate fields;
- signed non-agent approval is bound to amount, currency, payee, and reference through the act digest;
- a valid token for a different request body or act digest is refused before dispatch;
- proposal and order idempotency;
- idempotency conflict refusal;
- Sandbox-only endpoint enforcement and live-mode refusal;
- payer approval before capture;
- normal capture remains unestablished until GET reconciliation;
- controlled lost-confirmation recovery by original order ID;
- capture re-entry and process restart never send a second capture;
- an agent can recommend reconciliation, but the typed tool returns `permission: false` and `NOT_DISPATCHED`;
- the capture barrier remains latched even when GET proves no capture; another payment requires a new signed mission;
- lost create response is separately eligible for same-request-ID replay inside the documented six-hour window;
- pending capture, declined/failed capture, approved-with-no-capture, and voided/expired order outcomes produce explicit decisions;
- two concurrent capture callers produce one provider capture POST;
- cross-mission observation rejection;
- journal hash-chain verification;
- complete CLI fixture story without credentials or network;
- schema-constrained AI intent interpretation with proposal-only authority;
- clarification without mission/payment creation;
- malformed model-output refusal and remote model-endpoint refusal;
- one actual stdio MCP exchange from client to a pure tool server, with no database created;
- a three-moment fixture covering GET-established completion, agent retry refusal, and wrong-digest token refusal;
- four mutation variants, each detected by the scenario it breaks;
- a 20-case four-fault deterministic model in which the naive policy duplicates 20/20 times while the governed policy duplicates 0/20 times.
- a one-command restart demonstration in which the first Gate process exits at
  `OUTCOME_UNKNOWN`, a second process recovers the same mission and order from SQLite,
  redispatch is refused, GET establishes `COMPLETED`, and the journal and anchor verify.

## Restart-runner result

Command:

```powershell
python -I -B demo_runner.py fixture
```

The verified deterministic run used three distinct roles: an Executor process, a first Gate
process that committed the capture barrier and dropped the fixture response, and a second Gate
process that recovered the same SQLite mission. The second process observed
`capture_attempted=true`, returned `NOT_DISPATCHED` for capture re-entry, and reconciled the
original fixture order to `COMPLETED`. One capture dispatch event was present, the event chain
verified, and the terminal anchor matched.

This runner uses fixture model output and a fixture PayPal provider. It tests real local
process separation, persistence, barriers, tokens, decisions, and verification; it does not
claim live PayPal or live-model evidence. Its live subcommand is available for an interactive
Sandbox rerun and writes a separately classified, credential-free evidence record.

## Deterministic story result

The offline governed story ended with:

- state immediately after response drop: `OUTCOME_UNKNOWN`;
- state after original-order GET: `COMPLETED`;
- fixture create calls: `1`;
- fixture capture calls: `1`;
- journal chain: valid.

The four-fault model ended with 40 naive captures versus 20 governed captures across 20 cases. Classification: `DETERMINISTIC_INJECTED_FAULT_MODEL_NOT_PAYPAL_EVIDENCE_NOT_T5`. It demonstrates the intended policies under a controlled model and is not empirical evidence about PayPal or model reliability.

## Live Sandbox result

The separated runtime was executed on 25 October 2026 with local Ollama `qwen3:8b` and
PayPal Sandbox. The model produced the typed USD 1.00 proposal and later recommended
`RECONCILE` with no authority or dispatch. PayPal created an order (identifier redacted from this public copy); the
controlled capture-confirmation drop produced `OUTCOME_UNKNOWN`; capture re-entry was
`NOT_DISPATCHED`; and GET of that original order established `COMPLETED` with a capture
(identifier redacted from this public copy). A valid token bound to another act digest was separately refused before
any provider call.

The journal contained 16 events, recomputed successfully, and matched terminal anchor head
`156c8c66f26774d469d0cc212aa09344dd3ccc3667853d2b38acf88b2094ee05`.
`LIVE_SANDBOX_EVIDENCE.json` records the credential-free evidence. No client secret, OAuth
token, Sandbox password, approval URL, or payer identifier is included.

A temporary local Executor outage during the pre-capture GET correctly left the mission at
`OUTCOME_UNKNOWN` with `HOLD_FOR_REVIEW` and `capture_attempted=false`. After the Executor was
restarted, repeating GET established payer approval. This is useful failure-safety evidence,
not a PayPal defect.

PayPal's own idempotency remains the primary create-retry control: the implementation keeps the same `PayPal-Request-Id`, and the documented Orders default retention is six hours. The capture lock is never released for the same mission. Balance's additional claim is limited to policy, signed approval, durable barriers, token/body binding, longer-lived local state, and verification from the original order. The SQLite hash chain is not independently tamper-evident unless its terminal head is anchored under a separate principal. PayPal credential read-only capability remains unestablished; GET and writes share the credential-holding Executor under the trusted-host assumption.

## Preserved artifacts

The final SHA-256 recheck matched the inspection baseline:

| Protected artifact | SHA-256 |
| --- | --- |
| CANDIDATE01 package | `0EE394F4D00B7BEF7A90FEDFCD91D0861FA5FFEFFCB057BBFB5D359A075C24EF` |
| QUAL01 evidence package | `878C26F2AB33C86E3F58C1F41CE1F711E7651991CB380108F8C6CD584E4022D8` |
| E01 v0.1 package | `86732B375E5B65A9ED5A363A5E91D7C45DA25685B79247F2A2CE8089A7CA3F1C` |
| H02 inspection package | `5BEF53578DA83E164C03EFE021FF6A7CB0142E53096AD509CB9C32439DD9C74E` |

T4 was not opened or modified. T5 was not run.

