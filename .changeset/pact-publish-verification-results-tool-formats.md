---
"@apiome/cli": minor
---

`apiome pact publish-verification-results --format` accepts `schemathesis`, `newman` and `dredd` beside `auto`, `pact-verifier-json` and `junit`: a Schemathesis `--report ndjson` stream or JUnit file, a Newman `-r json` or `-r junit` report, or a Dredd `--reporter xunit` file is read on the server, one interaction per operation, execution or test case. `auto` recognises Schemathesis and Dredd from the report itself; `.ndjson` / `.jsonl` files are sent as `application/x-ndjson`.
