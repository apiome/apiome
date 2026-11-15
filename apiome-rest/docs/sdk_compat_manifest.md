# Generator compatibility manifest (SGD-2.1, #4735)

`GET /v1/tenants/{tenant}/projects/{project}/sdk-compatibility?version=` → `apiome.sdk.compat-manifest/v1`
(`app/sdk_compat_manifest.py`, `app/sdk_compat_routes.py`). Rendered by the dashboard (**Export studio → SDK
compatibility**) and `apiome sdk compatibility`.

## How it is built

The route loads the revision (`load_export_source`, any revision the caller can view, latest by default) and the
project's SDK settings, builds the **same** SDK kit the browse Get SDK route serves (`build_client_kit`), and turns
the kit's `manifest.json` plus the archive (for `go.mod` / `pyproject.toml` / `package.json`) into the manifest with
`build_compat_manifest`. Nothing is re-generated differently from the kit. The revision's CTG-3.1 changelog, when
`ready`, supplies the semver block.

## Contents

| Block | From |
|---|---|
| `api`, `source` | the canonical model; source digest = sha256 of the captured contract (or of the model) |
| `options` | SDK settings; digest = the settings `content_fingerprint` |
| `constructs` | the canonical model (operations, HTTP operations, types by kind, security schemes, servers, streaming, pagination query parameters) |
| `artifacts[]` | one per kit artifact: coverage, runtime + dependencies, auth (supported / unsupported), pagination (`manual` when page/cursor parameters exist — no generator auto-paginates), generator digest (name + schema version + Apiome version), artifact digest (sha256 over its files' `path\tsha256`), findings |
| `semver` | changelog `max_severity` → required bump; the version labels → declared bump; `consistent` |

## Findings

Every skipped operation, unsupported auth scheme, failed generator, Terraform readiness warning and operation cap
is a finding with a stable `code` and a fixed `action` (`ACTIONS`). Skipped operations are classified against the
canonical model (no HTTP binding vs. over the cap), not by parsing free text. Snippets never render security
schemes (`app.snippet_render`'s documented limitation), so each declared scheme is a snippet finding.

## Versioning and fixtures

- `schema_version` is `apiome.sdk.compat-manifest/v1`; models are `extra="forbid"`.
- `schemas/sdk-compat-manifest.v1.json` is generated from the model (`scripts/generate_sdk_compat_schema.py`); a test
  fails on drift.
- `tests/golden/sdk_compat_manifest/widgets.json` is the golden manifest (regenerate with `pytest --update-golden`),
  shared with `apiome-cli/tests/test_sdk_command.py` and `apiome-ui/tests/sdk-compat-*.test.ts*`.
