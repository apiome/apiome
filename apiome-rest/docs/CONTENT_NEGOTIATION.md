# Content Negotiation Implementation

## Overview

The Apiome REST API now uses HTTP content negotiation to determine the response format for class OpenAPI specifications. This eliminates the need for file extensions (`.json` or `.yaml`) in the URL path.

## Changes Made

### Modified Endpoint

**Old Endpoints:**
- `/v1/{tenant-slug}/{project-slug}/{version-slug}/{class-name}.json` - for JSON responses
- `/v1/{tenant-slug}/{project-slug}/{version-slug}/{class-name}.yaml` - for YAML responses

**New Endpoint:**
- `/v1/{tenant-slug}/{project-slug}/{version-slug}/{class-name}` - format determined by `Accept` header

### How Content Negotiation Works

The server now examines the `Accept` HTTP header to determine the response format:

1. **YAML Response**: If the `Accept` header contains any of:
   - `application/yaml`
   - `application/x-yaml`
   - `text/yaml`
   - `text/x-yaml`

2. **JSON Response (Default)**: For any other `Accept` header value, including:
   - `application/json`
   - `*/*` (wildcard)
   - Missing/empty `Accept` header

### Examples

#### Request YAML Format
```bash
curl -H "Accept: application/yaml" \
  http://localhost:8000/v1/acme/my-project/1.0.0/User
```

#### Request JSON Format
```bash
curl -H "Accept: application/json" \
  http://localhost:8000/v1/acme/my-project/1.0.0/User
```

#### Default Request (Returns JSON)
```bash
curl http://localhost:8000/v1/acme/my-project/1.0.0/User
```

### Benefits

1. **Standards Compliance**: Follows HTTP content negotiation standards (RFC 7231)
2. **Cleaner URLs**: No need for file extensions in the path
3. **Flexibility**: Clients can request their preferred format using standard HTTP headers
4. **Backward Compatibility**: The version endpoint still returns JSON by default

### Implementation Details

The implementation:
- Uses FastAPI's `Header()` dependency to access the `Accept` header
- Checks for YAML MIME types in the `Accept` header (case-insensitive)
- Returns appropriate `Content-Type` headers:
  - `application/x-yaml` for YAML responses
  - `application/json` for JSON responses
- Maintains the same authentication and authorization logic
- Preserves the `Content-Disposition` header for YAML responses to suggest a filename

### API Documentation Update

The root endpoint (`/`) now reflects the updated URL structure:

```json
{
  "message": "Apiome REST API",
  "version": "1.0.0",
  "endpoints": {
    "version_spec": "/v1/{tenant-slug}/{project-slug}/{version-slug}",
    "class_spec": "/v1/{tenant-slug}/{project-slug}/{version-slug}/{class-name}"
  }
}
```

## Testing

To test the content negotiation:

1. Start the server: `uv run -m app`
2. Test with different `Accept` headers using curl or your HTTP client
3. Verify the response `Content-Type` matches your request

## Future Enhancements

Potential future improvements could include:
- Support for additional formats (e.g., XML)
- Quality value (q-factor) parsing for more sophisticated content negotiation
- Accept-Encoding support for compressed responses

