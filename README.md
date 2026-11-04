# Balance AI — PayPal transaction safety gate

Balance AI is a prototype safety layer for AI-initiated PayPal payments. The AI can investigate an invoice and propose an action, but a proposal is not authority. A separate Gate admits only actions that match a Gate-owned trusted invoice and policy, verifies approval over the exact action, commits durable barriers before dispatch, and reconciles uncertain outcomes against the original provider order.

This repository is the judge-facing source snapshot of the **v0.5.2 demo-orchestration development candidate**, derived from the published v0.5.1 Executor-observation candidate. It includes the frozen v0.5 test corpus for provenance. It is not production-ready, does not authorize a payment, and has not completed credential-bearing v0.5.2 live qualification. Historical QF-01 remains **INCONCLUSIVE**.

## Why this exists

An AI-generated payment proposal may contain an injected instruction, the wrong amount, a substituted merchant, or a replacement attempt after a payment outcome becomes uncertain. Balance keeps proposal, approval, execution, and provider observation as separate steps so that model output alone cannot cause a consequential operation.

## Core behavior

- **Proposal is non-authoritative.** The model has proposal and recommendation tools, not payment credentials or approval authority.
- **Trusted invoices are Gate-owned.** Amount, currency, merchant/payee, reference, and operation are checked against trusted state rather than accepted from model text.
- **Unauthorized changes are refused.** The v0.5 diagnostics include injected `$9` proposals that are rejected as trusted-invoice mismatches.
- **Locks survive uncertainty.** After a capture attempt is durably committed, a lost response produces `OUTCOME_UNKNOWN`; a valid-looking replacement is refused because the trusted invoice is locked.
- **Restart does not imply retry.** The Gate reloads durable state and reconciles the original order. It marks the invoice paid only when supported by provider evidence.
- **The lock is scoped.** It is per Gate-owned trusted invoice. This is not a claim of universal duplicate-payment prevention across unrelated invoices, systems, or credentials.

## Architecture

1. A proposal-only agent produces structured intent.
2. The Gate checks the trusted invoice and policy, then records the decision.
3. A non-agent approval is bound to the exact action digest.
4. The Gate commits an attempt barrier and mints a short-lived request-bound token.
5. The Executor validates the token and request before provider dispatch.
6. A separate local collector records observed Executor ingress and pre-dispatch events for test windows.
7. Reconciliation queries the original provider order and establishes the observed outcome.

The collector and Executor in the local v0.5.1 evidence are separate processes under the same Windows account. That improves observability but is not an independently protected trust boundary.

## Five-minute credential-free check

Requirements: Python 3.11+; no third-party packages, PayPal credentials, buyer approval, `.env`, or external network access are required.

```powershell
Set-Location <path-to-cloned-repository>
python -B run_tests.py
```

Expected result for this snapshot: **42 tests, all passing**.

To exercise the v0.5.2 collector lifecycle and effect-free negative matrix:

```powershell
python -B demo_orchestrator.py effect-free-preflight --output-dir "$PWD\out\v052-preflight"
python -B tests\run_v052_effect_free.py --out "$PWD\out\v052-matrix"
```

These commands do not load PayPal credentials, run model inference, request buyer approval, or permit payment dispatch.

To reproduce the observed-Executor fixture exercise in a fresh output directory:

```powershell
python -B tests\run_observed_offline.py --out "$PWD\out\observed-evidence"
python -B tests\audit_observation.py --out "$PWD\out\observed-evidence"
```

This starts loopback-only local services and injects `FixturePayPalSandbox`. It does not load PayPal credentials or instantiate the real PayPal client. Do **not** run `executor_cli.py` for the fixture demonstration.

For a clean-clone sequence, expected results, output files, and explicit claim boundaries, see [`JUDGE_QUICK_START.md`](JUDGE_QUICK_START.md).

## Evidence by version

| Version | What is available | What it establishes | What it does not establish |
| --- | --- | --- | --- |
| v0.3 retained milestone | Sanitized record of a 25 Oct 2026 PayPal Sandbox restart/reconcile run | Historical Sandbox behavior for the earlier recovery design | v0.5 security behavior or v0.5/v0.5.1 live qualification |
| v0.5 frozen candidate | Pinned 48-file source identity; scripted/model diagnostics; integrated fictional fixture logs | Local refusal, lock, re-entry, concurrency, and fixture reconciliation behavior | Full QF-01; independent credential-bearing Executor evidence |
| v0.5.1 development candidate | 42 regression tests and four observed local fixture windows | Production handler path with injected fictional provider and separate collector process | Real PayPal egress, credential-bearing live qualification, protected independent custody |
| v0.5.2 demo-orchestration candidate | Collector-lifecycle wrapper, effect-free Executor preflight, replay audit, and 11-case negative matrix | Local orchestration and fail-closed behavior without payment effects | Live PayPal execution, independent OS-enforced custody, production readiness, or QF-01 PASS |

See [`evidence/EVIDENCE_INDEX.md`](evidence/EVIDENCE_INDEX.md) for artifact-level hashes, provenance, and limitations. [`PUBLICATION_PROVENANCE.md`](PUBLICATION_PROVENANCE.md) maps the v0.5.2 executable additions byte-for-byte to the separately frozen recording candidate.

## Demonstration story

The intended order is:

1. investigate the trusted invoice;
2. show an injected instruction producing an unauthorized `$9` proposal;
3. refuse it;
4. admit the legitimate proposal and attempt the authorized payment;
5. lose the capture response and enter `OUTCOME_UNKNOWN`;
6. refuse a valid-looking replacement after the lock exists;
7. restart the Gate;
8. reconcile the original order and mark the invoice paid only from provider evidence.

The Route B demonstration uses genuine local `qwen3:8b` inference and current-build fictional-provider execution. It is not live PayPal footage. Full uncut evidence remains separate from the edited submission video, and any cuts or speed changes must be visibly labelled. The retained v0.3 Sandbox run may be used only as clearly labelled historical evidence with narrower claims.

## Qualification and safety limits

- QF-01 remains **INCONCLUSIVE**; historical evidence is not reinterpreted.
- v0.5.2 is a separate, unqualified development candidate derived from v0.5.1.
- Local fixture tests are not PayPal-provider evidence.
- Process separation on one user account is not strong isolation.
- A dispatch-begin log does not prove the provider completed an effect.
- The repository includes credential-bearing entry points for architecture completeness; the public demo uses only the fictional fixture path.
- No production-readiness claim is made.

## Repository safety

Do not commit `.env` files, credentials, private keys, buyer data, approval URLs, or raw local evidence containing personal paths. Review [`SECURITY.md`](SECURITY.md) before publication. The release-preparation reports document the local content scan and its limitations.

## License

MIT. See [`LICENSE`](LICENSE).
