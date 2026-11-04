# Historical public-copy hash correction — 2026-11-04

This correction is additive. It records three values that were published in `EVIDENCE_INDEX.md` at commit `e1ca697ae0e943755a3711993d87906176fdb381`, alongside the SHA-256 values independently recomputed from the repository bytes on 2026-11-04.

No affected evidence file was edited to make a hash match. The index was corrected to match the retained public copies. This record does not change the version boundaries, qualification claims, or the historical **INCONCLUSIVE** disposition of QF-01.

| Public artifact | Previously published value (erroneous) | Recomputed public-copy SHA-256 |
| --- | --- | --- |
| `v0.3-retained-sandbox/LIVE_SANDBOX_EVIDENCE.json` | `B1F20547E63DB7C02616B307F1A96BA0EB1CE3A9AF6A71996CB76A7320C93ED6` | `BBA7023A5CFAE6EBF476F07B690D9B11E45E2F085B6F7702DC0E65B9160C6DD3` |
| `v0.3-retained-sandbox/VERIFICATION_REPORT.md` | `A4C3A6F646546D91F5678F57532D960596A273B1ED875456DFC28DC58B23763F` | `F613E76C1BA6F6B64F4501AFE276A9FE0B25F66659791FC71574698A2136DC01` |
| `v0.3-retained-sandbox/CANDIDATE_BOUNDARY.json` | `07953266DBAC9231ACA972FB5F1DBE5B8D1B945F2FAFBB1B129D9D002AFD586B` | `CA2EEBE5D5EC63CE66B4C2AA8157DDBC4EEBE94E6A89B2E5D6C531B7CDBEA778` |

## Reproducible check

From the repository root in PowerShell:

```powershell
Get-FileHash -Algorithm SHA256 -LiteralPath `
  'evidence\v0.3-retained-sandbox\LIVE_SANDBOX_EVIDENCE.json', `
  'evidence\v0.3-retained-sandbox\VERIFICATION_REPORT.md', `
  'evidence\v0.3-retained-sandbox\CANDIDATE_BOUNDARY.json'
```

The reason the earlier index values diverged from the retained public-copy bytes has not been established. This correction therefore makes no unsupported causal claim.
