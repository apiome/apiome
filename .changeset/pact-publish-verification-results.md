---
"@apiome/cli": minor
---

`apiome pact publish-verification-results <report> --provider … --consumer … --pact-version … --provider-app-version …` publishes a verification that ran elsewhere — `pact_verifier_cli --json` output or JUnit XML — as a verification result in the workspace's Pact Broker, so can-i-deploy sees it. `--branch`, `--tag` and `--build-url` record the provider build. It prints the verdict and every note about what the server could not use; `--fail-on-failure` exits 1 when the result is a failure.
