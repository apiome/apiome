# How do I… browse published specs?

Browse is the read surface for **published** versions. Public versions are reachable without
authentication; private versions require an in-scope API key. A fresh tenant always has at least one
browsable spec — the seeded, published `petstore-sample` project.

---

## In the UI

- Open **Published** at `/ade/dashboard/published` to see your tenant's published versions.
- The dedicated `apiome-browse` app renders the catalog and each spec's rendered OpenAPI.

## Interactive Swagger UI for a published spec

Every published version has its own hosted Swagger UI:

```
GET /v1/swagger/{tenant_slug}/{project_slug}/{version_slug}
```

Open that URL in a browser (e.g. `http://localhost:8000/v1/swagger/acme-corp/petstore-sample/1.0.0`)
to get a fully interactive API reference for that spec. This is distinct from `/docs`, which
documents the Apiome REST API itself — see [api-reference.md](api-reference.md).

## With the REST API

```http
GET /v1/browse/tenants/{tenant_slug}/projects                              # public projects
GET /v1/browse/tenants/{tenant_slug}/projects/{project_slug}/versions      # published versions
```

These browse routes serve public content without authentication.

## With the CLI

```bash
apiome projects list                    # projects you can see
apiome versions list --project-id <id>  # versions in a project
```

## Verify

The version you published in [publish-a-version.md](publish-a-version.md) appears in the published
list and renders in its Swagger UI.

## Related

- [export-a-spec.md](export-a-spec.md) — download the raw OpenAPI document
- [mcp-quickstart.md](mcp-quickstart.md) — query the same published specs from an MCP host
