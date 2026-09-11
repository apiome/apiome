# Package publishing pipelines — SDK-4.1 (#4495)

Downloading a zip is not how SDKs are consumed at scale: a team expects `npm install @acme/api`
and `pip install acme-api`. This is the pipeline that gets them there — a place to store a
registry token, a deterministic rule for what version to publish under, a deterministic archive to
publish, and a ledger recording every attempt.

## Where the pieces live

| Layer | File |
|---|---|
| Envelope encryption (shared with the MCP vault) | `src/app/envelope_crypto.py` |
| Credential vocabulary, sealing, scope resolution | `src/app/sdk_registry_credentials.py` |
| Version-line → package-version mapping (pure) | `src/app/sdk_publish_version.py` |
| Deterministic `.tar.gz` writing | `src/app/tar_bundle.py` |
| Distribution builder (npm tarball, PyPI sdist) | `src/app/sdk_distribution.py` |
| Upload transports | `src/app/sdk_registry_client.py` |
| Orchestration and the run ledger | `src/app/sdk_publish_pipeline.py` |
| HTTP surface | `src/app/sdk_publish_routes.py` |
| SQL accessors | `src/app/database.py` (`*_sdk_registry_credential*`, `*_sdk_publish_run*`) |
| Schema | `apiome-db/scripts/V256__sdk_package_publishing_4495.sql` |

## What is published

SDK-4.1's stated dependency was "EPIC-2 stable" — the TypeScript (#4485) and Python (#4486)
client generators — and a publish step on the SDK-1.1 job service (#4481). All three were closed
**not-planned**, along with the generator SPI (#4482) and the dashboard/CLI surfaces
(#4491/#4492). Following the SDK-2.3/2.4/2.5/3.3/3.4 precedent, the pipeline publishes what *did*
ship, read straight from the persisted canonical model:

* **npm** — `package.json`, a CommonJS entry point with typings, the published contract verbatim
  under `spec/`, and one runnable TypeScript snippet per operation under `snippets/`.
* **PyPI** — a PEP 625 sdist: `PKG-INFO`, `pyproject.toml` (setuptools backend, the contract kept
  as package data), an importable module exposing `PROVENANCE` / `OPERATIONS` / `read_spec()`, and
  one runnable Python snippet per operation.

A distribution is assembled from a *list of files plus metadata*, so when a real client generator
lands it becomes another contributor to that list rather than a second pipeline.

Two things a package never hides. An operation with no HTTP binding (a gRPC method, a GraphQL
subscription) has no snippet defined for it and lands in `skipped` with a reason rather than
failing the build — the contract still describes it in full. And an API with more renderable
operations than `MAX_KIT_OPERATIONS` sets `truncated` in the provenance *and* says so in the
README: a package that silently omitted operations would be worse than one that admits it did.

`gomod` is deliberately not publishable: it names a module path, and a Go module is released by
pushing a git tag — that is SDK-4.2's territory.

## The version rule

The published version is **`major.minor.<regen counter>`**:

| Version line | Series | First publish | Then |
|---|---|---|---|
| `1.4` | `1.4` | `1.4.0` | `1.4.1`, `1.4.2` … |
| `1.4.2` | `1.4` | `1.4.0` | `1.4.1` … |
| `v3` | `3.0` | `3.0.0` | `3.0.1` … |
| `2026-01-04` | `2026.1` | `2026.1.0` | `2026.1.1` … |
| `1.5-beta` | `1.5-beta` | npm `1.5.0-beta.0` / PyPI `1.5.0b0` | `…beta.1` / `…b1` |

Three decisions are load-bearing:

* **The counter is allocated per release *series*, not per line.** Lines `1.4.2` and `1.4.3` are
  the same `1.4` series and draw from one counter, so they cannot both claim `1.4.0`. That is what
  makes the mapping injective.
* **A prerelease line stays a prerelease.** Dropping a `-beta` would publish a beta as a stable
  release, which npm's `latest` tag and pip's default resolver would then hand to everyone.
* **A line with no leading number is refused** (`latest`, `draft`). It carries no ordering, and
  inventing one would mean two such lines publishing over each other.

The counter is **derived from the run ledger**, never stored on a project row, so it cannot drift
from what was actually published. `idx_sdk_publish_runs_claim` makes that derivation safe under
concurrency: a run is inserted `in_progress` holding its version *before* the upload, and a
publish that loses the race takes the next number instead.

## Credentials

Stored in `apiome.sdk_registry_credentials` as **ciphertext only**, sealed by the shared envelope
cipher under the SDK vault's own magic (`OSRV`) and its own master-key map:

```bash
# Generate a key
python -c "import base64, os; print(base64.b64encode(os.urandom(32)).decode())"

export APIOME_SDK_REGISTRY_CREDENTIAL_ENCRYPTION_KEYS='{"1": "<base64 key>"}'
# Optional; defaults to the highest version present.
export APIOME_SDK_REGISTRY_CREDENTIAL_ACTIVE_KEY_VERSION=1
```

Separate keys from the MCP credential vault on purpose: a publish token and an outbound MCP token
are different blast radii, and the vault magic means a blob cannot be moved between the two even
under a shared key. Rotation works the same way — add a higher version, point the active version
at it, and older rows stay readable under the key that sealed them.

A credential is **write-only**. `GET` describes what is stored — the ecosystem, the registry, the
token's *public* scheme prefix (`npm_`, `pypi-`), its length and a truncated SHA-256 — and there is
no route that returns one. A project credential replaces the workspace one for that ecosystem,
whole: unlike SDK-3.4's settings, a token is atomic and does not merge.

## Routes

```
GET|PUT|DELETE /v1/tenants/{t}/governance/sdk-registry-credentials[/{ecosystem}]
GET|PUT|DELETE /v1/projects/{t}/{project}/sdk-registry-credentials[/{ecosystem}]
POST           /v1/projects/{t}/{project}/sdk-publish
GET            /v1/projects/{t}/{project}/sdk-publish-runs[/{run_id}]
```

Credential management is `projects:view` / `projects:edit`; publishing — **including a dry run**,
which decrypts a credential and predicts the next version — is `versions:publish`. No new RBAC
resource, for the reason CTG-4.4, CTG-4.5 and SDK-3.4 all gave.

### Dry run

`POST …/sdk-publish` defaults to `dryRun: true`. Uploading to a public registry is irreversible,
so publishing is always the deliberate act.

```bash
curl -sX POST "$APIOME/v1/projects/acme/widgets/sdk-publish" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"ecosystem": "npm", "version": "1.4.2"}'
```

A dry run does everything a publish does except the HTTP request: it resolves the branding,
resolves *and decrypts* the credential, computes the version the next real publish would claim,
builds the archive and reports its SHA-256 and contents. Because the build is byte-deterministic,
the digest a dry run reports is the digest a publish uploads.

## Provenance

The acceptance criterion is that provenance rides in the **package's own metadata**, not in a
manifest beside it, so an installed package traces back to its spec with nothing but the package
manager:

* **npm** — an `apiome` object in `package.json`, re-exported from the module as `provenance`.
* **PyPI** — `Project-URL` entries in the core metadata, and `PROVENANCE` in the module.

Both name the **revision id** rather than only the version label, because a label can be
re-published and a revision cannot, plus the release series, the regen counter, the renderer and
the SDK-3.4 settings fingerprint.

## Secrets never reach a log

The token is read into memory by `resolve_credential`, handed to the transport, and never touched
again. Every run-log line — including anything a registry said — passes through
`redact_secrets(text, [token])`, exact-substring redaction over the token actually in play. That
is stronger than the heuristic scrubbing `app.intake_secret_scrub` must do for uploaded documents,
because here we know precisely what the secret is.

## Statuses

| Status | Means | Holds a version number? |
|---|---|---|
| `dry_run` | Validated; nothing uploaded | No |
| `in_progress` | Claim held while the upload is in flight | Yes |
| `published` | The registry accepted it | Yes |
| `already_published` | The registry already had this version | Yes |
| `failed` | The build or the upload was refused | No — the number is freed |

A run that dies mid-upload stays `in_progress` and keeps its number reserved. That is the safe
failure: the upload may well have landed.

## Tests

| File | Asserts |
|---|---|
| `tests/test_envelope_crypto.py` | the shared cipher: round trip, tampering, vault isolation, rotation, no secrets in logs |
| `tests/test_mcp_credential_crypto.py` | that extracting the cipher preserved MCAT-6.2's stored blob format |
| `tests/test_sdk_publish_version.py` | the mapping is injective, monotonic, and refuses rather than guesses |
| `tests/test_tar_bundle.py` | the four pins byte-determinism rests on, including gzip's own header timestamp |
| `tests/test_sdk_distribution.py` | archive layout, embedded provenance, determinism, and **the generated package running under `node`** |
| `tests/test_sdk_registry_credentials.py` | validation, describe-without-revealing, redaction, scope precedence |
| `tests/test_sdk_registry_client.py` | the exact request each registry gets, and that no path returns the token |
| `tests/test_sdk_publish_pipeline.py` | dry run vs publish, the claim race, every refusal code, log redaction |
| `tests/test_sdk_publish_routes.py` | permissions, scopes, status mapping, audit payloads |
| `tests/test_sdk_publish_database.py` | the id guards and the SQL shape |
| `tests/test_sdk_package_publishing_migration.py` | V256's structural promises |
| `apiome-db/test/sdk-package-publishing.test.ts` | the same promises, from the schema side |

## What SDK-4.2 and SDK-4.3 inherit

* **`Distribution`** is "a list of files plus metadata". SDK-4.2 (git delivery) opens a PR carrying
  the same file list rather than uploading it — see `sdk_git_delivery.md`; a future client
  generator contributes to that list.
* **The version rule** is a pure function (`app.sdk_publish_version`), so a PR branch name or a git
  tag can carry the same number a registry release would.
* **The run ledger** already has a status vocabulary and an event log; SDK-4.3 (auto-regen on
  publish) needs a subscription and a worker, not a second record of what happened — see
  `sdk_regen_on_publish.md`. Its jobs call `publish()` unchanged and link to the run each attempt
  wrote. `PublishOutcome.retryable` (in-process, not persisted) carries the registry's own
  `RegistryUploadError.retryable`, so the worker retries a registry outage and dead-letters a refusal.
