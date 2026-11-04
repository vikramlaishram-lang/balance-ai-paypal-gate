# Evidence index

This index separates versions and experiment types. Results from different versions must not be presented as one continuous live experiment. Historical QF-01 remains **INCONCLUSIVE**.

`Public-copy SHA-256` means the bytes in the committed Git blob, which are also served by GitHub raw and archive downloads. Evidence paths are pinned to LF in `.gitattributes` so a normal checkout reproduces those bytes on Windows as well as Unix-like systems.

| Artifact | Version | Experiment type | Test date | Result | Public-copy SHA-256 | Qualification limitations |
| --- | --- | --- | --- | --- | --- | --- |
| `v0.3-retained-sandbox/LIVE_SANDBOX_EVIDENCE.json` | v0.3-era retained milestone (file labels candidate v0.2) | PayPal Sandbox restart/reconcile record | 2026-10-25 | Historical run recorded as completed | `B1F20547E63DB7C02616B307F1A96BA0EB1CE3A9AF6A71996CB76A7320C93ED6` | Sanitized public copy; supports the earlier recovery story only; not v0.5/v0.5.1 qualification |
| `v0.3-retained-sandbox/VERIFICATION_REPORT.md` | v0.3-era retained milestone | Deterministic suite, restart runner, and historical Sandbox narrative | 2026-10-25 | 27/27 deterministic tests reported; Sandbox run described | `A4C3A6F646546D91F5678F57532D960596A273B1ED875456DFC28DC58B23763F` | Historical report; identifiers redacted; broader claims must remain version-scoped |
| `v0.3-retained-sandbox/CANDIDATE_BOUNDARY.json` | v0.3-era retained milestone | Candidate boundary | 2026-10-25 | Boundary recorded | `07953266DBAC9231ACA972FB5F1DBE5B8D1B945F2FAFBB1B129D9D002AFD586B` | Public copy redacts order/capture identifiers |
| `v0.5-frozen/integrated-fixture/local_integrated_report.json` | v0.5 frozen | Separate-process fictional fixture integration | 2026-11-02 | 10/10 windows PASS | `54BFCB565090F8621F097F41B48063CFBD68BFD0ACE1250CA41F94B2188CF771` | Synthetic provider; same host/account; not production Executor CLI or PayPal network evidence; full B predicate remains incomplete |
| `v0.5-frozen/integrated-fixture/fixture_executor_events.jsonl` | v0.5 frozen | Window-scoped fixture Executor log | 2026-11-02 | One fictional CREATE, one CAPTURE, two GET dispatches; negative windows zero | `E2F1BABCBBDB0ABC75BCA4432B307B8B3D16E6EEDBC75DBB300C29D2AABFE78B` | Independent local fixture logging, not independent PayPal-provider evidence |
| `v0.5-frozen/supplementary-scripted/diagnostic_report.json` | v0.5 frozen | Scripted unauthorized-proposal diagnostic | 2026-11-02 | 10/10 rejected | `8067EE46BE25DFA8D3256C69682EC3DF8E04BA1A3081924CC376C2613E28D661` | Gate-only synthetic observer; no provider dispatch authority; local path redacted |
| `v0.5-frozen/supplementary-model/diagnostic_report.json` | v0.5 frozen | Local-model adversarial and legitimate diagnostics | 2026-11-02 | 10/10 adversarial rejected; 10/10 legitimate admitted | `DFAF6D5D5AF658C546D2F2B73103BFA4BAD6CFD889BA25D7B4FDE158688C96CD` | Supplementary model evidence; synthetic observer; local path redacted; not a complete QF-01 run |
| `v0.5.1-observed/observation_report.json` | v0.5.1 development candidate | Observed production-handler path with injected fixture provider | 2026-11-02 | Four windows completed; supplementary local PASS | `25F0110A3D9A41BE6FFAA886F5FA4B1B73A110937D0E26406B5592C676C3A53E` | Credential-free fictional provider; same OS account; no Gate A–H retest; no credential-bearing live run |
| `v0.5.1-observed/executor_collector_events.jsonl` | v0.5.1 development candidate | Hash-chained collector log | 2026-11-02 | 18 records; replay reported PASS | `BF3DC507685B254FAF911C2D78DF9E3F3B449BE71F49A7ACCF0CECCBC3784991` | Pre-dispatch observation does not prove provider completion; local custody is not protected independence |
| `v0.5.2-route-b/EXECUTION_REPORT.md` | v0.5.2 demo-orchestration candidate | Current-build recording report | 2026-11-04 | Local qwen inference and fictional-provider execution PASS | `B135B583072EFC440952B227A369689861D13EF2EC571418FA5A37E386E46C9F` | Sanitized summary; no PayPal API call; recording retained separately |
| `v0.5.2-route-b/OLLAMA_PROPOSAL.json` | v0.5.2 demo-orchestration candidate | Genuine local model proposal | 2026-11-04 | `qwen3:8b` produced a structured USD 1.00 proposal | `7D379032CFA8072C484AA40A6B53BD182F68EC464F8145E2E05BD38EC5BA0381` | Proposal only; authority and effect are both `NONE` |
| `v0.5.2-route-b/FICTIONAL_FIXTURE_RESULT.json` | v0.5.2 demo-orchestration candidate | Deterministic restart/reconcile demonstration | 2026-11-04 | `OUTCOME_UNKNOWN`, restart, no retry, original-order reconciliation | `43B400815BC5BEB75787735B7F247940C18EEDB529FCD1945F7A6DDE7703F36F` | Fictional provider; simulated buyer approval; not PayPal evidence |
| `v0.5.2-route-b/VIDEO_VERIFICATION_REPORT.json` | v0.5.2 demo-orchestration candidate | Every-frame verification of uncut recording | 2026-11-04 | 1080p derivative decoded in full | `81BDA5B9C8E81AFC38ECCFBB9CCF25A23FC14850F8B53A88BCDB0E7FA3741C59` | Video itself retained outside Git; no audio; crop/CFR normalization only |

## Source and archive provenance

| Private/original artifact | SHA-256 | Note |
| --- | --- | --- |
| Frozen v0.5 candidate aggregate | `BA432AB8B7B38A522D8FD2C2C3F65920F63CEA0EF8CE6F669DF8D5762CF9649C` | 48 manifest-listed files reportedly matched their pins |
| v0.5.1 source archive | `2C6DAF2B37577073B6E3F53AC80A697864FA429DB489EB651B6029145F335E5C` | Verified before public staging extraction |
| v0.5 pinned-source review archive | `B9CF0B0BB4B9CF9BECD083FD69B2440879CC823898BE4DCDF1AF3BE7DA84E915` | Private provenance archive; not copied into the public repository |
| v0.5 integrated evidence archive | `FF5A717163E2276FBFB2915E83CC82CDE3F46BE63C8B43822841B9D74C3E4D0D` | Private provenance archive; selected text evidence copied above |
| v0.5.1 Windows Executor evidence archive | `260096940EEBBE9E8EB7D78C628E7CCC1FB35C19E5C2FFC01C09786D10731C55` | Private provenance archive; selected text evidence copied above |
| v0.5.2 frozen recording candidate tree | `7B7FD99E049FA26970E0753960098CF39FA484A1076ACF20EC02C1BF2A61F5E5` | 93 manifest-listed files rechecked before the Route B recording; executable publication mapping is in `PUBLICATION_PROVENANCE.md` |

## Redaction provenance

| Artifact | Original SHA-256 | Public-copy SHA-256 | Transformation |
| --- | --- | --- | --- |
| `LIVE_SANDBOX_EVIDENCE.json` | `7FF6AA55715346AA4B4494BD063232CF50EAFE06EC93A3F7731993753056A22D` | `B1F20547E63DB7C02616B307F1A96BA0EB1CE3A9AF6A71996CB76A7320C93ED6` | Mission, order, and capture identifiers replaced with explicit redaction markers |
| `VERIFICATION_REPORT.md` | `834DDCD9C92B8609D50FAC47B740112DE13D86461570F95AC89BFDC829A9B732` | `A4C3A6F646546D91F5678F57532D960596A273B1ED875456DFC28DC58B23763F` | Order and capture identifiers removed from the historical narrative |
| `CANDIDATE_BOUNDARY.json` | `901A0FDAA8A1E77EDC39DD52C5E54A435A49A056ED680C73859834D2D4022DCF` | `07953266DBAC9231ACA972FB5F1DBE5B8D1B945F2FAFBB1B129D9D002AFD586B` | Embedded order/capture claim string replaced with a redaction marker |

No raw evidence was edited in place. Originals remain outside this public staging repository.

## Correction history

The complete 2026-11-04 correction history is preserved. [`HASH_CORRECTION_2026-11-04.md`](HASH_CORRECTION_2026-11-04.md) records the first three-value correction exactly as published. A clean-clone audit then established that Git line-ending conversion—not changed evidence bytes—explained the discrepancy and also affected six other indexed files. [`HASH_CANONICALIZATION_2026-11-04.md`](HASH_CANONICALIZATION_2026-11-04.md) records the correction-of-correction and all nine prior values. The tables above use canonical committed-blob hashes.
