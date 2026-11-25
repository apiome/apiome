# HTTP Contract Runner (ECA-2.1)

> apiome#4732 — the first half of Executable Contract Assurance Epic 2 (parent #4943 / umbrella #4941).
> Consumes ECA-1.1 (#4729) suites, ECA-1.2 (#4730) targets, and always writes ECA-1.3 (#4731) evidence.
> Blocks ECA-2.2 (`apiome verify contract`) and feeds ECA-3.1 policy evaluation.

## Why

A compiled suite and a registered target are inert until something **executes** the cases, judges
the responses, and leaves evidence a gate can cite. Without a bounded runner:

* CI invents ad-hoc curl scripts with inconsistent timeouts and no SSRF guard;
* a flaky retry can turn a real contract failure into a green build;
* there is no durable record of which suite digest ran against which target.

The runner closes that gap inside `apiome-rest`.

## Modules

| Module | Role |
|---|---|
| `app/contract_runner.py` | Pure execution: build requests, honour policy, assert status/schema, transport-only retries. |
| `app/contract_runner_rpc.py` | gRPC-family cases (XPC-3.2): the Connect and native gRPC transports and the status/message judge. |
| `app/contract_runner_service.py` | Compile → resolve → run → `record_run`. |
| `app/contract_runner_routes.py` | `POST /v1/tenants/{tenant}/contracts/{version_ref}/run`. |
| `app/ssrf_guard.build_guarded_client(allow_private=…)` | Private-network targets (e.g. localhost mock) skip public-IP filtering but keep scheme/credential rules. |

## Endpoint

```
POST /v1/tenants/{tenant_slug}/contracts/{version_ref}/run
```

Body:

```json
{
  "target_ref": "mock",
  "options": {},
  "idempotency_key": "ci-build-42",
  "context": { "commit": "abc123", "branch": "main" }
}
```

Permissions: `versions:view` **and** `verification_evidence:create`. Target selection is audited via
the existing resolve path.

* **201** — new evidence was written (`created: true`).
* **200** — idempotent replay, or `ok: false` with a taxonomy `error` (no executable cases, auth
  unavailable, compile refusal).
* **400/404/422** — addressing or target faults. **422 `target-protocol-mismatch`** when the
  target's `protocol` is not the suite's (an `http` target given a GraphQL version).

## GraphQL suites (XPC-1.2)

A GraphQL version compiles into `protocol: graphql` cases (see `contract_suite.md`), and the run
must name a target with `protocol: graphql` whose `base_url` **is** the GraphQL endpoint — for the
hosted mock, `http://localhost:8775/{tenant}/{project}/{version}/graphql`. Each case is a `POST`
of `{query, variables, operationName}` to that exact URL (nothing is appended), with
`Accept: application/graphql-response+json, application/json`.

The verdict comes from the envelope:

| Case | Passes when |
|---|---|
| success | status `2XX`, no `errors`, and `data` satisfies `graphql:<operation key>`. A violation is recorded per pointer into `data` (`/pet/name`). |
| negative | status `2XX` or `4XX`, and a non-empty `errors` array. |

A mutation is a mutating case and obeys `allow_mutating_methods`. A query is not, although it is
also sent as `POST`. The run's evidence records `protocol: graphql` (V371), and the JUnit export
carries it as the `apiome.protocol` property.

## gRPC/Connect suites (XPC-3.2)

A Protobuf version compiles into `protocol: grpc` cases (see `contract_suite.md`). The run may name
a target with `protocol: connect` or `protocol: grpc`; the evidence records which (V374).

| Target | How each case is sent |
|---|---|
| `connect` | `POST {base_url}/{package.Service}/{Method}` with the protobuf-JSON message, `Content-Type: application/json`, `Connect-Protocol-Version: 1` and `Connect-Timeout-Ms` from the policy, through the guarded httpx client. A `200` carries the reply; any other status carries a Connect error `{code, message}` (a body without `code` is mapped from its HTTP status by the Connect table). |
| `grpc` | A `grpcio` channel to `base_url`'s host and port (TLS for `https`), the deadline from `request_timeout_seconds`, auth headers as metadata. The server's descriptors are read once per run through **server reflection**; each message is encoded to binary protobuf with them and each reply decoded back to protobuf JSON. A public target's host is re-checked by the SSRF guard. `json_only` negatives are `skipped` (`rpc-negative-json-only`). |

The verdict: the reply's status must equal the case's `rpc.expect_code` (`ok` or
`invalid_argument`); a success reply must then decode to a JSON object satisfying
`rpc:<operation key>`, one assertion per pointer into the message (`/items/0/quantity`).
`UNAVAILABLE` and `DEADLINE_EXCEEDED` are transport failures (retried); every other status is
judged. A method without `idempotency_level = NO_SIDE_EFFECTS` obeys `allow_mutating_methods`.

The `…/run` response lists the manifest's `unsupported` operations; non-empty means the evidence
is partial. Provider-verification reports carry the count as `coverage.operations_unsupported`,
and the deploy gate's verification signal reports a would-be pass as `warn`
(`verification-partial`) when it is non-zero.

## Policy the runner honours

From the ECA-1.2 target `VerificationPolicy`:

| Field | Behaviour |
|---|---|
| `request_timeout_seconds` | Per-case httpx timeout |
| `max_concurrency` | Thread-pool size across cases |
| `retry_attempts` / `retry_backoff_ms` | **Transport failures only** |
| `allow_mutating_methods` | When false, POST/PUT/PATCH/DELETE cases, GraphQL mutations, and gRPC methods not marked `NO_SIDE_EFFECTS` are `skipped` |
| `follow_redirects` / `verify_tls` | Passed to the guarded client |

A status or schema mismatch **never** retries. `attempts > 1` on an evidence case always means
the transport was retried.

## Failure codes

| Code | When |
|---|---|
| `status-mismatch` | Response status outside `expect.status_codes` (incl. `2XX` / `4XX`) |
| `response-schema-mismatch` | Body fails IXH-5.1 `validate_json_instance` |
| `transport-error` / `timeout` | Could not get an answer to judge |
| `auth-unavailable` | Env/stored credential could not be materialised (run refuses before cases) |
| `mutating-method-blocked` | Case skipped by policy (a mutating method, or a GraphQL mutation) |
| `graphql-errors-present` | A GraphQL success case was answered with `errors` |
| `graphql-errors-missing` | A GraphQL negative case was answered without `errors` |
| `graphql-envelope-invalid` | A GraphQL case was answered with something that is not a JSON object |
| `rpc-status-mismatch` | A gRPC-family reply's status was not the case's `expect_code` |
| `rpc-response-undecodable` | A gRPC-family success reply is not a protobuf-JSON message |
| `rpc-negative-json-only` | A JSON-only negative skipped over native gRPC |
| `rpc-reflection-unavailable` | A `grpc` target's reflection could not be read (or its descriptors do not load) |
| `rpc-descriptor-mismatch` | The server's reflected descriptors lack the case's types or reject its message |

## Manual golden path (hosted SIM / mock)

1. Publish a petstore (or golden-path) version and enable the Apiome mock.
2. Register a verification target:
   - `environment: mock`
   - `network_class: private` with an `approval_reason` (required for `http://localhost:8775/…`)
   - `base_url`: `http://localhost:8775/{tenant}/{project}/{version}`
   - `auth.kind: none` (or env/stored as needed)
3. `POST …/contracts/project/{slug}/{version}/run` with `"target_ref": "<slug>"`.
4. Expect `ok: true`, `run.outcome: passed` (modulo skipped mutating cases), and a retrievable
   evidence record / JUnit export.

Deliberate break: point the same suite at a stub that returns 500 or drops a required field —
evidence must be `failed` with `status-mismatch` or `response-schema-mismatch`.

## Out of scope

* CLI `apiome verify contract` — ECA-2.2 (#4733)
* Policy evaluator — ECA-3.1 (#4734)
* Portable mock runtime packaging — PMR

## Pact cases and case hooks

> apiome#6932 (PFX-3.2) — the hosted Pact verifier (`app.pact_verifier*`) runs on this runner.

**A pact case is judged by the pact.** A case compiled from a pact interaction (`case.pact` set,
`source: pact_interaction`) has no response schema. After its status matches
`expect.status_codes`, the runner compares the response with `pact.response` under the pact's
matching rules (`app.pact_value_match.match_response`):

| Assertion | `kind` | `subject` | `code` when failed |
| --- | --- | --- | --- |
| A recorded header | `header` | The header name | `pact-header-mismatch` |
| The body | `custom` | JSON Pointer into the response body (`$` for the whole body) | `pact-body-mismatch` |

Each mismatch is one failed assertion with `expected`, `actual` and a `message` that ends with
`(rule: <matcher>)`; `app.pact_value_match.mismatch_rule` reads the rule back. A rule the engine
cannot apply is a mismatch, never a pass. When everything matches, one passed assertion is
recorded for the headers and one for the body the pact records.

**Hooks surround each case that is sent.** `run_suite(..., hooks=CaseHooks(before, after))`:

- `before(case)` runs just before the request. Returning `CaseDecision(run=False, skip_code=…)`
  records the case as `skipped` with that reason; raising skips it with `case-hook-failed`.
- `after(case, result)` runs once the case has been sent; an exception is logged and ignored.
- A run with hooks sends **one case at a time**, whatever the target's `max_concurrency`.
- A hook cannot widen anything: the target policy's mutating-method gate is checked after it.

The verifier uses hooks for provider states (`app.pact_verifier.state_hooks`): the
`ProviderStateHandler` seam that the provider-state registry (PFX-3.3, #6933) implements.

Tests: `tests/test_contract_runner_pact.py`, `tests/test_pact_value_match.py`,
`tests/test_pact_verifier.py`, `tests/test_pact_verifier_service.py`,
`tests/test_pact_verifier_routes.py`.
