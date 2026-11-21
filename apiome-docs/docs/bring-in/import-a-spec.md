---
title: "Import a specification"
description: "Turn an existing API description into a project or catalog item."
sidebar_position: 2
tags: [import]
---

Importing turns an existing API description into something Apiome can search, diff, lint and
convert. Import is **asynchronous**: you create a job, it runs in the background, and you poll it
to completion.

**Apiome imports 100<!--format-count:importable--> formats**, spanning all
6<!--format-count:paradigms--> canonical paradigms, and exports 66<!--format-count:exportable-->
of them again. The full list — with each format's registry key, input kinds, version coverage,
file extensions and export support — is generated from the running registries at
[Supported formats](./supported-formats.md). Do not maintain a copy of it anywhere else.

The same answer is machine-readable at `GET /v1/formats/matrix` and printed by `apiome formats`:

```bash
apiome formats                              # every format, as a table
apiome formats --direction import           # only what Apiome can read
apiome formats --paradigm event --json      # one paradigm, machine-readable
```

The page above is rendered from that response, so the guide, the API and the CLI cannot disagree.

## Two importers, one registry

Which importer handles a document is decided by the server, from the format it normalizes to:

- **The Projects importer** takes **OpenAPI 3.x** and **Swagger 2.0**. These normalize onto the
  editable class/property/path model, so an import becomes a **publishable Project** you can
  version, lint and publish. This is the path the rest of this page describes.
- **The Catalog importer** takes **everything else** — Protobuf/gRPC, GraphQL, AsyncAPI, Arazzo,
  JSON Schema, Thrift, Smithy, TypeSpec, WSDL, XSD, OData, EDI X12, UN/EDIFACT, SAP IDoc, SWIFT MT, HL7 v2, FHIR, COBOL copybooks,
  FIX, ISO 20022/8583 and the rest. A catalog import keeps the format's **own** structure rather
  than forcing it into the OpenAPI shape, so what you get back is what you put in. Catalog items
  are searchable, diffable and convertible; they are not publishable until converted.

Both importers read the same import-source registry, so a format is offered as soon as its adapter
is registered — the file pickers derive their `accept` lists from it rather than hard-coding one.
An unrecognized file extension is **not** rejected: the bytes are sent to content detection, and
the detector's verdict is what you are shown.

> Converting a catalog item into a publishable Project is a separate step — see
> [Convert a catalog item to OpenAPI](./convert-to-openapi.md) and [Understand export fidelity](../ship/export-fidelity.md) for
> what survives the conversion.

## Formats that need a bundled tool

A few adapters do not parse the document themselves — they shell out to the authoritative parser
for that format, which the container image bundles. The **Runtime** column of
[Supported formats](./supported-formats.md) says which, and a format whose tool is missing is
reported there (and on the source card) as *Needs toolchain* rather than being offered and then
failing mid-import.

**AsyncAPI is the exception: it is a hard dependency, not a degradable one.** The AsyncAPI
adapter runs `@asyncapi/parser` (the JavaScript reference parser) to validate and dereference the
document, and there is deliberately **no fallback parser** behind it.

### The fallback policy, stated

We considered shipping a minimal pure-Python structural parser for AsyncAPI 2.x/3.x that would
keep the format `available` with reduced capability, and rejected it. A reduced parse would
produce a canonical model that *looks* like a successful import while quietly differing from the
real one — different validation verdicts, unresolved `$ref`s, a different fingerprint, and
therefore a different diff and lint score for the same document depending on which runtime
imported it. A format that is honestly unavailable is recoverable; a format that is silently
half-parsed is not. So:

- **The image ships the parser.** Its exact version is pinned in the REST service's toolchain
  manifest (`apiome-rest/toolchain/package.json`) and installed during the container build, which
  smoke-tests it before the image is finished.
- **Startup verifies it and says so.** The service invokes the parser at boot and logs the
  version it resolved, so a deployment's logs always name the `@asyncapi/parser` it is running.
- **A missing parser fails loudly, never silently.** With `APIOME_REQUIRE_TOOLCHAIN=1` — the
  default in the shipped image and in any production deployment — the service **refuses to
  start** and names the tool, the formats it gates, and the override to point at a sidecar
  binary. Set `APIOME_REQUIRE_TOOLCHAIN=0` to accept a deployment without AsyncAPI import: the
  service then starts, logs the loss as an `ERROR`, and reports the format as unavailable
  everywhere it is listed. It never comes up quietly missing a format.
- **The health surface reports it.** `GET /health` carries a `toolchain` block
  (`status`, `enforced`, `required`, `available`, `missing`). It states availability and nothing
  more — the endpoint is unauthenticated, so resolved paths and exact parser versions stay
  behind `GET /v1/ops/toolchain` (platform-admin), which also names which formats each tool
  gates. The version the runtime resolved is in the startup log either way.

Every other bundled tool (`buf` for Protobuf/gRPC and Connect, the linters, the diff CLIs)
remains optional: its absence degrades exactly one format to a stated *Needs toolchain*, and the
service starts normally.

Running the service outside the container? `apiome-rest/scripts/install_dev_toolchain.sh`
installs the pinned parser (and `buf`) into `apiome-rest/.tools`; `./run.sh` and `yarn dev` call
it for you.

---

## In the UI

1. On **Projects**, **click “Import”** (or press <kbd>I</kbd>) and choose a source — a file, a URL,
   pasted content or a Git repository.
2. Go through **Analyze → Preview → Import**; see [Import your first
   project](../getting-started/first-project.mdx) for each step, and the [Import
   wizard](./import-wizard.mdx) for formats other than OpenAPI.
3. When the job says **Completed**, **click “Continue”**; the wizard shows **Import Complete!** and
   the new project appears on **Projects**.

## With the CLI

The CLI auto-detects the format, uploads it, and waits for the job by default:

```bash
apiome import openapi ./petstore.openapi.yaml      # explicit format
apiome import swagger ./legacy-swagger.json
apiome import auto    ./some-spec.yaml             # auto-detect

# useful flags
apiome import openapi ./petstore.openapi.yaml \
  --project-name "Pet Store" \
  --dry-run                                             # validate without writing
```

`--dry-run` validates and reports without persisting; `--no-wait` returns immediately with the job
id; `--poll-interval` tunes how often the job is polled. See [CLI quick-start](../reference/cli-quickstart.md).

## With the REST API

```http
POST /v1/tenants/{tenant_slug}/imports
Content-Type: application/json
X-API-Key: <your-api-key>

{ "document_base64": "<base64 bytes>", "filename": "petstore.openapi.yaml" }
```

Returns **202 Accepted** with a job id. Poll the job until it reports `completed`, then commit it.
A multipart variant exists for direct file uploads:

```http
POST /v1/tenants/{tenant_slug}/imports/upload
Content-Type: multipart/form-data
```

## Check quality before importing

Pre-flight scores a document **without writing anything**, so you can decide whether it is worth
importing (and fix it first if it is not):

```http
POST /v1/tenants/{tenant_slug}/import/preflight
Content-Type: application/json
X-API-Key: <your-api-key>

{ "document_base64": "<base64 bytes>", "filename": "petstore.openapi.yaml" }
```

Returns **200** with the detected format and confidence, where the import would land
(project / catalog / types), the entity counts, the lint **score and grade**, and the findings
ranked worst-first — each with its rule id, severity, location, and how to fix it. Omit
`source_kind` to auto-detect, or set it to force a specific importer.

A document that cannot be imported is still a 200: `ok` is `false` and `error.code` carries a
stable code (for example `INPUT_MALFORMED`, `FORMAT_UNRECOGNIZED`, `INPUT_TOO_LARGE`) plus
remediation text — key your automation off the code, not the message. Pre-flighting the same bytes
twice is served from cache and says so in `cache.hit`.

### In the catalog import wizard

The wizard runs this for you. Its steps are **Source → Detect & route → Options → Quality →
Import**: the **Quality** step shows the grade orb and score, the error/warning/info tally, the
ranked findings (each links to its line in the source pane beside the list), and the style guide
that scored them. Nothing is written to the catalog until you confirm there — **Cancel** and
**Back** leave no trace.

When a quality policy blocks the document, **Import** is disabled with the reason stated; if the
policy permits an override, **Import anyway** commits it and records a waiver against that report's
fingerprint. If pre-flight itself cannot run, the step says so and offers **Retry pre-flight** or an
explicit import without a score.

Tick **Skip this step for clean imports** to stop pausing here for documents that pass. The
pre-flight still runs, and the step still stops whenever the verdict blocks or cannot be produced.

### Set the tenant quality policy

By default nothing is blocked: a fresh tenant scores every import and reports the result without
refusing anything. To make the gate real, **go to Govern → Style guides** and edit the
[**Import & export quality policy**](../govern/style-guides.mdx#import--export-policy) (over the REST
API,
[`PUT /v1/tenants/{tenant_slug}/governance/quality-policy`](../reference/rest/governance.md#put-quality-policy-v1-tenants-tenant-slug-governance-quality-policy-put)):

- **Minimum grade / minimum score / refuse findings at** — the three floors. Leave one blank to
  not use it; a scope with no floor can never block.
- **Refuse the import when a floor is missed** — off means *advisory* (the shortfall is reported,
  the import proceeds); on means the commit is refused.
- **Overrides** — whether a blocked user may proceed by recording a waiver, which role slugs may
  (tenant administrators resolve to `owner`), and how long a waiver is honoured.
- **Per-format overrides** — a format may tighten a floor without restating the rest; resolution is
  *format override → tenant → default*, and the pre-flight verdict names the tier that won
  (`policy.source`).

Each save appends an immutable version, listed underneath with its fingerprint and author
(`GET …/governance/quality-policy/versions` over the API), and writes an audit entry. Every verdict names the `policyVersionId` it applied.

The policy is enforced **on the server**, at `POST /v1/tenants/{tenant_slug}/imports` — not only in
the wizard. An import that policy refuses comes back as **409** with
`detail.code = QUALITY_POLICY_BLOCKED`, the reason, the remediation, and the full verdict, and no
job is created. A dry run is never gated (it writes nothing).

### Waivers

"Import anyway" records a waiver in the tenant's ledger with the actor, the reason, the scope, and
an expiry taken from the policy's waiver lifetime. It is matched on the candidate's content hash
and the format it was granted for, so the same bytes commit through the gate until it expires — at
which point the shared waiver-expiry sweep has already warned the tenant (`lint.waiver.expiring`,
`kind: quality:import`). Active waivers are listed under the policy on Style guides. To grant one
over the REST API:

```bash
curl -X POST "$APIOME_API/v1/tenants/$TENANT/governance/quality-waivers" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"scope":"import","subjectKey":"<cache.content_hash from the pre-flight report>",
       "formatKey":"openapi","reason":"vendor spec we do not control"}'
```

The grant is refused with **403** unless the policy permits overrides *and* names your role — the
check is server-side, so a client cannot grant itself one.

## Streaming responses (OpenAPI 3.2)

OpenAPI 3.2 describes a streamed body with `itemSchema`: the schema of **each element** of the
stream, not of the whole body. The Projects importer reads `itemSchema` wherever it would read
`schema`, in request bodies and responses. The catalog reads it too, with the same stream kinds;
see [The same result in the catalog](#the-same-result-in-the-catalog):

```yaml
responses:
  "200":
    content:
      application/jsonl:
        itemSchema:
          $ref: '#/components/schemas/LogEvent'
```

| Media type | Stream kind |
| --- | --- |
| `application/jsonl` (and any `+jsonl` type) | `jsonl` — JSON Lines |
| `application/json-seq` (and any `+json-seq` type) | `json-seq` — JSON text sequence |
| `text/event-stream` | `sse` — Server-Sent Events |
| Any other media type with an `itemSchema`, such as a stream of `application/problem+json` | `sequential` |

What the import does with it:

- **The element becomes a class.** A `$ref` element imports as the class it points at. An inline
  element with properties becomes a class named after the operation, such as
  `ImportLogsRequestStreamItem` for a request body or `StreamLogsStreamItem` for a response. A
  number is added if that name is taken. An element without properties, such as a plain `string`,
  stays inline on the path.
- **The class is tagged.** Each element class carries `x-apiome-stream-kind` with the stream kind
  from the table, so a stream element is never mistaken for a single body. A class streamed as two
  different kinds is tagged `sequential`.
- **The path links to it.** The operation's request body or response points at the element class.

On the **Analyze** step, **Feature compatibility** lists **Sequential / streaming media types**.
The entry names each streaming media type with its kind and counts its uses. A stream media type
that has only a `schema` and no `itemSchema` is listed too, and imports as a regular body.

## QUERY and custom methods (OpenAPI 3.2)

OpenAPI 3.2 declares operations outside the fixed verbs (`get`, `put`, `post`, `delete`,
`options`, `head`, `patch`, `trace`) in two places on a path:

```yaml
paths:
  /search:
    query:                 # the HTTP QUERY method
      requestBody:
        content:
          application/json:
            schema: { $ref: '#/components/schemas/SearchFilter' }
    additionalOperations:  # any other method, keyed by its token
      REPORT:
        responses: { "207": { description: Report } }
```

The Projects importer and the catalog walk both, the same way they walk the fixed verbs:

- **Every operation imports.** A `query` operation imports as **QUERY**. Each
  `additionalOperations` entry imports under its method, such as **REPORT**. Their parameters,
  request bodies and responses link to their classes like any other operation's.
- **The method token is kept.** The token as written (`QUERY`, `REPORT`, or a mixed-case
  `Purge`) is stored on the operation.
- **A method declared twice imports once.** If a path declares a method in two places, such as
  `get` and `additionalOperations.GET`, the first declaration imports and the import shows a
  warning naming the method.

An OpenAPI 3.1 document has no field for these methods, so export writes them to extensions on
the path: QUERY to `x-apiome-query-operation`, others to `x-apiome-additional-operations` under
their token. Importing that document again restores the same operations.

On the **Analyze** step, **Feature compatibility** lists **QUERY HTTP method** and
**additionalOperations (custom HTTP methods)** as information, with a use count for each.

## Tag hierarchy (OpenAPI 3.2)

OpenAPI 3.2 tags can carry a `summary`, a `kind` (such as `nav`, `badge` or `audience`) and a
`parent` naming another tag, which turns the tags into a tree:

```yaml
tags:
  - name: billing
    kind: nav
  - name: invoices
    parent: billing
  - name: refunds
    parent: billing
```

The Projects importer keeps the whole taxonomy (the catalog builds the same tree; see
[The same result in the catalog](#the-same-result-in-the-catalog)):

- **Every tag field is kept.** `name`, `summary`, `description`, `parent`, `kind` and
  `externalDocs` are stored on the project's metadata under `x-apiome-tag-taxonomy`. A later
  import into the same project that declares tags replaces it. In a project built from several
  repository files, the highest-precedence file's taxonomy wins.
- **Operations keep their tags.** Each operation keeps the tag names it lists.
- **Classes keep the tags they declare.** A schema that names tags with `x-tags`, `x-tag` or
  `tags` imports as a class that lists them in `x-apiome-tags`. OpenAPI schemas have no tag field
  of their own, so a schema without one of these imports untagged.

Two problems are fixed during import, and each one shows as an import warning:

| Problem | What the import does |
| --- | --- |
| `parent` names a tag the document does not declare | The tag imports as a top-level tag. |
| Tags form a parent cycle (`a` → `b` → `a`, or a tag that is its own parent) | Every tag on the cycle imports as a top-level tag. Tags below the cycle stay under their parent. |

A tag name declared twice keeps its first declaration, also with a warning.

On the **Analyze** step, **Feature compatibility** lists **Tag taxonomy (summary / parent /
kind)**. It shows the number of tags, levels and top-level tags, and the kinds used. It appears
only when a tag uses `summary`, `parent` or `kind`, or when the tag hierarchy has a problem. The
entry is a warning when the hierarchy has a problem, and names it.

## References: `$self` and `$ref` overrides (OpenAPI 3.2)

OpenAPI 3.2 lets a document name itself with `$self`. Each `$ref` is a URI resolved against it,
so a reference can point back into the same document by its full or relative address:

```yaml
openapi: 3.2.0
$self: https://api.example.com/specs/orders.yaml
components:
  schemas:
    Order:
      properties:
        customer:
          $ref: https://api.example.com/specs/orders.yaml#/components/schemas/Customer
          summary: Billing customer
          description: Overrides Customer.description for this field
        shipping:
          $ref: ./orders.yaml#/components/schemas/Address
```

What the Projects importer does (the catalog does the same):

- **Same-document references resolve.** A `$ref` that resolves against `$self` to the same
  document imports as a local reference, the same as `#/components/schemas/Customer`. Both
  `customer` and `shipping` above link to their classes.
- **References to other documents are kept, not followed.** A `$ref` that resolves to another
  document, such as `common.yaml#/components/schemas/Customer`, is kept as written. The import
  shows a warning that lists it.
- **Without `$self`, nothing changes.** References are read exactly as before.

A `summary` or `description` written beside a `$ref` is a **local override**:

- On a property, the sibling `description` becomes the property's description and the `summary`
  stays on the property. The referenced class keeps its own description.
- On a class built with `allOf`, a sibling `description` on a `$ref` entry is used instead of the
  referenced class's description. Without a sibling, the referenced class's description is used,
  as before.
- On a class that is a `$ref` to another class, the sibling `description` becomes the class's
  description.

Circular references still stop at the first repeat.

On the **Analyze** step, **Feature compatibility** lists **Document base URI ($self)**. It counts
the references that point back into the document and names any that point to another document.
The entry is a warning when some do. Same-document references written as full URLs no longer
count as **External references**.

## Arazzo sources in a Projects import

An Arazzo workflow lists the API descriptions its steps call in `sourceDescriptions`. Each step
names its target with `operationId` or `operationPath`:

```yaml
sourceDescriptions:
  - name: petstore
    type: openapi
    url: ../specs/petstore.yaml
workflows:
  - workflowId: adopt
    steps:
      - stepId: pet
        operationId: petstore.getPet
      - stepId: byPath
        operationPath: '{$sourceDescriptions.petstore.url}#/paths/~1pets~1{petId}/get'
```

The **Import** dialog reads Arazzo **1.0.x** and **1.1.x** documents. The analysis step names the
version the document declares (for example **Arazzo 1.1.0**); any other version, such as
`arazzo: 2.0.0`, shows as **unsupported version** and is not imported.

When an Arazzo document goes through the Projects importer (an Arazzo file in the **Import**
dialog, or an Arazzo file imported from a repository), the import checks every source and step:

- **Each source is validated.** Its `type` must be `openapi` or `arazzo`, or `asyncapi` in a
  document that declares Arazzo 1.1 or later. Its `url` must match a
  document supplied with the import, either relative to the workflow's folder or to the root of
  the set. Every source that fails one of these checks is reported with a code.
- **Each step is resolved.** An `operationId` can be bare (`getPet`), name its source
  (`petstore.getPet`) or use the Arazzo expression (`$sourceDescriptions.petstore.getPet`). An
  `operationPath` names a path and method in a source. A resolved step records the operation's
  path, method and `operationId`. A bare id found in more than one source does not resolve; name
  the source instead.
- **Nothing is dropped.** A step that does not resolve keeps its reference as written, and the
  import shows a warning with the reason. A step that calls another workflow (`workflowId`) is
  recorded and not resolved.
- **AsyncAPI steps are left to the server.** In an Arazzo 1.1 document, a step that calls an
  `asyncapi` source (for example `$sourceDescriptions.orderEvents.receivePaymentSettled`) is
  recorded with its reference and no warning; the server-side Arazzo importer links it to the event
  it waits for.

The **Import** dialog and repository-file imports send only the workflow document today. Until
they send the source documents too, every source is reported as **not in the import bundle**,
and steps keep their raw references with a warning.

| Code | Meaning |
| --- | --- |
| `SOURCE_INVALID` | A `sourceDescriptions` entry has no `name` or no `url`. |
| `SOURCE_DUPLICATE` | Two entries share a name; the first is kept. |
| `SOURCE_TYPE_UNSUPPORTED` | The `type` is not `openapi` or `arazzo` (or `asyncapi` in an Arazzo 1.1 document). An `asyncapi` source in a 1.0 document names the version it needs: change `arazzo:` to `1.1.0`. |
| `SOURCE_NOT_IN_BUNDLE` | No document supplied with the import matches the `url`. |
| `SOURCE_TYPE_MISMATCH` | The matched document is not the declared type. |
| `STEP_REFERENCE_UNRESOLVED` | A step's `operationId` or `operationPath` did not resolve. |

The full result (every source, every step's resolution and every issue) is returned on the
import job's summary as `arazzoResolution`. Each workflow and its steps are also stored as records
of their own, with each step's resolved operation; the item's **Workflows** tab shows them — see
[Arazzo workflows](../build/arazzo-workflows.mdx). To read the records from a terminal or a script,
use `apiome arazzo list` / `show` or the `/v1/workflows` REST routes, and run
`apiome arazzo validate --catalog <item-uuid>` in CI to fail when a step did not resolve. Every
field is described in [Arazzo workflow records](../reference/arazzo-workflow-records.md).

## Import an Arazzo workflow with its API files

To bring in a workflow and the OpenAPI or AsyncAPI files it calls in one import, ship them
together. This uses the catalog Arazzo importer (registry key `arazzo`).

1. **Put the files in one archive.** Zip (or tar) the workflow and every description its
   `sourceDescriptions` point at, keeping the relative paths the `url`s use. For example,
   `flow.arazzo.yaml` with `url: ./pets.yaml` and `url: apis/users.openapi.json` needs
   `pets.yaml` next to it and `users.openapi.json` in an `apis/` folder.
2. **Import the archive.** With the CLI, pass the archive or the folder itself:

   ```bash
   apiome import arazzo ./adopt-a-pet.zip --dry-run
   apiome import arazzo ./adopt-a-pet/ --root flow.arazzo.yaml
   ```

   With the REST API, send the archive bytes to `POST /v1/tenants/{tenant_slug}/imports` with
   `"filename": "adopt-a-pet.zip"` and `metadata.source_kind` set to `arazzo`. A repository
   import works the same way: ticking the workflow in a repository's files also fetches the files
   its `sourceDescriptions` name.
3. **Check the import report.** The finished job's summary has an `arazzo_sources` block, and the
   CLI prints it as `Arazzo sources: 2 resolved (2 fileset), 0 unresolved`.

The workflow is picked as the archive's root, because the API files it calls are its sources, not
competing roots. Use `--root` (or `metadata.options.archive_root`) when the archive also holds an API file
the workflow does not call. In that case the import can't tell which file you meant.

Each source is looked up in this order, and the first match wins:

| Order | Tier | What matches |
| --- | --- | --- |
| 1 | `fileset` | A relative `url` names a file in the archive, relative to the workflow's folder or to the archive root. |
| 2 | `catalog` | A spec you already imported: from the same repository and branch at that path, or from exactly that URL. |
| 3 | `remote` | An absolute `https://` URL, fetched through the SSRF guard. Only when the import sets `metadata.options.resolve_remote_refs` to `true` and the deployment allows remote resolution. |

A resolved source's document is used to check the steps that call it, so a step naming an
operation the API does not have is reported by the `arazzo.dangling-operation-id` lint rule.

In an Arazzo 1.1 workflow, a step can wait on an event channel instead of calling an operation. It
names the channel with `channelPath`, for example
`$sourceDescriptions.account-events#/channels/customerSignedUp`. The catalog importer takes that as
the step's target and records the step as asynchronous. It keeps the step's `action`,
`correlationId` and `timeout`, and the workflow's `parameters` and the document's `$self`, so the
workflow exports back unchanged.

**Nothing is dropped silently.** Every source no tier resolves is listed in
`arazzo_sources.unresolved_sources` with a reason code. It is also raised as an
`ARAZZO_SOURCES_UNRESOLVED` warning on the job and stored on the catalog item's
`format_metadata.arazzoSources`.

| Reason | Meaning |
| --- | --- |
| `not-in-fileset` | A relative `url` names no file in the archive and no catalog spec. |
| `relative-without-fileset` | A single-file import has a relative `url` and no catalog spec. Upload the archive instead. |
| `unparseable-member` | The file the `url` names is in the archive but is not valid JSON or YAML. |
| `invalid-source-description` | The entry has no `name` or no `url`. |
| `resolution-disabled` | An absolute URL, not in the catalog, and remote resolution is off for this import. |
| `blocked-by-ssrf-guard` | The URL points at a private address or uses a refused scheme such as `file:`. |
| `fetch-failed` | The fetch failed (timeout, connection error, or an error status). |
| `unparseable-document` | The fetched document is not valid JSON or YAML. |
| `budget-exhausted-refs`, `budget-exhausted-bytes`, `budget-exhausted-time` | The import's remote-fetch budget ran out. |

## The same result in the catalog

An OpenAPI or Arazzo document can also land in the **catalog**: a connector sync, an Arazzo
fileset import, or an OpenAPI item you later convert with **“Convert to Project”**. The catalog
reads the document with the server's importer instead of the Projects importer. Both read the
OpenAPI 3.2 and Arazzo constructs on this page the same way:

| Construct | Projects and catalog both… | How each stores it |
| --- | --- | --- |
| Streaming `itemSchema` | Read the element of each streamed media type, with the same stream kind (`jsonl`, `json-seq`, `sse`, `sequential`). A media type with only a `schema` is a regular body on both. | Projects turns an inline object element into a class named after the operation, such as `ImportLogsRequestStreamItem`, and tags element classes with `x-apiome-stream-kind`. The catalog keeps an inline element inline, on the request or response. |
| `query` and `additionalOperations` | Import every operation once, under the same method (**QUERY**, **REPORT**). A method declared twice keeps its first declaration and is reported. A token written in mixed case, such as `Purge`, is kept as written. | The same on both. |
| Tag hierarchy | Keep a tag's first declaration and its `summary`, `kind` and `parent`. Make a tag whose `parent` is not declared, or that is on a `parent` cycle, a top-level tag. Report each repair. | Projects stores every tag field in the project's `x-apiome-tag-taxonomy` and lists a schema's `x-tags` on its class. The catalog keeps `externalDocs` and a schema's `x-tags` in the stored source, and writes them back on export. |
| `$self` and `$ref` overrides | Resolve same-document references against `$self`. Keep a reference to another document as written, without linking it to a schema of the same name. Use a sibling `description` as the property's description. | Projects keeps a sibling `summary` on the property. The catalog keeps it in the stored source and writes it back on export. |
| Arazzo sources and steps | Resolve a step's `operationId` (in every spelling) and `operationPath` to the same operation, and report the same sources and steps as unresolved. | Projects resolves only against the files imported with the workflow. The catalog also looks in the catalog and, when allowed, fetches a remote URL (see [Import an Arazzo workflow with its API files](#import-an-arazzo-workflow-with-its-api-files)), and links an AsyncAPI step to its channel. |

Tests import the same set of documents both ways and compare the results. A difference that is
not in the **How each stores it** column fails the build.

## Verify

- **UI:** the wizard shows **Import Complete!** and the new project appears on **Projects**.
- **CLI:** `apiome schemas list` shows the new classes; `apiome projects list` shows the
  project the import created.

## Related

- [Supported formats](./supported-formats.md) — every format Apiome imports and exports,
  generated from the registries (its **Runtime** column is where a missing bundled tool shows up)
- [Import an AWS API Gateway export](./aws-api-gateway-import.md) — what an exported REST or HTTP API's extensions become
- [Import an Azure API Management API](./azure-api-management-import.md) — what an APIM API's policies become
- [Import an Apigee proxy bundle](./apigee-proxy-bundle-import.md) — what a bundle's flows, targets and policies become
- [Import Envoy and Istio routes](./envoy-istio-route-import.md) — service-mesh route tables as inferred operations
- [Import reverse-proxy routes](./reverse-proxy-route-import.md) — Traefik, nginx, HAProxy, Consul and Tyk routing as inferred operations
- [Import TypeScript types](./typescript-types-import.md) — a module's exported interfaces, type aliases and enums as catalog schema types
- [Import Zod schemas](./zod-schema-import.md) — a Zod module's exported schemas, with their validation constraints
- [Import a tRPC router](./trpc-router-import.md) — a router's procedures as query, mutation and subscription operations
- [Import Pydantic models](./pydantic-model-import.md) — a Python module's models and their constraints, read without running it
- [Import CUE, Pkl and Dhall schemas](./typed-config-import.md) — typed configuration schemas with their constraints, evaluated by each language's own tool
- [Import an OPC UA NodeSet2 model](./opcua-nodeset-import.md) — an industrial information model's types, methods and reference graph, with its namespaces and model versions
- [Import SHACL, OWL and JSON-LD](./linked-data-import.md) — SHACL shapes graphs, OWL / RDFS ontologies and JSON-LD contexts as data schemas, with IRIs kept as provenance and open-world semantics declared
- [Import ROS 2 interfaces](./ros2-import.md) — `.msg`, `.srv` and `.action` files or a whole interface package, as records, request/response operations and action feedback channels
- [Import PL/I structures](./pli-structure-import.md) — `DCL` structures and their `%INCLUDE` members as records with a byte-accurate storage map, `UNION` shown as shared storage, and the layout assumptions stated
- [Import IMS DBD and PSB](./ims-dbd-psb-import.md) — IMS segment hierarchies as nested records with byte-accurate fields, and each program's `PROCOPT` as a declared access profile
- [Import Natural / ADABAS DDM](./natural-ddm-import.md) — an ADABAS file's fields with byte lengths, multiple-value fields and periodic groups as arrays, and descriptors as declared key metadata
- [Import VSAM cluster definitions and CICS BMS maps](./vsam-cics-bms-import.md) — IDCAMS and LISTCAT cluster definitions as record envelopes with their keys, and BMS mapsets as screen records with fields positioned by row and column
- [Import LwM2M and Matter device models](./device-model-import.md) — LwM2M / IPSO object definitions as data schemas and Matter clusters and device types as RPC APIs, with units, ranges, access modes and defaults
- [Import MQTT Sparkplug B payloads](./sparkplug-import.md) — Sparkplug B topics as MQTT channels and metrics as the message schema, from payloads or a topic-namespace description
- [Import an A2A Agent Card](./a2a-agent-card-import.md) — catalog an agent's skills, tags and security, from a file or its well-known URI
- [Import ACP agent manifests](./acp-agent-manifest-import.md) — catalog an ACP server's agents and capabilities, from a file or its `/agents` listing
- [Import agentic-web site manifests](./agents-manifest-import.md) — catalog a site's agents.json, agent.json, agents.txt or llms.txt and the agent descriptors it points at
- [Import a CNCF xRegistry](./xregistry-import.md) — catalog CloudEvents schemas, message definitions and endpoints from an xRegistry document or a live registry
- [Import a FIX Orchestra repository](./fix-orchestra-import.md) — catalog the declared FIX schema: messages, code sets, components, groups and presence
- [Read a catalog item's format details](./catalog-format-details.md) — what a catalog item records per format
- [Convert a catalog item to OpenAPI](./convert-to-openapi.md) — promote a catalog item to a publishable Project
- [Edit classes and properties](../build/edit-classes-and-properties.md) — refine what you imported
- [Edit paths and operations](../build/edit-paths.md) — refine the imported paths/operations
