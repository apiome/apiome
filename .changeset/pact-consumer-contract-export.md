---
"@apiome/cli": minor
---

`apiome pact export-consumer-contract --project … --consumer …` writes a Pact v4 file generated from a consumer surface declared in the UI picker, using the specification's examples as sample values, and prints every value it had to invent and everything it left out. `apiome pact publish-consumer-contract … --consumer-app-version …` publishes the same pact to the workspace's Pact Broker with `--branch`, `--tag` and `--build-url`. `--fail-on-findings` exits 1 when the pact has findings.
