---
"@apiome/cli": minor
---

`apiome pact export-postman` takes `--all-consumers` (with `--provider`, and optionally `--tag` or `--branch`): one collection with a folder per consumer, each from its latest such pact; a consumer without one is listed as left out. `--state-setup` gives each request that needs provider states a pre-request script that POSTs `{"state", "params", "action": "setup"}` to `{{stateChangeUrl}}` first, and `--state-change-url` fills that variable in (PFX-8.18).
