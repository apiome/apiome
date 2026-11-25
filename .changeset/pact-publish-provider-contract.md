---
"@apiome/cli": minor
---

`apiome pact publish-provider-contract <openapi-file> --provider … --provider-app-version … --evidence <report>` publishes a provider contract for bi-directional contract testing with its self-verification evidence: a Schemathesis, Dredd, Newman or other JUnit report, Newman JSON or Schemathesis NDJSON (`--evidence`), or an Apiome provider-verification report (`--evidence-report`). It prints what the evidence proved and the comparisons the publish ran; `--fail-on-unverified` exits 1 when the contract has no passing evidence.
