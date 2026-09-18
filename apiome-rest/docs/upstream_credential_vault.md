# Upstream auth vault — AGX-2.2 (#4534)

Agents never hold real API credentials. When an agent calls a tenant's API through a managed MCP
toolset, the AGX-2.1 invocation proxy (#4533) injects the tenant's upstream credential on the
server. The agent only ever holds a scoped Apiome agent key. This vault is where that credential
lives. It is encrypted at rest, write-only, bound to one toolset and one server URL, rotatable in
place, and every use is audited as metadata only.

## Where the pieces live

| Piece | What it owns |
| --- | --- |
| `apiome-db/scripts/V268__upstream_credentials_agx_2_2.sql` | `upstream_credentials` (sealed secret, binding, placement) and `upstream_credential_uses` (write-once use ledger, 90-day purge function) |
| `app.upstream_credential_binding` | Pure rules: server-URL normalization, `apiKey` placement, **`binds()`**, and building and applying the header or query parameter |
| `app.upstream_credentials` | The vault: validation, sealing (`EnvelopeCipher`, magic `OUCV`), create / rotate / delete / list, and **`resolve_injection()`**, the only function that opens a secret |
| `app.upstream_credential_routes` | The REST surface (below) |
| `app.redacted_validation_route` | Route class that keeps FastAPI's `422` from echoing a submitted secret |
| `app.database` | The seven `*upstream_credential*` accessors |

## Configuration

The vault uses the same envelope scheme as the MCP credential vault (MCAT-6.2) and the SDK
registry vault (SDK-4.1): AES-256-GCM, a per-secret data key, and a versioned master key from the
environment. That is the same AES-256-GCM, operator-held-32-byte-key pattern the backups use. The
vault has its own key map and its own magic, so a blob cannot be moved between vaults.

```bash
# Generate a key
python -c "import base64, os; print(base64.b64encode(os.urandom(32)).decode())"
export APIOME_UPSTREAM_CREDENTIAL_ENCRYPTION_KEYS='{"1": "<base64 key>"}'
# Optional; defaults to the highest version present.
export APIOME_UPSTREAM_CREDENTIAL_ACTIVE_KEY_VERSION=1
```

With no key configured the server still starts. Storing a credential is then a `503` naming the
variable, and a stored credential can't be opened (the call fails closed). A key map that is
present but malformed fails at startup. To rotate the master key, add a higher version: older rows
keep opening under their own version, and rotating a credential re-seals it under the newest.
`docker-compose.yml` passes the key map through to the `rest` service.

## Routes

All four routes are scoped by the **authenticated** tenant. The `{t}` slug in the URL is
informational, as on every `/v1/tenants/{t}` surface.

| Route | Permission | Result |
| --- | --- | --- |
| `GET /v1/tenants/{t}/agent-toolsets/{toolset}/upstream-credentials` | `api_keys:view` | `200` metadata list |
| `POST /v1/tenants/{t}/agent-toolsets/{toolset}/upstream-credentials` | `api_keys:create` | `201` · `409` binding taken · `422` · `503` |
| `POST …/upstream-credentials/{id}/rotate` | `api_keys:edit` | `200` · `404` · `422` · `503` |
| `DELETE …/upstream-credentials/{id}` | `api_keys:delete` | `204` · `404` |

No new RBAC resource: an upstream credential is the other half of an agent's access, and AGX-3.1's
agent keys are `api_keys` too. Under the built-in roles, Owner, Admin and Editor can manage
credentials and Viewer can list their metadata.

```bash
# apiKey in a header
curl -sX POST "$APIOME/v1/tenants/acme/agent-toolsets/$TOOLSET/upstream-credentials" \
     -H "X-API-Key: $APIOME_KEY" -H 'Content-Type: application/json' \
     -d '{"serverUrl": "https://api.example.com/v1", "kind": "apiKey",
          "in": "header", "name": "X-Api-Key", "secret": {"value": "sk_live_…"}}'

# bearer
-d '{"serverUrl": "https://api.example.com", "kind": "bearer", "secret": {"token": "…"}}'

# basic (the password may be empty, for APIs that take the key as the username)
-d '{"serverUrl": "https://api.example.com", "kind": "basic",
     "secret": {"username": "svc", "password": "…"}}'

# rotate: same secret shape as the credential's kind
curl -sX POST "$APIOME/v1/tenants/acme/agent-toolsets/$TOOLSET/upstream-credentials/$ID/rotate" \
     -H "X-API-Key: $APIOME_KEY" -H 'Content-Type: application/json' \
     -d '{"secret": {"value": "sk_live_new…"}}'
```

Every response is `agx.upstream-credential.v1` metadata: `id`, `toolsetId`, `serverUrl`, `kind`,
`in`, `name`, `keyVersion`, `readable` (whether the secret opens with the keys configured now),
`createdAt`/`createdBy`, `rotatedAt`/`rotatedBy` and `lastUsedAt`. There is no fingerprint of the
secret: a truncated hash of a low-entropy basic-auth password can be guessed offline.

Create, rotate and delete write `agent.upstream_credential.create|rotate|delete` rows to the
tenant's access audit, with the credential id, toolset, server URL, kind, placement and key version.

## The binding

A credential is sent only with a request that `binds()` to its server URL:

- the server URL is `https://` only, with no `user:pass@`, query, fragment or dot segments. It is
  stored normalized (lower-case host, no default port, no trailing slash), so one server has one
  spelling and the unique index on (tenant, toolset, server URL) means what it says;
- the request must have the same scheme, host and port and no userinfo. Its path must equal the
  base path or continue it after a `/`: `https://api.example.com/v1` covers `/v1/pets`, but not
  `/v10`, `/admin`, `http://…` or `api.example.com.evil.com`;
- a request path with a `.`/`..` segment is never bound, however it is spelled: raw,
  percent-encoded (a path still decoding after five rounds counts as one), with matrix
  parameters (`..;x`, which Tomcat reads as `..`), full-width (`．．`), or behind a backslash;
- when base paths nest (`https://api.example.com` and `https://api.example.com/v2`), the most
  specific one wins.

`apiKey` names follow the RFC 9110 token grammar for headers, and the unreserved set for query
parameters. Framing and routing headers (`Host`, `Content-Length`, `Transfer-Encoding`, `Cookie`,
`Proxy-Authorization`, …) are refused. Secrets may not contain control characters. A bearer token
may not contain whitespace, and a basic username may not contain `:`.

## Rotation without downtime

`rotate_credential` validates and seals the new secret first. It then swaps it with one `UPDATE` of
the same row, and never deletes and re-inserts. A concurrent `resolve_injection` reads the old row
or the new one, never a gap. An invocation already in flight holds its own `CredentialInjection`,
which is immutable, and finishes with the old secret. `test_rotation_has_no_downtime_for_concurrent_invocations`
races forty rotations against six resolver threads.

## For AGX-2.1: using a credential

```python
from app.upstream_credentials import resolve_injection, UpstreamCredentialUnavailableError

injection = resolve_injection(tenant_id, toolset_id, request_url)   # audits the use
if injection is not None:
    request_url, headers = injection.apply(request_url, headers)    # replaces same-named values
```

- `None` means no credential of this toolset is bound to that URL. The call may go out bare.
- `UpstreamCredentialUnavailableError` means a bound credential won't open. **Fail the call**;
  never send it unauthenticated. It is recorded as `unavailable`.
- `apply()` **replaces** any header or query parameter with the credential's name, including one
  hidden behind a `;` separator, so an agent can't smuggle in a competing `Authorization` or
  `api_key`. Other query parameters keep their exact bytes.
- Pass your HTTP client exactly the URL string `binds()` checked, and percent-encode
  agent-supplied path parameters before building it.
- `CredentialInjection`'s `repr` shows names only. Still, never log the applied URL or headers:
  an `apiKey` in `query` is now in the URL.
- Resolve with the URL you will actually request. Redirects need their own `binds()` check (or
  none): never follow one to another host with the credential attached.
- `resolve_injection` uses apiome-rest's synchronous `db`. An async caller in apiome-mcp can run
  it in a thread, or issue the same SELECT through its own pool and call `binds()` and
  `build_injection()` directly. The use ledger row is then the caller's to write.

## For AGX-1.2: the toolset foreign key

`toolset_id` has no foreign key, because `agent_toolsets` did not exist yet. AGX-1.2's migration
must delete `upstream_credentials` (and optionally `upstream_credential_uses`) rows whose toolset
does not exist, then add `REFERENCES agent_toolsets(id) ON DELETE CASCADE`. It should also make the
routes answer `404` for a toolset that isn't in the tenant. Until then any UUID is accepted and
every read and write is scoped by tenant.

## Tests

| File | Pins |
| --- | --- |
| `tests/test_upstream_credential_binding.py` | URL normalization, placement grammar, the `binds()` matrix (downgrade, look-alike hosts, ports, userinfo, prefix confusion, encoded traversal), injection building and `apply()` |
| `tests/test_upstream_credentials.py` | Validation, sealing and cross-vault isolation, scoping, in-place rotation under concurrency, fail-closed opening, metadata-only use audit |
| `tests/test_upstream_credential_routes.py` | Permissions, status mapping, audit rows, and no secret in any response, including FastAPI `422`s |
| `tests/test_upstream_credential_secret_sweep.py` | **The AC sweep:** every `GET` route in the app, plus the OpenAPI schemas and the source, never yield secret material |
| `tests/test_redacted_validation_route.py` | The redacting route class on its own |
| `tests/test_upstream_credentials_migration.py`, `apiome-db/test/upstream-credentials.test.ts` | The V268 schema promises |
