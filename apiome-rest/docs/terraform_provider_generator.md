# Terraform provider generator (SDK-4.4, #4498)

`app.terraform_provider_generator` turns a persisted `CanonicalApi` into a buildable **Terraform
provider** written in Go on the Terraform Plugin Framework (`v1.18.0`): resources and data sources
derived from the contract's CRUD conventions and its `x-terraform` hints, provider configuration
derived from its security schemes, registry-layout docs, and example `.tf` configuration.

It is a pure function — no clock, no environment, no filesystem — called from `app.sdk_kit`, whose
archive carries the output under `terraform/` (see `public_sdk_kit.md`).

## Why it generates from the canonical model

SDK-4.4 was to run under the generator SPI (SDK-1.2, #4482), on top of the codegen preprocessing
pass (SDK-1.3, #4483), and join the SDK-1.4 compile-gate matrix (#4484). All three were closed
**not-planned**. Following the precedent the Go client (SDK-2.4) and the server stubs (SDK-2.5)
set, the generator reads the persisted canonical model directly and rides the client kit. The SPI's
readiness-warning channel did not ship either, so the warnings travel in the provider's own
README and in the kit manifest's `terraform_provider.warnings`.

## Three modules

| Module | Role |
| --- | --- |
| `app.terraform_provider_plan` | Decides what the provider contains: groups operations into resources and data sources, reads `x-terraform` hints, maps security schemes to settings, and records every readiness warning. Built on `app.server_stub_plan`, so the provider and the server stubs agree on parameters, bodies and schemas |
| `app.terraform_provider_generator` | Writes the provider from the plan: per-contract Go, docs, examples, README, `go.mod` |
| `app.terraform_provider_runtime` | The fixed Go — one generic resource, two generic data sources, the JSON⇄`tftypes` codec and the HTTP transport — plus the pinned `go.mod` requirements and `go.sum` |

The fixed Go was written and compiled as ordinary Go and is embedded verbatim, so it is reviewable
as Go rather than as string templates. Every generated resource is that one implementation driven
by a **spec table** (paths, methods, which attribute travels in which body), so a nested object, a
list of objects and a map all travel through the same few functions.

## CRUD conventions

| Operation | Role |
| --- | --- |
| `POST /widgets` | create |
| `GET /widgets/{id}` | read — the response schema is the resource's schema |
| `PUT /widgets/{id}` (`PATCH` if there is no `PUT`) | update |
| `DELETE /widgets/{id}` | delete |
| `GET /widgets` (array, or an object with exactly one array-of-records member) | list → `<name>_list` data source |

- A group with create, read and delete is a **resource**. A group with a read but no create or
  delete is a **data source** only, reported as `terraform.incomplete-resource`.
- The identifier is the hint's `id` member, else the member named like the item placeholder, else
  `id`; it must be a string or an integer, and the create response must carry it.
- A parent placeholder (`/orgs/{orgId}/projects`) becomes a required attribute that forces
  replacement; the import ID is the parents and the identifier, slash-separated (`org/123`).
- Attribute modes: required in the create body → **Required**; optional in it → **Optional +
  Computed**; `readOnly` or absent from the create body → **Computed**. Computed values carry
  `UseStateForUnknown`. Without an update, or for a member the update body does not carry, a
  configurable attribute forces replacement.
- A union, an untyped value, a record nested more than four levels or referring back to itself is
  held as a JSON-encoded string (`terraform.json-attribute`, info).
- A required query or cookie parameter on a CRUD operation disqualifies the resource; a required
  **header** does not — the provider's `headers` setting sends it (`terraform.required-header`).

## `x-terraform` hints

Read from the source OpenAPI document (`CanonicalApi.raw`), because the canonical model keeps only
the extensions it interprets.

| Where | Hint | Effect |
| --- | --- | --- |
| Operation | `{"resource": "widget", "operation": "create"}` | Assign the operation to a resource and role (`create`, `read`, `update`, `delete`, `list`); it joins the group whose read already names that resource, or starts one, and displaces a conventional operation in that role |
| Operation | `false` or `{"ignore": true}` | Leave it out (`terraform.operation-ignored`, info) |
| Schema | `"resource": "<name>"` / `false` | Name the resource / keep the schema a data source only |
| Schema | `"id": "<member>"` | The identifier member |
| Schema | `"ignore": [...]` | Members dropped from the resource and its data sources |
| Schema | `"forceNew": [...]` | Members whose change replaces the resource |
| Schema | `"import": false` | No `terraform import` |
| Schema | `"dataSource": false` | No data sources for the schema |

An invalid hint is reported as `terraform.invalid-hint` and ignored; the conventions still apply.

## Provider configuration

`endpoint` (default: the first declared server), `headers` (sent on every request — a tenant
header, or `X-Mock-Session` for the Apiome mock's stateful CRUD), and one setting per security
scheme: `token` for bearer / OAuth 2 / OpenID Connect, `username` + `password` for HTTP Basic,
`api_key` for an API key in a header, query parameter or cookie. Each falls back to
`<PROVIDER>_<SETTING>` in the environment. A scheme with no setting (mutual TLS, digest) is
reported as `terraform.unsupported-auth`.

## What it emits

| File | Contents |
| --- | --- |
| `go.mod`, `go.sum` | The module path, `go 1.24.0`, and the pinned dependency set — `go build` needs no `go mod tidy` |
| `main.go` | `providerserver.Serve` at the registry address, with `-debug` |
| `internal/client/client.go` | The JSON-over-HTTP transport (fixed) |
| `internal/provider/runtime.go` | The generic resource and data sources and the codec (fixed) |
| `internal/provider/provider.go` | Configuration, auth, and registration of every resource and data source |
| `internal/provider/resource_<name>.go` | One spec table and schema per resource |
| `internal/provider/data_source_<name>.go` | One per data source (`<name>` and `<name>_list`) |
| `docs/` | `index.md`, `resources/`, `data-sources/` in the layout the Terraform Registry publishes |
| `examples/` | `provider/provider.tf`, `resources/<type>/resource.tf` (+ `import.sh`), `data-sources/<type>/data-source.tf` |
| `terraform-registry-manifest.json` | Plugin protocol 6 |
| `README.md` | Build, `dev_overrides`, configuration, resources, data sources, the readiness report, the hints, provenance |

Every `.go` file carries `// Code generated by Apiome. DO NOT EDIT.` and, when configured, the
tenant's SDK-3.4 licence header. The README footer records the generator schema
(`sdk.terraform-provider.v1`), module, address and revision; the kit manifest records a digest of
every file.

## Names

| Name | Derivation |
| --- | --- |
| Provider type name | The project slug's letters and digits (`acme-widgets` → `acmewidgets`) — Terraform reads the provider from the text before a resource type's first underscore |
| Registry address | `registry.terraform.io/<tenant slug>/<provider name>` |
| Module path | A sibling of the tenant's configured `gomod` path (`github.com/acme/widgets-go` → `github.com/acme/terraform-provider-widgets`), else `example.com/<tenant>/terraform-provider-<name>` |
| Resource / data source | The schema's name in `snake_case` (or the hint), allocated without collisions; list data sources are `<name>_list` |

## Testing

`tests/test_terraform_provider_plan.py` covers the planner against the corpus fixture
`apiome-ui/examples/openapi/38-terraform-crud-conventions.yaml` (feature tag `terraform-crud`) and
one small document per edge case. `tests/test_terraform_provider_generator.py` checks the emitted
text and runs two gates when the toolchains are on `PATH`:

- with `go`: `go build`, `go vet` and `gofmt -l` under `-mod=readonly`, which also proves the
  pinned `go.mod`/`go.sum` are complete;
- with `go` and `terraform`: `terraform validate` and `terraform fmt -check` on every example, then
  `apply` → in-place update → `import` → `destroy` against a stateful fake of the fixture's widgets,
  with a clean `plan -detailed-exitcode` after each step.

The same cycle runs against the SIM mock: export the fixture as a mock bundle, serve it with
`apiome-mock run --bundle …`, and point the provider at it with
`headers = { "X-Mock-Session" = "<any>" }` so the mock keeps state.

## Known limitations

- Read-after-write: create and update read the instance back; an API that answers a read with
  different values for configured attributes keeps the planned values (Terraform requires it), so
  the difference surfaces on the next refresh.
- Query parameters are not modelled; a required one disqualifies the operation.
- `additionalProperties` maps with no named value type arrive as JSON strings, because the
  canonical model records them as untyped.
- No generated acceptance tests (`TF_ACC`) or registry publishing yet; those are SDX-3.2 / SDX-4.5.
