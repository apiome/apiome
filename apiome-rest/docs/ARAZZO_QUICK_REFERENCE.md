# Arazzo Endpoints - Quick Reference

## Endpoint Summary

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/arazzo/{tenant}/{project}/{version}` | GET | Get all workflows for a version |
| `/v1/arazzo/{tenant}/{project}/{version}/{class}` | GET | Get workflow for a single class |

## Quick Examples

### Get All Workflows (JSON)
```bash
curl http://localhost:8000/v1/arazzo/my-tenant/my-project/1.0.0
```

### Get All Workflows (YAML)
```bash
curl -H "Accept: application/yaml" \
  http://localhost:8000/v1/arazzo/my-tenant/my-project/1.0.0
```

### Get Single Class Workflow (JSON)
```bash
curl http://localhost:8000/v1/arazzo/my-tenant/my-project/1.0.0/User
```

### Get Single Class Workflow (YAML)
```bash
curl -H "Accept: application/yaml" \
  http://localhost:8000/v1/arazzo/my-tenant/my-project/1.0.0/User
```

### Private Version (with API Key)
```bash
curl -H "X-API-Key: your-api-key" \
  http://localhost:8000/v1/arazzo/my-tenant/my-project/1.0.0
```

## Response Structure

### Arazzo Document
```json
{
  "arazzo": "1.0.1",
  "info": { ... },
  "sourceDescriptions": [ ... ],
  "workflows": [ ... ]
}
```

### Workflow Structure
```json
{
  "workflowId": "userWorkflow",
  "summary": "User CRUD Workflow",
  "description": "Operations for User",
  "steps": [ ... ]
}
```

### Step Structure
```json
{
  "stepId": "createUser",
  "description": "Create a new User",
  "operationId": "createUser",
  "parameters": [],
  "requestBody": { ... },
  "successCriteria": [ ... ],
  "outputs": { ... },
  "dependsOn": [ ... ]
}
```

## CRUD Workflow Pattern

Each class generates 4 steps:

1. **CREATE** → Outputs: `{class}Id`
2. **GET** → Depends on: CREATE
3. **UPDATE** → Depends on: CREATE  
4. **DELETE** → Depends on: UPDATE

## Status Codes

| Code | Meaning |
|------|---------|
| 200 | Success |
| 401 | Missing/invalid API key |
| 403 | Not published or no access |
| 404 | Not found |

## Content Types

| Accept Header | Response Format |
|--------------|-----------------|
| `application/json` | JSON (default) |
| `application/yaml` | YAML |
| `application/x-yaml` | YAML |
| `text/yaml` | YAML |
| `text/x-yaml` | YAML |

## Testing

### Basic Test
```bash
# Get workflows
curl http://localhost:8000/v1/arazzo/test-tenant/test-project/1.0.0

# Check response
echo $?  # Should be 0 for success
```

### Python Test
```python
import requests

response = requests.get(
    "http://localhost:8000/v1/arazzo/my-tenant/my-project/1.0.0"
)
assert response.status_code == 200
arazzo_spec = response.json()
assert arazzo_spec["arazzo"] == "1.0.1"
```

### With httpie
```bash
# JSON
http GET localhost:8000/v1/arazzo/my-tenant/my-project/1.0.0

# YAML
http GET localhost:8000/v1/arazzo/my-tenant/my-project/1.0.0 \
  Accept:application/yaml
```

## Common Patterns

### Download YAML File
```bash
curl -H "Accept: application/yaml" \
  http://localhost:8000/v1/arazzo/my-tenant/my-project/1.0.0 \
  -o workflows.yaml
```

### Save JSON Response
```bash
curl http://localhost:8000/v1/arazzo/my-tenant/my-project/1.0.0 \
  -o workflows.json
```

### Pretty Print JSON
```bash
curl http://localhost:8000/v1/arazzo/my-tenant/my-project/1.0.0 | jq .
```

### Check Specific Workflow
```bash
curl http://localhost:8000/v1/arazzo/my-tenant/my-project/1.0.0 | \
  jq '.workflows[] | select(.workflowId == "userWorkflow")'
```

### Count Workflows
```bash
curl http://localhost:8000/v1/arazzo/my-tenant/my-project/1.0.0 | \
  jq '.workflows | length'
```

### List All Workflow IDs
```bash
curl http://localhost:8000/v1/arazzo/my-tenant/my-project/1.0.0 | \
  jq '.workflows[].workflowId'
```

## Integration Examples

### Use with Postman
1. Import as Arazzo specification
2. Execute workflows sequentially
3. View step dependencies

### Use with Newman (CLI)
```bash
newman run workflows.json
```

### Use with Python
```python
import requests
import yaml

# Get YAML format
response = requests.get(
    "http://localhost:8000/v1/arazzo/my-tenant/my-project/1.0.0",
    headers={"Accept": "application/yaml"}
)

spec = yaml.safe_load(response.text)
print(f"Found {len(spec['workflows'])} workflows")
```

### Use with JavaScript/TypeScript
```javascript
const response = await fetch(
  'http://localhost:8000/v1/arazzo/my-tenant/my-project/1.0.0'
);
const arazzo = await response.json();

arazzo.workflows.forEach(workflow => {
  console.log(`Workflow: ${workflow.workflowId}`);
  console.log(`Steps: ${workflow.steps.length}`);
});
```

## Troubleshooting

### 404 Not Found
- Check tenant/project/version slugs are correct
- Verify version exists and is published

### 401 Unauthorized
- Add `X-API-Key` header for private versions
- Verify API key is valid and not expired

### 403 Forbidden
- Ensure version is published
- Check API key belongs to correct tenant

### Empty Workflows
- Verify classes exist in the version
- Check database connection

## Links

- [Full Documentation](ARAZZO_ENDPOINTS.md)
- [Arazzo Spec](https://spec.openapis.org/arazzo/latest.html)
- [OpenAPI Spec](https://spec.openapis.org/oas/latest.html)

---

**Last Updated:** December 7, 2024

