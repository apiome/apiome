---
"@apiome/cli": minor
---

`apiome pact scaffold-provider-tests --provider <name> --language typescript|java|go|python` writes a ready provider verification test (pact-js, pact-jvm, pact-go or pact-python) from the provider's pacts: the broker from `PACT_BROKER_BASE_URL` / `PACT_BROKER_TOKEN`, the recommended selectors, pending pacts on, and one state handler stub per provider state with its parameters. States not registered in Apiome are flagged; `--fail-on-unregistered` exits 1 when there are any (PFX-8.19).
