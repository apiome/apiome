# API reference

The Apiome REST API is a **FastAPI** application, so it publishes its own interactive API
reference automatically — there is nothing to generate or host separately. Point a browser at the
running REST service.

The REST service listens on **`http://localhost:8000`** by default (the `rest` service in
`docker-compose.yml`).

| Reference | URL | What it is |
|---|---|---|
| **Swagger UI** | `http://localhost:8000/docs` | Interactive, try-it-out reference for every REST route |
| **ReDoc** | `http://localhost:8000/redoc` | Read-optimized rendering of the same spec |
| **OpenAPI document** | `http://localhost:8000/openapi.json` | The raw machine-readable schema |

> In production, substitute your deployed host for `localhost:8000` (e.g.
> `https://api.example.com/docs`). See [runbooks/PRODUCTION_DEPLOY.md](../runbooks/PRODUCTION_DEPLOY.md).

---

## Authenticating in Swagger UI

The schema declares two security schemes; click **Authorize** in `/docs` and supply either:

- **Bearer** — a JWT from the UI session (`Authorization: Bearer <token>`), or
- **ApiKey** — a workspace API key sent as the `X-API-Key` header (tenant-scoped access).

Create an API key in the UI under **Dashboard → API keys** (`/ade/dashboard/api-keys`).

## Swagger UI for a *published spec* vs. the API reference

There are two different Swagger UIs in Apiome — don't confuse them:

| You want… | Use |
|---|---|
| To explore the **Apiome REST API** (import, classes, versions, …) | `/docs` (this page) |
| To explore a **published OpenAPI spec** authored in Apiome | `/v1/swagger/{tenant}/{project}/{version}` — see [browse-published-specs.md](browse-published-specs.md) |

## Related

- [cli-quickstart.md](cli-quickstart.md) — the CLI calls these same routes
- [mcp-quickstart.md](mcp-quickstart.md) — the MCP server exposes published specs to AI hosts
