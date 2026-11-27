---
"@apiome/cli": minor
---

`apiome pact verify` gains `--provider-states-setup-url` (POST each provider state to the provider's own setup endpoint — a path on the target or an http(s) URL — instead of the registered states) and `--skip-already-verified` (pacts that already have a result for `--provider-app-version` are listed as skipped, not replayed). The run's output now says when the target could not be reached (`could-not-connect`, not a failed verification) and lists each skipped pact with its reason. `--allow-mutating` against a production target is refused by the server.
