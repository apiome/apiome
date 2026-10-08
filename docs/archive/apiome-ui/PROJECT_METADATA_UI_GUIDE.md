# Project Metadata UI Guide

## Create Project Dialog

### Before
```
┌─────────────────────────────────────┐
│ Create New Project                  │
├─────────────────────────────────────┤
│ [From Scratch] [From OpenAPI Import]│
│                                     │
│ Project Name: [__________________] │
│ Slug: [__________________]         │
│ Description: [__________________]   │
│              [__________________]   │
│              [__________________]   │
│              [__________________]   │
│                                     │
│           [Cancel] [Create Project] │
└─────────────────────────────────────┘
```

### After (Expanded with Metadata)
```
┌───────────────────────────────────────────────────────────┐
│ Create New Project                                        │
├───────────────────────────────────────────────────────────┤
│ [From Scratch] [From OpenAPI Import]                      │
│                                                           │
│ ═══ Basic Information ═══                                │
│ Project Name: [_____________________________________]    │
│ Slug: [_____________________________________]            │
│ Description: [_____________________________________]      │
│              [_____________________________________]      │
│              [_____________________________________]      │
│                                                           │
│ ═══ OpenAPI Metadata (Optional) ═══                      │
│ API Summary: [_____________________________________]      │
│   Short summary of the API                               │
│                                                           │
│ Terms of Service URL: [_____________________________________] │
│   https://example.com/terms                              │
│                                                           │
│ ═══ Contact Information ═══                              │
│ Contact Name: [_____________________________________]     │
│   API Support Team                                       │
│                                                           │
│ Contact URL: [_____________________________________]      │
│   https://example.com/support                            │
│                                                           │
│ Contact Email: [_____________________________________]    │
│   support@example.com                                    │
│                                                           │
│ ═══ License Information ═══                              │
│ License (SPDX Identifier): [Apache License 2.0 ▼]       │
│   Select from SPDX license list or enter custom...      │
│   • MIT License (MIT)                                    │
│   • Apache License 2.0 (Apache-2.0) ← SELECTED          │
│   • BSD 2-Clause "Simplified" License (BSD-2-Clause)    │
│   • ...                                                  │
│                                                           │
│ License Name: [Apache License 2.0] (auto-populated)     │
│                                                           │
│ License URL: [https://spdx.org/licenses/Apache-2.0.html] │
│                    (auto-populated)                      │
│                                                           │
│                            [Cancel] [Create Project]     │
└───────────────────────────────────────────────────────────┘
```

## Edit Project Dialog

### Before
```
┌─────────────────────────────────────┐
│ Edit Project                        │
├─────────────────────────────────────┤
│                                     │
│ Project Name: [__________________] │
│ Slug: [__________________]         │
│ Description: [__________________]   │
│              [__________________]   │
│              [__________________]   │
│              [__________________]   │
│                                     │
│          [Cancel] [Save Changes]    │
└─────────────────────────────────────┘
```

### After (With Tabs)
```
┌───────────────────────────────────────────────────────────┐
│ Edit Project                                              │
├───────────────────────────────────────────────────────────┤
│ [Basic Information] [API Metadata]                        │
│ ─────────────────── ─────────────                         │
│                                                           │
│ ═══ Tab 1: Basic Information ═══                         │
│ Project Name: [_____________________________________]    │
│ Slug: [_____________________________________]            │
│   URL-friendly identifier (lowercase, numbers, dashes)   │
│                                                           │
│ Description: [_____________________________________]      │
│              [_____________________________________]      │
│              [_____________________________________]      │
│              [_____________________________________]      │
│                                                           │
│                            [Cancel] [Save Changes]       │
└───────────────────────────────────────────────────────────┘

When "API Metadata" tab is clicked:

┌───────────────────────────────────────────────────────────┐
│ Edit Project                                              │
├───────────────────────────────────────────────────────────┤
│ [Basic Information] [API Metadata]                        │
│  ─────────────────  ─────────────                         │
│                                                           │
│ ═══ Tab 2: API Metadata ═══                              │
│                                                           │
│ ═══ OpenAPI Metadata ═══                                 │
│ API Summary: [_____________________________________]      │
│   Short summary of the API                               │
│                                                           │
│ Terms of Service URL: [_____________________________________] │
│   https://example.com/terms                              │
│                                                           │
│ ═══ Contact Information ═══                              │
│ Contact Name: [_____________________________________]     │
│ Contact URL: [_____________________________________]      │
│ Contact Email: [_____________________________________]    │
│                                                           │
│ ═══ License Information ═══                              │
│ License (SPDX Identifier): [MIT License ▼]               │
│ License Name: [MIT License]                              │
│ License URL: [https://spdx.org/licenses/MIT.html]       │
│                                                           │
│                            [Cancel] [Save Changes]       │
└───────────────────────────────────────────────────────────┘
```

## SPDX License Autocomplete

```
┌─────────────────────────────────────────────────────────┐
│ License (SPDX Identifier): [apache ▼]                   │
├─────────────────────────────────────────────────────────┤
│ Search results:                                         │
│                                                         │
│ ┌───────────────────────────────────────────────────┐  │
│ │ Apache License 2.0 (Apache-2.0)           ✓ OSI  │  │
│ ├───────────────────────────────────────────────────┤  │
│ │ GNU Affero General Public License v3.0...  ✓ OSI  │  │
│ └───────────────────────────────────────────────────┘  │
│                                                         │
│ ✓ OSI = OSI Approved License                           │
└─────────────────────────────────────────────────────────┘

When license selected:
- License Name: Auto-populated → "Apache License 2.0"
- License URL: Auto-populated → "https://spdx.org/licenses/Apache-2.0.html"
```

## Generated OpenAPI Spec (Studio Code View)

### Before Metadata
```json
{
  "openapi": "3.1.0",
  "info": {
    "title": "My API",
    "version": "1.0.0",
    "description": "Generated OpenAPI 3.1.0 specification from Apiome Studio"
  },
  "components": {
    "schemas": { ... }
  }
}
```

### After Metadata
```json
{
  "openapi": "3.1.0",
  "info": {
    "title": "My API",
    "version": "1.0.0",
    "summary": "A comprehensive REST API for managing resources",
    "description": "Full API specification with metadata",
    "termsOfService": "https://api.example.com/terms",
    "contact": {
      "name": "API Support Team",
      "url": "https://api.example.com/support",
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

## Key UI Improvements

1. **Organized Sections**
   - Clear headings for each metadata category
   - Logical grouping of related fields
   - Visual separation with spacing

2. **Helper Text**
   - Placeholder examples for each field
   - Helper text explaining purpose
   - Format hints (URL, email)

3. **Smart Autocomplete**
   - Type-ahead search for licenses
   - Visual indication of OSI-approved licenses
   - Auto-population of related fields

4. **Tab Organization (Edit)**
   - Separate basic info from metadata
   - Reduces cognitive load
   - Cleaner interface

5. **Responsive Layout**
   - Dialog expands to `md` width for more space
   - Fields stack vertically for readability
   - Proper spacing between sections

6. **Optional Fields**
   - All metadata fields clearly optional
   - No required fields except name/slug
   - Flexible for different use cases

