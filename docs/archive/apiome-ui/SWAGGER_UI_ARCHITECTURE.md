# Studio View Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Studio Header                            │
│  ┌────────────┐  ┌────────────┐  ┌────────────────────────┐    │
│  │  Project   │  │  Version   │  │  [Canvas][Code][Swagger]│    │
│  │  Selector  │  │  Selector  │  │   View Switcher        │    │
│  └────────────┘  └────────────┘  └────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                        Main Content Area                         │
│                                                                   │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────┐  │
│  │  Canvas View     │  │   Code View      │  │ Swagger View │  │
│  │  (ReactFlow)     │  │  (Monaco Editor) │  │ (Swagger UI) │  │
│  ├──────────────────┤  ├──────────────────┤  ├──────────────┤  │
│  │ • Class Nodes    │  │ • JSON Format    │  │ • Endpoints  │  │
│  │ • Relationships  │  │ • YAML Format    │  │ • Schemas    │  │
│  │ • Drag & Drop    │  │ • Syntax Highlight│  │ • Try It Out │  │
│  │ • Auto-Layout    │  │ • Read-only      │  │ • Filter     │  │
│  │ • Edit Dialogs   │  │ • Copy/Export    │  │ • Copy/Export│  │
│  └──────────────────┘  └──────────────────┘  └──────────────┘  │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

## Data Flow

```
┌─────────────────┐
│  User Actions   │
│  (Select        │
│   Project/      │
│   Version)      │
└────────┬────────┘
         │
         ▼
┌─────────────────────┐
│ Load Classes &      │
│ Properties from DB  │
└────────┬────────────┘
         │
         ▼
┌──────────────────────────┐
│ generateOpenApiSpec()    │
│ (OpenAPI 3.1.0)          │
└────────┬─────────────────┘
         │
         ├──────────────┬──────────────┐
         ▼              ▼              ▼
┌─────────────┐  ┌──────────┐  ┌──────────────┐
│ Canvas View │  │Code View │  │ Swagger View │
│ (Visual)    │  │(Text)    │  │(Interactive) │
└─────────────┘  └──────────┘  └──────────────┘
```

## Component Structure

```
Studio (ReactFlowProvider wrapper)
└── StudioContent
    ├── Header Section
    │   ├── Project Selector
    │   ├── Version Selector
    │   └── View Switcher [Canvas|Code|Swagger]
    │
    └── Main Content (Conditional Rendering)
        │
        ├── Empty State
        │   └── "No Project Selected" message
        │
        ├── Canvas View (viewMode === 'canvas')
        │   ├── ReactFlow Component
        │   │   ├── ClassNodes[]
        │   │   ├── Edges[]
        │   │   ├── Background
        │   │   ├── Controls
        │   │   ├── MiniMap
        │   │   └── Panels (Layout, Read-Only)
        │   └── Dialogs
        │       ├── ClassEditDialog
        │       └── ClassPropertyEditDialog
        │
        ├── Code View (viewMode === 'code')
        │   ├── Header
        │   │   ├── Title & Description
        │   │   ├── Format Toggle [JSON|YAML]
        │   │   └── Actions [Copy|Export]
        │   └── Monaco Editor
        │       └── OpenAPI Spec (read-only)
        │
        └── Swagger View (viewMode === 'swagger') ✨ NEW
            ├── Header
            │   ├── Title & Description
            │   └── Actions [Copy Spec|Export Spec]
            └── SwaggerUI Component
                ├── spec={openApiSpec}
                ├── docExpansion="list"
                ├── filter={true}
                └── tryItOutEnabled={true}
```

## View Modes Comparison

```
┌──────────────┬─────────────────┬──────────────────┬─────────────────┐
│   Feature    │   Canvas View   │    Code View     │  Swagger View   │
├──────────────┼─────────────────┼──────────────────┼─────────────────┤
│ Library      │ @xyflow/react   │ monaco-editor    │ swagger-ui-react│
│ Format       │ Visual Diagram  │ JSON/YAML Text   │ Interactive UI  │
│ Editing      │ Yes (dialogs)   │ No (read-only)   │ No (view-only)  │
│ Auto-Layout  │ Yes (4 modes)   │ N/A              │ N/A             │
│ Copy/Export  │ No              │ Yes              │ Yes             │
│ Testing      │ No              │ No               │ Yes (Try it out)│
│ Search       │ No              │ Editor search    │ Yes (filter)    │
│ Dark Mode    │ Yes             │ Yes              │ Default theme   │
│ SSR Safe     │ Yes             │ No (dynamic)     │ No (dynamic)    │
└──────────────┴─────────────────┴──────────────────┴─────────────────┘
```

## State Management

```
StudioContent Component State:
┌────────────────────────────────┐
│ • projects[]                   │
│ • versions[]                   │
│ • selectedProjectId            │
│ • selectedVersionId            │
│ • viewMode: 'canvas'|'code'|'swagger' ✨
│ • codeFormat: 'json'|'yaml'    │
│ • openApiSpec: string          │
│ • nodes[] (ReactFlow)          │
│ • edges[] (ReactFlow)          │
│ • layoutDirection              │
│ • editPropertyDialogOpen       │
│ • classEditDialogOpen          │
│ • editingClassData             │
│ • editingClassProperty         │
│ • isReadOnly                   │
└────────────────────────────────┘
```

## Conditional Rendering Logic

```typescript
{!selectedProjectId || !selectedVersionId ? (
  // No selection - Show empty state
  <EmptyState />
  
) : viewMode === 'canvas' ? (
  // Canvas mode - Show ReactFlow diagram
  <ReactFlow>
    <ClassNodes />
    <Edges />
    <Controls />
  </ReactFlow>
  
) : viewMode === 'code' ? (
  // Code mode - Show Monaco editor
  <MonacoEditor
    value={openApiSpec}
    language={codeFormat}
    readOnly
  />
  
) : (
  // Swagger mode - Show Swagger UI ✨
  <SwaggerUI
    spec={JSON.parse(openApiSpec)}
    tryItOutEnabled={true}
  />
)}
```

## Integration Points

```
┌─────────────────────────────────────────────────────────┐
│                    Studio Context                        │
│  • selectedProjectId                                     │
│  • selectedVersionId                                     │
│  • canvasRefreshKey                                      │
│  • isReadOnly                                            │
│  • triggerSidebarRefresh()                               │
└─────────────────────┬───────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────┐
│                 Database Helpers                         │
│  • getProjectsForTenant()                                │
│  • getVersionsForProject()                               │
│  • getClassesForVersion()                                │
│  • getPropertiesForClass()                               │
└─────────────────────┬───────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────┐
│              OpenAPI Generator Utility                   │
│  • generateOpenApiSpec(classes, options)                 │
│  • Returns: JSON string of OpenAPI 3.1.0 spec            │
└─────────────────────┬───────────────────────────────────┘
                      │
                      ├────────┬────────┬────────┐
                      ▼        ▼        ▼        
              Canvas View  Code View  Swagger View ✨
```

## File Imports

```typescript
// React & Next.js
import { useCallback, useState, useEffect } from 'react'
import { useSession } from 'next-auth/react'
import dynamic from 'next/dynamic'

// Icons & Utilities
import { Copy, Download } from 'lucide-react'
import YAML from 'yaml'

// Components
import ClassEditDialog from '../../components/ade/studio/ClassEditDialog'
import ClassPropertyEditDialog from '../../components/ade/studio/ClassPropertyEditDialog'
import ClassNode from '../../components/ade/studio/ClassNode'

// Utilities
import { generateOpenApiSpec } from '../../utils/openapi'
import { getLayoutedElements } from './layoutUtils'

// Context
import { useStudio } from './StudioContext'

// React Flow
import { ReactFlow, ... } from '@xyflow/react'
import '@xyflow/react/dist/style.css'

// Swagger UI ✨
import 'swagger-ui-react/swagger-ui.css'

// Dynamic Imports
const Editor = dynamic(() => import('@monaco-editor/react'), { ssr: false })
const SwaggerUI = dynamic(() => import('swagger-ui-react'), { ssr: false }) ✨
```

## Legend
✨ = New addition for Swagger UI integration
