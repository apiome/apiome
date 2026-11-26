---
"@apiome/cli": minor
---

`apiome pact export-postman --provider … --consumer …` writes a stored pact as a Postman Collection v2.1 — the latest pact, or the one of `--consumer-version`, `--tag`, `--branch` or `--pact-version` — and `--pact-file` does the same for a local Pact file. One request per HTTP interaction against `{{baseUrl}}` (`--provider-base-url` fills it in), a saved example of the expected response and a test script that checks it (`--no-tests` leaves the scripts out). It prints every notice — interactions left out, values not asserted, generators not applied, the provider states to set up — with a reason; `--fail-on-left-out` exits 1 when an interaction was left out.
