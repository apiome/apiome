# How do I… edit paths & operations?

A **path** is an OpenAPI URL template (e.g. `/pets/{petId}`); each path carries **operations** (GET,
POST, …) with parameters, request bodies, and responses. Paths are authored **on a specific version
(revision)** — unlike classes, they belong to the revision you are editing.

---

## In the UI

1. Open the **Designer** and go to **Paths** at `/ade/studio/paths`.
2. Add or select a path template, then edit its summary, tags, and description.
3. Add operations and wire their parameters, request bodies, and responses to your classes.

## With the REST API

All path routes are scoped by tenant **and** version id.

| Action | Method & route |
|---|---|
| List paths | `GET /v1/paths/{tenant_slug}/{version_id}` |
| Get one path | `GET /v1/paths/{tenant_slug}/{version_id}/{path_id}` |
| Create a path | `POST /v1/paths/{tenant_slug}/{version_id}` |
| Update a path | `PUT /v1/paths/{tenant_slug}/{version_id}/{path_id}` |
| Delete a path | `DELETE /v1/paths/{tenant_slug}/{version_id}/{path_id}` |

Operations, parameters, request bodies, and responses hang off a path under
`/v1/paths/{tenant_slug}/{version_id}/{path_id}/…` (e.g. `…/operations`).

```http
PUT /v1/paths/{tenant_slug}/{version_id}/{path_id}
X-API-Key: <your-api-key>

{ "summary": "Find pet by ID", "tags": ["pets"] }
```

## With the CLI

The CLI inspects paths, operations, and Arazzo workflows for a version (read-only):

```bash
apiome paths      list --project <id-or-slug> --version <id-or-label>
apiome paths      show <path-ref> --project <id-or-slug> --version <id-or-label>
apiome operations show <op-ref>   --project <id-or-slug> --version <id-or-label>
apiome workflows  list --project <id-or-slug> --version <id-or-label>
```

`paths list` accepts `--tag`, `--method`, and `--q` (text search) filters.

## Verify

- **CLI:** `apiome paths list --project <p> --version <v>` lists the path and its operations.
- **Export:** the path appears in the reconstructed OpenAPI document — see
  [export-a-spec.md](export-a-spec.md).

## Related

- [cut-a-version.md](cut-a-version.md) — paths are authored on the revision you cut
- [lint-and-quality.md](lint-and-quality.md) — undocumented operations show up as findings
