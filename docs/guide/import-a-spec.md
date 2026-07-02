# How do I… import a specification?

Importing turns an existing OpenAPI, Swagger 2.0, Arazzo, or JSON Schema document into Apiome
classes, properties, paths, and operations you can edit. Import is **asynchronous**: you create a
job, it runs in the background, and you poll it to completion.

Supported inputs: **OpenAPI 3.x**, **Swagger 2.0**, **Arazzo 1.0**, **JSON Schema 2020-12**.

---

## In the UI

1. Open the **Designer** at `/ade/studio`.
2. Choose **Import** and select a file (or paste a document / URL).
3. Watch the job progress; when it reaches **completed**, the imported classes and paths appear on
   the canvas.

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
id; `--poll-interval` tunes how often the job is polled. See [cli-quickstart.md](cli-quickstart.md).

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

## Verify

- **UI:** the imported classes are listed in the Designer.
- **CLI:** `apiome schemas list` shows the new classes; `apiome projects list` shows the
  project the import created.

## Related

- [edit-classes-and-properties.md](edit-classes-and-properties.md) — refine what you imported
- [edit-paths.md](edit-paths.md) — refine the imported paths/operations
