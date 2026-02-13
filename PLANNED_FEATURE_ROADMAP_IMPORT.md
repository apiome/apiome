# Import feature set


### 4. Import System (Enterprise-Grade)

The import system provides comprehensive, enterprise-level capabilities for importing OpenAPI specifications and related formats. It supports multiple input methods, validation layers, conflict resolution, and seamless integration with existing projects.

#### 4.1 Import Methods ✅ PARTIALLY IMPLEMENTED

##### File Upload
- ✅ **Single File Upload**: Standard file picker for individual files
- 📋 **Multi-File Upload**: Batch import multiple specification files
- ✅ **Drag & Drop Zone**: Visual dropzone with file type indicators
- [TODO] **Folder Upload**: Import entire specification directories
- [TODO] **Large File Handling**: Chunked upload for files > 10MB
- [TODO] **Upload Resume**: Resume interrupted uploads

| Ticket | Feature Description                  |
|--------|--------------------------------------|
| #498   | Adds multi-file upload functionality |

##### Integration Import 📋 PLANNED
- 📋 **API Gateway Import**: AWS API Gateway, Azure APIM, Kong
- [TODO] **CI/CD Pipeline Integration**: Import from build artifacts
- [TODO] **Registry Import**: Import from schema registries
- [TODO] **Webhook Import**: Automated import via webhook triggers
- 📋 **Objectified Import**: Import from Objectified schema registry

| Ticket | Feature Description                            |
|--------|------------------------------------------------|
| #350   | Adds the ability to import via AWS API Gateway |
| #800   | Add ability to import Objectified schema       |

#### 4.2 Supported Formats ✅ PARTIALLY IMPLEMENTED

##### OpenAPI Specifications
- ✅ **OpenAPI 3.1.x**: Full JSON Schema Draft 2020-12 support
- ✅ Warn on older versions of OpenAPI Specification
- ✅ **OpenAPI 3.0.x**: Automatically converted to OpenAPI 3.1.x
- ✅ **OpenAPI 2.0 (Swagger)**
- [TODO] **Multi-File Specs**: Support for $ref across multiple files
- [TODO] **External References**: Resolve external $ref URLs

| Ticket | Feature Description                |
|--------|------------------------------------|
| #496   | Adds OpenAPI 3.0 support           |

##### Schema Import/Export

**Import From** 📋 PLANNED
- 📋 Arazzo
- ✅ OpenAPI 2.0 (Swagger)
- ✅ OpenAPI 3.0.x
- ✅ OpenAPI 3.1.x
- ✅ JSON Schema
- [TODO] Postman Collections
- ✅ GraphQL SDL
- 📋 AsyncAPI
- 📋 RAML
- [TODO] API Blueprint
- 📋 Protobuf
- 📋 Avro
- 📋 Thrift
- [TODO] Excel/CSV (data definitions)
- [TODO] Database (reverse engineer from DB)

| Ticket | Feature Description         |
|--------|-----------------------------|
| #236   | Import from AsyncAPI        |
| #237   | Import from RAML            |
| #238   | Import from Protobuf        |
| #239   | Import from Avro            |
| #240   | Import from Thrift          |
| #299   | Import from Arazzo          |

#### 4.5 Conflict Resolution ✅ PARTIALLY IMPLEMENTED

##### Merge Options
- ✅ **Additive Merge**: Add new properties, keep existing
- ✅ **Override Merge**: Imported values take precedence
- ✅ **Selective Merge**: Choose per-property merge strategy (#593)
- 📋 **Deep Merge**: Recursively merge nested objects
- 📋 **Array Merge Strategies**: Append, replace, or deduplicate

| Ticket | Feature Description                                  |
|--------|------------------------------------------------------|
| #594   | Deep merge for nested objects                        |
| #595   | Array merge strategies: append, replace, deduplicate |

#### 4.6 Import Execution 📋 PLANNED

##### Error Handling
- ✅ **Graceful Degradation**: Continue on non-critical errors
- ✅ **Error Recovery**: Retry failed operations
- ✅ **Rollback Support**: Undo partial imports (post-commit rollback)
- ✅ **Error Export**: Download detailed error report
- 📋 **Support Ticket Creation**: One-click issue reporting

| Ticket | Feature Description                  |
|--------|--------------------------------------|
| #737   | One-click support ticket creation    |

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

##### Quality Score ✅ IMPLEMENTED
- ✅ **Completeness Score**: Descriptions, examples, documentation
- ✅ **Consistency Score**: Naming conventions, patterns
- ✅ **Best Practices Score**: Industry standard compliance
- ✅ **Security Score**: Security scheme coverage
- ✅ **Overall Quality Rating**: A-F grade with breakdown

##### Progress Tracking ✅ IMPLEMENTED
- ✅ **Step-by-Step Progress**: Current phase indicator
- ✅ **Percentage Complete**: Overall progress bar
- ✅ **Schema Counter**: X of Y schemas imported
- ✅ **Time Estimate**: Estimated completion time

##### Import Summary ✅ IMPLEMENTED
- ✅ **Success Count**: Schemas successfully imported
- ✅ **Warning Count**: Items with warnings
- ✅ **Error Count**: Failed imports
- ✅ **Skip Count**: Intentionally skipped items
- ✅ **Time Taken**: Total import duration

##### Specification Analysis ✅ IMPLEMENTED
- ✅ **Schema Count**: Number of schemas to be imported
- ✅ **Property Count**: Total properties across all schemas
- ✅ **Reference Analysis**: Count and map all $ref relationships
- ✅ **Circular Reference Detection**: Identify circular dependencies
- ✅ **External Reference Inventory**: List all external URLs

##### Format Detection & Validation ✅ IMPLEMENTED
- ✅ **Auto-Detection**: Automatically identify specification format
- ✅ **Version Detection**: Detect OpenAPI/JSON Schema version
- ✅ **Syntax Validation**: Real-time YAML/JSON syntax checking
- ✅ Import summarization details

##### AI Import ✅ IMPLEMENTED
- ✅ **Natural Language to Spec**: Generate OpenAPI from text description

##### URL Import ✅ IMPLEMENTED
- ✅ **Direct URL Import**: Fetch spec from public URL
- ✅ **Authenticated URL**: Support for Bearer, API Key, Basic Auth
- ✅ **Git Repository Import**: Clone from GitHub, GitLab, Bitbucket, Private Repos
- ✅ **Branch/Tag Selection**: Import specific versions from git
- ✅ **Swagger Hub Integration**: Direct import from SwaggerHub
- ✅ **Postman Collection Import**: Import from Postman workspace URL

##### Execution Options ✅ IMPLEMENTED
- ✅ **Dry Run Mode**: Preview changes without committing
- ✅ **Transaction Mode**: All-or-nothing import
- ✅ **Incremental Mode**: Import available, skip failures

#### 4.3 Pre-Import Analysis 📋 PLANNED

##### Compatibility Check
- ✅ **Feature Compatibility**: Identify unsupported features
- ✅ **Extension Detection**: List all x- custom extensions
- ✅ **Deprecated Feature Warning**: Flag deprecated constructs (#575)

##### Schema Selection ✅ IMPLEMENTED
- ✅ **Select All / None**: Bulk selection controls
- ✅ **Individual Selection**: Cherry-pick specific schemas
- ✅ **Dependency Resolution**: Auto-select required dependencies
- ✅ **Search & Filter**: Find schemas by name, type, tags

#### 4.4 Import Preview & Mapping ✅ IMPLEMENTED

##### Visual Preview
- ✅ **Schema Tree View**: Hierarchical view of all schemas
- ✅ **Property Listing**: Expandable property details
- ✅ **Relationship Diagram**: Preview of schema relationships (#578)

#### 4.6 Import Execution ✅ IMPLEMENTED

##### Real-Time Feedback ✅ IMPLEMENTED
- ✅ **Live Log**: Streaming import log
- ✅ **Success Indicators**: Green checkmarks for completed
- ✅ **Warning Indicators**: Yellow for non-critical issues
- ✅ **Error Indicators**: Red for failures with details
- ✅ **Skip Indicators**: Gray for intentionally skipped items

##### Name Mapping ✅ IMPLEMENTED
- ✅ **Auto-Generated Names**: Smart naming from schema context
- ✅ **Custom Name Override**: Manual name assignment
- ✅ **Naming Convention Enforcement**: camelCase, PascalCase, etc.
- ✅ **Prefix/Suffix Rules**: Apply consistent naming patterns
- ✅ **Reserved Name Detection**: Prevent conflicts with keywords (#756)

##### Property Mapping ✅ IMPLEMENTED
- ✅ **Type Mapping**: Map external types to internal types
- ✅ **Default Value Assignment**: Set defaults during import
- ✅ **Required Field Override**: Modify required status
- ✅ **Description Enhancement**: Add/modify property descriptions during import
- ✅ **Example Generation**: Auto-generate missing examples

##### Conflict Report
- ✅ **Conflict Summary**: Overview of all detected conflicts
- ✅ **Impact Analysis**: What will change if resolved
- ✅ **Conflict Export**: Export conflict report for review

##### Conflict Detection
- ✅ **Duplicate Schema Detection**: Same name, different definition
- ✅ **Property Conflicts**: Incompatible property definitions
- ✅ **Reference Conflicts**: Broken or ambiguous references
- ✅ **Type Mismatches**: Incompatible type assignments
- ✅ **Semantic Conflicts**: Logically incompatible constraints

#### 4.5 Conflict Resolution ✅ IMPLEMENTED

##### Resolution Strategies
- ✅ **Keep Existing**: Preserve current schema, skip import
- ✅ **Replace**: Overwrite existing with imported schema
- ✅ **Merge**: Intelligently merge properties and constraints
- ✅ **Rename**: Import with modified name to avoid conflict
- ✅ **Create Version**: Import as new version of existing schema (sub-version e.g. 1.0.0b)

---

## Suggested Enterprise Improvements

> The following features were identified by reviewing the current importer implementation against enterprise user expectations, cross-referencing with the canvas roadmap, and analyzing competitive gaps. They are organized by priority and impact.

---

### E1. Import History & Audit Dashboard 📋 PLANNED

[TODO] The importer currently has no persistent record of past imports. Enterprise compliance, governance, and operational visibility require a complete audit trail of all import activity across the organization.

- [TODO] **Import History Table**: Searchable, sortable table of all past imports with columns: date, user, source type, source URL/file, format, schema count, status (success/partial/failed), duration
- [TODO] **Import Detail View**: Click any past import to see full event log, schemas imported, warnings, errors, and the diff of what changed
- [TODO] **Re-Import from History**: One-click re-import from the same source with the same settings (useful for spec updates)
- [TODO] **Import Comparison**: Compare two past imports side-by-side to see what changed between runs (useful when re-importing updated specs)
- [TODO] **Import Audit Export**: Export full import audit log as CSV/JSON for compliance reporting (SOC 2, ISO 27001, HIPAA)
- [TODO] **User Attribution**: Every import action (initiate, approve, rollback, cancel) logged with user identity, IP address, and timestamp
- [TODO] **Retention Policy**: Configurable retention period for import history (30 days, 90 days, 1 year, forever) with automatic archival
- [TODO] **Organization-Wide Dashboard**: Admin-level view of import activity across all projects, users, and teams with usage analytics

---

### E2. Import Access Control & Approval Workflows 📋 PLANNED

[TODO] The importer currently allows any authenticated user to import into any project. Enterprise environments require fine-grained access control and approval gates.

- [TODO] **Role-Based Import Permissions**: Define who can import (e.g., Admin, Editor) vs. who needs approval (e.g., Viewer, Contributor)
- [TODO] **Project-Level Import Lock**: Lock a project or version against imports to prevent accidental changes during release freeze
- [TODO] **Approval Workflow**: Require designated approvers to review and approve imports before they are committed (extends the existing pending-approval state)
- [TODO] **Multi-Approver Support**: Require approval from N of M designated reviewers before an import is committed
- [TODO] **Approval Notification**: Email/Slack/webhook notification to approvers when an import is pending their review
- [TODO] **Approval SLA**: Configurable time limit for approval; auto-rollback if not approved within the window
- [TODO] **Import Quotas**: Limit the number of imports per user/team per day or the maximum schema count per import to prevent runaway bulk operations
- [TODO] **IP Allowlisting**: Restrict import sources (URLs, Git repos) to a pre-approved list of domains/IPs for security-conscious organizations

---

### E3. Import API & Headless Import (CI/CD Integration) 📋 PLANNED

[TODO] Enterprise teams need to trigger imports programmatically from CI/CD pipelines, scripts, or automation tools without using the browser UI.

- [TODO] **REST API for Import**: Expose a REST endpoint (`POST /api/v1/imports`) that accepts a spec file or URL, import options, and target project/version, and returns a job ID
- [TODO] **Import Status API**: `GET /api/v1/imports/{jobId}` to poll import status, progress, and results programmatically
- [TODO] **Import Commit/Rollback API**: `POST /api/v1/imports/{jobId}/commit` and `POST /api/v1/imports/{jobId}/rollback` for programmatic approval workflows
- [TODO] **CLI Tool**: A lightweight `objectified-cli` command-line tool wrapping the import API for use in shell scripts and CI/CD pipelines (e.g., `objectified import --file openapi.yaml --project my-api --version v2`)
- [TODO] **GitHub Action / GitLab CI Template**: Pre-built CI/CD templates that import the latest spec on every push to a branch or tag
- [TODO] **Webhook-Triggered Import**: Register a webhook URL that, when called (e.g., by GitHub on push), automatically triggers an import from the configured repository and branch
- [TODO] **API Key Authentication**: Dedicated API keys for headless/service-account imports, scoped to specific projects
- [TODO] **Dry Run via API**: `POST /api/v1/imports?dryRun=true` to validate and preview an import without committing, returning the analysis and conflict report as JSON

---

### E4. Import Templates & Presets 📋 PLANNED

[TODO] The roadmap references import templates in the UI mockups, but no formal feature definition exists. Enterprise teams need reusable, organization-wide import configurations.

- [TODO] **Built-In Templates**: Pre-configured import profiles:
  - [TODO] "Standard OpenAPI" — default settings, resolve refs, create relationships, auto-layout
  - [TODO] "Minimal Import" — core schemas only, skip examples and descriptions
  - [TODO] "Strict Mode" — fail on any validation error or warning, require complete metadata
  - [TODO] "Migration Mode" — lenient validation for legacy specs (Swagger 2.0, RAML, etc.)
  - [TODO] "Security Audit" — import only security schemes and auth-related schemas
- [TODO] **Custom Templates**: Save any import configuration as a named, reusable template
- [TODO] **Organization-Wide Templates**: Admin-created templates shared across all projects and users in the organization
- [TODO] **Template Versioning**: Track changes to templates over time with diff view
- [TODO] **Template Import/Export**: Share templates as JSON files between organizations or environments
- [TODO] **Template Auto-Apply**: Set a default template per project so imports automatically use it
- [TODO] **Template Variables**: Parameterized templates with variables (e.g., `{{projectName}}`, `{{version}}`) filled in at import time

---

### E5. Import Scheduling & Automated Sync 📋 PLANNED

[TODO] Enterprise teams often maintain OpenAPI specs in Git repositories that evolve independently. The importer needs the ability to automatically re-import on a schedule to keep Objectified in sync.

- [TODO] **Scheduled Imports**: Configure a cron-like schedule (hourly, daily, weekly) to re-import from a URL or Git repository
- [TODO] **Change Detection**: Before re-importing, compare the remote spec to the last imported version; skip if unchanged (avoid unnecessary operations)
- [TODO] **Differential Import**: On re-import, only process schemas that changed since the last import instead of re-importing everything
- [TODO] **Schedule Management UI**: List, enable/disable, edit, and delete scheduled imports from a dedicated management page
- [TODO] **Schedule Notifications**: Send email/Slack/webhook alerts when a scheduled import succeeds, fails, or detects changes
- [TODO] **Schedule History**: Log every scheduled run with result, duration, and changes detected
- [TODO] **Schedule Pause on Failure**: Auto-pause a schedule after N consecutive failures to prevent runaway errors; notify admin
- [TODO] **Git Branch Tracking**: Automatically track a branch (e.g., `main`) and re-import whenever new commits are pushed (via polling or webhook)

---

### E6. Conflict Resolution UI & Intelligence 📋 PLANNED

[TODO] Conflict detection exists at the database constraint level but there is no user-facing resolution UI. When importing into projects with existing schemas, enterprise users need visual tools to understand and resolve conflicts.

- [TODO] **Conflict Resolution Panel**: Dedicated step in the import wizard between Preview and Import that shows all detected conflicts in a scrollable list
- [TODO] **Per-Conflict Resolution Controls**: For each conflict, offer resolution strategies inline: Keep Existing, Replace, Merge (additive), Merge (override), Rename, Create New Version
- [TODO] **Visual Diff per Conflict**: Inline side-by-side diff showing existing schema vs. incoming schema with green/red/yellow property-level highlighting
- [TODO] **Bulk Resolution**: "Apply to all similar conflicts" button to apply the same strategy (e.g., "Replace All", "Keep All Existing") across multiple conflicts at once
- [TODO] **AI-Suggested Resolutions**: Use the LLM integration to suggest the best resolution strategy per conflict based on schema context and history
- [TODO] **Conflict Preview Impact**: For each resolution choice, show a preview of the resulting schema so users understand the impact before committing
- [TODO] **Conflict Report Export**: Export the conflict analysis as a PDF/JSON report for architecture review meetings
- [TODO] **Conflict Memory**: Remember resolution choices per source; on re-import, auto-apply the same resolution strategy for recurring conflicts
- [TODO] **Three-Way Merge**: When a schema was previously imported and both the local and remote versions have diverged, show a three-way merge view (base, local, remote)

---

### E7. Import Notifications & Alerts 📋 PLANNED

[TODO] The importer provides real-time feedback during execution but has no notification system for asynchronous events (approval requests, scheduled import results, failures).

- [TODO] **In-App Notifications**: Toast/bell notifications when an import completes, fails, or requires approval
- [TODO] **Email Notifications**: Configurable email alerts for import events (success, failure, pending approval, rollback)
- [TODO] **Slack Integration**: Post import results to a configured Slack channel (summary, schema count, warnings, link to review)
- [TODO] **Microsoft Teams Integration**: Post import results to a configured Teams channel
- [TODO] **Webhook Notifications**: Fire a webhook on import events for custom integrations (PagerDuty, Jira, etc.)
- [TODO] **Notification Preferences**: Per-user notification preferences (which events, which channels) configurable in profile settings
- [TODO] **Digest Mode**: Daily/weekly digest email summarizing all import activity across projects the user is subscribed to
- [TODO] **Failure Escalation**: If an import fails and is not addressed within a configurable window, escalate the notification to team leads or admins

---

### E8. Cross-Project & Cross-Version Import 📋 PLANNED

[TODO] Enterprise organizations manage dozens of API projects. The ability to import schemas between Objectified projects and versions is critical for schema reuse and consistency.

- [TODO] **Import from Another Project**: Browse and select schemas from another Objectified project to import into the current project (internal schema marketplace)
- [TODO] **Import from Another Version**: Import schemas from a different version of the same project (e.g., promote schemas from v1 to v2)
- [TODO] **Schema Linking vs. Copying**: Choose whether to create an independent copy or a linked reference to the source schema (linked schemas auto-update when the source changes)
- [TODO] **Dependency Resolution Across Projects**: When importing a schema that references schemas in another project, offer to import the dependencies as well or create cross-project references
- [TODO] **Shared Schema Registry**: Organization-level schema registry where teams publish reusable schemas that can be imported by any project
- [TODO] **Schema Catalog Browser**: Visual catalog of all schemas across all projects with search, tags, and usage statistics to help users discover reusable schemas
- [TODO] **Cross-Project Conflict Detection**: Warn when importing a schema that conflicts with a schema in a different project that shares the same consumers

---

### E9. Import Data Transformation Pipeline 📋 PLANNED

[TODO] Enterprise specs often need systematic transformations during import — renaming to match internal conventions, injecting required metadata, stripping vendor extensions, etc.

- [TODO] **Transformation Rules Engine**: Define ordered transformation rules that are applied to schemas during import (before they are persisted)
- [TODO] **Property Renaming Rules**: Regex-based rules to transform property names (e.g., `snake_case` to `camelCase`, strip prefixes like `x_`)
- [TODO] **Type Coercion Rules**: Map external types to internal types (e.g., `string:date-time` → custom `DateTime` type, `integer:int32` → `Int32`)
- [TODO] **Metadata Injection**: Automatically add required fields to every imported schema (e.g., `description`, `x-team-owner`, `x-data-classification`)
- [TODO] **Vendor Extension Stripping**: Optionally strip all `x-` vendor extensions during import to normalize schemas
- [TODO] **Description Templating**: Apply a template to schema descriptions (e.g., prepend "Imported from {{source}} on {{date}}")
- [TODO] **Property Filtering**: Exclude properties matching certain patterns (e.g., strip all `deprecated` properties, remove internal fields like `_id`)
- [TODO] **Transformation Preview**: Show a before/after diff of the transformation rules applied to the imported schemas before committing
- [TODO] **Reusable Transformation Profiles**: Save transformation configurations as named profiles; apply different profiles per project or per source
- [TODO] **Transformation Chaining**: Compose multiple transformation profiles in sequence for complex pipelines

---

### E10. Import Sandbox / Staging Environment 📋 PLANNED

[TODO] Enterprise users need the ability to evaluate an import in an isolated staging area before it affects the production project data.

- [TODO] **Staging Import Mode**: Import into a temporary, isolated staging area that does not affect the live project until explicitly promoted
- [TODO] **Staging Preview Canvas**: View the staged import on a read-only canvas to visually inspect the result before promoting
- [TODO] **Staging Diff**: Side-by-side comparison of the staging area vs. the live project showing what will change on promotion
- [TODO] **Staging Expiration**: Staging areas auto-expire after a configurable period (e.g., 7 days) if not promoted, freeing resources
- [TODO] **Multiple Staging Slots**: Support multiple concurrent staging imports per project (e.g., one from a URL source and one from a Git source) for comparison
- [TODO] **Promote to Live**: One-click promotion of a staged import to the live project version, with final confirmation dialog
- [TODO] **Staging Sharing**: Share a link to a staging area with team members for review before promotion

---

### E11. Large-Scale Import Performance 📋 PLANNED

[TODO] The current importer handles typical spec files well, but enterprise monorepos and API gateways can produce specs with 500+ schemas and 50MB+ files.

- [TODO] **Chunked File Upload**: Split large files into chunks for upload with resume capability if the connection drops
- [TODO] **Streaming Parser**: Parse YAML/JSON using a streaming parser to avoid loading the entire spec into memory at once
- [TODO] **Background Import Processing**: Move import execution to a background worker/job queue so the browser tab does not need to stay open
- [TODO] **Import Progress via WebSocket**: Replace polling with WebSocket-based real-time progress updates for lower latency and reduced server load
- [TODO] **Parallel Schema Processing**: Import independent schemas in parallel (batch inserts) rather than sequentially to reduce wall-clock time
- [TODO] **Import Size Estimation**: Before starting, show an estimated import time based on schema count and historical averages
- [TODO] **Memory-Efficient Preview**: For large specs (100+ schemas), virtualize the schema selection list in the Preview step to avoid browser lag
- [TODO] **Import Pagination**: For very large imports, process schemas in pages/batches and show incremental results rather than waiting for the full import to complete
- [TODO] **Spec Splitting Recommendation**: When a spec exceeds a configurable threshold (e.g., 200 schemas), suggest splitting it into multiple domain-specific imports

---

### E12. Import Validation Rules Engine 📋 PLANNED

[TODO] The analyzer provides quality scores, but enterprise organizations need enforceable, configurable validation rules that can gate or block imports.

- [TODO] **Custom Validation Rules**: Define organization-specific rules that run during the Analysis step (e.g., "All schemas must have a `description`", "No property names longer than 40 characters")
- [TODO] **Rule Severity Levels**: Each rule can be configured as Error (blocks import), Warning (allows import with notice), or Info (informational only)
- [TODO] **Rule Categories**: Group rules by category (naming conventions, documentation, security, data types, complexity)
- [TODO] **Quality Gate**: Set a minimum quality score threshold below which imports are blocked (e.g., "Import blocked: quality score 52/100 is below the minimum 70")
- [TODO] **Spectral Integration**: Import and apply Spectral rulesets (`.spectral.yaml`) for industry-standard API linting during import
- [TODO] **Per-Project Rule Overrides**: Allow individual projects to override organization-level rules (with admin approval)
- [TODO] **Rule Violation Report**: Detailed report of all rule violations with line numbers, suggestions, and links to documentation
- [TODO] **Auto-Fix Suggestions**: For common violations (missing descriptions, wrong casing), offer one-click auto-fix during the Preview step
- [TODO] **Compliance Certification**: Mark an import as "compliance-reviewed" after all rules pass, recording the ruleset version and results for audit

---

### E13. Import Dependency Visualization 📋 PLANNED

[TODO] The Preview step currently shows a flat list of schemas. Enterprise specs with deep reference chains need a visual dependency graph to help users understand the import scope.

- [TODO] **Interactive Dependency Graph**: In the Preview step, display a visual graph (using React Flow or a lightweight graph library) showing how imported schemas reference each other via `$ref`
- [TODO] **Dependency Depth Indicator**: Color-code or badge each schema by its depth in the dependency tree (root schemas, 1st-degree deps, 2nd-degree deps, etc.)
- [TODO] **Circular Dependency Highlighting**: Visually highlight circular reference cycles in red with a warning tooltip explaining the cycle path
- [TODO] **Impact Preview**: When hovering over a schema in the graph, highlight all schemas that depend on it (downstream) and all schemas it depends on (upstream)
- [TODO] **Select by Subgraph**: Click a root schema to auto-select it and all its transitive dependencies in the selection checklist
- [TODO] **Dependency Count Badge**: Show the number of inbound and outbound references on each schema node in the selection list
- [TODO] **Orphan Schema Detection**: Highlight schemas that have no inbound references (they are not used by any other schema) so users can decide whether to include them

---

### E14. Multi-Source Batch Import 📋 PLANNED

[TODO] Enterprise teams often need to import from multiple sources in a single session (e.g., a main OpenAPI spec from Git plus supplementary JSON Schema files from a file upload).

- [TODO] **Multi-Source Import Queue**: Allow users to queue multiple import sources (e.g., a URL + a file + a clipboard paste) and process them sequentially into the same project/version
- [TODO] **Source Priority & Conflict Rules**: When the same schema appears in multiple sources, define which source takes precedence
- [TODO] **Combined Preview**: After all sources are analyzed, show a unified Preview panel with schemas from all sources, color-coded by source
- [TODO] **Cross-Source Dependency Resolution**: Automatically link schemas across sources when `$ref` URIs match between files
- [TODO] **Batch Import Report**: Single summary report covering all sources with per-source breakdowns

---

### E15. Import Comparison & Drift Detection 📋 PLANNED

[TODO] When re-importing a spec that was previously imported, enterprise users need to see exactly what has changed since the last import to avoid unintended regressions.

- [TODO] **Drift Detection**: Compare the current project state against the remote source to identify schemas that have drifted (changed locally but not in the source, or vice versa)
- [TODO] **Import Diff View**: Side-by-side diff showing the last imported version vs. the new version for each schema, with property-level green/red/yellow highlighting
- [TODO] **Change Summary**: Aggregate change summary: N schemas added, N modified, N removed, N unchanged
- [TODO] **Selective Re-Import**: Choose which changed schemas to re-import and which to skip (don't force all-or-nothing on re-import)
- [TODO] **Drift Alerts**: Automatically notify users when a monitored source has changed since the last import (requires scheduled polling — see E5)
- [TODO] **Version Pinning**: Pin an import to a specific version/commit/tag so that scheduled re-imports always use the same version unless manually updated

---

### E16. Postman Collection Import 📋 PLANNED

[TODO] The roadmap mentions Postman Collection import (ticket #333) but the implementation details are not specified. Enterprise teams heavily use Postman and need a smooth migration path.

- [TODO] **Postman Collection v2.1 Parser**: Parse Postman Collection v2.1 JSON format, extracting requests, responses, schemas, and examples
- [TODO] **Postman Environment Import**: Import Postman environment variables and map them to server URLs and auth configurations
- [TODO] **Postman Folder Mapping**: Map Postman collection folders to schema groups/tags in Objectified
- [TODO] **Request Body to Schema Extraction**: Infer JSON Schema from Postman request body examples when no explicit schema is defined
- [TODO] **Response Example to Schema**: Generate schemas from Postman saved response examples
- [TODO] **Postman Workspace URL Import**: Fetch collections directly from a Postman workspace via the Postman API using an API key
- [TODO] **Postman-to-OpenAPI Conversion Preview**: Show the intermediate OpenAPI spec generated from the Postman collection before importing into Objectified

---

### E17. Import Error Recovery & Resilience 📋 PLANNED

[TODO] The current importer rolls back the entire import on failure. Enterprise users importing large specs need more granular error recovery.

- [TODO] **Partial Import with Skip**: When a single schema fails to import, skip it and continue importing the remaining schemas (incremental mode with per-schema error capture)
- [TODO] **Retry Failed Schemas**: After a partial import completes, offer a "Retry Failed" button to re-attempt only the schemas that failed
- [TODO] **Import Checkpoints**: For large imports (50+ schemas), create periodic checkpoints during execution so that a failure doesn't require re-importing everything from scratch
- [TODO] **Offline-Tolerant Import**: If the network drops during a URL/Git import after the spec has been fetched, continue the import using the locally cached spec
- [TODO] **Error Categorization**: Categorize errors as transient (network timeout, rate limit) vs. permanent (schema validation failure, duplicate name) and auto-retry only transient errors
- [TODO] **Import Resume**: If the browser tab is closed or the session expires during a long-running import, allow resuming from the last checkpoint when the user returns
- [TODO] **Dead Letter Queue**: Schemas that fail after all retries are placed in a "dead letter" list for manual review and re-import

---

### E18. Smart Schema Matching & Deduplication 📋 PLANNED

[TODO] When importing specs into projects that already contain schemas, exact name matching is insufficient. Enterprise specs often have schemas with slightly different names that represent the same entity.

- [TODO] **Fuzzy Name Matching**: Detect potential duplicates using fuzzy string matching (e.g., "UserResponse" vs. "UserRes", "PetModel" vs. "Pet") and surface them as potential conflicts
- [TODO] **Structural Similarity Detection**: Compare schema structures (property names, types, nesting) to detect schemas that are structurally identical or nearly identical, regardless of name
- [TODO] **AI-Powered Schema Matching**: Use the LLM integration to suggest which imported schemas correspond to existing schemas based on name, description, and structure
- [TODO] **Deduplication Suggestions**: Before import, show a "Potential Duplicates" panel listing schemas that may already exist under a different name, with a confidence percentage
- [TODO] **Merge Suggestion Preview**: For each potential duplicate, show a suggested merged schema and let the user approve, modify, or reject the merge
- [TODO] **Fingerprinting**: Generate a structural fingerprint for each schema (hash of property names, types, and nesting depth) to enable fast duplicate detection across large projects

---

### E19. Import Report & Documentation Generation 📋 PLANNED

[TODO] The ImportCompletePanel shows basic stats but enterprise stakeholders (architects, product managers, compliance officers) need richer reports.

- [TODO] **Detailed Import Report**: Generate a comprehensive import report including: source details, timestamp, user, schema inventory, property inventory, relationship inventory, validation results, quality scores, and conflict resolutions applied
- [TODO] **PDF Export**: Export the import report as a formatted PDF document with the organization's branding (logo, colors)
- [TODO] **Shareable Report Link**: Generate a unique, read-only URL to the import report that can be shared with stakeholders who don't have Objectified access
- [TODO] **Changelog Generation**: Auto-generate a human-readable changelog from the import diff (e.g., "Added 3 new schemas: Order, Payment, Refund. Modified 2 schemas: User (added `phone` property), Product (changed `price` type from string to number).")
- [TODO] **Architecture Decision Record (ADR)**: Optionally generate an ADR template pre-filled with the import rationale, source, schema list, and conflict resolution decisions
- [TODO] **Report Annotations**: Allow users to annotate the import report with notes, decisions, and action items before sharing
- [TODO] **Report History**: Store all generated reports linked to the import history for future reference

---

### E20. Import Plugin / Extension System 📋 PLANNED

[TODO] The importer currently supports a fixed set of formats via built-in parsers. Enterprise organizations with proprietary spec formats or internal registries need the ability to add custom importers.

- [TODO] **Importer Plugin Interface**: Define a public TypeScript interface (`IImporter`) with methods for format detection, validation, normalization, and schema extraction that third-party plugins can implement
- [TODO] **Plugin Registry**: Admin UI to register, enable/disable, and configure custom importer plugins
- [TODO] **Plugin Sandboxing**: Execute custom importer plugins in an isolated context (Web Worker or server-side sandbox) to prevent security issues
- [TODO] **Built-In Plugin Templates**: Provide starter templates for common plugin patterns (REST API fetcher, file parser, database reverse-engineer)
- [TODO] **Plugin Marketplace**: A future community marketplace where organizations can publish and discover importer plugins
- [TODO] **Plugin Versioning**: Version plugins independently from the main application; support rollback to previous plugin versions
- [TODO] **Plugin Logging**: Dedicated log output for plugin execution visible in the import log for debugging

---

### E21. Import Localization & Multi-Language Support 📋 PLANNED

[TODO] Enterprise organizations operating globally may maintain API specifications with descriptions and documentation in multiple languages.

- [TODO] **Multi-Language Description Import**: When a spec contains `x-translations` or similar extensions with descriptions in multiple languages, import all language variants
- [TODO] **Primary Language Selection**: During import, select which language to use as the primary `description` field and store alternatives as metadata
- [TODO] **Right-to-Left (RTL) Support**: Properly handle and display RTL text (Arabic, Hebrew) in imported descriptions
- [TODO] **Character Encoding Detection**: Detect and properly handle non-UTF-8 encoded spec files (ISO-8859-1, Windows-1252, etc.)
- [TODO] **Translation Placeholder Injection**: Optionally inject translation placeholders (e.g., `{{t:description_key}}`) for schemas missing translations in the target language

---

### E22. Import Observability & Telemetry 📋 PLANNED

[TODO] Enterprise DevOps and platform teams need visibility into import system health, performance, and usage patterns across the organization.

- [TODO] **Import Metrics Dashboard**: Admin dashboard showing import volume over time, average duration, success/failure rates, most-used sources, and most-imported formats
- [TODO] **Performance Metrics**: Track and display p50/p95/p99 import durations by schema count, file size, and format
- [TODO] **Error Rate Monitoring**: Track import error rates with automatic alerting when error rates exceed a threshold
- [TODO] **Source Health Check**: For scheduled imports, monitor the health of configured sources (URL availability, Git repo accessibility) and alert on failures
- [TODO] **Usage Analytics**: Track which users and teams import most frequently, which sources are most popular, and which formats are most common
- [TODO] **Capacity Planning**: Provide recommendations on infrastructure scaling based on import volume trends

---

### E23. Database & SQL DDL Reverse-Engineering Import 📋 PLANNED

[TODO] Enterprise teams often need to create API schemas from existing database tables. Reverse-engineering a database schema into Objectified schemas eliminates manual re-creation.

- [TODO] **SQL DDL Import**: Parse `CREATE TABLE` statements from SQL DDL files (PostgreSQL, MySQL, SQL Server, Oracle, SQLite) and generate corresponding schemas
- [TODO] **Live Database Connection**: Connect to a live database via connection string, introspect the schema catalog, and import selected tables as schemas
- [TODO] **Foreign Key to Relationship Mapping**: Map database foreign key constraints to `$ref` relationships between schemas
- [TODO] **Index & Constraint Mapping**: Import `UNIQUE`, `NOT NULL`, `CHECK`, and `DEFAULT` constraints as JSON Schema validation rules (`uniqueItems`, `required`, `pattern`, `default`)
- [TODO] **DBML Import**: Parse DBML (Database Markup Language, used by dbdiagram.io) and generate schemas
- [TODO] **Prisma Schema Import**: Parse Prisma `.prisma` schema files and generate corresponding OpenAPI schemas
- [TODO] **TypeORM / Sequelize Model Import**: Parse TypeScript/JavaScript ORM model definitions and extract schemas
- [TODO] **Table Selection**: When importing from a database, show a table browser with search/filter and allow selecting which tables to import
- [TODO] **Column-to-Property Type Mapping**: Configurable mapping from database column types to JSON Schema types (e.g., `VARCHAR(255)` → `string` with `maxLength: 255`, `TIMESTAMP` → `string` with `format: date-time`)


#### 4.3 Pre-Import Analysis 📋 PLANNED

##### Compatibility Check
- [TODO] **Security Scheme Analysis**: Identify auth requirements
- [TODO] **Breaking Change Detection**: Compare with existing version

#### 4.4 Import Preview & Mapping 📋 PLANNED

##### Visual Preview
- [TODO] **Side-by-Side Comparison**: Compare with existing schemas
- [TODO] **Diff Highlighting**: Visual diff for updates

##### Schema Selection 📋 PARTIALLY IMPLEMENTED
- [TODO] **Category Grouping**: Group by tag, path, or custom criteria (will apply when path functionality is added)

#### 4.2 Supported Formats ✅ PARTIALLY IMPLEMENTED

##### JSON Schema
- [TODO] **JSON Schema Draft 2020-12**: Latest specification
- [TODO] **JSON Schema Draft 07**: Common enterprise format
- [TODO] **JSON Schema Draft 04**: Legacy support
- [TODO] **Bundled Schemas**: Multi-schema documents

##### Data Formats
- [TODO] **YAML**: Full YAML 1.2 support with anchors/aliases
- [TODO] **JSON**: Standard JSON with comments support (JSONC)
- [TODO] **JSON5**: Extended JSON format support

##### Conflict Report
- [TODO] **Resolution Recommendations**: AI-suggested resolutions
- [TODO] **Batch Resolution**: Apply same strategy to similar conflicts

#### 4.7 Post-Import Actions 📋 PLANNED

##### Follow-Up Actions 📋 PLANNED
- [TODO] **Generate Documentation**: Create docs from import
- [TODO] **Share Import Report**: Send summary to team
- [TODO] **Schedule Re-Import**: Set up recurring import
- [TODO] **Export Transformed**: Export in different format
