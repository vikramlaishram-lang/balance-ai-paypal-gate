# v0.5.2 publication provenance

The 2026-11-04 Route B recording used the separately frozen `v0.5.2-demo-orchestration` candidate whose 93-file manifest produced aggregate tree SHA-256 `7b7fd99e049fa26970e0753960098cf39fa484a1076acf20ec02c1bf2a61f5e5`.

This public repository is a judge-facing publication snapshot, not that private evidence directory. The executable v0.5.2 additions below are byte-identical to the frozen recording candidate. Publication-only documentation, the evidence-hash correction ledger, and sanitized evidence were added separately.

| File | Frozen/public SHA-256 |
| --- | --- |
| `executor_cli.py` | `C5649C4EE17F4AEE77ADB534061A90CA5CF63DDFAF6D0520C3D05BD4012CA2F6` |
| `audit_v052_collector.py` | `6FBD72473144E304BF801695FE7BDFD50213605221AED0A718E877EBFC5DE1C4` |
| `balance_paypal/collector_audit.py` | `5032E441BCFE5271E0AFE6D3C60AF24F4A6EFEB5BD36DB913AC68064CA6A9132` |
| `balance_paypal/demo_orchestration.py` | `50C3BE0978B7A82053D3D2283A03C95919588FC13493171264D544166AAFEC74` |
| `demo_orchestrator.py` | `2E0F56A99D80A24C45186339B6CFA652B6B0856BD62F47F5C961A0E20651F2DD` |
| `tests/run_v052_effect_free.py` | `A28927F9E0AFDE5E03A52D55CD8EAC41A850E077101149E44DA506E7029D4A45` |
| `V052_BASELINE.json` | `DBF2816AC664636DC8A0D5E026BEAB2C836F84256268C68272F718FA559BE0BD` |
| `V052_OPERATOR_RUNBOOK.md` | `CB11B402B0B511388D43FCAE3DAD549D7E777BC744D910A66018DF6A641E4195` |

The recording established genuine local `qwen3:8b` proposal inference and deterministic fictional-provider execution. It made no PayPal API call and did not authorize a payment. QF-01 remains **INCONCLUSIVE**.
