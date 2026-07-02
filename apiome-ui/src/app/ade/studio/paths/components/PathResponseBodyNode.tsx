// Path Response Body Node Component for React Flow Canvas
'use client';

import React, { useState, useEffect } from 'react';
import { FileJson, Link2, Pencil, Trash2, ChevronRight, ChevronDown, Plus, AlertCircle, FileOutput } from 'lucide-react';
import { Position } from '@xyflow/react';
import { NodeCard } from '../../../../components/ade/canvas/NodeCard';
import { NODE_BODY_MIN_WIDTH_PX, NODE_BODY_MAX_WIDTH_PX } from './paths-theme';
import { NodeHeader } from '../../../../components/ade/canvas/NodeHeader';
import { NodeHandleDot } from '../../../../components/ade/canvas/NodeHandleDot';
import { accentVar, type NodeAccentRole } from '../../../../components/ade/canvas/canvas-theme';
import {
  buildPropertyTreeFromInlineSchema,
  getActiveCompositionKind,
  type InlineSchema,
  type PropertyTreeNode,
} from '../../../../../../lib/utils/inline-schema-utils';

function compositionSummary(inline: InlineSchema | null | undefined): string | null {
  const k = getActiveCompositionKind(inline ?? null);
  if (!k || !inline) return null;
  const arr = (inline as unknown as Record<string, unknown>)[k];
  const n = Array.isArray(arr) ? arr.length : 0;
  return `${k}${n ? `(${n})` : ''}`;
}

// =============================================================================
// TYPES
// =============================================================================

/** Single class property for read-only $ref display */
export interface ClassPropertyDisplay {
  id: string;
  name: string;
  data?: { type?: string; $ref?: string; format?: string; [key: string]: unknown };
  description?: string | null;
}

export interface ContentTypeInfo {
  id: string;
  media_type: string;
  class_id?: string | null;
  class_name?: string | null;
  inline_schema?: InlineSchema | null;
  examples?: any[] | null;
  /** When class_id is set, properties from the class for read-only $ref display */
  classProperties?: ClassPropertyDisplay[] | null;
}

export interface PathResponseBodyData {
  id: string;
  status_code: string;
  description?: string;
  contentTypes: ContentTypeInfo[];
  onDelete?: () => void;
  onEdit?: () => void;
  onPropertyDrop?: (contentId: string, propertyData: any, parentId?: string) => void;
  onClassDrop?: (contentId: string, classData: any, action: 'copy' | 'reference') => void;
  onPropertyEdit?: (contentId: string, propertyId: string) => void;
  onPropertyDelete?: (contentId: string, propertyId: string) => void;
  onAddContentType?: () => void;
  onCreateContentTypeWithProperty?: (responseId: string, propertyData: any) => void;
  onCreateContentTypeWithClass?: (responseId: string, classData: any, action: 'copy' | 'reference') => void;
  onShowClassDropDialog?: (classData: any, onConfirm: (action: 'copy' | 'reference') => void) => void;
  [key: string]: unknown; // Index signature for React Flow compatibility
}

// =============================================================================
// CONTENT TYPE BADGE
// =============================================================================

const MEDIA_TYPE_COLORS: Record<string, { bg: string; text: string }> = {
  'application/json': { bg: 'bg-green-100 dark:bg-green-900/30', text: 'text-green-700 dark:text-green-300' },
  'application/xml': { bg: 'bg-orange-100 dark:bg-orange-900/30', text: 'text-orange-700 dark:text-orange-300' },
  'application/pdf': { bg: 'bg-red-100 dark:bg-red-900/30', text: 'text-red-700 dark:text-red-300' },
  'text/html': { bg: 'bg-blue-100 dark:bg-blue-900/30', text: 'text-blue-700 dark:text-blue-300' },
  'text/plain': { bg: 'bg-gray-100 dark:bg-gray-700', text: 'text-gray-700 dark:text-gray-300' },
};

function ContentTypeBadge({ content }: { content: ContentTypeInfo }) {
  const colors = MEDIA_TYPE_COLORS[content.media_type] || {
    bg: 'bg-gray-100 dark:bg-gray-700',
    text: 'text-gray-700 dark:text-gray-300'
  };

  const isReference = !!content.class_id;
  const propertyCount = content.inline_schema?.properties?.length || 0;
  const comp = compositionSummary(content.inline_schema);
  const refLabel = isReference ? `$ref: ${content.class_name || 'Unknown'}` : null;

  return (
    <div className={`flex items-center gap-1.5 px-2 py-1 rounded-full text-[10px] font-medium ${colors.bg} ${colors.text}`}>
      {isReference ? (
        <>
          <Link2 className="w-3 h-3" />
          <span className="truncate max-w-[120px]" title={content.class_name || undefined}>{refLabel}</span>
        </>
      ) : comp ? (
        <>
          <Pencil className="w-3 h-3" />
          <span className="truncate max-w-[120px]" title={comp}>{comp}</span>
        </>
      ) : (
        <>
          <Pencil className="w-3 h-3" />
          <span>{propertyCount} props</span>
        </>
      )}
      <span className="opacity-60 ml-1">{content.media_type.replace('application/', '')}</span>
    </div>
  );
}

// =============================================================================
// PROPERTY TREE ITEM
// =============================================================================

interface PropertyTreeItemProps {
  property: PropertyTreeNode;
  depth: number;
  expanded: boolean;
  onToggle: () => void;
  onEdit?: () => void;
  onDelete?: () => void;
  onDrop?: (propertyData: any, parentId?: string) => void;
}

function PropertyTreeItem({
  property,
  depth,
  expanded,
  onToggle,
  onEdit,
  onDelete,
  onDrop,
}: PropertyTreeItemProps) {
  const [isDragOver, setIsDragOver] = useState(false);
  const dragCounterRef = React.useRef(0);
  const hasChildren = property.children && property.children.length > 0;
  const isObjectType = property.data?.type === 'object';

  const handleDragOver = (e: React.DragEvent) => {
    // Only handle drag over for object types - let others bubble up
    if (!isObjectType) {
      return; // Don't stop propagation, let parent handle it
    }
    e.preventDefault();
    e.stopPropagation();
    e.nativeEvent.stopImmediatePropagation(); // Stop all event propagation
    setIsDragOver(true);
    e.dataTransfer.dropEffect = 'copy';
  };

  const handleDragEnter = (e: React.DragEvent) => {
    // Only handle drag enter for object types - let others bubble up
    if (!isObjectType) {
      return; // Don't stop propagation, let parent handle it
    }
    e.preventDefault();
    e.stopPropagation();
    e.nativeEvent.stopImmediatePropagation(); // Stop all event propagation
    dragCounterRef.current++;
    setIsDragOver(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    // Only handle drag leave for object types - let others bubble up
    if (!isObjectType) {
      return; // Don't stop propagation, let parent handle it
    }
    e.preventDefault();
    e.stopPropagation();
    e.nativeEvent.stopImmediatePropagation(); // Stop all event propagation
    dragCounterRef.current--;
    if (dragCounterRef.current === 0) {
      setIsDragOver(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    // Only handle drops on object types - let others bubble up to parent
    if (!onDrop || !isObjectType) {
      return; // Don't stop propagation, let parent handle it
    }

    e.preventDefault();
    e.stopPropagation();
    e.nativeEvent.stopImmediatePropagation(); // Stop all event propagation
    dragCounterRef.current = 0;
    setIsDragOver(false);

    try {
      const dataStr = e.dataTransfer.getData('application/json');
      if (!dataStr) return;

      const dropData = JSON.parse(dataStr);
      if (dropData.type === 'property') {
        onDrop(dropData, property.id);
      }
    } catch (error) {
      console.error('Error parsing dropped data:', error);
    }
  };

  const getTypeDisplay = () => {
    const type = property.data?.type;
    const format = property.data?.format;

    if (type === 'array' && property.data?.items) {
      const itemType = property.data.items.type || property.data.items.$ref?.split('/').pop();
      return `array<${itemType}>`;
    }
    if (format) return `${type} (${format})`;
    return type || 'string';
  };

  return (
    <div style={{ marginLeft: `${depth * 12}px` }}>
      <div
        onDragEnter={handleDragEnter}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        data-drop-handler="property-tree-item"
        className={`
          flex items-center gap-1 px-2 py-1 rounded group hover:bg-gray-100 dark:hover:bg-gray-700/50
          ${isDragOver ? 'bg-emerald-50 dark:bg-emerald-900/30 ring-1 ring-emerald-300 dark:ring-emerald-600' : ''}
          ${property.data?.required ? 'font-medium' : ''}
        `}
      >
        {hasChildren && (
          <button
            onClick={onToggle}
            className="p-0.5 hover:bg-gray-200 dark:hover:bg-gray-600 rounded"
          >
            {expanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
          </button>
        )}
        {!hasChildren && <div className="w-4" />}

        <FileJson className="w-3 h-3 text-gray-400" />

        <span className="text-xs flex-1 truncate">{property.name}</span>
        <span className="text-[10px] text-gray-500 dark:text-gray-400 font-mono">
          {getTypeDisplay()}
        </span>

        <div className="hidden group-hover:flex items-center gap-0.5 ml-1">
          {onEdit && (
            <button
              onClick={(e) => {
                e.stopPropagation();
                onEdit();
              }}
              className="p-0.5 hover:bg-gray-200 dark:hover:bg-gray-600 rounded"
              title="Edit property"
            >
              <Pencil className="w-3 h-3 text-gray-500" />
            </button>
          )}
          {onDelete && (
            <button
              onClick={(e) => {
                e.stopPropagation();
                onDelete();
              }}
              className="p-0.5 hover:bg-red-100 dark:hover:bg-red-900/30 rounded"
              title="Delete property"
            >
              <Trash2 className="w-3 h-3 text-red-500" />
            </button>
          )}
        </div>
      </div>

      {expanded && hasChildren && (
        <div>
          {property.children.map((child) => (
            <PropertyTreeItem
              key={child.id}
              property={child}
              depth={depth + 1}
              expanded={false}
              onToggle={() => {}}
              onEdit={onEdit}
              onDelete={onDelete}
              onDrop={onDrop}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// =============================================================================
// CONTENT TYPE PANEL
// =============================================================================

interface ContentTypePanelProps {
  content: ContentTypeInfo;
  onPropertyDrop?: (propertyData: any, parentId?: string) => void;
  onClassDrop?: (classData: any, action: 'copy' | 'reference') => void;
  onShowClassDropDialog?: (classData: any, onConfirm: (action: 'copy' | 'reference') => void) => void;
  onPropertyEdit?: (propertyId: string) => void;
  onPropertyDelete?: (propertyId: string) => void;
}

function ContentTypePanel({
  content,
  onPropertyDrop,
  onClassDrop,
  onShowClassDropDialog,
  onPropertyEdit,
  onPropertyDelete,
}: ContentTypePanelProps) {
  const [expandedProperties, setExpandedProperties] = useState<Set<string>>(new Set());
  const [isDragOver, setIsDragOver] = useState(false);
  const [refDragOver, setRefDragOver] = useState(false);
  const dragCounterRef = React.useRef(0);
  const refDragCounterRef = React.useRef(0);

  const propertyTree: PropertyTreeNode[] = content.inline_schema
    ? buildPropertyTreeFromInlineSchema(content.inline_schema)
    : [];

  const handleToggleExpand = (id: string) => {
    setExpandedProperties((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const handleDragEnter = (e: React.DragEvent) => {
    if (content.class_id) return; // Can't drop on class reference
    e.preventDefault();
    e.stopPropagation();
    e.nativeEvent.stopImmediatePropagation(); // Stop all event propagation
    dragCounterRef.current++;
    setIsDragOver(true);
  };

  const handleDragOver = (e: React.DragEvent) => {
    if (content.class_id) return; // Can't drop on class reference
    e.preventDefault();
    e.stopPropagation();
    e.nativeEvent.stopImmediatePropagation(); // Stop all event propagation
    setIsDragOver(true);
    e.dataTransfer.dropEffect = 'copy';
  };

  const handleDragLeave = (e: React.DragEvent) => {
    if (content.class_id) return;
    e.preventDefault();
    e.stopPropagation();
    e.nativeEvent.stopImmediatePropagation(); // Stop all event propagation
    dragCounterRef.current--;
    if (dragCounterRef.current === 0) {
      setIsDragOver(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    e.nativeEvent.stopImmediatePropagation(); // Stop all event propagation
    dragCounterRef.current = 0;
    setIsDragOver(false);

    if (content.class_id) return;

    try {
      const dataStr = e.dataTransfer.getData('application/json');
      if (!dataStr) return;

      const dropData = JSON.parse(dataStr);

      if (dropData.type === 'property' && onPropertyDrop) {
        onPropertyDrop(dropData);
      } else if (dropData.type === 'class') {
        if (onShowClassDropDialog) {
          // Show dialog to ask user what action to take
          onShowClassDropDialog(dropData, (action: 'copy' | 'reference') => {
            if (onClassDrop) {
              onClassDrop(dropData, action);
            }
          });
        } else if (onClassDrop) {
          // Fallback: default to copy if no dialog handler
          onClassDrop(dropData, 'copy');
        }
      }
    } catch (error) {
      console.error('Error parsing dropped data:', error);
    }
  };

  const handleNestedDrop = (propertyData: any, parentId?: string) => {
    if (onPropertyDrop) {
      onPropertyDrop(propertyData, parentId);
    }
  };

  // If it's a class reference ($ref), show $ref label, read-only properties, and a drop zone to replace
  if (content.class_id) {
    const handleRefDragEnter = (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      refDragCounterRef.current++;
      setRefDragOver(true);
    };
    const handleRefDragOver = (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      setRefDragOver(true);
      e.dataTransfer.dropEffect = 'copy';
    };
    const handleRefDragLeave = (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      refDragCounterRef.current--;
      if (refDragCounterRef.current === 0) setRefDragOver(false);
    };
    const handleRefDrop = (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      refDragCounterRef.current = 0;
      setRefDragOver(false);
      try {
        const dataStr = e.dataTransfer.getData('application/json');
        if (!dataStr) return;
        const dropData = JSON.parse(dataStr);
        if (dropData.type === 'property' && onPropertyDrop) {
          onPropertyDrop(dropData);
        } else if (dropData.type === 'class') {
          if (onShowClassDropDialog) {
            onShowClassDropDialog(dropData, (action: 'copy' | 'reference') => {
              if (onClassDrop) onClassDrop(dropData, action);
            });
          } else if (onClassDrop) {
            onClassDrop(dropData, 'copy');
          }
        }
      } catch (err) {
        console.error('Error parsing dropped data:', err);
      }
    };
    const classProps = content.classProperties || [];
    const getTypeLabel = (p: ClassPropertyDisplay) => {
      const d = p.data as { type?: string; $ref?: string; items?: { $ref?: string } } | undefined;
      if (!d) return 'any';
      if (d.$ref) return d.$ref.split('/').pop() || 'ref';
      if (d.type === 'array' && d.items?.$ref) return `${d.items.$ref.split('/').pop()}[]`;
      return d.type || 'any';
    };
    return (
      <div className="space-y-2" data-drop-zone="response-body-content-type">
        <div className="p-3 bg-blue-50/50 dark:bg-blue-900/20 rounded-lg border border-blue-200 dark:border-blue-800">
          <div className="flex items-center gap-2 text-sm text-blue-700 dark:text-blue-300">
            <Link2 className="w-4 h-4" />
            <span className="font-medium">$ref: {content.class_name || 'Unknown'}</span>
          </div>
          <p className="text-xs text-blue-600/70 dark:text-blue-400/70 mt-1">
            Read-only; changes to the class will update this response.
          </p>
          {classProps.length > 0 && (
            <div className="mt-2 rounded border border-blue-200/60 dark:border-blue-700/60 bg-white/50 dark:bg-gray-800/50 p-2 max-h-[200px] overflow-y-auto">
              <div className="text-[10px] font-medium text-blue-600 dark:text-blue-400 mb-1.5">Properties (read-only)</div>
              <ul className="space-y-1">
                {classProps.map((p) => (
                  <li key={p.id} className="flex items-center justify-between gap-2 text-xs text-gray-700 dark:text-gray-300">
                    <span className="font-mono truncate">{p.name}</span>
                    <span className="text-gray-500 dark:text-gray-400 font-mono text-[10px] shrink-0">{getTypeLabel(p)}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
        <div
          onDragEnter={handleRefDragEnter}
          onDragOver={handleRefDragOver}
          onDragLeave={handleRefDragLeave}
          onDrop={handleRefDrop}
          className={`p-3 rounded-lg border-2 border-dashed text-center transition-colors text-xs ${
            refDragOver
              ? 'border-emerald-400 dark:border-emerald-600 bg-emerald-50 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300'
              : 'border-gray-300 dark:border-gray-600 bg-gray-50/50 dark:bg-gray-800/50 text-gray-500 dark:text-gray-400'
          }`}
        >
          <Plus className="w-4 h-4 mx-auto mb-1 opacity-70" />
          Drop a class or property to replace this $ref
        </div>
      </div>
    );
  }

  // Show inline schema with drag-drop
  return (
    <div data-drop-zone="response-body-content-type">
      {propertyTree.length === 0 ? (
        <div
          onDragEnter={handleDragEnter}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          data-drop-handler="content-type-panel"
          className={`
            p-4 rounded-lg border-2 border-dashed text-center transition-all
            ${isDragOver
              ? 'border-emerald-400 dark:border-emerald-600 bg-emerald-50 dark:bg-emerald-900/30'
              : 'border-gray-300 dark:border-gray-600 bg-gray-50/50 dark:bg-gray-800/50'
            }
          `}
        >
          <Plus className="w-6 h-6 mx-auto mb-2 text-gray-400" />
          <p className="text-xs text-gray-500 dark:text-gray-400">
            Drag properties here to define the response schema
          </p>
        </div>
      ) : (
        <div
          className={`
            rounded-lg border transition-all
            ${isDragOver
              ? 'border-emerald-400 dark:border-emerald-600 bg-emerald-50/50 dark:bg-emerald-900/20'
              : 'border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800'
            }
          `}
        >
          <div 
            className="p-2 space-y-0.5 max-h-[300px] overflow-y-auto min-h-[60px]"
            onDragEnter={handleDragEnter}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
            data-drop-handler="property-list"
          >
            {propertyTree.map((prop) => (
              <PropertyTreeItem
                key={prop.id}
                property={prop}
                depth={0}
                expanded={expandedProperties.has(prop.id)}
                onToggle={() => handleToggleExpand(prop.id)}
                onEdit={onPropertyEdit ? () => onPropertyEdit(prop.id) : undefined}
                onDelete={onPropertyDelete ? () => onPropertyDelete(prop.id) : undefined}
                onDrop={handleNestedDrop}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// =============================================================================
// MAIN RESPONSE BODY NODE
// =============================================================================

export default function PathResponseBodyNode({ data }: { data: PathResponseBodyData }) {
  const [selectedContentTypeIndex, setSelectedContentTypeIndex] = useState(0);
  const [isDragOverEmpty, setIsDragOverEmpty] = useState(false);
  const dragCounterRef = React.useRef(0);

  const currentContent = data.contentTypes[selectedContentTypeIndex];

  const statusRole: NodeAccentRole = (() => {
    const code = data.status_code;
    if (code.startsWith('2')) return 'status-2xx';
    if (code.startsWith('3')) return 'status-3xx';
    if (code.startsWith('4')) return 'status-4xx';
    if (code.startsWith('5')) return 'status-5xx';
    return 'response';
  })();
  const responseAccent = accentVar(statusRole);

  // Handle drag for empty state (no content types)
  const handleEmptyDragEnter = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounterRef.current++;
    setIsDragOverEmpty(true);
  };

  const handleEmptyDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOverEmpty(true);
    e.dataTransfer.dropEffect = 'copy';
  };

  const handleEmptyDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounterRef.current--;
    if (dragCounterRef.current === 0) {
      setIsDragOverEmpty(false);
    }
  };

  const handleEmptyDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounterRef.current = 0;
    setIsDragOverEmpty(false);

    try {
      const dataStr = e.dataTransfer.getData('application/json');
      if (!dataStr) return;

      const dropData = JSON.parse(dataStr);

      if (dropData.type === 'property') {
        if (data.onCreateContentTypeWithProperty) {
          data.onCreateContentTypeWithProperty(data.id, dropData);
        }
      } else if (dropData.type === 'class') {
        if (data.onShowClassDropDialog) {
          // Show dialog to ask user what action to take
          data.onShowClassDropDialog(dropData, (action: 'copy' | 'reference') => {
            if (data.onCreateContentTypeWithClass) {
              data.onCreateContentTypeWithClass(data.id, dropData, action);
            }
          });
        } else if (data.onCreateContentTypeWithClass) {
          data.onCreateContentTypeWithClass(data.id, dropData, 'copy');
        }
      }
    } catch (error) {
      console.error('Error parsing dropped data:', error);
    }
  };

  const ctSel = data.contentTypes[selectedContentTypeIndex];
  const compLabel = ctSel?.inline_schema ? compositionSummary(ctSel.inline_schema) : null;
  const schemaLabel = ctSel
    ? (ctSel.class_id
        ? `$ref: ${ctSel.class_name || 'Unknown'}`
        : compLabel
          ? compLabel
          : (ctSel.inline_schema?.properties?.length ?? 0) > 0
            ? `${ctSel.inline_schema!.properties!.length} props`
            : 'Object')
    : null;

  return (
    <>
      {/* Input handle at TOP - connects from parent response (not from operations) */}
      <NodeHandleDot
        type="target"
        position={Position.Top}
        id="response-input"
        isConnectable={false}
        color={responseAccent}
        style={{ cursor: 'not-allowed', opacity: 0.55 }}
      />

      <NodeCard role={statusRole} minWidth={NODE_BODY_MIN_WIDTH_PX} maxWidth={NODE_BODY_MAX_WIDTH_PX} customBorderColor={responseAccent}>
        <NodeHeader
          role={statusRole}
          customBackground={responseAccent}
          customTextColor="#ffffff"
          icon={<FileOutput size={14} />}
          iconSize={26}
          compact
          title={
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
              <span
                style={{
                  fontSize: '11px',
                  fontWeight: 700,
                  fontFamily: 'var(--app-font-mono, monospace)',
                  padding: '1px 6px',
                  borderRadius: '4px',
                  background: 'rgba(0, 0, 0, 0.2)',
                }}
              >
                {data.status_code}
              </span>
              <span style={{ fontWeight: 600 }}>Response</span>
              {schemaLabel && (
                <span
                  title={`Schema: ${schemaLabel}`}
                  style={{
                    fontSize: '11px',
                    fontWeight: 500,
                    opacity: 0.9,
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                    maxWidth: '160px',
                    fontFamily: 'var(--app-font-mono, monospace)',
                  }}
                >
                  → {schemaLabel}
                </span>
              )}
            </div>
          }
          subtitle={data.description ? <span>{data.description}</span> : undefined}
          badges={
            data.onDelete && (
              <button
                onClick={data.onDelete}
                title="Delete response"
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  width: '22px',
                  height: '22px',
                  borderRadius: '4px',
                  background: 'rgba(255, 255, 255, 0.16)',
                  color: '#ffffff',
                  cursor: 'pointer',
                  border: 'none',
                }}
              >
                <Trash2 size={13} />
              </button>
            )
          }
        />

        {/* Content Type Tabs */}
        {data.contentTypes.length > 1 && (
          <div className="px-3 pt-2 flex gap-1 overflow-x-auto">
            {data.contentTypes.map((ct, index) => (
              <button
                key={ct.id}
                onClick={() => setSelectedContentTypeIndex(index)}
                className={`
                  px-2 py-1 text-[10px] rounded-t transition-colors whitespace-nowrap
                  ${selectedContentTypeIndex === index
                    ? 'bg-gray-100 dark:bg-gray-700 text-gray-900 dark:text-white font-medium'
                    : 'text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700/50'
                  }
                `}
              >
                {ct.media_type}
              </button>
            ))}
          </div>
        )}

        {/* Content */}
        <div className="p-3 space-y-2">
          {data.contentTypes.length === 0 ? (
            <div
              onDragEnter={handleEmptyDragEnter}
              onDragOver={handleEmptyDragOver}
              onDragLeave={handleEmptyDragLeave}
              onDrop={handleEmptyDrop}
              className={`p-4 text-center border-2 border-dashed rounded-lg transition-all ${
                isDragOverEmpty
                  ? 'border-emerald-400 dark:border-emerald-600 bg-emerald-50 dark:bg-emerald-900/30'
                  : 'border-gray-300 dark:border-gray-600'
              }`}
            >
              <Plus className="w-6 h-6 mx-auto mb-2 text-gray-400" />
              <p className="text-xs text-gray-500 dark:text-gray-400">
                {isDragOverEmpty ? 'Drop to create schema' : 'Drag properties here to define schema'}
              </p>
              {data.onAddContentType && !isDragOverEmpty && (
                <button
                  onClick={data.onAddContentType}
                  className="mt-2 px-3 py-1 text-xs bg-emerald-500 text-white rounded hover:bg-emerald-600 transition-colors"
                >
                  Add Content Type
                </button>
              )}
            </div>
          ) : currentContent ? (
            <>
              <ContentTypeBadge content={currentContent} />
              <ContentTypePanel
                content={currentContent}
                onPropertyDrop={
                  data.onPropertyDrop && currentContent?.id
                    ? (propertyData, parentId) => data.onPropertyDrop!(currentContent.id, propertyData, parentId)
                    : undefined
                }
                onClassDrop={
                  data.onClassDrop && currentContent?.id
                    ? (classData, action) => data.onClassDrop!(currentContent.id, classData, action)
                    : undefined
                }
                onShowClassDropDialog={data.onShowClassDropDialog}
                onPropertyEdit={
                  data.onPropertyEdit
                    ? (propertyId) => data.onPropertyEdit!(currentContent.id, propertyId)
                    : undefined
                }
                onPropertyDelete={
                  data.onPropertyDelete
                    ? (propertyId) => data.onPropertyDelete!(currentContent.id, propertyId)
                    : undefined
                }
              />
            </>
          ) : null}
        </div>

        {/* Footer */}
        <div className="px-3 pb-2 flex items-center justify-between text-[10px] text-gray-500 dark:text-gray-400">
          <span>{data.contentTypes.length} content type(s)</span>
          {data.onEdit && (
            <button
              onClick={data.onEdit}
              className="flex items-center gap-1 px-2 py-1 hover:bg-gray-100 dark:hover:bg-gray-700 rounded transition-colors"
            >
              <Pencil className="w-3 h-3" />
              Edit
            </button>
          )}
        </div>
      </NodeCard>

      <NodeHandleDot
        type="source"
        position={Position.Bottom}
        id="response-output"
        isConnectable={false}
        color={responseAccent}
        style={{ cursor: 'not-allowed', opacity: 0.55 }}
      />
    </>
  );
}
