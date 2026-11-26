---
"@apiome/cli": patch
---

`apiome pact` now reads `PACT_BROKER_PASSWORD` as the workspace API key when no token or key is set, so a pipeline configured for `pact-broker` basic auth works unchanged (the server takes the key as the basic-auth password since PFX-4.2, #6939). `PACT_BROKER_USERNAME` without a password stops the command with the reason.
