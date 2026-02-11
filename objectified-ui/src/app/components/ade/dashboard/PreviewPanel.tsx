'use client';

import { useState, useEffect, useMemo } from 'react';
import { Package, Search, Check, ChevronRight, ChevronDown, ArrowUpAZ, ArrowDownAZ, LayoutGrid, Network, FolderTree } from 'lucide-react';
import * as Checkbox from '@radix-ui/react-checkbox';
import { AnalysisResult } from '../../../utils/openapi-analyzer';
import { buildSchemaTree, buildRelationshipDiagramEdges, extractSchemaReferences, getSchemaType, getSchemaTags, type SchemaTreeNode, type SchemaDisplayType } from '../../../utils/schema-tree-utils';
import { generateSlug } from '../../../utils/slug';
import YAML from 'yaml';
import Editor from '@monaco-editor/react';
import {
  ReactFlow,
  ReactFlowProvider,
  Background,
  Controls,
  MiniMap,
  Handle,
  Position,
  type Node,
  type Edge,
  MarkerType,
  BackgroundVariant,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '../../ui/Collapsible';

interface PreviewPanelProps {
  analysis: AnalysisResult;
  onImportOptionsChange?: (options: ImportOptions) => void;
}

export interface ImportOptions {
  projectName: string;
  projectSlug: string;
  versionSource: 'spec' | 'manual';
  targetVersion: string;
  selectedSchemas: string[];
  /** When true, preview changes without committing (dry run). */
  dryRun?: boolean;
  /** When true, import all available and skip failures (each class committed separately). */
  incrementalMode?: boolean;
}

interface SchemaInfo {
  name: string;
  properties: number;
  selected: boolean;
  required: boolean;
  schemaType: SchemaDisplayType;
  tags: string[];
}

const MAX_ENUM_DISPLAY = 4;

// Helper function to count properties including those from allOf/oneOf/anyOf
function countSchemaProperties(schema: any): number {
  let count = 0;

  // Count direct properties
  if (schema.properties) {
    count += Object.keys(schema.properties).length;
  }

  // Count properties from allOf (inheritance - all schemas apply)
  if (schema.allOf && Array.isArray(schema.allOf)) {
    schema.allOf.forEach((item: any) => {
      if (item.properties) {
        count += Object.keys(item.properties).length;
      }
    });
  }

  // Count properties from oneOf (variants - show max from any variant)
  if (schema.oneOf && Array.isArray(schema.oneOf)) {
    let maxOneOf = 0;
    schema.oneOf.forEach((item: any) => {
      if (item.properties) {
        maxOneOf = Math.max(maxOneOf, Object.keys(item.properties).length);
      }
    });
    count += maxOneOf;
  }

  // Count properties from anyOf (flexible - show max from any option)
  if (schema.anyOf && Array.isArray(schema.anyOf)) {
    let maxAnyOf = 0;
    schema.anyOf.forEach((item: any) => {
      if (item.properties) {
        maxAnyOf = Math.max(maxAnyOf, Object.keys(item.properties).length);
      }
    });
    count += maxAnyOf;
  }

  return count;
}

// Simple preview node component for the chart view
function PreviewClassNode({ data }: { data: { label: string; propertyCount: number; selected: boolean; hasComposition?: boolean; compositionType?: string } }) {
  return (
    <div className={`bg-white dark:bg-gray-800 rounded-lg shadow-md border-2 min-w-[120px] max-w-[180px] ${
      data.selected 
        ? 'border-indigo-400 dark:border-indigo-500' 
        : 'border-gray-300 dark:border-gray-600 opacity-50'
    }`}>
      <Handle type="target" position={Position.Top} className="w-2 h-2 !bg-indigo-500" />
      <Handle type="target" position={Position.Left} className="w-2 h-2 !bg-indigo-500" />

      <div className={`px-3 py-2 border-b border-gray-200 dark:border-gray-600 rounded-t-lg ${
        data.hasComposition 
          ? 'bg-purple-50 dark:bg-purple-900/30' 
          : 'bg-indigo-50 dark:bg-indigo-900/30'
      }`}>
        <div className="flex items-center gap-1.5">
          {data.hasComposition && data.compositionType && (
            <span className="text-[9px] px-1 py-0.5 bg-purple-200 dark:bg-purple-800 text-purple-700 dark:text-purple-300 rounded">
              {data.compositionType}
            </span>
          )}
          <span className="text-xs font-semibold text-gray-800 dark:text-gray-200 truncate">
            {data.label}
          </span>
        </div>
      </div>
      <div className="px-3 py-2">
        <div className="text-[10px] text-gray-500 dark:text-gray-400">
          {data.propertyCount} {data.propertyCount === 1 ? 'property' : 'properties'}
        </div>
      </div>

      <Handle type="source" position={Position.Right} className="w-2 h-2 !bg-indigo-500" />
      <Handle type="source" position={Position.Bottom} className="w-2 h-2 !bg-indigo-500" />
    </div>
  );
}

const previewNodeTypes = {
  previewClass: PreviewClassNode,
};

// Re-export for consumers that import from PreviewPanel
export type { SchemaTreeNode } from '../../../utils/schema-tree-utils';

// Get composition type if any
function getCompositionType(schema: any): string | null {
  if (schema.allOf) return 'allOf';
  if (schema.oneOf) return 'oneOf';
  if (schema.anyOf) return 'anyOf';
  return null;
}

// Expandable property row for import preview (#577)
function ExpandablePropertyRow({
  propName,
  propValue,
  isRequired,
  getPropertyType,
  expandKey,
  isExpanded,
  onOpenChange,
  accentClass = 'text-indigo-600 dark:text-indigo-400',
}: {
  propName: string;
  propValue: any;
  isRequired: boolean;
  getPropertyType: (prop: any) => string;
  expandKey: string;
  isExpanded: boolean;
  onOpenChange: (open: boolean) => void;
  accentClass?: string;
}) {
  const hasAny =
    propValue?.description ||
    propValue?.format ||
    propValue?.default !== undefined ||
    propValue?.example !== undefined ||
    (Array.isArray(propValue?.enum) && propValue.enum.length > 0) ||
    propValue?.nullable === true ||
    propValue?.minimum !== undefined ||
    propValue?.maximum !== undefined ||
    propValue?.minLength !== undefined ||
    propValue?.maxLength !== undefined ||
    propValue?.pattern;

  return (
    <Collapsible
      open={isExpanded}
      onOpenChange={onOpenChange}
    >
      <div className="text-sm group">
        <CollapsibleTrigger asChild>
          <button
            type="button"
            className="flex items-center gap-2 w-full text-left rounded px-1 -mx-1 hover:bg-gray-100 dark:hover:bg-gray-700/50"
          >
            {hasAny ? (
              isExpanded ? (
                <ChevronDown className="h-4 w-4 text-gray-500 dark:text-gray-400 flex-shrink-0" />
              ) : (
                <ChevronRight className="h-4 w-4 text-gray-500 dark:text-gray-400 flex-shrink-0" />
              )
            ) : (
              <span className="w-4 inline-block flex-shrink-0" aria-hidden />
            )}
            <span className={`font-mono ${accentClass}`}>{propName}</span>
            <span className="text-gray-500 dark:text-gray-400">: </span>
            <span className="text-gray-700 dark:text-gray-300">
              {getPropertyType(propValue)}
            </span>
            {isRequired && (
              <span className="ml-2 text-xs text-red-600 dark:text-red-400 font-medium">
                (required)
              </span>
            )}
          </button>
        </CollapsibleTrigger>
        <CollapsibleContent>
          {hasAny && (
            <div className="ml-6 mt-1 mb-2 pl-3 border-l border-gray-200 dark:border-gray-600 space-y-1.5 text-xs text-gray-600 dark:text-gray-400">
              {propValue?.description && (
                <div>
                  <span className="font-medium text-gray-500 dark:text-gray-500">Description: </span>
                  {propValue.description}
                </div>
              )}
              {propValue?.format && (
                <div>
                  <span className="font-medium text-gray-500 dark:text-gray-500">Format: </span>
                  <span className="font-mono">{propValue.format}</span>
                </div>
              )}
              {propValue?.default !== undefined && (
                <div>
                  <span className="font-medium text-gray-500 dark:text-gray-500">Default: </span>
                  <span className="font-mono">
                    {typeof propValue.default === 'object'
                      ? JSON.stringify(propValue.default)
                      : String(propValue.default)}
                  </span>
                </div>
              )}
              {propValue?.example !== undefined && (
                <div>
                  <span className="font-medium text-gray-500 dark:text-gray-500">Example: </span>
                  <span className="font-mono">
                    {typeof propValue.example === 'object'
                      ? JSON.stringify(propValue.example)
                      : String(propValue.example)}
                  </span>
                </div>
              )}
              {Array.isArray(propValue?.enum) && propValue.enum.length > 0 && (
                <div>
                  <span className="font-medium text-gray-500 dark:text-gray-500">Enum: </span>
                  <span className="font-mono">
                    {propValue.enum.map((v: unknown) => (typeof v === 'string' ? `"${v}"` : String(v))).join(', ')}
                  </span>
                </div>
              )}
              {propValue?.nullable === true && (
                <div>
                  <span className="font-medium text-gray-500 dark:text-gray-500">Nullable: </span>
                  true
                </div>
              )}
              {(propValue?.minimum !== undefined || propValue?.maximum !== undefined) && (
                <div>
                  <span className="font-medium text-gray-500 dark:text-gray-500">Range: </span>
                  {propValue.minimum !== undefined && (
                    <span className="font-mono">min {propValue.minimum}</span>
                  )}
                  {propValue.minimum !== undefined && propValue.maximum !== undefined && ' \u2013 '}
                  {propValue.maximum !== undefined && (
                    <span className="font-mono">max {propValue.maximum}</span>
                  )}
                </div>
              )}
              {(propValue?.minLength !== undefined || propValue?.maxLength !== undefined) && (
                <div>
                  <span className="font-medium text-gray-500 dark:text-gray-500">Length: </span>
                  <span className="font-mono">
                    {propValue.minLength ?? 0} \u2013 {propValue.maxLength ?? '\u221E'}
                  </span>
                </div>
              )}
              {propValue?.pattern && (
                <div>
                  <span className="font-medium text-gray-500 dark:text-gray-500">Pattern: </span>
                  <span className="font-mono break-all">{propValue.pattern}</span>
                </div>
              )}
            </div>
          )}
        </CollapsibleContent>
      </div>
    </Collapsible>
  );
}

// Single tree node for hierarchical schema view
function SchemaTreeItem({
  node,
  depth,
  parentKey,
  expandedSchemaNames,
  onToggleExpand,
  getSchemaInfo,
  onToggleSchema,
  onSelectSchema,
  selectedSchemaName,
}: {
  node: SchemaTreeNode;
  depth: number;
  parentKey: string;
  expandedSchemaNames: string[];
  onToggleExpand: (name: string) => void;
  getSchemaInfo: (name: string) => SchemaInfo | undefined;
  onToggleSchema: (name: string) => void;
  onSelectSchema: (name: string | null) => void;
  selectedSchemaName: string | null;
}) {
  const schemaInfo = getSchemaInfo(node.name);
  const hasChildren = node.children.length > 0;
  const isExpanded = expandedSchemaNames.includes(node.name);
  const isSelected = selectedSchemaName === node.name;
  const paddingLeft = depth * 16 + 12;

  return (
    <div className="space-y-0.5">
      <div
        className={`flex items-center gap-2 rounded-lg cursor-pointer transition-colors ${
          isSelected
            ? 'bg-indigo-50 dark:bg-indigo-900/20 border border-indigo-200 dark:border-indigo-800'
            : 'hover:bg-gray-50 dark:hover:bg-gray-700/50'
        }`}
        style={{ paddingLeft: `${paddingLeft}px`, paddingRight: 12, paddingTop: 8, paddingBottom: 8 }}
        onClick={() => onSelectSchema(node.name)}
      >
        <div className="flex items-center gap-1 flex-shrink-0 w-5">
          {hasChildren ? (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onToggleExpand(node.name);
              }}
              className="p-0.5 rounded hover:bg-gray-200 dark:hover:bg-gray-600 text-gray-600 dark:text-gray-400"
              aria-label={isExpanded ? 'Collapse' : 'Expand'}
            >
              {isExpanded ? (
                <ChevronDown className="h-4 w-4" />
              ) : (
                <ChevronRight className="h-4 w-4" />
              )}
            </button>
          ) : (
            <span className="w-4 inline-block" aria-hidden />
          )}
        </div>
        <Checkbox.Root
          checked={schemaInfo?.selected ?? false}
          onCheckedChange={() => onToggleSchema(node.name)}
          onClick={(e) => e.stopPropagation()}
          className="w-5 h-5 rounded border-2 border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 data-[state=checked]:bg-indigo-600 data-[state=checked]:border-indigo-600 flex items-center justify-center flex-shrink-0"
        >
          <Checkbox.Indicator>
            <Check className="w-4 h-4 text-white" />
          </Checkbox.Indicator>
        </Checkbox.Root>
        <Package className="h-4 w-4 text-indigo-600 dark:text-indigo-400 flex-shrink-0" />
        <div className="flex-1 min-w-0">
          <div className="font-medium text-gray-900 dark:text-white truncate text-sm">
            {node.name}
          </div>
          <div className="text-xs text-gray-500 dark:text-gray-400">
            {schemaInfo != null ? `${schemaInfo.properties} properties` : ''}
          </div>
        </div>
      </div>
      {hasChildren && (
        <Collapsible open={isExpanded}>
          <CollapsibleContent>
            {node.children.map((child, idx) => (
              <SchemaTreeItem
                key={`${parentKey}-${child.name}-${idx}`}
                node={child}
                depth={depth + 1}
                parentKey={`${parentKey}-${node.name}-${idx}`}
                expandedSchemaNames={expandedSchemaNames}
                onToggleExpand={onToggleExpand}
                getSchemaInfo={getSchemaInfo}
                onToggleSchema={onToggleSchema}
                onSelectSchema={onSelectSchema}
                selectedSchemaName={selectedSchemaName}
              />
            ))}
          </CollapsibleContent>
        </Collapsible>
      )}
    </div>
  );
}

export function PreviewPanel({ analysis, onImportOptionsChange }: PreviewPanelProps) {
  const [searchFilter, setSearchFilter] = useState('');
  const [filterType, setFilterType] = useState<SchemaDisplayType | ''>('');
  const [filterTag, setFilterTag] = useState<string>('');
  const [selectedSchemaName, setSelectedSchemaName] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<'summary' | 'json' | 'yaml'>('summary');
  const [panelView, setPanelView] = useState<'list' | 'chart' | 'tree'>('list');
  const [expandedSchemaNames, setExpandedSchemaNames] = useState<string[]>([]);
  const [expandedPropertyKeys, setExpandedPropertyKeys] = useState<Set<string>>(new Set());
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc' | null>(null);
  const [schemas, setSchemas] = useState<SchemaInfo[]>(() => {
    const schemaObj = analysis.document?.components?.schemas || analysis.document?.definitions || {};
    return Object.keys(schemaObj).map((name) => {
      const raw = schemaObj[name];
      return {
        name,
        properties: countSchemaProperties(raw),
        selected: true,
        required: false,
        schemaType: getSchemaType(raw),
        tags: getSchemaTags(raw),
      };
    });
  });

  const [importOptions, setImportOptions] = useState<ImportOptions>(() => {
    const title = analysis.document?.info?.title || 'New Project';
    return {
      projectName: title,
      projectSlug: generateSlug(title) || 'new-project',
      versionSource: 'spec',
      targetVersion: analysis.document?.info?.version || '1.0.0',
      selectedSchemas: schemas.map(s => s.name),
      dryRun: false
    };
  });

  // Track if user has manually edited the slug
  const [slugManuallyEdited, setSlugManuallyEdited] = useState(false);

  // Notify parent of initial import options on mount
  useEffect(() => {
    if (onImportOptionsChange) {
      onImportOptionsChange(importOptions);
    }
  }, []); // Empty dependency array - run only on mount


  const selectedSchema = selectedSchemaName
    ? (analysis.document?.components?.schemas?.[selectedSchemaName] ||
       analysis.document?.definitions?.[selectedSchemaName])
    : null;

  const allTags = Array.from(new Set(schemas.flatMap((s) => s.tags))).sort();

  const filteredSchemas = schemas
    .filter((schema) => {
      const matchesName = schema.name.toLowerCase().includes(searchFilter.toLowerCase());
      const matchesType = !filterType || schema.schemaType === filterType;
      const matchesTag = !filterTag || schema.tags.includes(filterTag);
      return matchesName && matchesType && matchesTag;
    })
    .sort((a, b) => {
      if (sortOrder === 'asc') return a.name.localeCompare(b.name);
      if (sortOrder === 'desc') return b.name.localeCompare(a.name);
      return 0; // Keep original order if no sort applied
    });

  const selectedCount = schemas.filter(s => s.selected).length;

  const schemaObj = analysis.document?.components?.schemas || analysis.document?.definitions || {};

  // Hierarchical tree for Tree View (#576): filter roots by name, type, tags (#580)
  const schemaTreeRoots = useMemo(() => {
    const allSchemaNames = Object.keys(schemaObj);
    const hasFilter = searchFilter.trim() || filterType || filterTag;
    const nameFilter = hasFilter
      ? (name: string) => {
          const info = schemas.find((s) => s.name === name);
          if (!info) return true;
          const matchesName = !searchFilter.trim() || name.toLowerCase().includes(searchFilter.toLowerCase());
          const matchesType = !filterType || info.schemaType === filterType;
          const matchesTag = !filterTag || info.tags.includes(filterTag);
          return matchesName && matchesType && matchesTag;
        }
      : undefined;
    return buildSchemaTree(schemaObj, allSchemaNames, nameFilter);
  }, [analysis.document, searchFilter, filterType, filterTag, schemas]);

  const toggleExpanded = (name: string) => {
    setExpandedSchemaNames((prev) =>
      prev.includes(name) ? prev.filter((n) => n !== name) : [...prev, name]
    );
  };

  const getSchemaInfo = (name: string): SchemaInfo | undefined =>
    schemas.find((s) => s.name === name);

  // Generate nodes and edges for the relationship diagram (#578) – use filtered schemas and edge labels
  const { chartNodes, chartEdges } = useMemo(() => {
    const schemaObj = analysis.document?.components?.schemas || analysis.document?.definitions || {};
    const allSchemaNames = Object.keys(schemaObj);
    const schemaNames = filteredSchemas.map((s) => s.name);

    if (schemaNames.length === 0) {
      return { chartNodes: [], chartEdges: [] };
    }

    const selectionMap = new Map(schemas.map((s) => [s.name, s.selected]));

    const cols = Math.ceil(Math.sqrt(schemaNames.length));
    const nodeWidth = 160;
    const nodeHeight = 80;
    const gapX = 80;
    const gapY = 60;

    const nodes: Node[] = schemaNames.map((name, index) => {
      const row = Math.floor(index / cols);
      const col = index % cols;
      const schema = schemaObj[name];
      const compositionType = getCompositionType(schema);

      return {
        id: name,
        type: 'previewClass',
        position: {
          x: col * (nodeWidth + gapX) + 50,
          y: row * (nodeHeight + gapY) + 50,
        },
        data: {
          label: name,
          propertyCount: countSchemaProperties(schema),
          selected: selectionMap.get(name) ?? true,
          hasComposition: !!compositionType,
          compositionType: compositionType,
        },
      };
    });

    // Build edges from $ref relationships with property labels (#578) via shared util
    const diagramEdges = buildRelationshipDiagramEdges(schemaObj, schemaNames);
    const edges: Edge[] = diagramEdges.map(({ source, target, label }) => ({
      id: `${source}-${target}`,
      source,
      target,
      type: 'smoothstep',
      animated: false,
      label,
      labelStyle: { fill: '#4338ca', fontSize: 10, fontWeight: 500 },
      labelBgStyle: { fill: 'white', fillOpacity: 0.9 },
      labelBgPadding: [4, 2] as [number, number],
      labelBgBorderRadius: 4,
      style: { stroke: '#6366f1', strokeWidth: 1.5 },
      markerEnd: {
        type: MarkerType.ArrowClosed,
        color: '#6366f1',
        width: 15,
        height: 15,
      },
    }));

    return { chartNodes: nodes, chartEdges: edges };
  }, [analysis.document, schemas, filteredSchemas]);

  const handleSelectAll = () => {
    const newSchemas = schemas.map(s => ({ ...s, selected: true }));
    setSchemas(newSchemas);
    updateSelectedSchemas(newSchemas);
  };

  const handleSelectNone = () => {
    const newSchemas = schemas.map(s => ({ ...s, selected: s.required }));
    setSchemas(newSchemas);
    updateSelectedSchemas(newSchemas);
  };

  const handlePropertyExpand = (expandKey: string, open: boolean) => {
    setExpandedPropertyKeys((prev) => {
      const next = new Set(prev);
      if (open) next.add(expandKey);
      else next.delete(expandKey);
      return next;
    });
  };

  const handleToggleSchema = (name: string) => {
    const newSchemas = schemas.map(s =>
      s.name === name ? { ...s, selected: !s.selected } : s
    );
    setSchemas(newSchemas);
    updateSelectedSchemas(newSchemas);
  };

  const updateSelectedSchemas = (schemaList: SchemaInfo[]) => {
    const selected = schemaList.filter(s => s.selected).map(s => s.name);
    const newOptions = { ...importOptions, selectedSchemas: selected };
    setImportOptions(newOptions);
    onImportOptionsChange?.(newOptions);
  };

  const handleOptionChange = (key: keyof ImportOptions, value: any) => {
    let newOptions = { ...importOptions, [key]: value };

    // Auto-update slug when project name changes (if not manually edited)
    if (key === 'projectName' && !slugManuallyEdited) {
      newOptions.projectSlug = generateSlug(value) || 'new-project';
    }

    setImportOptions(newOptions);
    onImportOptionsChange?.(newOptions);
  };

  const handleSlugChange = (value: string) => {
    // Filter to only allow valid slug characters
    const sanitized = value.toLowerCase().replace(/[^a-z0-9-]/g, '');
    setSlugManuallyEdited(true);
    const newOptions = { ...importOptions, projectSlug: sanitized };
    setImportOptions(newOptions);
    onImportOptionsChange?.(newOptions);
  };

  const handleVersionSourceChange = (source: 'spec' | 'manual') => {
    const specVersion = analysis.document?.info?.version || '1.0.0';
    const newOptions = {
      ...importOptions,
      versionSource: source,
      targetVersion: source === 'spec' ? specVersion : ''
    };
    setImportOptions(newOptions);
    onImportOptionsChange?.(newOptions);
  };

  const handleVersionChange = (version: string) => {
    // Only allow: 0-9, A-Z, a-z, ., -
    const sanitized = version.replace(/[^0-9A-Za-z.\-]/g, '');
    const newOptions = { ...importOptions, targetVersion: sanitized };
    setImportOptions(newOptions);
    onImportOptionsChange?.(newOptions);
  };

  const getPropertyType = (prop: any): string => {
    if (prop.$ref) {
      const refName = prop.$ref.split('/').pop();
      return `$ref → ${refName}`;
    }

    if (prop.type === 'array') {
      if (prop.items?.$ref) {
        const refName = prop.items.$ref.split('/').pop();
        return `array<$ref → ${refName}>`;
      }
      return `array<${prop.items?.type || 'any'}>`;
    }

    if (prop.enum) {
      const enumValues = prop.enum.slice(0, MAX_ENUM_DISPLAY).join(', ');
      const remaining = prop.enum.length - MAX_ENUM_DISPLAY;

      if (remaining > 0) {
        return `enum (${enumValues}, ... ${remaining} more)`;
      }

      return `enum (${enumValues})`;
    }
    return prop.type || 'any';
  };

  return (
    <div className="space-y-6">
      {/* View Mode Tabs and Schema Selection Controls */}
      <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
        <div className="flex items-center justify-between flex-wrap gap-4">
          {/* View Mode Tabs */}
          <div className="flex items-center gap-2 bg-gray-100 dark:bg-gray-700 rounded-lg p-1">
            <button
              onClick={() => setPanelView('list')}
              className={`flex items-center gap-2 px-3 py-1.5 text-sm font-medium rounded-md transition-colors ${
                panelView === 'list'
                  ? 'bg-white dark:bg-gray-600 text-indigo-600 dark:text-indigo-400 shadow-sm'
                  : 'text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white'
              }`}
            >
              <LayoutGrid className="h-4 w-4" />
              List View
            </button>
            <button
              onClick={() => setPanelView('chart')}
              className={`flex items-center gap-2 px-3 py-1.5 text-sm font-medium rounded-md transition-colors ${
                panelView === 'chart'
                  ? 'bg-white dark:bg-gray-600 text-indigo-600 dark:text-indigo-400 shadow-sm'
                  : 'text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white'
              }`}
            >
              <Network className="h-4 w-4" />
              Relationship Diagram
            </button>
            <button
              onClick={() => setPanelView('tree')}
              className={`flex items-center gap-2 px-3 py-1.5 text-sm font-medium rounded-md transition-colors ${
                panelView === 'tree'
                  ? 'bg-white dark:bg-gray-600 text-indigo-600 dark:text-indigo-400 shadow-sm'
                  : 'text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white'
              }`}
            >
              <FolderTree className="h-4 w-4" />
              Tree View
            </button>
          </div>

          {/* Selection Controls - show in list and tree view */}
          {(panelView === 'list' || panelView === 'tree') && (
            <div className="flex items-center gap-2">
              <button
                onClick={handleSelectAll}
                className="px-3 py-1.5 text-sm font-medium text-indigo-600 dark:text-indigo-400 hover:bg-indigo-50 dark:hover:bg-indigo-900/20 rounded-lg transition-colors"
              >
                Select All
              </button>
              <button
                onClick={handleSelectNone}
                className="px-3 py-1.5 text-sm font-medium text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg transition-colors"
              >
                Select None
              </button>
              <span className="text-sm text-gray-500 dark:text-gray-400">
                {selectedCount} of {schemas.length} selected
              </span>
            </div>
          )}

          {/* Search and filter by name, type, tags (#580) */}
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative flex-1 min-w-[140px]">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
              <input
                type="text"
                placeholder="Search by name..."
                value={searchFilter}
                onChange={(e) => setSearchFilter(e.target.value)}
                className="w-full pl-9 pr-4 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white placeholder-gray-400 focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
              />
            </div>
            <select
              value={filterType}
              onChange={(e) => setFilterType((e.target.value || '') as SchemaDisplayType | '')}
              className="py-2 pl-3 pr-8 text-sm border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
              title="Filter by type"
            >
              <option value="">All types</option>
              <option value="object">object</option>
              <option value="array">array</option>
              <option value="allOf">allOf</option>
              <option value="oneOf">oneOf</option>
              <option value="anyOf">anyOf</option>
              <option value="enum">enum</option>
              <option value="string">string</option>
              <option value="number">number</option>
              <option value="integer">integer</option>
              <option value="boolean">boolean</option>
              <option value="null">null</option>
              <option value="unknown">unknown</option>
            </select>
            <select
              value={filterTag}
              onChange={(e) => setFilterTag(e.target.value)}
              className="py-2 pl-3 pr-8 text-sm border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
              title="Filter by tag"
            >
              <option value="">All tags</option>
              {allTags.map((tag) => (
                <option key={tag} value={tag}>
                  {tag}
                </option>
              ))}
            </select>
          </div>

          {/* Schema count - always visible */}
          <span className="text-sm text-gray-500 dark:text-gray-400">
            {selectedCount} of {schemas.length} schemas selected
          </span>
        </div>
      </div>

      {/* Relationship Diagram (#578) */}
      {panelView === 'chart' && (
        <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
          <div className="border-b border-gray-200 dark:border-gray-700 p-4">
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
              Relationship Diagram
            </h3>
            <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
              Preview of schema relationships. Arrows show references; labels show the property or &quot;items&quot;. Filter by search, type, or tag above.
            </p>
          </div>
          <div className="h-[500px]">
            <ReactFlowProvider>
              <ReactFlow
                nodes={chartNodes}
                edges={chartEdges}
                nodeTypes={previewNodeTypes}
                fitView
                fitViewOptions={{ padding: 0.2 }}
                nodesDraggable={true}
                nodesConnectable={false}
                elementsSelectable={true}
                minZoom={0.2}
                maxZoom={2}
                proOptions={{ hideAttribution: true }}
              >
                <Background variant={BackgroundVariant.Dots} gap={20} size={1} />
                <Controls showInteractive={false} />
                <MiniMap
                  nodeColor={(node) => node.data?.selected ? '#6366f1' : '#9ca3af'}
                  maskColor="rgba(0, 0, 0, 0.1)"
                  className="bg-gray-100 dark:bg-gray-700"
                />
              </ReactFlow>
            </ReactFlowProvider>
          </div>
        </div>
      )}

      {/* List View and Tree View - Schema Selection and Preview */}
      {(panelView === 'list' || panelView === 'tree') && (
      <div className="grid grid-cols-3 gap-6">
        {/* Left: Schema List or Tree - 1/3 width */}
        <div className="col-span-1 bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700">
          <div className="border-b border-gray-200 dark:border-gray-700 p-4">
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                {panelView === 'tree' ? 'Schema Tree' : 'Schemas to Import'}
              </h3>
              {panelView === 'list' && (
                <div className="flex items-center gap-1">
                  <button
                    onClick={() => setSortOrder(sortOrder === 'asc' ? null : 'asc')}
                    className={`p-1.5 rounded transition-colors ${
                      sortOrder === 'asc'
                        ? 'bg-indigo-100 dark:bg-indigo-900/30 text-indigo-600 dark:text-indigo-400'
                        : 'text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700'
                    }`}
                    title="Sort A → Z"
                  >
                    <ArrowUpAZ className="h-4 w-4" />
                  </button>
                  <button
                    onClick={() => setSortOrder(sortOrder === 'desc' ? null : 'desc')}
                    className={`p-1.5 rounded transition-colors ${
                      sortOrder === 'desc'
                        ? 'bg-indigo-100 dark:bg-indigo-900/30 text-indigo-600 dark:text-indigo-400'
                        : 'text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700'
                    }`}
                    title="Sort Z → A"
                  >
                    <ArrowDownAZ className="h-4 w-4" />
                  </button>
                </div>
              )}
            </div>
            {panelView === 'tree' && (
              <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                Expand schemas to see referenced types ($ref)
              </p>
            )}
          </div>
          <div className="p-4 space-y-2 max-h-[400px] overflow-y-auto">
            {panelView === 'list' &&
              filteredSchemas.map((schema) => (
                <div
                  key={schema.name}
                  className={`flex items-center gap-3 p-3 rounded-lg cursor-pointer transition-colors ${
                    selectedSchemaName === schema.name
                      ? 'bg-indigo-50 dark:bg-indigo-900/20 border border-indigo-200 dark:border-indigo-800'
                      : 'hover:bg-gray-50 dark:hover:bg-gray-700/50'
                  }`}
                  onClick={() => setSelectedSchemaName(schema.name)}
                >
                  <Checkbox.Root
                    checked={schema.selected}
                    onCheckedChange={() => handleToggleSchema(schema.name)}
                    onClick={(e) => e.stopPropagation()}
                    className="w-5 h-5 rounded border-2 border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 data-[state=checked]:bg-indigo-600 data-[state=checked]:border-indigo-600 flex items-center justify-center"
                  >
                    <Checkbox.Indicator>
                      <Check className="w-4 h-4 text-white" />
                    </Checkbox.Indicator>
                  </Checkbox.Root>
                  <Package className="h-5 w-5 text-indigo-600 dark:text-indigo-400 flex-shrink-0" />
                  <div className="flex-1 min-w-0">
                    <div className="font-medium text-gray-900 dark:text-white truncate">
                      {schema.name}
                    </div>
                    <div className="text-xs text-gray-500 dark:text-gray-400">
                      {schema.properties} properties
                    </div>
                  </div>
                  {selectedSchemaName === schema.name && (
                    <ChevronRight className="h-4 w-4 text-indigo-600 dark:text-indigo-400" />
                  )}
                </div>
              ))}
            {panelView === 'tree' &&
              schemaTreeRoots.map((node, rootIndex) => (
                <SchemaTreeItem
                  key={`root-${node.name}-${rootIndex}`}
                  node={node}
                  depth={0}
                  parentKey={`root-${rootIndex}`}
                  expandedSchemaNames={expandedSchemaNames}
                  onToggleExpand={toggleExpanded}
                  getSchemaInfo={getSchemaInfo}
                  onToggleSchema={handleToggleSchema}
                  onSelectSchema={setSelectedSchemaName}
                  selectedSchemaName={selectedSchemaName}
                />
              ))}
          </div>
        </div>

        {/* Right: Schema Preview - 2/3 width */}
        <div className="col-span-2 bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700">
          <div className="border-b border-gray-200 dark:border-gray-700 p-4">
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                Schema Preview
              </h3>
              {selectedSchema && selectedSchemaName && (
                <div className="flex items-center gap-1 bg-gray-100 dark:bg-gray-700 rounded-lg p-1">
                  <button
                    onClick={() => setViewMode('summary')}
                    className={`px-3 py-1.5 text-xs font-medium rounded transition-colors ${
                      viewMode === 'summary'
                        ? 'bg-white dark:bg-gray-600 text-indigo-600 dark:text-indigo-400 shadow-sm'
                        : 'text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white'
                    }`}
                  >
                    Summary
                  </button>
                  <button
                    onClick={() => setViewMode('json')}
                    className={`px-3 py-1.5 text-xs font-medium rounded transition-colors ${
                      viewMode === 'json'
                        ? 'bg-white dark:bg-gray-600 text-indigo-600 dark:text-indigo-400 shadow-sm'
                        : 'text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white'
                    }`}
                  >
                    JSON
                  </button>
                  <button
                    onClick={() => setViewMode('yaml')}
                    className={`px-3 py-1.5 text-xs font-medium rounded transition-colors ${
                      viewMode === 'yaml'
                        ? 'bg-white dark:bg-gray-600 text-indigo-600 dark:text-indigo-400 shadow-sm'
                        : 'text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white'
                    }`}
                  >
                    YAML
                  </button>
                </div>
              )}
            </div>
          </div>
          <div className="p-4 max-h-[400px] overflow-y-auto">
            {selectedSchema && selectedSchemaName ? (
              <div className="space-y-4">
                {viewMode === 'summary' ? (
                  <>
                    <div>
                      <h4 className="text-xl font-bold text-gray-900 dark:text-white mb-2">
                        {selectedSchemaName}
                      </h4>
                      {selectedSchema.description && (
                        <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
                          {selectedSchema.description}
                        </p>
                      )}
                    </div>

                    {selectedSchema.properties && (
                      <div>
                        <h5 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-2">
                          Properties:
                        </h5>
                        <div className="space-y-0.5 pl-4 border-l-2 border-gray-200 dark:border-gray-700">
                          {Object.entries(selectedSchema.properties).map(([propName, propValue]: [string, any]) => {
                            const expandKey = `${selectedSchemaName}|${propName}`;
                            return (
                              <ExpandablePropertyRow
                                key={propName}
                                propName={propName}
                                propValue={propValue}
                                isRequired={selectedSchema.required?.includes(propName) ?? false}
                                getPropertyType={getPropertyType}
                                expandKey={expandKey}
                                isExpanded={expandedPropertyKeys.has(expandKey)}
                                onOpenChange={(open) => handlePropertyExpand(expandKey, open)}
                              />
                            );
                          })}
                        </div>
                      </div>
                    )}

                    {/* Show relationships from $ref in properties */}
                    {selectedSchema.properties && (
                      (() => {
                        const relationships: { name: string; type: string }[] = [];
                        Object.entries(selectedSchema.properties).forEach(([propName, propValue]: [string, any]) => {
                          if (propValue.$ref) {
                            const refName = propValue.$ref.split('/').pop();
                            relationships.push({ name: refName, type: 'composition' });
                          } else if (propValue.type === 'array' && propValue.items?.$ref) {
                            const refName = propValue.items.$ref.split('/').pop();
                            relationships.push({ name: refName, type: 'aggregation' });
                          }
                        });

                        if (relationships.length > 0) {
                          return (
                            <div>
                              <h5 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-2">
                                Relationships:
                              </h5>
                              <div className="space-y-1 pl-4 border-l-2 border-green-200 dark:border-green-700">
                                {relationships.map((rel, idx) => (
                                  <div key={idx} className="text-sm flex items-center gap-2">
                                    <span className="text-green-600 dark:text-green-400">→</span>
                                    <span className="font-mono text-gray-900 dark:text-white">{rel.name}</span>
                                    <span className="text-xs px-2 py-0.5 rounded bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-300">
                                      {rel.type}
                                    </span>
                                  </div>
                                ))}
                              </div>
                            </div>
                          );
                        }
                        return null;
                      })()
                    )}

                    {/* Show inheritance from allOf */}
                    {selectedSchema.allOf && (
                      <div>
                        <h5 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-2">
                          Inherits From (allOf):
                        </h5>
                        <div className="space-y-2 pl-4 border-l-2 border-blue-200 dark:border-blue-700">
                          {selectedSchema.allOf.map((item: any, idx: number) => {
                            if (item.$ref) {
                              const refName = item.$ref.split('/').pop();
                              return (
                                <div key={idx} className="text-sm flex items-center gap-2">
                                  <span className="text-blue-600 dark:text-blue-400">↑</span>
                                  <span className="font-mono text-gray-900 dark:text-white">{refName}</span>
                                  <span className="text-xs px-2 py-0.5 rounded bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300">
                                    extends
                                  </span>
                                </div>
                              );
                            } else if (item.type === 'object' && item.properties) {
                              const propEntries = Object.entries(item.properties || {});
                              return (
                                <div key={idx} className="space-y-1">
                                  <div className="text-sm flex items-center gap-2">
                                    <span className="text-blue-600 dark:text-blue-400">+</span>
                                    <span className="text-gray-700 dark:text-gray-300 font-medium">
                                      additional properties:
                                    </span>
                                  </div>
                                  <div className="ml-6 space-y-1 pl-3 border-l border-blue-100 dark:border-blue-800">
                                    {propEntries.map(([propName, propValue]: [string, any]) => (
                                      <div key={propName} className="text-sm">
                                        <span className="font-mono text-blue-600 dark:text-blue-400">
                                          {propName}
                                        </span>
                                        <span className="text-gray-500 dark:text-gray-400">: </span>
                                        <span className="text-gray-700 dark:text-gray-300">
                                          {getPropertyType(propValue)}
                                        </span>
                                        {item.required?.includes(propName) && (
                                          <span className="ml-2 text-xs text-red-600 dark:text-red-400 font-medium">
                                            (required)
                                          </span>
                                        )}
                                      </div>
                                    ))}
                                  </div>
                                </div>
                              );
                            }
                            return null;
                          })}
                        </div>
                      </div>
                    )}

                    {/* Show polymorphism from oneOf */}
                    {selectedSchema.oneOf && (
                      <div>
                        <h5 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-2">
                          Variants (oneOf):
                        </h5>
                        <div className="space-y-2 pl-4 border-l-2 border-purple-200 dark:border-purple-700">
                          {selectedSchema.oneOf.map((item: any, idx: number) => {
                            if (item.$ref) {
                              const refName = item.$ref.split('/').pop();
                              return (
                                <div key={idx} className="text-sm flex items-center gap-2">
                                  <span className="text-purple-600 dark:text-purple-400">◇</span>
                                  <span className="font-mono text-gray-900 dark:text-white">{refName}</span>
                                  <span className="text-xs px-2 py-0.5 rounded bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300">
                                    variant
                                  </span>
                                </div>
                              );
                            }
                            // Show inline schema details
                            const hasRequired = item.required && item.required.length > 0;
                            const hasProperties = item.properties && Object.keys(item.properties).length > 0;
                            return (
                              <div key={idx} className="space-y-1">
                                <div className="text-sm flex items-center gap-2">
                                  <span className="text-purple-600 dark:text-purple-400">◇</span>
                                  <span className="text-gray-700 dark:text-gray-300 font-medium">
                                    {hasRequired ? `requires: [${item.required.join(', ')}]` : 'inline schema'}
                                  </span>
                                </div>
                                {hasProperties && (
                                  <div className="ml-6 space-y-1 pl-3 border-l border-purple-100 dark:border-purple-800">
                                    {Object.entries(item.properties).map(([propName, propValue]: [string, any]) => (
                                      <div key={propName} className="text-sm">
                                        <span className="font-mono text-purple-600 dark:text-purple-400">
                                          {propName}
                                        </span>
                                        <span className="text-gray-500 dark:text-gray-400">: </span>
                                        <span className="text-gray-700 dark:text-gray-300">
                                          {getPropertyType(propValue)}
                                        </span>
                                        {item.required?.includes(propName) && (
                                          <span className="ml-2 text-xs text-red-600 dark:text-red-400 font-medium">
                                            (required)
                                          </span>
                                        )}
                                      </div>
                                    ))}
                                  </div>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    )}

                    {/* Show flexible matching from anyOf */}
                    {selectedSchema.anyOf && (
                      <div>
                        <h5 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-2">
                          Options (anyOf):
                        </h5>
                        <div className="space-y-2 pl-4 border-l-2 border-indigo-200 dark:border-indigo-700">
                          {selectedSchema.anyOf.map((item: any, idx: number) => {
                            if (item.$ref) {
                              const refName = item.$ref.split('/').pop();
                              return (
                                <div key={idx} className="text-sm flex items-center gap-2">
                                  <span className="text-indigo-600 dark:text-indigo-400">○</span>
                                  <span className="font-mono text-gray-900 dark:text-white">{refName}</span>
                                  <span className="text-xs px-2 py-0.5 rounded bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-300">
                                    option
                                  </span>
                                </div>
                              );
                            }
                            // Show inline schema details
                            const hasRequired = item.required && item.required.length > 0;
                            const hasProperties = item.properties && Object.keys(item.properties).length > 0;
                            return (
                              <div key={idx} className="space-y-1">
                                <div className="text-sm flex items-center gap-2">
                                  <span className="text-indigo-600 dark:text-indigo-400">○</span>
                                  <span className="text-gray-700 dark:text-gray-300 font-medium">
                                    {hasRequired ? `requires: [${item.required.join(', ')}]` : 'inline schema'}
                                  </span>
                                </div>
                                {hasProperties && (
                                  <div className="ml-6 space-y-1 pl-3 border-l border-indigo-100 dark:border-indigo-800">
                                    {Object.entries(item.properties).map(([propName, propValue]: [string, any]) => (
                                      <div key={propName} className="text-sm">
                                        <span className="font-mono text-indigo-600 dark:text-indigo-400">
                                          {propName}
                                        </span>
                                        <span className="text-gray-500 dark:text-gray-400">: </span>
                                        <span className="text-gray-700 dark:text-gray-300">
                                          {getPropertyType(propValue)}
                                        </span>
                                        {item.required?.includes(propName) && (
                                          <span className="ml-2 text-xs text-red-600 dark:text-red-400 font-medium">
                                            (required)
                                          </span>
                                        )}
                                      </div>
                                    ))}
                                  </div>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    )}
                  </>
                ) : viewMode === 'json' ? (
                  <div className="rounded-lg overflow-hidden border border-gray-200 dark:border-gray-700">
                    <Editor
                      height="350px"
                      defaultLanguage="json"
                      value={JSON.stringify(selectedSchema, null, 2)}
                      theme="vs-dark"
                      options={{
                        readOnly: true,
                        minimap: { enabled: false },
                        scrollBeyondLastLine: false,
                        fontSize: 12,
                        lineNumbers: 'on',
                        folding: true,
                        wordWrap: 'on',
                        wrappingIndent: 'indent',
                      }}
                    />
                  </div>
                ) : (
                  <div className="rounded-lg overflow-hidden border border-gray-200 dark:border-gray-700">
                    <Editor
                      height="350px"
                      defaultLanguage="yaml"
                      value={YAML.stringify(selectedSchema)}
                      theme="vs-dark"
                      options={{
                        readOnly: true,
                        minimap: { enabled: false },
                        scrollBeyondLastLine: false,
                        fontSize: 12,
                        lineNumbers: 'on',
                        folding: true,
                        wordWrap: 'on',
                        wrappingIndent: 'indent',
                      }}
                    />
                  </div>
                )}
              </div>
            ) : (
              <div className="text-center py-12 text-gray-400 dark:text-gray-500">
                Select a schema to preview
              </div>
            )}
          </div>
        </div>
      </div>
      )}

      {/* Import Options */}
      <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6">
        <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
          Import Options
        </h3>

        <div className="grid grid-cols-4 gap-6">
          {/* Project Name - 50% (2 columns) */}
          <div className="col-span-2">
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
              Project Name
            </label>
            <input
              type="text"
              value={importOptions.projectName}
              onChange={(e) => handleOptionChange('projectName', e.target.value)}
              placeholder="Enter project name"
              className="w-full px-4 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white placeholder-gray-400 focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
            />
            <div className="text-xs text-gray-500 dark:text-gray-400 mt-1">
              A new project will be created with this name
            </div>
          </div>

          {/* Project Slug - 25% (1 column) */}
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
              Slug
            </label>
            <input
              type="text"
              value={importOptions.projectSlug}
              onChange={(e) => handleSlugChange(e.target.value)}
              placeholder="project-slug"
              className="w-full px-4 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white placeholder-gray-400 focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
            />
            <div className="text-xs text-gray-500 dark:text-gray-400 mt-1">
              URL-friendly identifier
            </div>
          </div>

          {/* Version Configuration - 25% (1 column) */}
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
              Version
            </label>
            <div className="space-y-2">
              {/* Version Input */}
              <input
                type="text"
                value={importOptions.targetVersion}
                onChange={(e) => handleVersionChange(e.target.value)}
                placeholder={importOptions.versionSource === 'spec' ? 'Version from spec' : 'Enter version (e.g., 1.0.0)'}
                disabled={importOptions.versionSource === 'spec'}
                className="w-full px-4 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white placeholder-gray-400 focus:ring-2 focus:ring-indigo-500 focus:border-transparent disabled:opacity-50 disabled:cursor-not-allowed disabled:bg-gray-50 dark:disabled:bg-gray-800"
              />
              {/* Radio buttons for version source */}
              <div className="flex items-center gap-3">
                <label className="flex items-center gap-1.5 cursor-pointer">
                  <input
                    type="radio"
                    name="versionSource"
                    value="spec"
                    checked={importOptions.versionSource === 'spec'}
                    onChange={() => handleVersionSourceChange('spec')}
                    className="w-4 h-4 text-indigo-600 focus:ring-2 focus:ring-indigo-500"
                  />
                  <span className="text-xs text-gray-700 dark:text-gray-300">
                    From spec
                  </span>
                </label>
                <label className="flex items-center gap-1.5 cursor-pointer">
                  <input
                    type="radio"
                    name="versionSource"
                    value="manual"
                    checked={importOptions.versionSource === 'manual'}
                    onChange={() => handleVersionSourceChange('manual')}
                    className="w-4 h-4 text-indigo-600 focus:ring-2 focus:ring-indigo-500"
                  />
                  <span className="text-xs text-gray-700 dark:text-gray-300">
                    Manual
                  </span>
                </label>
              </div>
              <div className="text-xs text-gray-500 dark:text-gray-400">
                {importOptions.versionSource === 'spec'
                  ? `Using "${analysis.document?.info?.version || '1.0.0'}" from specification`
                  : 'Allowed: 0-9, A-Z, a-z, . (dot), - (dash)'}
              </div>
            </div>
          </div>

          {/* Dry run: preview without committing */}
          <div className="col-span-4 flex items-start gap-3 pt-2">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={importOptions.dryRun ?? false}
                onChange={(e) => handleOptionChange('dryRun', e.target.checked)}
                className="w-4 h-4 rounded border-gray-300 dark:border-gray-600 text-indigo-600 focus:ring-2 focus:ring-indigo-500 bg-white dark:bg-gray-700"
              />
              <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
                Dry run (preview only)
              </span>
            </label>
            <p className="text-xs text-gray-500 dark:text-gray-400">
              Simulate the import and show what would be created. No project or data is saved.
            </p>
          </div>

          {/* Incremental mode: skip failures */}
          <div className="col-span-4 flex items-start gap-3 pt-2">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={importOptions.incrementalMode ?? false}
                onChange={(e) => handleOptionChange('incrementalMode', e.target.checked)}
                className="w-4 h-4 rounded border-gray-300 dark:border-gray-600 text-indigo-600 focus:ring-2 focus:ring-indigo-500 bg-white dark:bg-gray-700"
              />
              <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
                Incremental mode (skip failures)
              </span>
            </label>
            <p className="text-xs text-gray-500 dark:text-gray-400">
              Import all available classes and skip any that fail. Changes are saved as each class is imported; no single transaction.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

