# Objectified REST API - Technical Documentation

## Architecture

The Objectified REST API is built with FastAPI and follows a layered architecture:

```
┌─────────────────────────────────────┐
│         FastAPI Routes              │  (main.py)
│  /v1/{tenant}/{project}/{version}   │
│  /v1/.../.../{class}.json           │
│  /v1/.../.../{class}.yaml           │
└─────────────────────────────────────┘
                  ↓
┌─────────────────────────────────────┐
│      OpenAPI Generator              │  (openapi_generator.py)
│  - Generate full version specs      │
│  - Generate single class specs      │
│  - Parse JSON schema fields         │
└─────────────────────────────────────┘
                  ↓
┌─────────────────────────────────────┐
│       Database Layer                │  (database.py)
│  - Connection management            │
│  - Query execution                  │
│  - Data retrieval                   │
└─────────────────────────────────────┘
                  ↓
┌─────────────────────────────────────┐
│      PostgreSQL Database            │
│  odb.tenants                        │
│  odb.projects                       │
│  odb.versions                       │
│  odb.classes                        │
│  odb.class_properties               │
└─────────────────────────────────────┘
```

## Database Schema

### Query Path
When a request comes in for `/v1/acme-corp/customer-api/1.0.0`:

1. **Find Version**: Join `tenants` → `projects` → `versions`
2. **Validate**: Check `published=true` and `deleted_at IS NULL`
3. **Check Access**: Verify `visibility` (public/private)
4. **Get Classes**: Query `classes` table for version
5. **Get Properties**: Query `class_properties` for each class
6. **Generate Spec**: Build OpenAPI 3.1.0 specification

### Key Tables

```sql
-- Tenants
odb.tenants (id, slug, name, ...)

-- Projects
odb.projects (id, tenant_id, slug, name, ...)

-- Versions
odb.versions (id, project_id, version_id, visibility, published, ...)

-- Classes
odb.classes (id, version_id, name, description, schema, ...)

-- Class Properties
odb.class_properties (id, class_id, name, description, data, ...)
```

## OpenAPI Generation

### Full Version Specification

When requesting `/v1/{tenant}/{project}/{version}`:

1. Retrieve all classes for the version
2. Retrieve all properties for each class
3. Build individual schemas for each class
4. Combine into single OpenAPI spec:

```json
{
  "openapi": "3.1.0",
  "info": {
    "title": "project-slug API",
    "version": "1.0.0"
  },
  "components": {
    "schemas": {
      "Customer": { ... },
      "Order": { ... },
      "Product": { ... }
    }
  }
}
```

### Single Class Specification

When requesting `/v1/{tenant}/{project}/{version}/{class}.json`:

1. Retrieve specific class by name
2. Retrieve properties for that class
3. Build OpenAPI spec with single schema:

```json
{
  "openapi": "3.1.0",
  "info": {
    "title": "Customer",
    "version": "1.0.0"
  },
  "components": {
    "schemas": {
      "Customer": {
        "type": "object",
        "properties": {
          "id": { "type": "string" },
          "name": { "type": "string" },
          "email": { "type": "string", "format": "email" }
        }
      }
    }
  }
}
```

## Schema Building

### Property Data Parsing

Properties are stored as JSON in the database. The `parse_json_field()` function handles:
- String-encoded JSON
- Direct JSON objects
- Null values

### Schema Composition

Classes can have composition relationships (allOf, anyOf, oneOf):

```json
{
  "allOf": [
    { "$ref": "#/components/schemas/BaseEntity" },
    { "properties": { ... } }
  ]
}
```

These are preserved in the generated OpenAPI specification.

### Property References

Properties can reference other classes via `$ref`:

```json
{
  "address": {
    "$ref": "#/components/schemas/Address"
  }
}
```

Array properties can reference other classes:

```json
{
  "orders": {
    "type": "array",
    "items": {
      "$ref": "#/components/schemas/Order"
    }
  }
}
```

## Response Formats

### JSON Format (Default)

```bash
GET /v1/acme/api/1.0.0/Customer.json
Content-Type: application/json
```

Returns OpenAPI spec as JSON.

### YAML Format

```bash
GET /v1/acme/api/1.0.0/Customer.yaml
Content-Type: application/x-yaml
Content-Disposition: attachment; filename="Customer.yaml"
```

Returns OpenAPI spec as YAML with download headers.

## Error Handling

### 404 - Not Found

Returned when:
- Tenant slug doesn't exist
- Project slug doesn't exist
- Version ID doesn't exist
- Class name doesn't exist

### 403 - Forbidden

Returned when:
- Version is not published (`published=false`)
- API key is required but not provided (private versions)

### 500 - Internal Server Error

Returned when:
- Database connection fails
- Query execution fails
- JSON parsing fails

## Security

### Visibility Control

Two visibility levels:

1. **Public** (`visibility='public'`):
   - Accessible without authentication
   - Anyone can retrieve specifications

2. **Private** (`visibility='private'`):
   - Requires API key validation
   - Only authenticated tenants can access
   - TODO: Implement API key middleware

### Published Status

Only versions with `published=true` are accessible. This prevents:
- Draft versions from being exposed
- Work-in-progress specifications from being accessed
- Unpublished changes from being visible

### Soft Deletes

All queries filter by `deleted_at IS NULL`:
- Prevents access to deleted resources
- Maintains data integrity
- Supports recovery scenarios

## Performance Considerations

### Database Queries

Current implementation uses multiple queries:
1. One query to find version
2. One query to get all classes
3. N queries to get properties (one per class)

**Optimization Opportunity**: Could be reduced to 2-3 queries with JOINs.

### Caching Strategy (Future)

Recommended caching layers:
1. **Redis Cache**: Cache generated OpenAPI specs
2. **TTL**: Set based on version update frequency
3. **Invalidation**: Clear cache when version changes
4. **Key Format**: `{tenant}:{project}:{version}[:class]`

### Connection Pooling

Current implementation creates connections on-demand.

**Recommendation**: Use connection pooling for production:
```python
from psycopg2 import pool
connection_pool = pool.SimpleConnectionPool(1, 20, dsn)
```

## Configuration

### Environment Variables

```bash
# Database
DATABASE_URL=postgresql://user:pass@host:port/db

# Server
HOST=0.0.0.0
PORT=8000
RELOAD=True  # Development only

# Security (future)
API_KEY_HEADER=X-API-Key
REQUIRE_API_KEY=True

# Cache (future)
REDIS_URL=redis://localhost:6379
CACHE_TTL=3600
```

### Pydantic Settings

Settings are loaded via `pydantic-settings`:
- Type validation
- Environment variable parsing
- Default values
- Case-insensitive matching

## Extension Points

### Adding API Key Validation

In `main.py`, add dependency:

```python
from fastapi import Depends, Header, HTTPException

async def validate_api_key(x_api_key: str = Header(...)):
    # Query database for API key
    # Validate tenant matches
    # Check expiration
    # Return tenant_id
    pass

@app.get("/v1/{tenant_slug}/...")
async def endpoint(tenant_id: str = Depends(validate_api_key)):
    # Use tenant_id for authorization
    pass
```

### Adding Rate Limiting

```python
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

@app.get("/v1/{tenant_slug}/...")
@limiter.limit("10/minute")
async def endpoint(request: Request):
    pass
```

### Adding Request Logging

```python
import logging
from fastapi import Request

logger = logging.getLogger("objectified")

@app.middleware("http")
async def log_requests(request: Request, call_next):
    logger.info(f"{request.method} {request.url}")
    response = await call_next(request)
    logger.info(f"Status: {response.status_code}")
    return response
```

## Testing

### Unit Tests

Test individual functions:
- `parse_json_field()`
- `build_class_openapi_schema()`
- `generate_openapi_spec()`

### Integration Tests

Test API endpoints:
- Version retrieval
- Class retrieval (JSON/YAML)
- Error cases (404, 403)
- Database connectivity

### Load Tests

Use tools like:
- Apache Bench (ab)
- wrk
- Locust

## Deployment

### Docker

Create `Dockerfile`:

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY ../requirements.txt .
RUN pip install -r requirements.txt
COPY ../src .
CMD ["python", "run.py"]
```

### Docker Compose

```yaml
version: '3.8'
services:
  api:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql://...
    depends_on:
      - db
```

### Production Considerations

- Use Gunicorn with Uvicorn workers
- Enable HTTPS/TLS
- Configure CORS properly
- Set up logging aggregation
- Monitor with Prometheus/Grafana
- Use health checks for load balancers

## Monitoring

### Health Check Endpoint

```bash
curl http://localhost:8000/health
```

Returns:
```json
{
  "status": "healthy",
  "database": "connected"
}
```

### Metrics (Future)

Recommended metrics:
- Request count by endpoint
- Response time percentiles (p50, p95, p99)
- Error rate by status code
- Database query duration
- Cache hit/miss rate

## Troubleshooting

### Database Connection Issues

```python
# Check connection string
print(settings.database_url)

# Test connection manually
import psycopg2
conn = psycopg2.connect(settings.database_url)
```

### JSON Parsing Errors

Enable debug logging:
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

### Slow Queries

Use EXPLAIN ANALYZE:
```sql
EXPLAIN ANALYZE
SELECT * FROM odb.versions
WHERE ...
```

## Future Enhancements

1. **GraphQL Support**: Alternative to REST
2. **WebSocket Support**: Real-time updates
3. **Batch Endpoints**: Multiple classes at once
4. **Versioning**: API versioning (v2, v3)
5. **Swagger/ReDoc**: Enhanced documentation
6. **Export Formats**: Add more formats (Protobuf, Avro)
7. **Validation**: Schema validation service
8. **Diff Service**: Compare versions
9. **Statistics**: Usage analytics
10. **Webhooks**: Notify on changes

