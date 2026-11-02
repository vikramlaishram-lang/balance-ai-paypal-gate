# Balance Gate PayPal v0.5.1 — Executor observation development candidate

**Status:** separate successor development candidate, not an approved or qualified release. QF-01's historical verdict remains **INCONCLUSIVE**. Frozen v0.5 (48 files) is unchanged. **No PayPal transaction, live run, or buyer approval is authorized by this package.**

## Purpose and exact changes

1. The original `executor_cli.py` is the **credential-bearing Executor HTTP entrypoint**. This successor modifies that specific file (not the Gate) to require an active external collector window when starting. It preserves the original token-bound execution implementation.
2. `balance_paypal/observed_executor.py` wraps the real Executor ingress and each provider method. It sends request-received and pre-dispatch events to a separately running collector and waits for an acknowledgment **before provider call**. Missing collector or wrong window fails closed before dispatch. Outcomes/events after dispatch may be uncertain when logging is lost.
3. `collector_cli.py` is a collector with separately owned window IDs, explicit window opening/closing, monotonic timestamps and fsync-backed hash-chained JSONL events. Events are recorded by a separate process, rather than inferred from the Gate's own `NOT_DISPATCHED` field.
4. `tests/observed_fixture_server.py` uses the production `executor_cli.handler_for` and the original `TokenBoundExecutor`, but injects the in-memory `FixturePayPalSandbox`. It **does not** import `PayPalSandboxClient` or load PayPal credentials. This test-only server is not the credential-bearing runtime.
5. `tests/run_observed_offline.py` starts collector and observed fixture Executor as separate local processes, runs two positive requests (CREATE and GET) and three negative controls: bad token, wrong window and no-request window. `tests/audit_observation.py` separately verifies chain, event correlation and per-window counters from raw files.

**Original v0.5 contract/test files have not been modified.** The old `qf01_qualification.py` binding still pins v0.5 and is NOT a valid qualification for this changed v0.5.1 candidate. New source pinning and complete frozen-contract local acceptance are required before any live consideration.

## What the proof does NOT establish

- The local test uses a **fictional in-memory provider**, not the actual PayPal Sandbox client or credential-bearing process. The production entrypoint and dispatch wrapper code are exercised via injected dependency, but real PayPal calls are not.
- The collector and Executor run under the same local OS user during this development test. Separate processes and hash-chained files do not by themselves create an independently protected OS permission boundary or prevent coordinated tampering, forged events, or out-of-band PayPal calls.
- The source code cannot prove that an unseen process or bypass path did not perform dispatch. Real QF-01 needs independent Executor-produced request and dispatch evidence with established collector health/window boundaries, external egress/credential boundaries, and custody for the particular test window. Explicitly observe every forbidden CREATE, CAPTURE and GET path, as required by the frozen contract.
- Test B's full independently evaluated non-lock predicates (digest, approval, timing, etc.) are not closed by this instrumentation. The original frozen contract byte hash remains externally declared, not locally reverified.
- Even when the collector receives a `PROVIDER_DISPATCH_BEGIN` event, it does **not** prove the provider completed the effect. A missing event after a dispatch is uncertainty, not permission to retry.

## Windows PowerShell — offline local execution only

Extract the archive to a new directory, **not on top of v0.5**. In normal PowerShell:

```powershell
$root = Join-Path $env:USERPROFILE 'Documents\Codex\PAYPAL_MANUAL_REVIEW'
$archive = Join-Path $root 'Balance_PayPal_Gate_v0.5.1_Executor_Observed_CANDIDATE.zip'
$target = Join-Path $root 'v0.5.1-observed-candidate'
if (Test-Path $target) { throw 'STOP: Destination already exists' }
Expand-Archive -LiteralPath $archive -DestinationPath $target
Set-Location $target
python -B run_tests.py
if ($LASTEXITCODE -ne 0) { throw 'STOP: Regression failure; preserve output' }
$out = Join-Path $root ('v051-observed-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
python -B tests\run_observed_offline.py --out $out
if ($LASTEXITCODE -ne 0) { throw 'STOP: Offline observed test failed; preserve $out' }
python -B tests\audit_observation.py --out $out
if ($LASTEXITCODE -ne 0) { throw 'STOP: Offline evidence audit failed; preserve $out' }
Write-Host 'Offline evidence:' $out
```

The local test launches two loopback services itself on ephemeral ports; no PayPal credentials or approval are requested. In an uncertain environment with active external networking hooks, isolate this local test at the OS level if independent no-egress proof is needed. Source scripts make no intentional PayPal calls; Python guards are not equivalent to OS firewall proof.

**Do not** run `executor_cli.py` or configure real payment credentials as part of this pre-live step.

## Additional tests required before a complete QF-01 successor verdict

- Independent operator verifies source/candidate hashes and full QF-01 contract bytes.
- Repeat frozen A–H, scripted negative controls, model-generated legitimate controls, and adversarial corpus on separately pinned v0.5.1 with all required independent Executor logs and full B non-lock predicate evidence.
- Prove pre-dispatch refusal during missing collector, log corruption, wrong window, replay and collector outage, with corresponding non-mutated positive controls. Verify collector starts READY before the test window and attach precise endpoints and process identities.
- For any real PayPal Sandbox run, explicitly approve **fresh** $1 test action and its separate scope only after all pre-live qualification gates. Do not reuse previous approvals or treat this code as consent.
