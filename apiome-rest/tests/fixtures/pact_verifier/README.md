# Pact verifier fixtures (PFX-3.2, #6932)

Pact files in the shape each client library writes, for `tests/test_pact_verifier_service.py`:

| File | Shape | What it exercises |
| --- | --- | --- |
| `pact-js-v3.json` | pact-js 13 (specification 3.0.0) | `providerStates` with params, per-category rules with `combine`, header regex, timestamp format, `type` with `min` |
| `pact-jvm-v4.json` | pact-jvm 4.6 (specification 4.0) | interaction `key`, body `content` / `contentType`, header value lists, `statusCode`, `eachValue`, generators, a mutating interaction |
| `pact-go-v2.json` | pact-go v2 (specification 2.0.0) | `providerState` string, query string, `$.body.…` rule keys, implied `min` matcher, wildcard `*` |

They are written by hand from what the libraries emit; they were not captured from a client run.
