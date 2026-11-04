# v0.5.2 demo-orchestration candidate

This directory is a separate development candidate based on the published v0.5.1 commit
`e1ca697ae0e943755a3711993d87906176fdb381`. It adds an external collector-lifecycle
wrapper, a credential-free Executor preflight mode, independent collector replay, and an
effect-free negative-test matrix. It was promoted into the public judge-facing repository
without changing the frozen v0.5 evidence or reinterpreting historical results.

Quick effect-free check:

```powershell
python -B demo_orchestrator.py effect-free-preflight --output-dir out\new-preflight
python -B tests\run_v052_effect_free.py --out out\new-matrix
python -B run_tests.py
```

Effect-free PASS is not live authorization. No PayPal API call or model inference is
required by these commands. See `V052_OPERATOR_RUNBOOK.md` for the explicit live effects
boundary and incomplete-window recovery rules. Historical QF-01 remains INCONCLUSIVE.
