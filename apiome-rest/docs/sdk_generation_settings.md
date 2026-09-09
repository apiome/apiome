# SDK generation settings & branding — SDK-3.4 (#4494)

An organisation wants the code Apiome hands its consumers to carry the organisation's identity:
packages named under its own npm scope / PyPI / Go module naming pattern, its licence header on the
source, and its own user-agent on the traffic those clients generate. None of that is a property of
any single version, project row or generated file — it is tenant policy — so it gets one durable
home and one set of rules.

## Where the pieces live

| Layer | File |
|---|---|
| Vocabulary, merge, validation, fingerprint (pure) | `src/app/sdk_generation_settings.py` |
| Persistence and scope resolution | `src/app/sdk_generation_settings_store.py` |
| HTTP surface | `src/app/sdk_generation_settings_routes.py` |
| SQL accessors | `src/app/database.py` (`*_sdk_generation_settings*`) |
| Schema | `apiome-db/scripts/V255__sdk_generation_settings_4494.sql` |
| UI | `apiome-ui/src/app/ade/dashboard/sdk-settings/` + `/api/sdk-settings` proxy |

## The settings body

Addressed as `sdk.generation-settings.v1`:

```json
{
  "packageNamePatterns": {
    "npm": "@acme/{project}-sdk",
    "pypi": "acme-{project}",
    "gomod": "github.com/acme/{project}-go"
  },
  "licenseHeader": "Copyright (c) {year} Acme, Inc.\nSPDX-License-Identifier: Apache-2.0",
  "userAgent": "acme-sdk/{version}",
  "publicSdkEnabled": true
}
```

Patterns may contain `{tenant}`, `{project}`, `{version}` and `{year}`, substituted from the scope
being resolved. An unknown token is refused at save time rather than left as a literal brace.

Ecosystems are `npm`, `pypi` and `gomod` — only what the platform can actually name. `npm` and
`pypi` are reported by the SDK-2.3 snippet service; **`gomod` (SDK-2.4, #4488) is the `go.mod`
module path the generated Go client declares** and the identifier its consumers type into `go get`,
so a configured one is used verbatim. An unconfigured `gomod` falls back to
`example.com/<tenant>/<project>-go` — `example.com` is IANA-reserved, so a default module path can
never point at somebody's real repository. Adding a fourth ecosystem is one entry in `ECOSYSTEMS`
plus one branch in `_package_name_problem`; an unknown ecosystem is refused with the accepted list
rather than stored and silently ignored.

A Go module path is validated as slash-separated elements of letters, digits and `. - _ ~`, none
empty and none `.`/`..` — a dot in the first element is *not* required, because a tenant serving
from an internal proxy has a legitimate bare path.

`publicSdkEnabled` (boolean, added by SDK-3.3, #4493) is the odd one out: an **access control**
rather than branding. It opens the public browse portal's "Get SDK" client-kit download and its
anonymous per-operation snippets for the project — see `public_sdk_kit.md`. Because it gates
exposure it defaults to **`false`**, not `null`: for a permission, "not configured" and "not
allowed" are the same answer, and it is the safe one. Only a real boolean is accepted (`1` is
refused — `isinstance(True, int)` makes that easy to get wrong), and an unreadable settings row
reads as `false`, so the gate fails closed.

## The three rules worth knowing

**1. The merge is per key, not per row.** A project that overrides only its user-agent still
inherits its tenant's package pattern and licence header, and `packageNamePatterns` merges one
ecosystem at a time. This is the one place SDK-3.4 departs from CTG-4.5's `deploy_gate_policy`,
whose project override replaces the whole body — which is why the store reads *both* rows
(`get_sdk_generation_settings_rows`) rather than the winner.

**2. "Unset" and "set to nothing" are different answers.** A project whose body omits
`licenseHeader` inherits its tenant's; a project whose body carries `"licenseHeader": null` has
asked for *none*, and must not have the tenant's re-applied. Stored bodies therefore carry only the
keys their author named — `parse_settings_body` preserves that, and it is why the settings live in
one JSONB column rather than as nullable columns.

**3. A pattern is validated by being resolved.** `@acme/{project}-sdk` is not itself a legal npm
name, so a pattern is checked by substituting probe values (`acme` / `petstore` / `1.0.0` / `2026`)
and validating the *result*. At read time the rule tightens further: a package pattern whose tokens
this scope cannot fill is **omitted** from `resolved.packageNames` rather than resolved
approximately, because a package name is an exact identifier and a nearly-right one is worse than
none. The licence header and user-agent take the opposite rule — their unfillable tokens render
away, because a partial sentence still reads.

## Endpoints

```
GET|PUT|DELETE /v1/projects/{tenant_slug}/{project_ref}/sdk-settings
GET|PUT|DELETE /v1/tenants/{tenant_slug}/governance/sdk-generation-settings
```

A `GET` never materialises a row: a scope with nothing saved answers `source: "default"` with an
empty body and a fingerprint. A `DELETE` returns the settings **now** in force rather than a bare
`204`, so a caller can see what it fell back to. A `PUT` replaces the scope's whole body.

Every response carries three different things on purpose:

* `settings` — the merged result;
* `resolved` — that result with its tokens substituted for the addressed scope (the package names a
  publisher would actually use);
* `scopeBody` — what is saved at *exactly* this scope, verbatim. An editor needs the third: only
  the raw body distinguishes an absent key from an explicit `null`.

`contentFingerprint` is a `sha256:` digest of the merged body. Identical settings fingerprint
identically, which is the determinism guarantee: same settings in, same branding stamped onto the
artifact.

The canonical body always carries **every** key, including unset ones, so that a fingerprint keeps
meaning the same thing across releases. The corollary is that adding a key changes every
fingerprint's *value*: SDK-3.3's `publicSdkEnabled` did, so a fingerprint recorded before that
release will not match the one the same settings produce after it. Stored row fingerprints are
untouched until their row is next saved; the ones responses report changed immediately.

**Permissions.** `projects:view` to read, `projects:edit` to change — no new RBAC resource, and no
new API-key scope. A full-access key already reaches these routes; the two restricted CI scopes
(`diff:read`, `lint:read`) have nothing to do with package naming, and minting a third would have
to be carried through the Control Panel and apiome-db's key CLI for no extra safety. Both writes
are audited as `governance.sdk_generation_settings.update` / `.clear`, with the licence header
recorded by length rather than verbatim.

## What consumes the settings today

The **SDK-2.3 snippet service** (`app/snippet_render.py`, `app/snippet_routes.py`), on both its
authenticated and anonymous surfaces: the tenant's user-agent is added to the example request's
headers, and its licence header is prepended to the code as a **line**-comment block (never a block
comment — a licence containing `*/` would otherwise terminate it from the inside and turn the rest
into code). The applied values are reported back in the response's `branding` field, alongside the
resolved package names, so a "Get SDK" surface can show the package name without a second call.

Two properties hold that surface together:

* **Unbranded rendering is byte-identical to what preceded SDK-3.4.** `synthesize_request` and
  `render_snippet` take the branding as optional keyword arguments defaulting to `None`. That is
  what keeps the bulk request-file emitter (FMT-2.4), which shares those two functions, unchanged.
* **The ETag needs no cache-key work.** It digests the whole response, so changing a tenant's
  settings changes it automatically. The public route's `Cache-Control: public` stays correct
  because the tenant is already part of its URL.

An operation that declares its own `User-Agent` parameter keeps it: the spec is more authoritative
about its own API than a workspace default is.

The **SDK-3.3 public client kit** (`app/sdk_kit.py`, `app/sdk_kit_routes.py`) consumes both halves
of these settings: `publicSdkEnabled` decides whether the browse portal serves anything at all,
and the branding is stamped onto every snippet in the archive while the resolved package names and
their install commands go into its README and its info payload. The merged fingerprint travels in
the archive's `manifest.json`, so a changed kit is attributable to changed branding rather than to
a changed API. See `public_sdk_kit.md`.

The branding is deliberately **not** mirrored into the client-side snippet twin
(`apiome-ui/lib/tryit/snippet.ts`), despite the standing parity rule: the browse Try It panel
*sends* the request it renders, and stamping a tenant's attribution user-agent onto a reader's live
traffic would misattribute it.

`resolved.packageNames` is the seam SDK-3.3 (browse "Get SDK", #4493) and SDK-4.1 (package
publishing, #4495) are expected to read; neither exists yet, and nothing here assumes them.

## Tests

| File | Asserts |
|---|---|
| `tests/test_sdk_generation_settings.py` | the vocabulary: parsing, merging, resolution, fingerprint |
| `tests/test_sdk_generation_settings_store.py` | scope resolution and the degraded fallbacks |
| `tests/test_sdk_generation_settings_routes.py` | the HTTP contract and the audit rows |
| `tests/test_sdk_generation_settings_database.py` | the id guards and the SQL shape |
| `tests/test_sdk_generation_settings_migration.py` | V255's structural promises |
| `tests/test_snippet_branding.py` | branding applied to snippets, and the unbranded no-op |
| `apiome-db/test/sdk-generation-settings.test.ts` | V255 against the real migration runner's view |
