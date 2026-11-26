---
"@apiome/cli": minor
---

`apiome pact` gains `pact-broker`'s commands — `publish`, `list-pacticipants`, `describe-version`, `can-i-deploy`, `record-deployment`, `record-release`, `create-environment`, `create-webhook` — with the same flags and sentences, plus `verify` (Apiome's hosted verifier) and `migrate` (reserved; exits 1 until PFX-6.7). Every `apiome pact` command now reads `PACT_BROKER_BASE_URL` / `PACT_BROKER_TOKEN` as well as `APIOME_*`, takes `--broker-base-url` / `--broker-token` (`-b` / `-k`), prints `--output table|json|markdown`, and exits like `pact-broker`: `0` success, `1` any failure. The existing `apiome pact` commands now exit `1` (was `2`) for a refused request or a bad flag.
