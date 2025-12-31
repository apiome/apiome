# Import feature set


### 4. Import System (Enterprise-Grade)

The import system provides comprehensive, enterprise-level capabilities for importing OpenAPI specifications and related formats. It supports multiple input methods, validation layers, conflict resolution, and seamless integration with existing projects.

#### 4.1 Import Methods ✅ PARTIALLY IMPLEMENTED

##### File Upload
- ✅ **Single File Upload**: Standard file picker for individual files
- 📋 **Multi-File Upload**: Batch import multiple specification files
- ✅ **Drag & Drop Zone**: Visual dropzone with file type indicators
- **Folder Upload**: Import entire specification directories
- **Archive Support**: Import from ZIP, TAR.GZ containing specs
- **Large File Handling**: Chunked upload for files > 10MB
- **Upload Resume**: Resume interrupted uploads

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|
| #498   | Adds multi-file upload functionality            |

##### URL Import 📋 PLANNED
- ✅ **Direct URL Import**: Fetch spec from public URL
- ✅ **Authenticated URL**: Support for Bearer, API Key, Basic Auth
- 📋 **Git Repository Import**: Clone from GitHub, GitLab, Bitbucket
- 📋 **Branch/Tag Selection**: Import specific versions from git
- 📋 **Private Repository Support**: OAuth integration for private repos
- 📋 **Swagger Hub Integration**: Direct import from SwaggerHub
- 📋 **Postman Collection Import**: Import from Postman workspace URL

| Ticket | Feature Description                     |
|--------|-----------------------------------------|
| #332   | Ability to import SwaggerHub            |
| #333   | Ability to import Postman Collection    |

##### Integration Import 📋 PLANNED
- 📋 **API Gateway Import**: AWS API Gateway, Azure APIM, Kong
- **CI/CD Pipeline Integration**: Import from build artifacts
- **Registry Import**: Import from schema registries
- **Webhook Import**: Automated import via webhook triggers

| Ticket | Feature Description                             |
|--------|-------------------------------------------------|
| #350   | Adds the ability to import via AWS API Gateway  |

#### 4.2 Supported Formats ✅ PARTIALLY IMPLEMENTED

##### OpenAPI Specifications
- ✅ **OpenAPI 3.1.x**: Full JSON Schema Draft 2020-12 support
- ✅ Warn on older versions of OpenAPI Specification
- ⚠️ **OpenAPI 3.0.x**: Detected but not yet supported (upgrade path planned)
- ⚠️ **OpenAPI 2.0 (Swagger)**: Detected but not yet supported (automatic conversion planned)
- **Multi-File Specs**: Support for $ref across multiple files
- **External References**: Resolve external $ref URLs

| Ticket | Feature Description                |
|--------|------------------------------------|
| #496   | Adds OpenAPI 3.0 support           |
| #497   | Adds OpenAPI 2.0 (Swagger) support |

##### JSON Schema
- **JSON Schema Draft 2020-12**: Latest specification
- **JSON Schema Draft 07**: Common enterprise format
- **JSON Schema Draft 04**: Legacy support
- **Bundled Schemas**: Multi-schema documents

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

##### Data Formats
- **YAML**: Full YAML 1.2 support with anchors/aliases
- **JSON**: Standard JSON with comments support (JSONC)
- **JSON5**: Extended JSON format support

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

##### Schema Import/Export

**Import From** 📋 PLANNED
- 📋 Arazzo
- 📋 OpenAPI 2.0 (Swagger)
- 📋 OpenAPI 3.0/3.1
- 📋 JSON Schema
- Postman Collections
- 📋 GraphQL SDL
- 📋 AsyncAPI
- 📋 RAML
- API Blueprint
- 📋 Protobuf
- 📋 Avro
- 📋 Thrift
- Excel/CSV (data definitions)
- Database (reverse engineer from DB)

| Ticket | Feature Description         |
|--------|-----------------------------|
| #232   | Import from OpenAPI 2.0     |
| #233   | Import from OpenAPI 3.0/3.1 |
| #234   | Import from JSON Schema     |
| #235   | Import from GraphQL SDL     |
| #236   | Import from AsyncAPI        |
| #237   | Import from RAML            |
| #238   | Import from Protobuf        |
| #239   | Import from Avro            |
| #240   | Import from Thrift          |
| #299   | Import from Arazzo          |

#### 4.3 Pre-Import Analysis 📋 PLANNED

##### Format Detection & Validation 📋 PARTIALLY IMPLEMENTED
- ✅ **Auto-Detection**: Automatically identify specification format
- ✅ **Version Detection**: Detect OpenAPI/JSON Schema version
- ✅ **Syntax Validation**: Real-time YAML/JSON syntax checking
- **Schema Validation**: Validate against official meta-schemas
- **Custom Validation Rules**: Enterprise-specific validation

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

##### Specification Analysis 📋 PARTIALLY IMPLEMENTED
- ✅ **Schema Count**: Number of schemas to be imported
- ✅ **Property Count**: Total properties across all schemas
- **Reference Analysis**: Count and map all $ref relationships
- **Circular Reference Detection**: Identify circular dependencies
- **External Reference Inventory**: List all external URLs

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

##### Compatibility Check
- **Feature Compatibility**: Identify unsupported features
- **Extension Detection**: List all x- custom extensions
- **Deprecated Feature Warning**: Flag deprecated constructs
- **Security Scheme Analysis**: Identify auth requirements
- **Breaking Change Detection**: Compare with existing version

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

##### Quality Score 📋 PARTIALLY IMPLEMENTED
- **Completeness Score**: Descriptions, examples, documentation
- **Consistency Score**: Naming conventions, patterns
- **Best Practices Score**: Industry standard compliance
- ✅ **Security Score**: Security scheme coverage
- ✅ **Overall Quality Rating**: A-F grade with breakdown

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

#### 4.4 Import Preview & Mapping 📋 PLANNED

##### Visual Preview
- **Schema Tree View**: Hierarchical view of all schemas
- **Property Listing**: Expandable property details
- **Relationship Diagram**: Preview of schema relationships
- **Side-by-Side Comparison**: Compare with existing schemas
- **Diff Highlighting**: Visual diff for updates

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

##### Schema Selection 📋 PARTIALLY IMPLEMENTED
- ✅ **Select All / None**: Bulk selection controls
- ✅ **Individual Selection**: Cherry-pick specific schemas
- **Dependency Resolution**: Auto-select required dependencies
- **Search & Filter**: Find schemas by name, type, tags
- **Category Grouping**: Group by tag, path, or custom criteria

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

##### Name Mapping
- **Auto-Generated Names**: Smart naming from schema context
- **Custom Name Override**: Manual name assignment
- **Naming Convention Enforcement**: camelCase, PascalCase, etc.
- **Prefix/Suffix Rules**: Apply consistent naming patterns
- **Reserved Name Detection**: Prevent conflicts with keywords

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

##### Property Mapping
- **Type Mapping**: Map external types to internal types
- **Default Value Assignment**: Set defaults during import
- **Required Field Override**: Modify required status
- **Description Enhancement**: Add/modify descriptions
- **Example Generation**: Auto-generate missing examples

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

#### 4.5 Conflict Resolution 📋 PLANNED

##### Conflict Detection
- **Duplicate Schema Detection**: Same name, different definition
- **Property Conflicts**: Incompatible property definitions
- **Reference Conflicts**: Broken or ambiguous references
- **Type Mismatches**: Incompatible type assignments
- **Semantic Conflicts**: Logically incompatible constraints

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

##### Resolution Strategies
- **Keep Existing**: Preserve current schema, skip import
- **Replace**: Overwrite existing with imported schema
- **Merge**: Intelligently merge properties and constraints
- **Rename**: Import with modified name to avoid conflict
- **Create Version**: Import as new version of existing schema

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

##### Merge Options
- **Additive Merge**: Add new properties, keep existing
- **Override Merge**: Imported values take precedence
- **Selective Merge**: Choose per-property merge strategy
- **Deep Merge**: Recursively merge nested objects
- **Array Merge Strategies**: Append, replace, or deduplicate

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

##### Conflict Report
- **Conflict Summary**: Overview of all detected conflicts
- **Impact Analysis**: What will change if resolved
- **Resolution Recommendations**: AI-suggested resolutions
- **Batch Resolution**: Apply same strategy to similar conflicts
- **Conflict Export**: Export conflict report for review

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

#### 4.6 Import Execution 📋 PLANNED

##### Progress Tracking
- **Step-by-Step Progress**: Current phase indicator
- **Percentage Complete**: Overall progress bar
- **Schema Counter**: X of Y schemas imported
- **Time Estimate**: Estimated completion time
- **Speed Metrics**: Schemas per second

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

##### Execution Options
- **Dry Run Mode**: Preview changes without committing
- **Transaction Mode**: All-or-nothing import
- **Incremental Mode**: Import available, skip failures
- **Background Import**: Continue working during import
- **Scheduled Import**: Queue import for later execution

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

##### Real-Time Feedback
- **Live Log**: Streaming import log
- **Success Indicators**: Green checkmarks for completed
- **Warning Indicators**: Yellow for non-critical issues
- **Error Indicators**: Red for failures with details
- **Skip Indicators**: Gray for intentionally skipped items

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

##### Error Handling
- **Graceful Degradation**: Continue on non-critical errors
- **Error Recovery**: Retry failed operations
- **Rollback Support**: Undo partial imports
- **Error Export**: Download detailed error report
- **Support Ticket Creation**: One-click issue reporting

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

#### 4.7 Post-Import Actions 📋 PLANNED

##### Import Summary
- **Success Count**: Schemas successfully imported
- **Warning Count**: Items with warnings
- **Error Count**: Failed imports
- **Skip Count**: Intentionally skipped items
- **Time Taken**: Total import duration

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

##### Automatic Actions
- **Auto-Layout**: Arrange imported schemas on canvas
- **Auto-Connect**: Create relationships from $ref
- **Auto-Tag**: Apply tags based on source/category
- **Auto-Document**: Generate descriptions from context
- **Auto-Validate**: Run validation on imported schemas

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

##### Review & Verification
- **Import Review Mode**: Highlight newly imported items
- **Comparison Report**: Before/after summary
- **Validation Report**: Full validation results
- **Quality Assessment**: Post-import quality score
- **Relationship Verification**: Confirm all refs resolved

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

##### Follow-Up Actions 📋 PLANNED
- **Open in Canvas**: Navigate to imported schemas
- **Generate Documentation**: Create docs from import
- **Share Import Report**: Send summary to team
- **Schedule Re-Import**: Set up recurring import
- **Export Transformed**: Export in different format

| Ticket | Feature Description          |
|--------|------------------------------|
| #319   | Open in canvas after import  |

#### 4.8 Import History & Audit 📋 PLANNED

##### Import History
- **Import Log**: Complete history of all imports
- **Source Tracking**: Where each schema originated
- **Timestamp Recording**: When imports occurred
- **User Attribution**: Who performed the import
- **Version Tracking**: Import version history

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

##### Audit Trail
- **Change Log**: Detailed record of all changes
- **Before/After Snapshots**: State comparison
- **Rollback Points**: Restore to pre-import state
- **Compliance Reporting**: Audit-ready reports
- **Retention Policies**: Configurable history retention

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

##### Re-Import Capabilities
- **Saved Import Configs**: Reuse import settings
- **Scheduled Re-Imports**: Periodic sync from source
- **Incremental Updates**: Only import changes
- **Change Detection**: Notify when source changes
- **Sync Status**: Dashboard of import freshness

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

#### 4.9 Import Templates & Presets 📋 PLANNED

##### Built-In Templates
- **Standard OpenAPI**: Default settings for OpenAPI import
- **Minimal Import**: Only essential schemas
- **Full Import**: All schemas with all metadata
- **Migration Mode**: Optimized for legacy conversion
- **Strict Mode**: Fail on any validation error

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

##### Custom Presets
- **Save Current Settings**: Create preset from current config
- **Preset Library**: Organization-wide preset sharing
- **Preset Parameters**: Variables in preset templates
- **Preset Versioning**: Track preset changes over time
- **Preset Import/Export**: Share presets across instances

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

##### Transformation Rules
- **Property Transformations**: Rename, restructure properties
- **Type Coercion Rules**: Convert between types
- **Constraint Adjustments**: Modify min/max, patterns
- **Metadata Injection**: Add standard metadata
- **Sanitization Rules**: Clean up imported data

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

#### 4.10 Enterprise Features 📋 PLANNED

##### Access Control
- **Import Permissions**: Role-based import access
- **Approval Workflow**: Require approval for imports
- **Quarantine Mode**: Review imports before activation
- **Import Quotas**: Limit import volume per user/org
- **Source Restrictions**: Whitelist allowed import sources

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

##### Integration & Automation
- **REST API**: Programmatic import via API
- **CLI Tool**: Command-line import utility
- **SDK Support**: Language-specific import libraries
- **Webhook Notifications**: Import event webhooks
- **CI/CD Integration**: GitHub Actions, GitLab CI, Jenkins

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

##### Compliance & Governance
- **Policy Enforcement**: Automatic policy validation
- **Naming Standards**: Enforce organization conventions
- **Required Fields**: Mandate specific metadata
- **Prohibited Patterns**: Block disallowed constructs
- **Compliance Certification**: Mark imports as certified

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

##### Performance & Scale
- **Parallel Processing**: Multi-threaded import
- **Queue Management**: Handle import backlog
- **Rate Limiting**: Prevent system overload
- **Caching**: Cache resolved external references
- **Optimization**: Memory-efficient large imports

| Ticket | Feature Description                              |
|--------|--------------------------------------------------|

#### 4.11 Import Flow UI Design 📋 PLANNED

The import flow is designed as a multi-step wizard with clear visual progression, responsive feedback, and intuitive controls. The UI adapts to both light and dark modes using Radix UI components and Tailwind CSS.

##### Step 1c: Git Repository Import View

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Import Specification                                              [X Close]│
├─────────────────────────────────────────────────────────────────────────────┤
│  ● Source  ━━━━  ○ Analyze  ━━━━  ○ Preview  ━━━━  ○ Import  ━━━━  ○ Done   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  [📁 File] [🔗 URL] [📋 Clipboard] [🐙 Git] [☁️ SwaggerHub] [📦 Registry]   │
│                                    ────────                                 │
│                                                                             │
│  Repository URL                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ https://github.com/org/api-specs                                    │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  ┌─── Branch / Tag ────────────────────────────────────────────────────┐   │
│  │                                                                     │   │
│  │  Branch: ┌──────────────────────┐  Tag: ┌──────────────────────┐   │   │
│  │          │ main              ▼  │       │ (none)            ▼  │   │   │
│  │          └──────────────────────┘       └──────────────────────┘   │   │
│  │                                                                     │   │
│  │  Spec Path: ┌───────────────────────────────────────────────────┐  │   │
│  │             │ /specs/openapi.yaml                               │  │   │
│  │             └───────────────────────────────────────────────────┘  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  ┌─── Repository Authentication ───────────────────────────────────────┐   │
│  │  [🔐 Connect GitHub]  [🔐 Connect GitLab]  [🔐 Connect Bitbucket]   │   │
│  │                                                                     │   │
│  │  ✓ Connected to GitHub as @username                                │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│                                           [← Back]  [Cancel]    [Next →]    │
└─────────────────────────────────────────────────────────────────────────────┘
```

##### Step 3: Preview & Mapping Panel

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Import Specification                                              [X Close]│
├─────────────────────────────────────────────────────────────────────────────┤
│  ✓ Source  ━━━━  ✓ Analyze  ━━━━  ● Preview  ━━━━  ○ Import  ━━━━  ○ Done   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─── Schema Selection ─────────────────────────────────────────────────┐  │
│  │  [Select All] [Select None] [Select Required]     🔍 Filter schemas  │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│  ┌─────────────────────────────────────┬────────────────────────────────┐  │
│  │  Schemas to Import                  │  Schema Preview                │  │
│  ├─────────────────────────────────────┼────────────────────────────────┤  │
│  │                                     │                                │  │
│  │  ☑ 📦 Pet                           │  Pet                           │  │
│  │     └─ 3 properties                 │  ──────────────────────────    │  │
│  │  ☑ 📦 Category                      │                                │  │
│  │     └─ 2 properties                 │  Properties:                   │  │
│  │  ☑ 📦 Tag                           │  ├─ id: integer (required)     │  │
│  │     └─ 2 properties                 │  ├─ name: string (required)    │  │
│  │  ☑ 📦 Order                         │  ├─ category: $ref → Category  │  │
│  │     └─ 6 properties                 │  ├─ photoUrls: array<string>   │  │
│  │  ☑ 📦 User                          │  ├─ tags: array<$ref → Tag>    │  │
│  │     └─ 8 properties                 │  └─ status: enum               │  │
│  │  ☐ 📦 ApiResponse                   │                                │  │
│  │     └─ 3 properties (skip)          │  Relationships:                │  │
│  │                                     │  ├─ → Category (composition)   │  │
│  │  ─────────────────────────          │  └─ → Tag (aggregation)        │  │
│  │  Dependencies (auto-selected):      │                                │  │
│  │  ☑ 📦 Category (required by Pet)    │  [View JSON]  [View YAML]      │  │
│  │  ☑ 📦 Tag (required by Pet)         │                                │  │
│  │                                     │                                │  │
│  └─────────────────────────────────────┴────────────────────────────────┘  │
│                                                                             │
│  ┌─── Conflict Resolution ─────────────────────────────────────────────┐   │
│  │  ⚠ 1 conflict detected                                              │   │
│  │                                                                     │   │
│  │  Pet (exists in project)                                            │   │
│  │  ┌────────────────────────────────────────────────────────────────┐ │   │
│  │  │  Resolution: (●) Merge  ( ) Replace  ( ) Skip  ( ) Rename      │ │   │
│  │  │                                                                │ │   │
│  │  │  [View Diff]  Preview: +2 properties, ~1 modified              │ │   │
│  │  └────────────────────────────────────────────────────────────────┘ │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  ┌─── Import Options ──────────────────────────────────────────────────┐   │
│  │  Target Project: [Default Project          ▼]                       │   │
│  │  Target Version: [v2.0.0                   ▼]  [+ New Version]      │   │
│  │                                                                     │   │
│  │  ☑ Auto-layout imported schemas on canvas                          │   │
│  │  ☑ Create relationships from $ref                                   │   │
│  │  ☑ Apply naming convention (PascalCase)                             │   │
│  │  ☐ Generate documentation from descriptions                         │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│                                           [← Back]  [Cancel]    [Import →]  │
└─────────────────────────────────────────────────────────────────────────────┘
```

##### Step 4: Import Execution Panel

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Import Specification                                              [X Close]│
├─────────────────────────────────────────────────────────────────────────────┤
│  ✓ Source  ━━━━  ✓ Analyze  ━━━━  ✓ Preview  ━━━━  ● Import  ━━━━  ○ Done   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─── Import Progress ─────────────────────────────────────────────────┐   │
│  │                                                                     │   │
│  │  ████████████████████████████░░░░░░░░░░░░░░░░░  65%                 │   │
│  │                                                                     │   │
│  │  Importing schema 8 of 12: Order                                    │   │
│  │  Estimated time remaining: 5 seconds                                │   │
│  │                                                                     │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  ┌─── Live Progress ───────────────────────────────────────────────────┐   │
│  │                                                                     │   │
│  │  ✓ Pet                      Imported successfully                   │   │
│  │  ✓ Category                 Imported successfully                   │   │
│  │  ✓ Tag                      Imported successfully                   │   │
│  │  ✓ Pet → Category           Relationship created                    │   │
│  │  ✓ Pet → Tag                Relationship created                    │   │
│  │  ⚠ Order                    Imported with warnings                  │   │
│  │    └─ Missing example for shipDate property                         │   │
│  │  ⏳ User                     Importing...                            │   │
│  │  ○ Customer                 Pending                                 │   │
│  │  ○ Address                  Pending                                 │   │
│  │  ○ Store                    Pending                                 │   │
│  │  ○ Inventory                Pending                                 │   │
│  │                                                                     │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  ┌─── Import Log ──────────────────────────────────────────────────────┐   │
│  │  [INFO]  Starting import of 12 schemas                              │   │
│  │  [INFO]  Creating schema: Pet (id: sch_abc123)                      │   │
│  │  [INFO]  Creating schema: Category (id: sch_def456)                 │   │
│  │  [WARN]  Order.shipDate missing example, using generated value     │   │
│  │  [INFO]  Creating relationship: Pet → Category                      │   │
│  │  ▼ Show more...                                                     │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│                                                            [Cancel Import]  │
└─────────────────────────────────────────────────────────────────────────────┘
```

##### Diff View Modal (for Conflict Resolution)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Schema Diff: Pet                                          [X Close]       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─── Current (Existing) ──────────────┬─── Imported (New) ────────────┐   │
│  │                                     │                               │   │
│  │  Pet:                               │  Pet:                         │   │
│  │    type: object                     │    type: object               │   │
│  │    properties:                      │    properties:                │   │
│  │      id:                            │      id:                      │   │
│  │        type: integer                │        type: integer          │   │
│  │        format: int64                │        format: int64          │   │
│  │      name:                          │      name:                    │   │
│  │        type: string                 │        type: string           │   │
│  │  ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─              │  + status:               NEW │   │
│  │                                     │  +   type: string             │   │
│  │                                     │  +   enum: [available, ...]   │   │
│  │      category:                      │      category:            MOD │   │
│  │        $ref: '#/.../Category'       │        $ref: '#/.../Category' │   │
│  │  ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─              │        description: "..."     │   │
│  │                                     │                               │   │
│  └─────────────────────────────────────┴───────────────────────────────┘   │
│                                                                             │
│  ┌─── Summary ─────────────────────────────────────────────────────────┐   │
│  │  + 1 property added (status)                                        │   │
│  │  ~ 1 property modified (category - added description)               │   │
│  │  - 0 properties removed                                             │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  Resolution: (●) Merge  ( ) Replace  ( ) Keep Current  ( ) Rename as...   │
│                                                                             │
│                                                    [Cancel]  [Apply]        │
└─────────────────────────────────────────────────────────────────────────────┘
```

##### Import Templates Sidebar

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Import Templates                                                  [X Close]│
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  🔍 Search templates...                                                     │
│                                                                             │
│  ┌─── Built-in Templates ──────────────────────────────────────────────┐   │
│  │                                                                     │   │
│  │  ┌─────────────────────────────────────────────────────────────────┐│   │
│  │  │  📋 Standard OpenAPI                                 [Apply]   ││   │
│  │  │  Default settings for OpenAPI 3.x import                       ││   │
│  │  │  ✓ Resolve refs  ✓ Create relationships  ✓ Auto-layout         ││   │
│  │  └─────────────────────────────────────────────────────────────────┘│   │
│  │                                                                     │   │
│  │  ┌─────────────────────────────────────────────────────────────────┐│   │
│  │  │  📋 Minimal Import                                   [Apply]   ││   │
│  │  │  Import only essential schemas, skip metadata                  ││   │
│  │  │  ✓ Core schemas only  ✗ Skip examples  ✗ Skip descriptions     ││   │
│  │  └─────────────────────────────────────────────────────────────────┘│   │
│  │                                                                     │   │
│  │  ┌─────────────────────────────────────────────────────────────────┐│   │
│  │  │  📋 Strict Mode                                      [Apply]   ││   │
│  │  │  Fail on any validation error or warning                       ││   │
│  │  │  ✓ Strict validation  ✓ No warnings  ✓ Complete metadata       ││   │
│  │  └─────────────────────────────────────────────────────────────────┘│   │
│  │                                                                     │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  ┌─── Custom Templates ────────────────────────────────────────────────┐   │
│  │                                                                     │   │
│  │  ┌─────────────────────────────────────────────────────────────────┐│   │
│  │  │  📋 Team API Standards                    [Apply] [Edit] [⋮]   ││   │
│  │  │  Organization-specific import settings                         ││   │
│  │  │  Created by @admin · Updated 3 days ago                        ││   │
│  │  └─────────────────────────────────────────────────────────────────┘│   │
│  │                                                                     │   │
│  │  [+ Create New Template]                                            │   │
│  │                                                                     │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

# Completed

##### Clipboard Import ✅ IMPLEMENTED
- ✅ **Paste JSON/YAML**: Direct paste into import dialog
- ✅ **Syntax Highlighting**: Live preview of pasted content
- ✅ **Format Auto-Detection**: Automatically detect JSON vs YAML

##### Import Sanity Checks ✅ IMPLEMENTED
- ✅ **Basic Validation**: Check for well-formed syntax
- ✅ **Schema Presence**: Ensure at least one schema defined
- ✅ **Version Detection**: Identify OpenAPI/JSON Schema version
- ✅ Validation check:
  - ✅ Generates OpenAPI from JSON Schema on import
  - ✅ Validates OpenAPI spec on import
  - ✅ Displays validation errors/warnings before import
