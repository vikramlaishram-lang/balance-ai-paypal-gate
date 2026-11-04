# Evidence hash canonicalization — 2026-11-04

This additive record corrects and explains the earlier evidence-index discrepancies without deleting either published history or any evidence file.

The repository had no `.gitattributes` rule for evidence. On Windows, `core.autocrlf` produced CRLF checkout bytes, while Git stored and GitHub served LF bytes. A local `Get-FileHash` therefore disagreed with GitHub raw/archive bytes even though the evidence content had not changed.

At commit `e1ca697ae0e943755a3711993d87906176fdb381`, the first three index values already matched the committed Git blobs. Commit `116e7695db7cb72014a9b41d088307f0fae1cb4c` replaced them with hashes of the CRLF checkout after treating the mismatch as an unexplained error. That first correction remains preserved in `HASH_CORRECTION_2026-11-04.md`; it is not rewritten or hidden.

The v0.5 and v0.5.1 rows had the inverse problem: their published index values matched CRLF checkout bytes rather than the committed blobs. The table below preserves every value and establishes one public definition: the SHA-256 of the committed blob, equivalent to GitHub raw/archive bytes.

| Public artifact | Value published before canonicalization | Canonical committed-blob SHA-256 | History |
| --- | --- | --- | --- |
| `v0.3-retained-sandbox/LIVE_SANDBOX_EVIDENCE.json` | `BBA7023A5CFAE6EBF476F07B690D9B11E45E2F085B6F7702DC0E65B9160C6DD3` | `B1F20547E63DB7C02616B307F1A96BA0EB1CE3A9AF6A71996CB76A7320C93ED6` | The canonical value was originally published at `e1ca697`; `116e769` substituted the CRLF-checkout hash. |
| `v0.3-retained-sandbox/VERIFICATION_REPORT.md` | `F613E76C1BA6F6B64F4501AFE276A9FE0B25F66659791FC71574698A2136DC01` | `A4C3A6F646546D91F5678F57532D960596A273B1ED875456DFC28DC58B23763F` | The canonical value was originally published at `e1ca697`; `116e769` substituted the CRLF-checkout hash. |
| `v0.3-retained-sandbox/CANDIDATE_BOUNDARY.json` | `CA2EEBE5D5EC63CE66B4C2AA8157DDBC4EEBE94E6A89B2E5D6C531B7CDBEA778` | `07953266DBAC9231ACA972FB5F1DBE5B8D1B945F2FAFBB1B129D9D002AFD586B` | The canonical value was originally published at `e1ca697`; `116e769` substituted the CRLF-checkout hash. |
| `v0.5-frozen/integrated-fixture/local_integrated_report.json` | `BF31CB0A22A754BAA42F2C634CF2433AC0991B628BC0799C1FB87ECAB34698D9` | `54BFCB565090F8621F097F41B48063CFBD68BFD0ACE1250CA41F94B2188CF771` | The prior value was the CRLF-checkout hash. |
| `v0.5-frozen/integrated-fixture/fixture_executor_events.jsonl` | `D6E7BE271D13FE5D666099F0434A38A221CEFEFCBF52C20D6A2CBB89BCAC7A16` | `E2F1BABCBBDB0ABC75BCA4432B307B8B3D16E6EEDBC75DBB300C29D2AABFE78B` | The prior value was the CRLF-checkout hash. |
| `v0.5-frozen/supplementary-scripted/diagnostic_report.json` | `C692E04D3AD8742181A1023107F613A275B52D532F5D92335CA6CE0EBA36D90F` | `8067EE46BE25DFA8D3256C69682EC3DF8E04BA1A3081924CC376C2613E28D661` | The prior value was the CRLF-checkout hash. |
| `v0.5-frozen/supplementary-model/diagnostic_report.json` | `4C179D747CD089DC40FA1E87D40F30F22F1DDD5040BCEC6D42A81EECD81C4755` | `DFAF6D5D5AF658C546D2F2B73103BFA4BAD6CFD889BA25D7B4FDE158688C96CD` | The prior value was the CRLF-checkout hash. |
| `v0.5.1-observed/observation_report.json` | `43D26EFA27E9DC02DC6FEEB04D05A10D25DE7A6029C3EC026C81526E34687B92` | `25F0110A3D9A41BE6FFAA886F5FA4B1B73A110937D0E26406B5592C676C3A53E` | The prior value was the CRLF-checkout hash. |
| `v0.5.1-observed/executor_collector_events.jsonl` | `136FBBC1926D9548B7B005FB28680769EBA05D207E76824A793104BB88FDBFE4` | `BF3DC507685B254FAF911C2D78DF9E3F3B449BE71F49A7ACCF0CECCBC3784991` | The prior value was the CRLF-checkout hash. |

## Reproducible check

The following example hashes the committed bytes rather than a line-ending-converted checkout:

```powershell
python -c "import hashlib, subprocess; p='evidence/v0.3-retained-sandbox/LIVE_SANDBOX_EVIDENCE.json'; print(hashlib.sha256(subprocess.check_output(['git','show','HEAD:'+p])).hexdigest().upper())"
```

`.gitattributes` now pins `evidence/**` to LF, so a fresh normal checkout also reproduces the canonical values with `Get-FileHash`.

No evidence file was edited during either correction. Version boundaries and qualification dispositions are unchanged. QF-01 remains **INCONCLUSIVE**.
