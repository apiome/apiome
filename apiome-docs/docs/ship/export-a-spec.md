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
**44<!--format-count:exportable--> formats** — AsyncAPI, GraphQL, Proto3, Avro, Thrift, Smithy,
TypeSpec, WSDL, XSD, OData, EDI X12, HL7 v2, FHIR, COBOL copybooks and more —
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

### Download Arazzo workflows by slug

`apiome schema arazzo` takes the published version as one `tenant/project/version` argument
(slugs, as in the REST route) and writes YAML to stdout by default, so it suits a redirect or a
build step:

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
| `--class NAME` | Download only that class's workflow. An unknown class exits 2. |
| `--format json\|yaml` | Serialization. Default **yaml**, the usual form for Arazzo. |
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
| JSON Schema | `GET /v1/json/{tenant}/{project}/{version}` |

For private versions, pass an in-scope API key via the `X-API-Key` header (or the `api_key` query
parameter).

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
- [Browse published specs](./browse-published-specs.md) — view the same spec rendered
- [CLI quick-start](../reference/cli-quickstart.md) — full CLI reference
