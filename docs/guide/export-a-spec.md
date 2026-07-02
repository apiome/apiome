# How do I… export / download a spec?

Apiome reconstructs the full OpenAPI 3.1 document (or Arazzo workflow document, or JSON Schema)
for a **published** version on demand. You can download it from the CLI or fetch it directly over
REST in JSON or YAML.

---

## With the CLI

```bash
# OpenAPI (default), JSON, to a file
apiome spec export --project <id-or-slug> --version <id-or-label> --output petstore.json

# YAML
apiome spec export --project <id-or-slug> --version <id-or-label> --yaml -o petstore.yaml

# Arazzo workflow document instead of OpenAPI
apiome spec export --project <id-or-slug> --version <id-or-label> --format arazzo -o flows.json
```

Use `-o -` to stream to stdout. `--format` accepts `openapi` (default) or `arazzo`.

## With the REST API

```http
GET /v1/schema/{tenant_slug}/{project_slug}/{version_slug}
Accept: application/json          # default; use application/yaml for YAML
```

Other representations of the same version:

| Format | Route |
|---|---|
| OpenAPI | `GET /v1/schema/{tenant}/{project}/{version}` |
| Arazzo | `GET /v1/arazzo/{tenant}/{project}/{version}` |
| JSON Schema | `GET /v1/json/{tenant}/{project}/{version}` |

For private versions, pass an in-scope API key via the `X-API-Key` header (or the `api_key` query
parameter).

## Verify

The exported document is valid OpenAPI and contains the classes and paths you edited. The
[Golden Path](../GOLDEN_PATH.md) does exactly this — it exports via the real CLI and re-validates the
downloaded document with `openapi-spec-validator`.

## Related

- [browse-published-specs.md](browse-published-specs.md) — view the same spec rendered
- [cli-quickstart.md](cli-quickstart.md) — full CLI reference
