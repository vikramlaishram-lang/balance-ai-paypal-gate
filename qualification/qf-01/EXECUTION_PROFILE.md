# QF-01 execution profile

This directory binds Balance Gate PayPal v0.5 to the frozen qualification contract
identified by SHA-256
`b365df35ac73b9ffe8445b53da24c7c872202ee2859783564a261dc2979e7ea0`.

The original contract bytes were not present in the workspace when this profile was
created. The supplied digest is therefore retained as an external contract identifier,
not reported as a locally recomputed file hash. A later copy of the contract is valid
only if its SHA-256 exactly matches that value.

Phase 1 is offline. It uses `FixturePayPalSandbox` with outbound socket connections
blocked. Fixture calls exercise state transitions; they are not PayPal Sandbox API calls.

The protection boundary is one Gate-owned trusted invoice identifier. It is not a
universal lock on a real-world purchase, another Gate database, or an external billing
system.

Phase 2 denominators are frozen by the pinned assets in this directory:

- exactly 10 adversarial model prompts;
- exactly 10 legitimate model prompts;
- exactly 10 scripted malicious proposals.

Model failures, Gate false acceptances, and Gate false refusals must be reported as
separate measures.
