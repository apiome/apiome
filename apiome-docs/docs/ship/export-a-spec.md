---
title: "Export a spec"
description: "Download a published version as OpenAPI, Arazzo or JSON Schema."
sidebar_position: 5
tags: [export]
---

Apiome reconstructs the full OpenAPI 3.1 document (or Arazzo workflow document, or JSON Schema)
for a **published** version on demand. You can download it from the CLI or fetch it directly over
REST in JSON or YAML.

Those three have dedicated endpoints, but they are not the whole export surface: Apiome emits
**51<!--format-count:exportable--> formats** — AsyncAPI, GraphQL, Proto3, Avro, Thrift, Smithy,
TypeSpec, WSDL, XSD, OData, EDI X12, SAP IDoc, HL7 v2, FHIR, COBOL copybooks and more —
through the export-target registry. The full list, and which formats round-trip (import *and*
export) versus export only, is generated at [Supported formats](../bring-in/supported-formats.md).

Run `apiome export targets` to see the same list for a specific version, and
`apiome export evidence --target <format>` to see what a given conversion preserves before you
generate it.

---

## With the CLI

```bash
# OpenAPI (default), JSON, to a file
apiome spec export --project <id-or-slug> --version <id-or-label> --output petstore.json

# YAML
apiome spec export --project <id-or-slug> --version <id-or-label> --yaml -o petstore.yaml

# Exporting to another format (AsyncAPI, GraphQL, Proto3, Avro, …)? Check what will be
# preserved — and why anything changes — before you generate:
apiome export targets  --project <id-or-slug> --version <id-or-label>
apiome export evidence --project <id-or-slug> --version <id-or-label> --target avro

# Arazzo workflow document instead of OpenAPI
apiome spec export --project <id-or-slug> --version <id-or-label> --format arazzo -o flows.json
```

Use `-o -` to stream to stdout. `--format` accepts `openapi` (default) or `arazzo`.

### Download Arazzo or JSON Schema by slug

`apiome schema arazzo` and `apiome schema json` take the published version as one
`tenant/project/version` argument (slugs, as in the REST route) and write to stdout by default,
so they suit a redirect, a pipe or a build step. They share the same flags; only the default
`--format` differs — **yaml** for Arazzo, **json** for JSON Schema.

```bash
# JSON Schema (2020-12) bundle, every class
apiome schema json acme-corp/payments-api/2.1.0 > schema.json

# One class's schema, straight into a code generator
apiome schema json acme-corp/payments-api/2.1.0 --class Charge \
  | npx quicktype --src-lang schema --lang go > charge.go
```

The JSON Schema is streamed exactly as the server emits it (`$schema:
https://json-schema.org/draft/2020-12/schema`); the CLI does not transform it.

```bash
# Full Arazzo bundle
apiome schema arazzo acme-corp/payments-api/2.1.0 > workflows.arazzo.yaml

# One class's workflow (the per-class route)
apiome schema arazzo acme-corp/payments-api/2.1.0 --class Charge > charge.arazzo.yaml

# JSON instead of YAML, written to a file
apiome schema arazzo acme-corp/payments-api/2.1.0 --format json --output workflows.arazzo.json

# Pin the exact bytes in CI: exit 6, and nothing written, if the document changed
apiome schema arazzo acme-corp/payments-api/2.1.0 -o workflows.arazzo.yaml \
  --expect-sha256 <sha256-from-a-first-run>
```

| Flag | What it does |
|---|---|
| `--class NAME` | Download only that class's workflow or schema. An unknown class exits 2. |
| `--format json\|yaml` | Serialization. Default **yaml** for `schema arazzo` (the usual form for Arazzo), **json** for `schema json`. |
| `--output FILE`, `-o` | Write to a file. Default `-`, stdout. |
| `--expect-sha256 HEX` | Compare the document's SHA-256 first; on a mismatch print both digests, write nothing and exit **6**. A `sha256:` prefix is accepted. |

The document is written byte for byte as the server sent it. A summary — bytes written, format and
`Checksum: sha256:…` — goes to stderr, so copy the checksum from a first run into
`--expect-sha256`. With the global `--json`, the summary is one JSON object: on stdout when the
document goes to a file, on stderr when the document goes to stdout.

The version must be published. An unknown or unpublished version, or a private one without an API
key, exits 2; set `APIOME_API_KEY` for private versions. No tenant configuration is needed — the
tenant is in the argument.

## With the REST API

```http
GET /v1/schema/{tenant_slug}/{project_slug}/{version_slug}
Accept: application/json          # default; use application/yaml for YAML
```

Other representations of the same version:

| Format | Route |
|---|---|
| OpenAPI | `GET /v1/schema/{tenant}/{project}/{version}` |
| Arazzo | `GET /v1/arazzo/{tenant}/{project}/{version}` (one class: append `/{class}`) |
| JSON Schema | `GET /v1/json/{tenant}/{project}/{version}` (one class: append `/{class}`) |

For private versions, pass an in-scope API key via the `X-API-Key` header (or the `api_key` query
parameter).

### Export to several formats in one job

To publish a version in several formats at once, send one export job with a `targets` list instead
of a single `target`. Apiome emits the version to every listed format and hands back **one zip**.

```http
POST /v1/export/{tenant_slug}/jobs
{
  "artifact": "<project-id>",
  "version": "1.0.0",
  "targets": [
    { "target": "openapi" },
    { "target": "graphql" },
    { "target": "protobuf", "options": { "package": "acme.payments.v1" } }
  ]
}
```

1. The `202` response carries a `status_path`. Poll it until `state` is `completed` or `failed`.
2. Download the zip from `result.download_path`. Each format sits in its own folder, named after
   the resolved format key (`openapi-3.1/`, `graphql/`, …), and a root `manifest.json` lists
   every folder, its files, its fidelity tier and the version that produced it.
3. Read the fidelity on the job result:
   - `result.targets[]` has one entry per format, in the order you sent them: its full fidelity
     report, transcoding guard, validation report, delivery decision and the files it added to
     the zip.
   - `result.fidelity_rollup` sums them up: the worst tier, the lowest and average preserved
     share, how many formats landed in each tier, and which formats are lossy or need
     confirmation.

| Rule | Behavior |
|---|---|
| `target` vs `targets` | Send one or the other. Mixing them, or putting `options` / `acknowledged_snapshot` at the top level next to `targets`, is rejected with `422`. |
| Per-format settings | `options` and `acknowledged_snapshot` go on each `targets` entry. |
| How many | Up to 16 entries in `targets`. Two entries that resolve to the same format (`openapi` and `openapi-3.1`) are rejected with `400`. |
| `dry_run: true` | Every format's fidelity report and the rollup, no zip. |
| Severe conversions | If any format needs confirmation, the job fails with `TRANSCODE_CONFIRMATION_REQUIRED` before anything is generated. Resubmit with `"confirm": true`. |
| Failures | All or nothing: the first format that fails fails the job, and `error.context.target` names it. No zip is kept. |
| Attestation | Each format is attested separately against the zip. Fetch one with `GET …/jobs/{job_id}/attestation?target=<format key>`. |

The same rules for snapshots and acknowledgements apply to each format; see
[Understand export fidelity](./export-fidelity.md#snapshots-and-the-risk-acknowledgement).

### Export a whole project or several versions in one job

To export more than one version of a project, send one export job with a `versions` list (version
labels or revision ids) or `"all_versions": true` instead of `version`. Every version is exported
to every target you name, and you get back **one zip**.

```http
POST /v1/export/{tenant_slug}/jobs
{
  "artifact": "<project-id>",
  "versions": ["1.0.0", "1.1.0", "2.0.0"],
  "targets": [
    { "target": "openapi" },
    { "target": "graphql" }
  ]
}
```

Each version × format pair is an **item**. An item that fails does not stop the others.

1. The `202` response carries a `status_path`. Poll it until `state` is `completed` or `failed`.
2. Read `result.batch` on the completed job:
   - `completed_count` and `failed_count` say how many items made it into the zip.
   - `items[]` has one entry per item: its version, format, `state`, folder in the zip, fidelity
     tier and preserved share, delivery decision, files, and, for a failed item, an `error` with
     the same `code`, `message` and `remediation` a failed single export carries.
   - `result.fidelity_rollup` sums up the fidelity of the completed items.
3. Download the zip from `result.download_path`. Each completed item sits in a
   `<version>/<format>/` folder (`1.0.0/openapi-3.1/`, `1.0.0/graphql/`, …). The root
   `manifest.json` lists every item, including the failed ones and why they failed.

| Rule | Behavior |
|---|---|
| Choosing versions | Send `versions` (up to 50 distinct entries) or `"all_versions": true`, never together and never with `version`. `all_versions` takes every version of the project, newest first. |
| Formats | Use `target` (with `options`) for one format, or a `targets` list for several. |
| How many | Up to 100 items (versions × formats). A longer `versions` list is rejected with `422`; an `all_versions` job over a bigger project fails with `EXPORT_BATCH_TOO_LARGE`. |
| Snapshots | `acknowledged_snapshot` is not accepted: a snapshot describes one version. Preview a version on its own to acknowledge it. |
| Failures | Per item. A version that does not exist, a format that fails, a severe conversion without `"confirm": true` or a blocked delivery fails only that item, and the job still completes. The job fails with `EXPORT_BATCH_FAILED` only when every item failed; `error.context.items` lists each one. |
| Same version twice | A label and its own revision id count as one version; the second is skipped with a `BATCH_VERSION_DUPLICATE` warning. |
| `dry_run: true` | Every item's fidelity tier and the rollup, no zip. |
| Attestation | Each completed item is attested against the zip. Fetch one with `GET …/jobs/{job_id}/attestation?version=<version>&target=<format key>`. |

## Verify

The exported document is valid OpenAPI and contains the classes and paths you edited. The
[Golden Path](https://github.com/apiome/apiome/blob/main/docs/GOLDEN_PATH.md) does exactly this — it exports via the real CLI and re-validates the
downloaded document with `openapi-spec-validator`.

## Test-drive it

For OpenAPI targets, the REST API can turn the artifact you just generated into
a **live mock** for a few minutes — one click, a base URL you can `curl`, responses generated from
the document's own response schemas, and a log of everything it served. It is the strongest check
available: a document that cannot answer its own operations is a finding no static validation would
surface.

```http
POST /v1/export/{tenant_slug}/mock
{ "artifact": "<project-id>", "version": "1.0.0", "target": "openapi" }
```

The mock expires by itself, and servers without the Mock Server deployed report the capability as
unavailable rather than offering a button that cannot work. See
[export_mock_test_drive.md](https://github.com/apiome/apiome/blob/main/apiome-rest/docs/export_mock_test_drive.md) for the endpoints,
the lifetime rules and the configuration. The test-drive panel lives in the Export studio, which is
not yet available.

## Related

- [Supported formats](../bring-in/supported-formats.md) — every format Apiome imports and exports,
  generated from the registries
- [Understand export fidelity](./export-fidelity.md) — cross-format exports: what is preserved,
  what is lost and why, and the risk acknowledgement
- [Export to an API gateway](./export-to-a-gateway.md) — Kong, Gateway API, Envoy, Istio, Traefik,
  AWS API Gateway, Azure API Management and Apigee configuration
- [Browse published specs](./browse-published-specs.md) — view the same spec rendered
- [Compare published versions](./compare-published-versions.md) — diff two published versions
  with `apiome schema diff`
- [CLI quick-start](../reference/cli-quickstart.md) — full CLI reference
