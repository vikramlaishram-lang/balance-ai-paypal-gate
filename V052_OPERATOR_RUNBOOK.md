# Balance PayPal v0.5.2 demo-orchestration operator runbook

This runbook applies only to the separately pinned `v0.5.2-demo-orchestration`
candidate derived from commit `e1ca697ae0e943755a3711993d87906176fdb381`.
It does not change the historical QF-01 disposition: **QF-01 remains INCONCLUSIVE**.

## 1. Preparation (read-only)

1. Verify the extracted candidate against `V052_SOURCE_SHA256_MANIFEST.json`.
2. Keep PayPal credentials, the Gate token key, the approver key, and the anchor
   directory outside the candidate and outside every evidence bundle.
3. Do not print or inspect credential or private-key contents during preparation.
4. Confirm the configured account is PayPal Sandbox only. The candidate refuses any
   `PAYPAL_MODE` other than `sandbox` and pins `https://api-m.sandbox.paypal.com`.
5. Run the configuration preflight. It checks only path metadata, loopback Ollama tags,
   the expected `qwen3:8b` name, port availability, static Sandbox enforcement, and
   candidate identity. It performs no inference and no PayPal request.

```powershell
python -B demo_orchestrator.py config-preflight --output config-preflight.json
```

A missing external path, unavailable Ollama endpoint, missing `qwen3:8b`, occupied port,
or identity mismatch is a **live NO-GO**. Do not compensate by placing secrets in the
candidate or downloading/installing anything without separate operator authorization.

## 2. Effect-free qualification

Choose a new, empty evidence directory for every run:

```powershell
python -B demo_orchestrator.py effect-free-preflight `
  --output-dir evidence-runs\effect-free-YYYYMMDDTHHMMSSZ
```

Acceptance conditions:

- the collector starts as a separate process and reports its process identity;
- the collector opens and returns its own window ID;
- `executor_cli.py --effect-free-preflight` reports that exact ID;
- an invalid execution token produces one independently collected ingress and refusal;
- create, capture, and get dispatch counters remain zero;
- the fictional provider tripwire remains zero;
- the window closes and independent replay validates the hash chain and counters.

This command does not load PayPal credential files, instantiate `PayPalSandboxClient`,
request buyer approval, run Ollama inference, or consume payment authorization.

## 3. Explicit payment authorization boundary

Stop after effect-free qualification unless a human operator separately authorizes a
PayPal Sandbox demonstration. The `--permit-live-run` flag is an explicit effects
boundary: supplying it permits the existing runner to request model inference, create a
Sandbox order, request buyer approval, capture, and reconcile according to its prompts.

Before crossing that boundary, confirm all of the following:

- the configuration preflight is live-ready;
- the source manifest is the approved manifest;
- a clean, empty evidence directory is reserved;
- the collector and Executor ports are free;
- the operator understands that local process separation is not protected independent
  custody and does not establish QF-01;
- no earlier approval or authorization is being reused.

## 4. Live demonstration (not executed by this qualification)

The wrapper opens one collector-owned window, binds an effect-free Executor reachability
probe to that exact window, stops the probe, and then invokes the existing `live` runner
with the same window binding. Console output remains visible and is simultaneously saved
as `runner.stdout.txt`.

```powershell
python -B demo_orchestrator.py live --permit-live-run `
  --evidence-dir evidence-runs\live-YYYYMMDDTHHMMSSZ -- `
  --payee-id SANDBOX_MERCHANT_ID --amount 1.00 --currency USD `
  --approval-wait-seconds 300
```

The runner still requires its own exact `APPROVE` and `PAYER APPROVED` confirmations.
On successful termination, the wrapper ends the collector window and replays it. On a
crash, timeout, runner error, or collector failure, the wrapper intentionally leaves the
window **INCOMPLETE** and preserves the log. It does not invent a terminal receipt.

## 5. Interrupted-run recovery and reconciliation

Never silently retry a CREATE or CAPTURE after an uncertain outcome. Retain the original
evidence directory unchanged. A recovery invocation must point to that retained
`INCOMPLETE` state and uses a fresh collector-owned window; the new state explicitly
links the prior window ID instead of pretending to reuse or replace it.

```powershell
python -B demo_orchestrator.py resume-live --permit-live-run `
  --prior-evidence-dir evidence-runs\live-INTERRUPTED `
  --evidence-dir evidence-runs\resume-YYYYMMDDTHHMMSSZ -- `
  --run-dir ORIGINAL_RUN_DIRECTORY --expected-order ORIGINAL_SANDBOX_ORDER_ID `
  --approval-wait-seconds 300
```

Reconciliation must query only the original order recorded by the Gate. If the retained
state does not prove the original mission/order binding, stop and classify the recovery
as INCONCLUSIVE. Do not create a replacement order to make the demonstration pass.

## 6. Post-run evidence handling

1. Preserve `orchestration-state.json`, `collector.jsonl`, process stdout/stderr, the
   runner transcript, and the runner's own evidence directory.
2. Replay each collector log independently:

```powershell
python -B audit_v052_collector.py evidence-runs\RUN\collector.jsonl
```

3. Treat `INCOMPLETE` as incomplete even when the partial hash chain is valid.
4. Verify the source manifest again and record the final evidence hashes.
5. Secret-scan before publication and perform a credential-free clean-clone fixture test.
6. Keep fictional fixture evidence distinct from historical PayPal Sandbox evidence.
7. Do not claim production readiness, v0.5.2 live qualification, or QF-01 PASS from an
   effect-free result.
