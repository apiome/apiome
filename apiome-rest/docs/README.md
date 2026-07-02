# Apiome REST API

A FastAPI-based REST service that exposes OpenAPI specifications for classes stored in the Apiome database.

## Features

- **Version Specifications**: Get complete OpenAPI specs for all classes in a version
- **Class Specifications**: Get individual class specs in JSON or YAML format
- **Content Negotiation**: Automatic format detection via HTTP Accept headers (RFC 7231)
- **Pydantic Models**: Type-safe request/response handling
- **PostgreSQL Integration**: Direct database access to Apiome data
- **Format Support**: JSON and YAML output formats
- **API Key Authentication**: Support for public and private version access control

## API Endpoints

### Get Version OpenAPI Specification
```
GET /v1/{tenant-slug}/{project-slug}/{version-slug}
```
Returns the complete OpenAPI 3.1.0 specification for all classes in the specified version.

**Example:**
```bash
curl http://localhost:8000/v1/acme-corp/customer-api/1.0.0
```

### Get Class Specification
```
GET /v1/{tenant-slug}/{project-slug}/{version-slug}/{class-name}
```
Returns the OpenAPI 3.1.0 specification for a single class. The response format (JSON or YAML) is determined by the `Accept` HTTP header.

**Examples:**

**JSON format (default):**
```bash
curl http://localhost:8000/v1/acme-corp/customer-api/1.0.0/Customer
# or explicitly request JSON
curl -H "Accept: application/json" \
  http://localhost:8000/v1/acme-corp/customer-api/1.0.0/Customer
```

**YAML format:**
```bash
curl -H "Accept: application/yaml" \
  http://localhost:8000/v1/acme-corp/customer-api/1.0.0/Customer
```

**Supported Accept headers for YAML:**
- `application/yaml`
- `application/x-yaml`
- `text/yaml`
- `text/x-yaml`

> **Note**: See [CONTENT_NEGOTIATION.md](./CONTENT_NEGOTIATION.md) for detailed information on content negotiation.

### Swagger UI Interface
```
GET /v1/{tenant-slug}/{project-slug}/{version-slug}/swagger
```
Returns an interactive Swagger UI interface displaying the OpenAPI specification for all classes in the specified version. This provides a user-friendly way to explore and visualize the schema.

**Example:**
```bash
# Open in browser
http://localhost:8000/v1/acme-corp/customer-api/1.0.0/swagger
```

**Features:**
- Interactive schema visualization
- Expandable nested structures
- Deep linking support
- Download OpenAPI spec directly
- Responsive design

> **Note**: See [swagger-ui-endpoint.md](./swagger-ui-endpoint.md) for detailed information on the Swagger UI endpoint.

### Health Check
```
GET /health
```
Returns the health status of the service and database connection.

## Installation

### Option 1: Using uv (Recommended)

1. **Install uv (if not already installed):**
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. **Configure environment:**
   ```bash
   cp .env.example .env
   ```
   Edit `.env` with your database connection details:
   ```
   DATABASE_URL=postgresql://user:password@localhost:5432/apiome
   HOST=0.0.0.0
   PORT=8000
   RELOAD=True
   ```

3. **Sync dependencies:**
   ```bash
   uv sync
   ```

### Option 2: Using pip

1. **Install Python dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure environment:** (same as above)

## Running the Server

### Using uv (Recommended):
```bash
# Simple command to run the server
uv run -m app

# Or use the helper script
./run.sh
```

### Using Python directly:
```bash
# Development Mode (with auto-reload)
cd src
python run.py

# Production Mode
cd src
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Using Docker (optional):
```bash
docker build -t apiome-rest .
docker run -p 8000:8000 --env-file .env apiome-rest
```

## Project Structure

```
apiome-rest/
├── src/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py              # FastAPI application and routes
│   │   ├── config.py            # Configuration settings
│   │   ├── database.py          # Database connection and queries
│   │   ├── models.py            # Pydantic models
│   │   └── openapi_generator.py # OpenAPI spec generation logic
│   └── run.py                   # Server entry point
├── requirements.txt             # Python dependencies
├── .env.example                 # Environment variables template
└── README.md                    # This file
```

## Configuration

The application uses Pydantic Settings for configuration management. All settings can be configured via environment variables:

- `DATABASE_URL`: PostgreSQL connection string
- `HOST`: Server host (default: 0.0.0.0)
- `PORT`: Server port (default: 8000)
- `RELOAD`: Enable auto-reload in development (default: True)

## Security

### Visibility Control

The API respects the `visibility` field on versions:
- **Public versions**: Accessible without authentication
- **Private versions**: Require API key validation (TODO: implement)

### Published Status

Only published versions are accessible via the API. Unpublished versions return a 403 Forbidden error.

## Development

### Adding New Endpoints

Add new routes in `src/app/main.py`:

```python
@app.get("/v1/your-endpoint")
async def your_endpoint():
    return {"message": "Hello"}
```

### Database Queries

Add new queries in `src/app/database.py`:

```python
def your_query(self, param: str) -> List[Dict[str, Any]]:
    query = "SELECT * FROM your_table WHERE field = %s"
    return self.execute_query(query, (param,))
```

## Testing

```bash
# Test version endpoint
curl http://localhost:8000/v1/acme-corp/customer-api/1.0.0

# Test class JSON endpoint
curl http://localhost:8000/v1/acme-corp/customer-api/1.0.0/Customer.json

# Test class YAML endpoint
curl http://localhost:8000/v1/acme-corp/customer-api/1.0.0/Customer.yaml

# Health check
curl http://localhost:8000/health
```

## API Documentation

Once the server is running, visit:
- **Interactive API docs (Swagger UI)**: http://localhost:8000/docs
- **Alternative API docs (ReDoc)**: http://localhost:8000/redoc
- **OpenAPI JSON**: http://localhost:8000/openapi.json

## Dependencies

- **FastAPI**: Modern web framework for building APIs
- **Uvicorn**: ASGI server
- **Pydantic**: Data validation using Python type annotations
- **psycopg2-binary**: PostgreSQL adapter
- **PyYAML**: YAML parser and emitter
- **python-dotenv**: Environment variable management

## License

See the main Apiome project license.

## TODO

- [ ] Implement API key validation for private versions
- [ ] Add rate limiting
- [ ] Add caching layer (Redis)
- [ ] Add request logging
- [ ] Add metrics/monitoring
- [ ] Add CORS configuration
- [ ] Add Docker support
- [ ] Add unit tests
- [ ] Add integration tests

