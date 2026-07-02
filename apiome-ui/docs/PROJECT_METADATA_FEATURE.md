# Project Metadata for OpenAPI Specification Generation

## Overview

Added the ability to edit metadata for projects, which is used to enhance OpenAPI specification generation with contact information, license details, and other API metadata.

## Features

### Metadata Fields

Projects now support the following metadata fields for OpenAPI specification generation:

1. **API Summary** - Short summary of the API
2. **Terms of Service URL** - URL to the Terms of Service document
3. **Contact Information**
   - Contact Name - Person or organization name
   - Contact URL - URL to contact/support page
   - Contact Email - Email address for API support
4. **License Information**
   - License Name - Name of the license (e.g., "Apache License 2.0")
   - License Identifier - SPDX license identifier with autocomplete dropdown
   - License URL - URL to the license text

### SPDX License Support

The license identifier field includes an autocomplete dropdown with 30+ common SPDX licenses:

**Permissive Licenses:**
- MIT License
- Apache License 2.0
- BSD 2-Clause, BSD 3-Clause
- ISC License
- 0BSD (BSD Zero Clause)

**Copyleft Licenses:**
- GPL 2.0, GPL 3.0 (only/or-later variants)
- LGPL 2.1, LGPL 3.0 (only/or-later variants)
- AGPL 3.0 (only/or-later variants)

**Other Popular Licenses:**
- Mozilla Public License 2.0
- Eclipse Public License 1.0/2.0
- Creative Commons (CC0, CC-BY, CC-BY-SA)
- Unlicense
- Boost Software License
- Proprietary/UNLICENSED

When selecting a license from the dropdown, the license name and URL are automatically populated.

## Database Changes

### Migration: 20251211-140000.sql

Added `metadata` JSONB column to the `projects` table:

```sql
ALTER TABLE projects ADD COLUMN metadata JSONB DEFAULT '{}'::jsonb;
CREATE INDEX idx_projects_metadata ON projects USING gin(metadata);
```

### Metadata Structure

```json
{
  "summary": "Short summary of the API",
  "termsOfService": "https://example.com/terms",
  "contact": {
    "name": "API Support Team",
    "url": "https://example.com/support",
    "email": "support@example.com"
  },
  "license": {
    "name": "Apache 2.0",
    "identifier": "Apache-2.0",
    "url": "https://www.apache.org/licenses/LICENSE-2.0.html"
  }
}
```

## Code Changes

### 1. Database Helper Functions (`lib/db/helper.ts`)

**Updated Functions:**

```typescript
// createProject now accepts metadata parameter
export async function createProject(
  tenantId: string,
  creatorId: string,
  name: string,
  description: string,
  slug: string,
  metadata?: any
)

// updateProject now accepts metadata parameter
export async function updateProject(
  projectId: string,
  name: string,
  description: string,
  slug: string,
  enabled: boolean,
  metadata?: any
)
```

### 2. SPDX License Utilities (`src/app/utils/spdx-licenses.ts`)

New utility file providing:
- `SPDX_LICENSES` - Array of 30+ common open source licenses
- `getLicenseUrl(identifier)` - Get SPDX license URL from identifier
- `getLicenseName(identifier)` - Get license name from identifier

### 3. OpenAPI Generator (`src/app/utils/openapi.ts`)

**Updated `generateOpenApiSpec` function:**

```typescript
export async function generateOpenApiSpec(
  classes: any[],
  options?: {
    projectName?: string;
    version?: string;
    description?: string;
    openapiVersion?: string;
    metadata?: {
      summary?: string;
      termsOfService?: string;
      contact?: { name?: string; url?: string; email?: string };
      license?: { name?: string; identifier?: string; url?: string };
    };
  }
): Promise<string>
```

The function now builds the OpenAPI `info` object with:
- `summary` (optional)
- `termsOfService` (optional)
- `contact` object (optional, includes name/url/email if provided)
- `license` object (optional, includes name/identifier/url if provided)

### 4. Projects Page (`src/app/ade/dashboard/projects/page.tsx`)

**Enhanced Create Dialog:**
- Changed from single form to organized sections
- Added "OpenAPI Metadata (Optional)" section
- Added "Contact Information" section with 3 fields
- Added "License Information" section with autocomplete dropdown
- Dialog width increased from `sm` to `md` to accommodate new fields

**Enhanced Edit Dialog:**
- Added tabs: "Basic Information" and "API Metadata"
- "Basic Information" tab: name, slug, description
- "API Metadata" tab: all metadata fields with same layout as create dialog
- Dialog width increased from `sm` to `md`

**State Management:**
Added 8 new state variables for metadata:
- `metadataSummary`
- `metadataTermsOfService`
- `metadataContactName`, `metadataContactUrl`, `metadataContactEmail`
- `metadataLicenseName`, `metadataLicenseIdentifier`, `metadataLicenseUrl`

### 5. Studio Page (`src/app/ade/studio/page.tsx`)

**Updated OpenAPI Generation:**

The `generateSpec` useEffect now passes project metadata:

```typescript
const spec = await generateOpenApiSpec(classesWithProperties, {
  projectName: currentProject?.name,
  version: currentVersion?.version_id,
  metadata: (currentProject as any)?.metadata
});
```

## User Experience

### Creating a Project

1. Click "New Project" button
2. Fill in basic information (name, slug, description)
3. Optionally fill in OpenAPI metadata:
   - API Summary
   - Terms of Service URL
4. Optionally fill in contact information:
   - Contact Name
   - Contact URL
   - Contact Email
5. Optionally select/enter license information:
   - Start typing in "License (SPDX Identifier)" to see autocomplete
   - Select a license (name and URL auto-populate)
   - Or manually enter custom license name/identifier/URL
6. Click "Create Project"

### Editing a Project

1. Click "Actions" → "Edit" on a project
2. Use tabs to switch between:
   - **Basic Information** - Name, slug, description
   - **API Metadata** - All metadata fields
3. Update any fields
4. Click "Save Changes"

### Generated OpenAPI Specification

When viewing the OpenAPI spec in Studio's Code view, the `info` section now includes:

```json
{
  "openapi": "3.1.0",
  "info": {
    "title": "My API",
    "version": "1.0.0",
    "summary": "A comprehensive REST API",
    "description": "Full API specification...",
    "termsOfService": "https://example.com/terms",
    "contact": {
      "name": "API Support Team",
      "url": "https://example.com/support",
      "email": "support@example.com"
    },
    "license": {
      "name": "Apache License 2.0",
      "identifier": "Apache-2.0",
      "url": "https://www.apache.org/licenses/LICENSE-2.0.html"
    }
  },
  "components": {
    "schemas": { ... }
  }
}
```

## Benefits

1. **Complete OpenAPI Specs** - Generated specs now include all recommended metadata
2. **License Compliance** - Easy selection of SPDX-compliant license identifiers
3. **API Documentation** - Contact info and terms of service enhance API usability
4. **Standards Compliance** - Follows OpenAPI 3.1.0 specification for info object
5. **Flexibility** - All metadata fields are optional
6. **User-Friendly** - Autocomplete for licenses, URL validation for links

## Examples

### Minimal Project (No Metadata)

```json
{
  "info": {
    "title": "Simple API",
    "version": "1.0.0",
    "description": "Generated OpenAPI 3.1.0 specification"
  }
}
```

### Full Metadata Project

```json
{
  "info": {
    "title": "E-Commerce API",
    "version": "2.1.0",
    "summary": "Complete e-commerce REST API",
    "description": "Comprehensive API for online shopping",
    "termsOfService": "https://api.example.com/terms",
    "contact": {
      "name": "E-Commerce API Team",
      "url": "https://api.example.com/support",
      "email": "api-support@example.com"
    },
    "license": {
      "name": "MIT License",
      "identifier": "MIT",
      "url": "https://spdx.org/licenses/MIT.html"
    }
  }
}
```

## Technical Notes

### Backward Compatibility

- ✅ Existing projects without metadata continue to work
- ✅ Default empty JSONB object `{}` for new projects
- ✅ All metadata fields are optional
- ✅ No breaking changes to existing functionality

### Performance

- GIN index on metadata column for efficient queries
- JSONB storage is compact and performant
- No impact on projects without metadata

### Validation

- License identifiers validated against SPDX list (via autocomplete)
- URL fields use HTML5 URL input type
- Email field uses HTML5 email input type
- All fields are trimmed before saving

## Future Enhancements

1. **Server Configuration** - Add `servers` array to OpenAPI spec
2. **Security Schemes** - Configure authentication/authorization
3. **External Documentation** - Add `externalDocs` links
4. **Tags** - Define global tags for organization
5. **Webhooks** - OpenAPI 3.1.0 webhooks configuration

## References

- [OpenAPI 3.1.0 - Info Object](https://spec.openapis.org/oas/v3.1.0#info-object)
- [SPDX License List](https://spdx.org/licenses/)
- [JSON Schema Draft 2020-12](https://json-schema.org/draft/2020-12/json-schema-core.html)

## Date Implemented

December 11, 2024

## Status

✅ **Complete** - Feature fully implemented and tested

