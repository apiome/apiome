# Debugging Metadata Display Issues

## Current Status

Added comprehensive debugging to track metadata flow through the OpenAPI generation process.

## How to Debug

### 1. Open Browser Console

1. Open your project in Studio
2. Switch to Code view → OpenAPI
3. Open Browser DevTools (F12 or Cmd+Option+I on Mac)
4. Go to Console tab

### 2. Check Debug Logs

You should see these console logs in order:

```
[Studio] Generating OpenAPI spec with: {
  classesCount: X,
  projectName: "Your Project",
  version: "1.0.0",
  hasMetadata: true/false
}

[OpenAPI generateOpenApiSpec] Received metadata: {
  "summary": "...",
  "contact": { ... },
  "license": { ... }
}

[OpenAPI generateOpenApiSpec] Final info object: {
  "title": "...",
  "version": "...",
  "summary": "...",    ← Should have metadata fields
  "contact": { ... },  ← Should be here
  "license": { ... }   ← Should be here
}

[OpenAPI generateOpenApiSpec] Template data keys: ["openapi", "info", "schemas", "xMetadata"]

[OpenAPI generateOpenApiSpec] Has xMetadata: true

[OpenAPI generateOpenApiSpec] Rendered output (first 500 chars): {
  "openapi": "3.1.0",
  "info": { ... },  ← Should contain metadata
  ...
}
```

### 3. What to Look For

#### Scenario 1: Metadata is NULL or undefined
```
[OpenAPI generateOpenApiSpec] Received metadata: null
```
**Problem:** Metadata is not being loaded from the database or passed from Studio

**Check:**
1. Does the project have metadata in the database?
   ```sql
   SELECT metadata FROM apiome.projects WHERE id = 'your-project-id';
   ```
2. Is `currentProject?.metadata` undefined in Studio?

#### Scenario 2: Metadata exists but not in info object
```
[OpenAPI generateOpenApiSpec] Received metadata: { "summary": "test" }
[OpenAPI generateOpenApiSpec] Final info object: { "title": "...", "version": "..." }
```
**Problem:** Metadata fields are not being added to info object

**Possible causes:**
- Empty strings (`.trim()` returns empty)
- Empty objects (`Object.keys().length === 0`)

#### Scenario 3: Info has metadata but not in rendered output
```
[OpenAPI generateOpenApiSpec] Final info object: { ..., "summary": "test" }
[OpenAPI generateOpenApiSpec] Rendered output: {
  "openapi": "3.1.0",
  "info": { "title": "...", "version": "..." }  ← Missing summary!
}
```
**Problem:** Template is not rendering the info object correctly

**Check:** Template file at `src/app/utils/templates/openapi-spec.hbs`

Should contain:
```handlebars
"info": {{{json info}}},
```

#### Scenario 4: Everything looks good in logs but not in UI
```
All logs show metadata correctly
```
**Problem:** Display issue in the Editor component

**Check:**
1. Is the generated spec being stored correctly? Look at `openApiSpec` state
2. Is the Editor receiving the correct value?

### 4. Check Database

Verify metadata exists in database:

```sql
-- Check if project has metadata
SELECT id, name, metadata 
FROM apiome.projects 
WHERE id = 'your-project-id';

-- Check all projects with metadata
SELECT id, name, metadata 
FROM apiome.projects 
WHERE metadata IS NOT NULL AND metadata != '{}'::jsonb;
```

### 5. Check Studio State

Add temporary debugging in Studio page:

```typescript
// In studio/page.tsx, around line 1543
console.log('[Studio] Current project metadata:', currentProject?.metadata);
console.log('[Studio] Metadata type:', typeof (currentProject as any)?.metadata);
```

## Common Issues and Solutions

### Issue: Empty Metadata Fields

If metadata fields exist but are empty strings:
```json
{
  "summary": "",
  "contact": { "email": "" }
}
```

The current code filters these out with `.trim()`, so they won't appear in the info object. This is by design.

### Issue: Metadata Not Loading

If `currentProject?.metadata` is undefined:

1. **Check getProjectsForTenant query** includes metadata column:
   ```sql
   SELECT p.*, u.name as creator_name, u.email as creator_email
   FROM apiome.projects p ...
   ```
   The `p.*` should include the metadata column.

2. **Check if column exists**:
   ```sql
   \d apiome.projects
   ```
   Should show `metadata` column of type `jsonb`.

### Issue: Template Not Rendering

If the template isn't rendering the info object correctly, check:

**File:** `src/app/utils/templates/openapi-spec.hbs`

Should be:
```handlebars
{
  "openapi": "{{openapi}}",
  "info": {{{json info}}},
{{#if xMetadata}}  "x-metadata": {{{json xMetadata}}},
{{/if}}  "components": {
    "schemas": { ... }
  }
}
```

## Next Steps

1. Open Studio in browser
2. Open Console (F12)
3. Navigate to Code view → OpenAPI
4. Look for the debug logs
5. Share the console output to identify where metadata is lost

## Debugging Commands

```bash
# Check if project has metadata in database
psql -U apiome -d apiome_db -c "SELECT id, name, metadata FROM apiome.projects WHERE metadata != '{}'::jsonb LIMIT 5;"

# Check template file
cat src/app/utils/templates/openapi-spec.hbs

# Check for TypeScript errors
npx tsc --noEmit --skipLibCheck 2>&1 | grep error
```

## Date Created

December 11, 2024

## Status

🔍 **DEBUGGING** - Added comprehensive logging to identify where metadata is lost in the generation pipeline

