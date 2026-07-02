# Content Negotiation - Before & After

## API Endpoint Structure

### BEFORE (File Extension Based)

```
┌─────────────────────────────────────────────────────────────────┐
│  Client Request                                                  │
├─────────────────────────────────────────────────────────────────┤
│  GET /v1/acme/project/1.0.0/User.json                           │
│  GET /v1/acme/project/1.0.0/User.yaml                           │
└─────────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  FastAPI Routes                                                  │
├─────────────────────────────────────────────────────────────────┤
│  @app.get("/{class_name}.json")                                 │
│      → get_class_openapi_json()                                 │
│                                                                   │
│  @app.get("/{class_name}.yaml")                                 │
│      → get_class_openapi_yaml()                                 │
└─────────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  Response                                                        │
├─────────────────────────────────────────────────────────────────┤
│  • Format determined by URL path                                │
│  • Two separate endpoints                                       │
│  • Duplicate business logic                                     │
└─────────────────────────────────────────────────────────────────┘
```

### AFTER (Content Negotiation Based)

```
┌─────────────────────────────────────────────────────────────────┐
│  Client Request                                                  │
├─────────────────────────────────────────────────────────────────┤
│  GET /v1/acme/project/1.0.0/User                                │
│  Accept: application/json                                        │
│                                                                   │
│  GET /v1/acme/project/1.0.0/User                                │
│  Accept: application/yaml                                        │
└─────────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  FastAPI Route                                                   │
├─────────────────────────────────────────────────────────────────┤
│  @app.get("/{class_name}")                                      │
│      → get_class_openapi_spec()                                 │
│         - Reads Accept header                                    │
│         - Returns appropriate format                             │
└─────────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  Content Negotiation Logic                                      │
├─────────────────────────────────────────────────────────────────┤
│  if "application/yaml" in accept_header:                        │
│      return Response(yaml_content, media_type="application/x-yaml")│
│  else:                                                           │
│      return JSONResponse(content)                               │
└─────────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  Response                                                        │
├─────────────────────────────────────────────────────────────────┤
│  • Format determined by Accept header                           │
│  • Single unified endpoint                                      │
│  • Cleaner URLs                                                 │
│  • Standards compliant (RFC 7231)                               │
└─────────────────────────────────────────────────────────────────┘
```

## Request Examples Comparison

### JSON Request

**BEFORE:**
```bash
curl http://localhost:8000/v1/acme/project/1.0.0/User.json
```

**AFTER:**
```bash
# Default (no Accept header)
curl http://localhost:8000/v1/acme/project/1.0.0/User

# Explicit
curl -H "Accept: application/json" \
     http://localhost:8000/v1/acme/project/1.0.0/User
```

### YAML Request

**BEFORE:**
```bash
curl http://localhost:8000/v1/acme/project/1.0.0/User.yaml
```

**AFTER:**
```bash
curl -H "Accept: application/yaml" \
     http://localhost:8000/v1/acme/project/1.0.0/User
```

## Advantages of Content Negotiation

1. ✅ **RESTful Design** - Uses HTTP headers as intended
2. ✅ **Cleaner URLs** - No file extensions polluting the URL
3. ✅ **Single Endpoint** - One route handles multiple formats
4. ✅ **Extensible** - Easy to add more formats (XML, etc.)
5. ✅ **Standards Compliant** - Follows RFC 7231
6. ✅ **Better Caching** - Same URL with different Accept headers
7. ✅ **Reduced Code** - Single implementation instead of two

