# Apiome REST API

REST API for serving OpenAPI and Arazzo specifications from the Apiome database.

## Overview

The Apiome REST API provides HTTP endpoints to retrieve schema specifications in multiple formats:

- **OpenAPI 3.1.0** - Standard API schema definitions
- **Arazzo 1.0.1** - Workflow specifications for API operations
- **Swagger UI** - Interactive API documentation

## Features

✨ **OpenAPI 3.1.0 Support** - Full compliance with latest OpenAPI specification
🔄 **Arazzo Workflows** - Generate executable API workflow specifications
📊 **Content Negotiation** - Automatic format selection (JSON/YAML) based on Accept header
🔒 **API Key Authentication** - Secure access to private versions
🎨 **Swagger UI Integration** - Interactive API documentation
🌐 **Multi-tenant Support** - Isolated tenant data with slug-based routing

## Quick Start

### Installation

```bash
# Clone the repository
git clone <repo-url>
cd apiome-rest

# Install dependencies
pip install -r requirements.txt

# Or use uv (recommended)
uv sync
```

### PostgreSQL (required)

The API connects at startup. Default database name is **`apiome`** (`POSTGRES_DB` / `DATABASE_URL`).

1. Ensure PostgreSQL is listening (often `localhost:5432`).
2. Create the database if it does not exist:

   ```bash
   psql -U postgres -h localhost -p 5432 -c 'CREATE DATABASE apiome;'
   ```

3. Apply schema migrations (run SQL files in timestamp order from the monorepo):

   ```bash
   cd ../apiome-db
   for f in scripts/*.sql; do echo "$f"; psql -U postgres -h localhost -d apiome -f "$f"; done
   ```

   See **`apiome-db/docs/README.md`** for details.

### Configuration

Create a `.env` file based on `.env.example`:

```env
DATABASE_URL=postgresql://user:password@localhost:5432/apiome
API_HOST=0.0.0.0
API_PORT=8000
```

#### MCP credential encryption-at-rest (MCAT-6.2)

Outbound MCP credentials (bearer tokens, custom-header values, OAuth2 token sets) are stored as
ciphertext only, sealed with AES-256-GCM envelope encryption. Configure the master key(s) so the
server can seal new secrets and unseal stored ones at connect time:

```env
# JSON map of integer key-version -> base64-encoded 32-byte (AES-256) master key.
APIOME_MCP_CREDENTIAL_ENCRYPTION_KEYS={"1": "<base64 key>"}
# Optional: which version new secrets are sealed under (defaults to the highest version present).
APIOME_MCP_CREDENTIAL_ACTIVE_KEY_VERSION=1
```

Generate a key with:

```bash
python -c "import base64, os; print(base64.b64encode(os.urandom(32)).decode())"
```

**Key rotation:** add a new, higher version to the map and point
`APIOME_MCP_CREDENTIAL_ACTIVE_KEY_VERSION` at it. Existing rows stay decryptable under the
version that sealed them; re-seal them onto the active key with
`mcp_credential_crypto.reseal_credential_payload`. If no key is configured the server still starts,
but credentials cannot be sealed (storing a secret fails closed) or unsealed (discovery runs
unauthenticated).

#### MCP credential REST + redaction (MCAT-6.5)

Tenants manage an endpoint's outbound credential over three tenant-scoped routes under
`/v1/mcp/{tenant_slug}/endpoints/{id}/credentials` (the URL slug is informational; scoping comes
from the authenticated token's tenant, so a cross-tenant id returns `404`):

- `PUT …/credentials` — set or replace the credential. Body: `auth_type` (one of `bearer`,
  `header`, `oauth2`, `env`) plus a `payload` matching that type — e.g.
  `{"auth_type": "bearer", "payload": {"token": "<secret>"}}`,
  `{"auth_type": "header", "payload": {"name": "X-Api-Key", "value": "<secret>"}}`. Optional
  non-secret `oauth_metadata` is stored as cleartext. The payload is validated, then sealed
  (encryption-at-rest above) and stored as ciphertext.
- `GET …/credentials` — the **redacted** status: `auth_type`, a `configured` flag, a fixed
  `masked_secret` placeholder when a secret is stored, `key_version`, `oauth_metadata`, and
  timestamps. **The secret itself is never returned.**
- `DELETE …/credentials` — clear the credential (idempotent; `removed` reports whether a row was
  dropped). This is how an endpoint returns to the anonymous `none` state.

A `PUT` with a payload that does not match its `auth_type` (or that would inject a header) is
rejected with `422`; a `PUT` while credential encryption is unconfigured fails closed with `503`.

### Running the Server

```bash
# Using Python
python -m src.app

# Or using uvicorn directly
uvicorn src.app.main:app --reload

# Or using the run script
./run.sh
```

The API will be available at `http://localhost:8000`

## API Endpoints

### OpenAPI Endpoints

#### Get Version OpenAPI Specification
```
GET /v1/schema/{tenant-slug}/{project-slug}/{version-slug}
```
Returns the complete OpenAPI 3.1.0 specification for all classes in a version.

**Example:**
```bash
curl http://localhost:8000/v1/schema/my-tenant/my-project/1.0.0
```

#### Get Class OpenAPI Specification
```
GET /v1/schema/{tenant-slug}/{project-slug}/{version-slug}/{class-name}
```
Returns the OpenAPI 3.1.0 specification for a single class.

**Example:**
```bash
curl http://localhost:8000/v1/schema/my-tenant/my-project/1.0.0/User
```

### Arazzo Endpoints

#### Get Version Arazzo Specification
```
GET /v1/arazzo/{tenant-slug}/{project-slug}/{version-slug}
```
Returns the complete Arazzo 1.0.1 workflow specification for all classes in a version.

**Example:**
```bash
curl http://localhost:8000/v1/arazzo/my-tenant/my-project/1.0.0
```

#### Get Class Arazzo Specification
```
GET /v1/arazzo/{tenant-slug}/{project-slug}/{version-slug}/{class-name}
```
Returns the Arazzo 1.0.1 workflow specification for a single class.

**Example:**
```bash
curl http://localhost:8000/v1/arazzo/my-tenant/my-project/1.0.0/User
```

### Interactive Documentation

#### Swagger UI
```
GET /v1/swagger/{tenant-slug}/{project-slug}/{version-slug}
```
View interactive API documentation using Swagger UI.

**Example:**
Open in browser: `http://localhost:8000/v1/swagger/my-tenant/my-project/1.0.0`

### Mock Server Endpoints (#3615)

Provision a hosted mock from a published version and consume the designed API before a backend
exists. The mock freezes the version's generated OpenAPI document and replays schema-valid responses.

**Management plane** (authenticated, tenant-scoped):
```
POST   /v1/mocks/{tenant-slug}                          # provision -> { baseUrl, ... }
GET    /v1/mocks/{tenant-slug}                          # list instances
GET    /v1/mocks/{tenant-slug}/{mock-id}                # inspect
PUT    /v1/mocks/{tenant-slug}/{mock-id}/active-scenario # switch scenario
DELETE /v1/mocks/{tenant-slug}/{mock-id}                # destroy
```

Provision body (camelCase or snake_case): `{ "projectSlug": "...", "versionSlug": "1.0.0",
"name": "...", "ttlHours": 24, "rateLimitPerMinute": 60, "scenarios": [...], "activeScenario": "..." }`.

**Data plane** (public — the mock itself):
```
ANY /v1/mock/{mock-id}/{path}
```
Responses are generated from the operation's response schema and validated against it. Select a
scenario per request with the `X-Mock-Scenario` header (built-ins: `happy-path`, `server-error`,
`not-found`, `slow`). Free-tier mocks auto-expire (`410 Gone`) and are rate limited per instance
(`429` with `Retry-After`). Disable the feature with `APIOME_MOCK_SERVER_ENABLED=false`.

**Example:**
```bash
# Provision (returns a stable baseUrl like http://localhost:8000/v1/mock/<id>)
curl -X POST http://localhost:8000/v1/mocks/my-tenant \
  -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"projectSlug":"my-project","versionSlug":"1.0.0"}'

# Consume the mock
curl http://localhost:8000/v1/mock/<id>/pets/1
```

### Utility Endpoints

#### Root / Discovery
```
GET /
```
Returns API information and available endpoints.

#### Health Check
```
GET /health
```
Returns API health status and database connection status.

## Content Negotiation

All schema endpoints support content negotiation via the `Accept` header:

### JSON (default)
```bash
curl -H "Accept: application/json" \
  http://localhost:8000/v1/schema/my-tenant/my-project/1.0.0
```

### YAML
```bash
curl -H "Accept: application/yaml" \
  http://localhost:8000/v1/schema/my-tenant/my-project/1.0.0
```

Supported YAML MIME types:
- `application/yaml`
- `application/x-yaml`
- `text/yaml`
- `text/x-yaml`

## Authentication

### Public Versions
Public versions can be accessed without authentication.

### Private Versions
Private versions require an API key in the `X-API-Key` header:

```bash
curl -H "X-API-Key: your-api-key-here" \
  http://localhost:8000/v1/schema/my-tenant/my-project/1.0.0
```

## Response Formats

### OpenAPI 3.1.0 Response
```json
{
  "openapi": "3.1.0",
  "info": {
    "title": "my-project API",
    "version": "1.0.0",
    "description": "API description"
  },
  "paths": {},
  "components": {
    "schemas": {
      "User": {
        "type": "object",
        "properties": {
          "id": { "type": "string" },
          "name": { "type": "string" }
        }
      }
    }
  }
}
```

### Arazzo 1.0.1 Response
```json
{
  "arazzo": "1.0.1",
  "info": {
    "title": "my-project Workflows",
    "version": "1.0.0",
    "description": "API workflows"
  },
  "sourceDescriptions": [{
    "name": "openapi-source",
    "type": "openapi",
    "url": "/v1/schema/my-tenant/my-project/1.0.0"
  }],
  "workflows": [{
    "workflowId": "userWorkflow",
    "summary": "User CRUD Workflow",
    "steps": [
      {
        "stepId": "createUser",
        "operationId": "createUser",
        "successCriteria": [{"condition": "$statusCode == 201"}]
      }
    ]
  }]
}
```

## Error Responses

| Status Code | Description |
|-------------|-------------|
| 200 | Success |
| 401 | Unauthorized - Missing or invalid API key |
| 403 | Forbidden - Version not published or insufficient permissions |
| 404 | Not Found - Tenant, project, version, or class not found |
| 500 | Internal Server Error |

## Project Structure

```
apiome-rest/
├── src/
│   └── app/
│       ├── __init__.py
│       ├── __main__.py
│       ├── main.py              # FastAPI application and endpoints
│       ├── config.py            # Configuration management
│       ├── database.py          # Database connection and queries
│       ├── models.py            # Pydantic models
│       ├── openapi_generator.py # OpenAPI spec generation
│       └── arazzo_generator.py  # Arazzo spec generation
├── docs/
│   └── ARAZZO_ENDPOINTS.md      # Arazzo endpoint documentation
├── tests/
│   ├── test_arazzo_endpoints.py
│   ├── test_description.py
│   └── test_swagger_endpoint.py
├── requirements.txt
├── pyproject.toml
├── uv.lock
├── .env.example
├── run.sh
└── README.md
```

## Development

### Running Tests

```bash
# Run all tests
pytest

# Run specific test file
pytest test_arazzo_endpoints.py

# Run with verbose output
pytest -v

# Run with coverage
pytest --cov=src/app
```

### Code Style

The project follows PEP 8 style guidelines. Use tools like `black` and `ruff` for formatting:

```bash
# Format code
black src/

# Lint code
ruff check src/
```

## Documentation

- **[Arazzo Endpoints](docs/ARAZZO_ENDPOINTS.md)** - Detailed Arazzo endpoint documentation
- **[OpenAPI Specification](https://spec.openapis.org/oas/latest.html)** - OpenAPI 3.1.0 spec
- **[Arazzo Specification](https://spec.openapis.org/arazzo/latest.html)** - Arazzo 1.0.1 spec

## Technology Stack

- **[FastAPI](https://fastapi.tiangolo.com/)** - Modern Python web framework
- **[PostgreSQL](https://www.postgresql.org/)** - Database
- **[psycopg2](https://www.psycopg.org/)** - PostgreSQL adapter
- **[PyYAML](https://pyyaml.org/)** - YAML parsing and generation
- **[Swagger UI](https://swagger.io/tools/swagger-ui/)** - Interactive API documentation

## Use Cases

### 1. Schema Distribution
Distribute OpenAPI schemas to API consumers via simple HTTP endpoints.

### 2. Workflow Documentation
Provide Arazzo workflows showing how to use your APIs in sequence.

### 3. Testing & Validation
Use generated specs for API testing and validation frameworks.

### 4. Code Generation
Feed specs into code generators for client SDKs.

### 5. API Discovery
Allow developers to explore available schemas and workflows.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Submit a pull request

## License

[Your License Here]

## Support

For issues and questions:
- Create an issue in the repository
- Contact the development team

## Changelog

### v1.0.0 (2024-12-07)
- ✨ Added Arazzo 1.0.1 workflow specification endpoints
- ✨ Added content negotiation for JSON/YAML responses
- ✨ Added API key authentication for private versions
- ✨ Added Swagger UI integration
- 🎉 Initial release with OpenAPI 3.1.0 support

---

**Built with ❤️ using FastAPI**

