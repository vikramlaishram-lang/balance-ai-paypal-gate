# Judge Quick Start

This is a credential-free, loopback-only evaluation of the published development prototype. It does not contact PayPal, create or capture a payment, or change the historical **INCONCLUSIVE** disposition of QF-01.

## Requirements

- Python 3.11 or newer
- PowerShell on Windows, or an equivalent shell
- No third-party Python packages
- No PayPal credentials, `.env` file, buyer approval, or external network access

## Run from a clean clone

```powershell
git clone https://github.com/vikramlaishram-lang/balance-ai-paypal-gate.git
Set-Location .\balance-ai-paypal-gate
python -B run_tests.py
python -B tests\run_observed_offline.py --out "$PWD\out\judge-observed"
python -B tests\audit_observation.py --out "$PWD\out\judge-observed"
```

Expected published-snapshot results:

- regression suite: `42 tests, all passing`;
- observed fictional-provider exercise: four completed windows;
- observation audit: PASS;
- PayPal API calls: none.

The observed exercise starts loopback-only services and injects `FixturePayPalSandbox`. Do not use `executor_cli.py` for this fixture demonstration.

## What to inspect

- `out/judge-observed/observation_report.json`
- `out/judge-observed/executor_collector_events.jsonl`
- `evidence/EVIDENCE_INDEX.md`
- `evidence/HASH_CORRECTION_2026-11-04.md`

## Claim boundaries

- The current local demonstration uses a fictional provider and is not a PayPal transaction.
- The retained 2026-10-25 PayPal Sandbox evidence is historical and version-scoped; its file labels identify an earlier v0.2-era candidate within the retained v0.3 milestone.
- The published source is a v0.5.1 Executor-observation development candidate, not a production-ready release and not a credential-bearing live qualification.
- QF-01 remains **INCONCLUSIVE**.
