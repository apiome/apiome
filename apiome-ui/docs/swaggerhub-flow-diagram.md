# SwaggerHub Import - Visual Flow Diagram

## User Flow

```
┌─────────────────────────────────────────────────────────────┐
│                     IMPORT DIALOG                           │
│                                                             │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐     │
│  │  File   │  │   URL   │  │   Git   │  │SwaggerHub│     │
│  └─────────┘  └─────────┘  └─────────┘  └────┬────┘     │
│                                                │           │
│                                                ▼           │
│  ┌───────────────────────────────────────────────────┐    │
│  │        SwaggerHub Import Panel                    │    │
│  │                                                   │    │
│  │  Owner/Org: [_________________]                  │    │
│  │  API Name:  [_________________]                  │    │
│  │  ☑ Use latest version                           │    │
│  │  Version:   [_________________] (optional)       │    │
│  │                                                   │    │
│  │  🔐 API Key (for private APIs)                  │    │
│  │  [_____________________] [👁]                    │    │
│  │                                                   │    │
│  │           [Test & Fetch]                         │    │
│  │                                                   │    │
│  │  ✅ Successfully fetched specification           │    │
│  │  📄 Specification Preview                        │    │
│  │     Title: Swagger Petstore                      │    │
│  │     Version: 1.0.0                               │    │
│  │     Format: JSON                                 │    │
│  └───────────────────────────────────────────────────┘    │
│                                                             │
│                     [← Back]  [Analyze →]                  │
└─────────────────────────────────────────────────────────────┘
```

## Technical Flow

```
┌─────────────────────────────────────────────────────────────┐
│                   USER INTERACTION                          │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│              SwaggerHubImportPanel.tsx                      │
│  • Renders UI                                               │
│  • Handles form state                                       │
│  • Real-time validation                                     │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│              swaggerhub-import.ts                           │
│                                                             │
│  validateSwaggerHubOptions()                                │
│  ├─ Check owner format                                     │
│  ├─ Check API name format                                  │
│  └─ Check version format                                   │
│                                                             │
│  fetchFromSwaggerHub()                                      │
│  ├─ Get latest version (if needed)                         │
│  ├─ Build API URL                                          │
│  ├─ Add API key header (if provided)                       │
│  └─ Fetch specification                                    │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│              SwaggerHub API                                 │
│         https://api.swaggerhub.com                          │
│                                                             │
│  GET /apis/{owner}/{api}/{version}                          │
│  • Returns OpenAPI specification                            │
│  • JSON or YAML format                                      │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│              extractFileMetadata()                          │
│  • Parse OpenAPI spec                                       │
│  • Extract title, description                               │
│  • Detect format and version                                │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│              onSpecificationFetched()                       │
│  • Store content in ImportDialog state                      │
│  • Enable Analyze button                                    │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│              handleAnalyze()                                │
│  • Analyze specification                                    │
│  • Validate format                                          │
│  • Check completeness                                       │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│              Standard Import Flow                           │
│  • Preview                                                  │
│  • Import Options                                           │
│  • Execute Import                                           │
│  • Complete                                                 │
└─────────────────────────────────────────────────────────────┘
```

## Error Handling Flow

```
User Action: Test & Fetch
         │
         ▼
┌────────────────────────┐
│ validateSwaggerHubOptions│
└──────┬─────────────────┘
       │
       ├─ Invalid? ───────► Show validation error
       │                    (inline, real-time)
       │
       ▼
┌────────────────────────┐
│ fetchFromSwaggerHub    │
└──────┬─────────────────┘
       │
       ├─ 401 Unauthorized ───► "Authentication failed.
       │                         Please check your API key."
       │
       ├─ 403 Forbidden ──────► "Access denied. This API may
       │                         be private or your API key
       │                         lacks permissions."
       │
       ├─ 404 Not Found ──────► "API not found:
       │                         {owner}/{api}/{version}"
       │
       ├─ Network Error ──────► "Failed to fetch specification:
       │                         {error message}"
       │
       └─ Success ────────────► Display metadata preview
                                Enable Analyze button
```

## State Management

```
ImportDialog.tsx State:
┌─────────────────────────────────────────┐
│ swaggerHubContent: string | null        │
│ swaggerHubFilename: string | null       │
│ swaggerHubMetadata: FileMetadataPreview │
└─────────────────────────────────────────┘
                  │
                  ▼
         Used by handleAnalyze()
                  │
                  ▼
         Passed to analyzeSpecification()
                  │
                  ▼
         Standard import flow continues
```

## Component Integration

```
ImportDialog.tsx
├── Source Selection
│   ├── File
│   ├── URL
│   ├── Clipboard
│   ├── Git
│   └── SwaggerHub ◄────── NEW
│
├── File Upload Step
│   └── SwaggerHubImportPanel ◄────── NEW
│       ├── Form Inputs
│       ├── Validation
│       ├── Test & Fetch
│       └── Metadata Preview
│
├── Analysis Step
│   └── AnalysisPanel
│       └── Uses swaggerHubContent ◄────── UPDATED
│
├── Preview Step
│   └── PreviewPanel
│
├── Import Step
│   └── ImportExecutionPanel
│
└── Complete Step
    └── ImportCompletePanel
```

## API Request Example

### Public API Request
```
GET https://api.swaggerhub.com/apis/swagger-api/petstore/1.0.0
Headers:
  Accept: application/json

Response:
  200 OK
  {
    "openapi": "3.1.0",
    "info": {
      "title": "Swagger Petstore",
      "version": "1.0.0"
    },
    "paths": { ... }
  }
```

### Private API Request
```
GET https://api.swaggerhub.com/apis/mycompany/internal-api/2.1.0
Headers:
  Accept: application/json
  Authorization: abc123def456...

Response:
  200 OK
  {
    "openapi": "3.1.0",
    "info": {
      "title": "Internal API",
      "version": "2.1.0"
    },
    "paths": { ... }
  }
```

## Validation Flow

```
User types in Owner field
         │
         ▼
    onChange event
         │
         ▼
    useEffect hook
         │
         ▼
    Regex validation: /^[a-zA-Z0-9_-]+$/
         │
         ├─ Match ────► Clear error
         │              Enable Test & Fetch
         │
         └─ No match ─► Show error message
                        Disable Test & Fetch
```

## Success Flow Summary

```
1. User selects "SwaggerHub" source
   ↓
2. SwaggerHub panel displays
   ↓
3. User enters: owner, api, version (optional), API key (optional)
   ↓
4. Real-time validation passes
   ↓
5. User clicks "Test & Fetch"
   ↓
6. validateSwaggerHubOptions() → OK
   ↓
7. fetchFromSwaggerHub() → Success
   ↓
8. extractFileMetadata() → Metadata
   ↓
9. Display preview with title, description, format, version
   ↓
10. User clicks "Analyze →"
   ↓
11. handleAnalyze() processes content
   ↓
12. Analysis panel shows results
   ↓
13. User continues with standard import flow
   ↓
14. Import completes successfully
```

---

**Legend**:
- ◄── : Indicates new or updated component
- ───► : Flow direction
- └──  : Decision branch
- │    : Flow continuation
- ▼    : Next step

