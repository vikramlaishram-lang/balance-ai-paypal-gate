# Security and publication boundary

This repository is a hackathon prototype and is not production-ready.

- Never place PayPal client IDs, client secrets, OAuth tokens, buyer credentials, approval URLs, signing private keys, or real `.env` files in the repository.
- Run only the credential-free fixture commands documented in `README.md` unless a separately approved experiment defines new scope.
- Do not run `executor_cli.py` as part of local reproducibility testing.
- Treat real order, capture, merchant, buyer, and account identifiers as publication-sensitive.
- Report suspected exposures privately to the repository owner before public disclosure.

The included test keys, tokens, merchant names, order IDs, and account names are explicitly fictional fixture values. They grant no external authority.
