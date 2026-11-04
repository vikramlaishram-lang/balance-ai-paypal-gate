# Evidence index

This index separates versions and experiment types. Results from different versions must not be presented as one continuous live experiment. Historical QF-01 remains **INCONCLUSIVE**.

| Artifact | Version | Experiment type | Test date | Result | Public-copy SHA-256 | Qualification limitations |
| --- | --- | --- | --- | --- | --- | --- |
| `v0.3-retained-sandbox/LIVE_SANDBOX_EVIDENCE.json` | v0.3-era retained milestone (file labels candidate v0.2) | PayPal Sandbox restart/reconcile record | 2026-10-25 | Historical run recorded as completed | `BBA7023A5CFAE6EBF476F07B690D9B11E45E2F085B6F7702DC0E65B9160C6DD3` | Sanitized public copy; supports the earlier recovery story only; not v0.5/v0.5.1 qualification |
| `v0.3-retained-sandbox/VERIFICATION_REPORT.md` | v0.3-era retained milestone | Deterministic suite, restart runner, and historical Sandbox narrative | 2026-10-25 | 27/27 deterministic tests reported; Sandbox run described | `F613E76C1BA6F6B64F4501AFE276A9FE0B25F66659791FC71574698A2136DC01` | Historical report; identifiers redacted; broader claims must remain version-scoped |
| `v0.3-retained-sandbox/CANDIDATE_BOUNDARY.json` | v0.3-era retained milestone | Candidate boundary | 2026-10-25 | Boundary recorded | `CA2EEBE5D5EC63CE66B4C2AA8157DDBC4EEBE94E6A89B2E5D6C531B7CDBEA778` | Public copy redacts order/capture identifiers |
| `v0.5-frozen/integrated-fixture/local_integrated_report.json` | v0.5 frozen | Separate-process fictional fixture integration | 2026-11-02 | 10/10 windows PASS | `BF31CB0A22A754BAA42F2C634CF2433AC0991B628BC0799C1FB87ECAB34698D9` | Synthetic provider; same host/account; not production Executor CLI or PayPal network evidence; full B predicate remains incomplete |
| `v0.5-frozen/integrated-fixture/fixture_executor_events.jsonl` | v0.5 frozen | Window-scoped fixture Executor log | 2026-11-02 | One fictional CREATE, one CAPTURE, two GET dispatches; negative windows zero | `D6E7BE271D13FE5D666099F0434A38A221CEFEFCBF52C20D6A2CBB89BCAC7A16` | Independent local fixture logging, not independent PayPal-provider evidence |
| `v0.5-frozen/supplementary-scripted/diagnostic_report.json` | v0.5 frozen | Scripted unauthorized-proposal diagnostic | 2026-11-02 | 10/10 rejected | `C692E04D3AD8742181A1023107F613A275B52D532F5D92335CA6CE0EBA36D90F` | Gate-only synthetic observer; no provider dispatch authority; local path redacted |
| `v0.5-frozen/supplementary-model/diagnostic_report.json` | v0.5 frozen | Local-model adversarial and legitimate diagnostics | 2026-11-02 | 10/10 adversarial rejected; 10/10 legitimate admitted | `4C179D747CD089DC40FA1E87D40F30F22F1DDD5040BCEC6D42A81EECD81C4755` | Supplementary model evidence; synthetic observer; local path redacted; not a complete QF-01 run |
| `v0.5.1-observed/observation_report.json` | v0.5.1 development candidate | Observed production-handler path with injected fixture provider | 2026-11-02 | Four windows completed; supplementary local PASS | `43D26EFA27E9DC02DC6FEEB04D05A10D25DE7A6029C3EC026C81526E34687B92` | Credential-free fictional provider; same OS account; no Gate A–H retest; no credential-bearing live run |
| `v0.5.1-observed/executor_collector_events.jsonl` | v0.5.1 development candidate | Hash-chained collector log | 2026-11-02 | 18 records; replay reported PASS | `136FBBC1926D9548B7B005FB28680769EBA05D207E76824A793104BB88FDBFE4` | Pre-dispatch observation does not prove provider completion; local custody is not protected independence |

## Source and archive provenance

| Private/original artifact | SHA-256 | Note |
| --- | --- | --- |
| Frozen v0.5 candidate aggregate | `BA432AB8B7B38A522D8FD2C2C3F65920F63CEA0EF8CE6F669DF8D5762CF9649C` | 48 manifest-listed files reportedly matched their pins |
| v0.5.1 source archive | `2C6DAF2B37577073B6E3F53AC80A697864FA429DB489EB651B6029145F335E5C` | Verified before public staging extraction |
| v0.5 pinned-source review archive | `B9CF0B0BB4B9CF9BECD083FD69B2440879CC823898BE4DCDF1AF3BE7DA84E915` | Private provenance archive; not copied into the public repository |
| v0.5 integrated evidence archive | `FF5A717163E2276FBFB2915E83CC82CDE3F46BE63C8B43822841B9D74C3E4D0D` | Private provenance archive; selected text evidence copied above |
| v0.5.1 Windows Executor evidence archive | `260096940EEBBE9E8EB7D78C628E7CCC1FB35C19E5C2FFC01C09786D10731C55` | Private provenance archive; selected text evidence copied above |

## Redaction provenance

| Artifact | Original SHA-256 | Public-copy SHA-256 | Transformation |
| --- | --- | --- | --- |
| `LIVE_SANDBOX_EVIDENCE.json` | `7FF6AA55715346AA4B4494BD063232CF50EAFE06EC93A3F7731993753056A22D` | `BBA7023A5CFAE6EBF476F07B690D9B11E45E2F085B6F7702DC0E65B9160C6DD3` | Mission, order, and capture identifiers replaced with explicit redaction markers |
| `VERIFICATION_REPORT.md` | `834DDCD9C92B8609D50FAC47B740112DE13D86461570F95AC89BFDC829A9B732` | `F613E76C1BA6F6B64F4501AFE276A9FE0B25F66659791FC71574698A2136DC01` | Order and capture identifiers removed from the historical narrative |
| `CANDIDATE_BOUNDARY.json` | `901A0FDAA8A1E77EDC39DD52C5E54A435A49A056ED680C73859834D2D4022DCF` | `CA2EEBE5D5EC63CE66B4C2AA8157DDBC4EEBE94E6A89B2E5D6C531B7CDBEA778` | Embedded order/capture claim string replaced with a redaction marker |

No raw evidence was edited in place. Originals remain outside this public staging repository.

## Correction history

On 2026-11-04, three previously published public-copy hashes were found not to match the bytes in this repository. The tables above now contain freshly computed SHA-256 values. The erroneous values and the exact correction are preserved in [`HASH_CORRECTION_2026-11-04.md`](HASH_CORRECTION_2026-11-04.md). The affected evidence files were not changed as part of this correction.
