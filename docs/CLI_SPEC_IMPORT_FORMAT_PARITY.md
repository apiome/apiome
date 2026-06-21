# CLI specification import — format parity checklist

This checklist aligns **`objectified import spec`** with the dashboard **Import dialog** (`ImportDialog` + `openapi-analyzer` content detection), the **repository filename scanner** (`objectified-rest` `detected_kind_from_path`), and the **REST import** surface (`POST /v1/tenants/{tenant_slug}/imports`). It satisfies Epic **[#3328 — Specification Import via REST (CLI)](https://github.com/KenSuenobu/objectified-commercial/issues/3328)** acceptance criteria for documented parity (child issue [#3332](https://github.com/KenSuenobu/objectified-commercial/issues/3332)).

## Epic acceptance criteria (cross-link)

- End-to-end tenant-scoped **spec file import** through the same REST pipeline as the app (no duplicate parsers in the CLI).
- Parsed output persists as **project-linked draft schema** with job polling and commit / rollback semantics.
- **Parity target:** CLI accepts the same **product import kinds** as the importer supports; filename sniff + `--format` mirrors UI behavior when content is ambiguous.

Source: [PLANNED_ROADMAP_CLI.md — Epic 13 (#3328)](./PLANNED_ROADMAP_CLI.md#epic-13-3328-specification-import-via-rest-cli).

## Checklist

Legend: **UI** = Import dialog / analyzer path; **Scan** = `detected_kind_from_path`; **CLI sniff** = `resolveSpecImportKind` without `--format`; **`--format`** = explicit kind via flag (`spec-format.ts` aliases + passthrough).

| Format | Typical inputs | UI analyzer | Repo scan | CLI sniff | `--format` | Server / notes |
|--------|----------------|--------------|-----------|-----------|------------|----------------|
| OpenAPI 3.x | `.yaml`/`.yml`/`.json`, `openapi*` / `swagger*` names | Yes | `openapi-candidate` | YAML/JSON body sniff | `openapi-3`, aliases `openapi`, `swagger`, … | REST contract; handlers may return **501** until importer is wired. |
| Swagger 2.x | Same extensions | Yes (`swagger`) | Via `swagger*` name | Same as OpenAPI when parsed as OpenAPI/Swagger JSON/YAML | `openapi-3` after conversion server-side (product-defined) | Treated as OpenAPI family in CLI metadata. |
| AsyncAPI | `.yaml`/`.yml`/`.json`, `asyncapi*` names | Yes | `asyncapi-candidate` | Body sniff `asyncapi` | `asyncapi-2`, aliases `asyncapi`, … | CLI sends discriminant server expects for AsyncAPI 2.x style payloads. |
| Arazzo | `.yaml`/`.yml`/`.json`, `arazzo*` / `.arazzo.yaml` | Yes | `arazzo-candidate` | Not inferred by CLI sniff | `arazzo` | **CLI gap:** use `--format arazzo` for Arazzo imports. |
| GraphQL | `.graphql`, `.gql` | Yes | `graphql-candidate` | Extension → `graphql` | `graphql` | |
| Protobuf | `.proto` | Yes | `protobuf-candidate` | Extension → `protobuf`; body can reinforce | `protobuf`, alias `proto` | |
| Avro | `.avsc` | Yes | `avro-candidate` | Extension → `avro` | `avro` | |
| Postman | `postman_collection.json`, `*.postman.json` | Yes (collections) | `postman-candidate` | Not sniffed from JSON or filename in CLI | `postman` | **CLI gap:** use `--format postman`. |
| RAML | `.raml`, YAML with RAML headers | Yes | Not specialized (often `yaml-candidate`) | No dedicated extension hint/content sniff | `raml` | **Scanner + CLI gap:** scan may only see generic YAML; CLI requires `--format raml`. |
| Thrift | `.thrift` | Yes | Not in `detected_kind_from_path` | No extension hint | `thrift` | **Scanner gap:** no `*-candidate`; **CLI gap:** no `.thrift` extension sniff — use `--format thrift`. |
| DBML | `.dbml` | If presented as analyzable doc | `dbml-candidate` | No dedicated extension hint/content sniff | `dbml` | **CLI gap:** use `--format dbml`. |
| Prisma | `schema.prisma` | Product-dependent | `prisma-candidate` | No path sniff for `schema.prisma` | `prisma` | **CLI gap:** no prisma path heuristic — use `--format prisma` and a sensible `--filename`. |
| SQL DDL | `.sql`, `.ddl` | Product-dependent | `sql-ddl-candidate` | Not sniffed | `sql` (passthrough) | Confirm server kind string matches importer. |
| ZIP bundle | `.zip` | When server accepts archives | Not classified by `detected_kind_from_path` | Not sniffed | `zip` (passthrough) | **Scanner + CLI sniff gap:** use `--format` if required by API; verify multipart vs JSON endpoints for large blobs. |
| Generic YAML/JSON | `.yaml`, `.yml`, `.json` | Analyzer may classify deeper | `yaml-candidate` / `json-candidate` | OpenAPI/AsyncAPI sniff only when keys present | Any supported kind | |

## Import dialog sources vs CLI

The dashboard Import dialog supports multiple **sources** (file upload, URL, clipboard, Git, SwaggerHub, Postman, etc.). The CLI accepts a **local path or stdin** (`-`) only; remote pulls are out of scope for `import spec`. Behavior stays aligned once bytes reach `POST …/imports`.

## References

- CLI command: `objectified-cli/src/commands/import/spec.ts`
- Kind resolution: `objectified-cli/src/lib/import/spec-format.ts`
- UI detection: `objectified-ui/src/app/utils/openapi-analyzer.ts` (`detectFormat`)
- Repository scan: `objectified-rest/src/app/repository_file_scan.py` (`detected_kind_from_path`)
- REST models: `objectified-rest` OpenAPI / `spec_import` routes (see codegen in `objectified-cli/src/generated/`)
