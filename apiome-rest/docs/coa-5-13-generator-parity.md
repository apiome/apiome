# Generator parity audit — COA-5.13 (#7089)

Before the UI's TypeScript OpenAPI generator was removed, it and the REST generator rendered the
same revisions and every difference was classified. This is the report the ticket asks for. Each
difference is either **fixed** (the REST generator changed) or **accepted** (the UI now shows what
REST renders), with the reason.

## Result

| | Before the fixes | After the fixes |
| --- | --- | --- |
| Revisions rendered by both generators | 47 | 47 |
| Byte-for-byte identical after parsing | 0 | 0 |
| Difference classes | 17 | 10, all accepted |
| Differences that lose or change API meaning | 6 | 0 |

No revision is identical, because two accepted differences touch every document (`info.title` and
`info.description`).

## Method

- **Revisions.** A scratch database (migrated to V406, dev seeds applied) received every file of
  the OpenAPI corpus (`apiome-ui/examples/openapi/**`, 49 manifest entries) through the real import
  worker (`apiome-ui/scripts/rest-spec-import-worker.ts`), one project per file. 46 imported; the
  3 that did not are negative fixtures that are not parseable documents
  (`negative/01-syntactic-unclosed-flow-sequence.yaml`, `negative/02-truncated-mid-quoted-ref.yaml`,
  `negative/03-wrong-format-graphql-sdl.graphql`). The seeded Pet Store sample project is the 47th.
- **TypeScript side.** `buildOpenApiSpecJsonForVersion(row, project.name, project.metadata)`, the
  call every UI screen made.
- **REST side.** `build_live_spec(…)`: before the fixes as `GET /v1/schema` rendered it (OpenAPI
  3.1, private operations removed); after the fixes as the new members' document (OpenAPI 3.2,
  private operations kept).
- **Comparison.** A structural walk of the two parsed documents. Each difference is recorded by
  JSON Pointer and kind (only in one, different value, different list length, different key order),
  then pointers are generalised (schema, property, path and method names replaced by `*`) so that
  one cause is one class.

### Limits of the audit

- **No tenant data.** The ticket asks for a sample of real tenants' revisions as well. No such
  database is reachable from the development machine, so the sample is the corpus plus the seeded
  sample project. The corpus is the wider of the two in constructs; real revisions may still hold
  hand-edited rows the importer never writes.
- **Not exercised by the corpus** — settled by reading both generators instead: private operations,
  canvas notes, pinned library components, revision deprecation metadata and the project tag list.
  They are listed below under the same two headings.

## Fixed in the REST generator

These were defects of `app/openapi_generator.py` / `app/paths_generator.py`. They also affected
`GET /v1/schema`, the classified diff, compatibility checks and exports. Tests:
`tests/test_openapi_generator_parity.py`.

| # | Difference | Revisions | Occurrences | Fix |
| --- | --- | --- | --- | --- |
| 1 | A property's description was missing. REST read it only from the property's JSON; the row's `description` column, where the importer and the editor write it, was ignored. | 31 | 312 | The column wins, then the JSON, then the JSON's `title`. |
| 2 | `operationId` was missing from every operation. The row names it `operation_id`; the generator read `operationId`. | 10 | 45 | Both spellings are read. |
| 3 | Only `apiKey` security schemes were written; `http`, `oauth2`, `openIdConnect`, `mutualTLS` and custom schemes were dropped. | 2 | 2 | Every stored scheme type is written, with the same rules the UI used. |
| 4 | An object property with required children lost its own `required` flag on its parent: the child list replaced the flag before it was read. | 1 | 3 names | The flag is read from the stored JSON, at every nesting level. |
| 5 | `type: object` was forced on a schema composed with `allOf` / `anyOf` / `oneOf`. Beside `oneOf` of scalars that rejects every value. | 5 | 22 | A composed schema keeps only the type it declares. |

Because the output for unchanged rows changed, `OPENAPI_GENERATOR_VERSION` is now `2`: stored
`rendered_openapi` documents are rendered again on their next read. Frozen versions keep their bytes.

## Resolved by a second rendering

| # | Difference | Revisions | Resolution |
| --- | --- | --- | --- |
| 6 | `openapi: 3.2.0` (UI) against `3.1.0` (REST); 3.2 constructs native in one and on `x-apiome-*` stashes in the other. | 47 | The UI reads a **members' document** (`GET /v1/versions/{tenant}/{project}/{version}/document`, kind `openapi_members`): OpenAPI 3.2. `GET /v1/schema` stays 3.1. |
| 7 | Operations marked `x-private` were shown by the UI and removed by REST. *(Not in the corpus.)* | — | The members' document keeps them, each with `x-private: true`. `GET /v1/schema` still removes them. |

## Accepted: the UI now shows what REST renders

| # | Difference | Revisions | Why it is accepted |
| --- | --- | --- | --- |
| 8 | `info.title`: the project's name (UI) against `<project slug> API` (REST). | 47 | One title per project everywhere a document is served. |
| 9 | `info.description`: the revision's note (UI) against the project's description (REST). | 47 | The revision note changed between any two revisions, so it showed as a change in every compare. The project description does not. |
| 10 | Every schema carries `title` = its class name (REST only). | 38 | Additional and harmless; consumers of `GET /v1/schema` already receive it. |
| 11 | Top-level `security` listing every scheme with no scopes (UI only). | 3 | The UI derived it from the list of schemes; the document's own top-level `security` is not stored by the importer. In one of the three files it happened to match the source, in the others it added a requirement the source did not have. REST writes none. Storing the source's `security` is separate work. |
| 12 | `requestBody.required: false` written (UI) or left out (REST). | 1 | The same meaning: `false` is the default. |
| 13 | `maxItems` on an inline response schema kept by REST, dropped by the UI. | 1 | REST keeps more of the source. |
| 14 | Key order inside `requestBody`, inline `properties` and the document root. | 12 | JSON objects are unordered. A text diff compares two documents from the same generator, so order never shows as a change. |
| 15 | Canvas sticky notes: `x-apiome-note` on a schema and `x-apiome-canvas` on the document (UI only). *(Not in the corpus.)* | — | The notes come from the signed-in user's own canvas layout, so two people saw different documents for the same revision. A document cached per revision cannot carry them. Decided on #7089 (2026-11-21): dropped from these views. Notes stay on the canvas; importing a document that carries them still restores them. |
| 16 | Pinned library components materialised into `components` (REST only). *(Not in the corpus.)* | — | REST's document is the complete one: the UI's left pinned components out. |
| 17 | `info.x-apiome-revision-deprecation` (REST only). *(Not in the corpus.)* | — | Additional; the UI's document simply lacked it. |

The project tag list (`tags`, with `summary` / `parent` / `kind` in 3.2) and the `x-metadata`
extension are written the same way by both.

## What a user will notice

- **View OpenAPI**, **Compare**, the Catalog **Versions** diff and the merge-request / review
  **Spec** and plain diff show REST's document: the title reads `<slug> API`, the description is the
  project's, schemas have a `title`, and canvas notes and the derived top-level `security` are gone.
- `GET /v1/schema` gains property descriptions, `operationId`, the missing security schemes and the
  corrected `required` and `type`. Its `ETag` changes once per unfrozen version.

## Reproducing

The harness lived outside the repository and cannot be run again as it was, because the TypeScript
generator is deleted in the same change. The REST half is kept as tests:
`tests/test_openapi_generator_parity.py` (each fix), `tests/test_rendered_documents.py` and
`tests/test_rendered_documents_db.py` (the members' document), and the per-PR
`tests/test_large_spec_harness.py` (a warm Compare read runs no generator).
