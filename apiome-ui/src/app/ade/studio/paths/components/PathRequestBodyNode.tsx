// Path Request Body Node Component for React Flow Canvas
'use client';

import React, { useState, useEffect } from 'react';
import { Link2, Pencil, Trash2, ChevronRight, ChevronDown, Plus, AlertCircle, Sparkles, FileInput } from 'lucide-react';
import { Position } from '@xyflow/react';
import * as DropdownMenu from '@radix-ui/react-dropdown-menu';
import { NodeCard } from '../../../../components/ade/canvas/NodeCard';
import { NODE_BODY_MIN_WIDTH_PX, NODE_BODY_MAX_WIDTH_PX } from './paths-theme';
import { NodeHeader } from '../../../../components/ade/canvas/NodeHeader';
import { NodeHandleDot } from '../../../../components/ade/canvas/NodeHandleDot';
import { NodeBadge } from '../../../../components/ade/canvas/NodeBadge';
import {
  buildPropertyTreeFromInlineSchema,
  buildSchemaFromInlineProperties,
  type InlineSchema,
  type PropertyTreeNode,
} from '../../../../../../lib/utils/inline-schema-utils';
import jsf from 'json-schema-faker';

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
  encoding?: Record<string, any> | null;
  examples?: any[] | null;
  /** When class_id is set, properties from the class for read-only $ref display */
  classProperties?: ClassPropertyDisplay[] | null;
}

export interface PathRequestBodyData {
  id: string;
  name: string;
  description?: string;
  required?: boolean;
  contentTypes: ContentTypeInfo[];
  onDelete?: () => void;
  onEdit?: () => void;
  onPropertyDrop?: (contentId: string, propertyData: any, parentId?: string) => void;
  onClassDrop?: (contentId: string, classData: any, action: 'copy' | 'reference') => void;
  onPropertyEdit?: (contentId: string, propertyId: string) => void;
  onPropertyDelete?: (contentId: string, propertyId: string) => void;
  /** Called with the selected media type when user adds a new content type branch (e.g. application/json, multipart/form-data). */
  onAddContentType?: (mediaType: string) => void;
  /** Called when the user saves a new or updated description for the request body. */
  onDescriptionChange?: (description: string) => void;
  /** Called when the user saves examples for a content type (contentId, examples array). */
  onExamplesChange?: (contentId: string, examples: Array<{ summary?: string; value: unknown }>) => void;
  /** Called when the user saves encoding options for a content type (multipart/form-data, etc.). */
  onEncodingChange?: (contentId: string, encoding: Record<string, Record<string, unknown>> | null) => void;
  onShowClassDropDialog?: (classData: any, onConfirm: (action: 'copy' | 'reference') => void) => void;
  [key: string]: unknown; // Index signature for React Flow compatibility
}

// =============================================================================
// CONTENT TYPE BADGE
// =============================================================================

const MEDIA_TYPE_COLORS: Record<string, { bg: string; text: string }> = {
  'application/json': { bg: 'bg-green-100 dark:bg-green-900/30', text: 'text-green-700 dark:text-green-300' },
  'application/xml': { bg: 'bg-orange-100 dark:bg-orange-900/30', text: 'text-orange-700 dark:text-orange-300' },
  'multipart/form-data': { bg: 'bg-purple-100 dark:bg-purple-900/30', text: 'text-purple-700 dark:text-purple-300' },
  'application/x-www-form-urlencoded': { bg: 'bg-blue-100 dark:bg-blue-900/30', text: 'text-blue-700 dark:text-blue-300' },
  'text/plain': { bg: 'bg-gray-100 dark:bg-gray-700', text: 'text-gray-700 dark:text-gray-300' },
};

/** Options for adding a new content type branch (application/json, multipart/form-data, etc.) */
const ADD_CONTENT_TYPE_OPTIONS = [
  { value: 'application/json', label: 'application/json' },
  { value: 'application/xml', label: 'application/xml' },
  { value: 'multipart/form-data', label: 'multipart/form-data' },
  { value: 'application/x-www-form-urlencoded', label: 'application/x-www-form-urlencoded' },
  { value: 'text/plain', label: 'text/plain' },
  { value: 'application/octet-stream', label: 'application/octet-stream' },
];

function ContentTypeBadge({ content }: { content: ContentTypeInfo }) {
  const colors = MEDIA_TYPE_COLORS[content.media_type] || {
    bg: 'bg-gray-100 dark:bg-gray-700',
    text: 'text-gray-700 dark:text-gray-300'
  };

  const isReference = !!content.class_id;
  const propertyCount = content.inline_schema?.properties?.length || 0;

  return (
    <div className={`flex items-center gap-1.5 px-2 py-1 rounded-full text-[10px] font-medium ${colors.bg} ${colors.text}`}>
      {isReference ? (
        <>
          <Link2 className="w-3 h-3" />
          <span className="truncate max-w-[100px]">{content.class_name || 'Unknown'}</span>
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
  onDrop?: (propertyData: any, parentId: string) => void;
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
  const hasChildren = property.children.length > 0;
  const canAcceptChildren = property.data?.type === 'object' ||
    (property.data?.type === 'array' && !property.data?.items?.$ref);

  const handleDragEnter = (e: React.DragEvent) => {
    if (!canAcceptChildren) return;
    e.preventDefault();
    e.stopPropagation();
    dragCounterRef.current++;
    setIsDragOver(true);
  };

  const handleDragOver = (e: React.DragEvent) => {
    if (!canAcceptChildren) return;
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    if (!canAcceptChildren) return;
    e.preventDefault();
    e.stopPropagation();
    dragCounterRef.current--;
    if (dragCounterRef.current === 0) {
      setIsDragOver(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounterRef.current = 0;
    setIsDragOver(false);

    if (!canAcceptChildren || !onDrop) return;

    const dataStr = e.dataTransfer.getData('application/json');
    if (dataStr) {
      try {
        const dropData = JSON.parse(dataStr);
        if (dropData.type === 'property') {
          onDrop(dropData, property.id);
        }
      } catch (err) {
        console.error('Failed to parse drop data:', err);
      }
    }
  };

  // Get type display
  const getTypeDisplay = () => {
    const data = property.data || {};
    if (data.$ref) {
      const parts = data.$ref.split('/');
      return parts[parts.length - 1];
    }
    if (Array.isArray(data.type)) {
      return data.type.filter((t: string) => t !== 'null').join(' | ') + '?';
    }
    let typeStr = data.type || 'any';
    if (data.format) {
      typeStr += `:${data.format}`;
    }
    return typeStr;
  };

  const isRequired = property.data?.required === true;

  return (
    <div>
      <div
        className={`flex items-center gap-1 px-2 py-1 text-xs cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700 rounded group ${
          isDragOver ? 'bg-green-100 dark:bg-green-900/30 ring-1 ring-green-400' : ''
        }`}
        style={{ paddingLeft: `${8 + depth * 12}px` }}
        onDragEnter={handleDragEnter}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
      >
        {/* Expand/Collapse toggle */}
        <button
          onClick={(e) => {
            e.stopPropagation();
            onToggle();
          }}
          className={`p-0.5 rounded hover:bg-gray-200 dark:hover:bg-gray-600 ${
            !hasChildren && !canAcceptChildren ? 'invisible' : ''
          }`}
        >
          {expanded ? (
            <ChevronDown className="w-3 h-3 text-gray-500" />
          ) : (
            <ChevronRight className="w-3 h-3 text-gray-500" />
          )}
        </button>

        {/* Property name */}
        <span className="font-medium text-gray-800 dark:text-gray-200 truncate">
          {property.name}
        </span>

        {/* Required indicator */}
        {isRequired && (
          <span className="text-red-500 text-[10px]">*</span>
        )}

        {/* Type */}
        <span className="text-gray-500 dark:text-gray-400 text-[10px] ml-auto">
          {getTypeDisplay()}
        </span>

        {/* Action buttons - visible on hover */}
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

      {/* Render children if expanded */}
      {expanded && hasChildren && (
        <div>
          {property.children.map((child) => (
            <PropertyTreeItem
              key={child.id}
              property={child}
              depth={depth + 1}
              expanded={false}
              onToggle={() => {}}
              onEdit={onEdit ? () => onEdit() : undefined}
              onDelete={onDelete ? () => onDelete() : undefined}
              onDrop={onDrop}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// =============================================================================
// REQUEST BODY CONTENT TYPE PANEL (matches response body: $ref vs inline drop zones)
// =============================================================================

interface RequestBodyContentTypePanelProps {
  content: ContentTypeInfo;
  onPropertyDrop?: (propertyData: any, parentId?: string) => void;
  onClassDrop?: (classData: any, action: 'copy' | 'reference') => void;
  onShowClassDropDialog?: (classData: any, onConfirm: (action: 'copy' | 'reference') => void) => void;
  onPropertyEdit?: (propertyId: string) => void;
  onPropertyDelete?: (propertyId: string) => void;
}

function RequestBodyContentTypePanel({
  content,
  onPropertyDrop,
  onClassDrop,
  onShowClassDropDialog,
  onPropertyEdit,
  onPropertyDelete,
}: RequestBodyContentTypePanelProps) {
  const [expandedProps, setExpandedProps] = useState<Set<string>>(new Set());
  const [isDragOver, setIsDragOver] = useState(false);
  const [refDragOver, setRefDragOver] = useState(false);
  const dragCounterRef = React.useRef(0);
  const refDragCounterRef = React.useRef(0);

  const propertyTree = buildPropertyTreeFromInlineSchema(content.inline_schema || null);

  const toggleExpanded = (propId: string) => {
    setExpandedProps((prev) => {
      const next = new Set(prev);
      if (next.has(propId)) next.delete(propId);
      else next.add(propId);
      return next;
    });
  };

  const handleDragEnter = (e: React.DragEvent) => {
    if (content.class_id) return;
    e.preventDefault();
    e.stopPropagation();
    dragCounterRef.current++;
    setIsDragOver(true);
  };
  const handleDragOver = (e: React.DragEvent) => {
    if (content.class_id) return;
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(true);
    e.dataTransfer.dropEffect = 'copy';
  };
  const handleDragLeave = (e: React.DragEvent) => {
    if (content.class_id) return;
    e.preventDefault();
    e.stopPropagation();
    dragCounterRef.current--;
    if (dragCounterRef.current === 0) setIsDragOver(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounterRef.current = 0;
    setIsDragOver(false);
    if (content.class_id) return;
    const dataStr = e.dataTransfer.getData('application/json');
    if (!dataStr) return;
    try {
      const dropData = JSON.parse(dataStr);
      if (dropData.type === 'property' && onPropertyDrop) {
        onPropertyDrop(dropData, undefined);
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
      console.error('Failed to parse drop data:', err);
    }
  };

  const handleNestedDrop = (propertyData: any, parentId?: string) => {
    if (onPropertyDrop) onPropertyDrop(propertyData, parentId);
  };

  // $ref: show read-only class + drop zone "Drop a class or property to replace this $ref"
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
    // Same design as PathResponseBodyNode $ref block: one blue box (header + properties list), then draggable section below
    return (
      <div className="space-y-2" data-drop-zone="request-body-content-type">
        <div className="p-3 bg-blue-50/50 dark:bg-blue-900/20 rounded-lg border border-blue-200 dark:border-blue-800">
          <div className="flex items-center gap-2 text-sm text-blue-700 dark:text-blue-300">
            <Link2 className="w-4 h-4" />
            <span className="font-medium">$ref: {content.class_name || 'Unknown'}</span>
          </div>
          <p className="text-xs text-blue-600/70 dark:text-blue-400/70 mt-1">
            Read-only; changes to the class will update this request body.
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

  // Inline schema: "Drop class or property to add properties to this schema"
  if (propertyTree.length === 0) {
    return (
      <div
        onDragEnter={handleDragEnter}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        className={`p-4 rounded-lg border-2 border-dashed text-center transition-all ${
          isDragOver
            ? 'border-emerald-400 dark:border-emerald-600 bg-emerald-50 dark:bg-emerald-900/30'
            : 'border-gray-300 dark:border-gray-600 bg-gray-50/50 dark:bg-gray-800/50'
        }`}
      >
        <Plus className="w-6 h-6 mx-auto mb-2 text-gray-400" />
        <p className="text-xs text-gray-500 dark:text-gray-400">
          Drop class or property to add properties to this schema
        </p>
      </div>
    );
  }

  // Inline schema with properties: same layout as response – properties list first, then draggable section below
  return (
    <div className="space-y-2" data-drop-zone="request-body-content-type">
      <div
        className={`rounded-lg border transition-all ${
          isDragOver
            ? 'border-emerald-400 dark:border-emerald-600 bg-emerald-50/50 dark:bg-emerald-900/20'
            : 'border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800'
        }`}
      >
        <div
          className="p-2 space-y-0.5 max-h-[300px] overflow-y-auto min-h-[60px]"
          onDragEnter={handleDragEnter}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
        >
          {propertyTree.map((prop) => (
            <PropertyTreeItem
              key={prop.id}
              property={prop}
              depth={0}
              expanded={expandedProps.has(prop.id)}
              onToggle={() => toggleExpanded(prop.id)}
              onEdit={onPropertyEdit ? () => onPropertyEdit(prop.id) : undefined}
              onDelete={onPropertyDelete ? () => onPropertyDelete(prop.id) : undefined}
              onDrop={handleNestedDrop}
            />
          ))}
        </div>
      </div>
      <div
        onDragEnter={handleDragEnter}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        className={`p-3 rounded-lg border-2 border-dashed text-center transition-colors text-xs ${
          isDragOver
            ? 'border-emerald-400 dark:border-emerald-600 bg-emerald-50 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300'
            : 'border-gray-300 dark:border-gray-600 bg-gray-50/50 dark:bg-gray-800/50 text-gray-500 dark:text-gray-400'
        }`}
      >
        <Plus className="w-4 h-4 mx-auto mb-1 opacity-70" />
        Drop class or property to add to this schema
      </div>
    </div>
  );
}

// =============================================================================
// ADD CONTENT TYPE DROPDOWN
// =============================================================================

interface AddContentTypeDropdownProps {
  existingMediaTypes: string[];
  onSelect: (mediaType: string) => void;
  triggerClassName?: string;
  triggerLabel?: string;
}

function AddContentTypeDropdown({
  existingMediaTypes,
  onSelect,
  triggerClassName = 'flex items-center gap-1 px-2 py-1 text-[10px] hover:bg-gray-100 dark:hover:bg-gray-700 rounded transition-colors text-gray-600 dark:text-gray-400',
  triggerLabel = 'Add content type',
}: AddContentTypeDropdownProps) {
  const available = ADD_CONTENT_TYPE_OPTIONS.filter(
    (opt) => !existingMediaTypes.includes(opt.value)
  );

  if (available.length === 0) return null;

  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button
          type="button"
          onClick={(e) => e.stopPropagation()}
          className={triggerClassName}
        >
          <Plus className="w-3 h-3" />
          {triggerLabel}
          <ChevronDown className="w-3 h-3 opacity-70" />
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content
          className="min-w-[220px] rounded-lg bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 shadow-lg py-1 z-[10000]"
          sideOffset={4}
          align="start"
          onClick={(e) => e.stopPropagation()}
        >
          {available.map((opt) => (
            <DropdownMenu.Item
              key={opt.value}
              className="flex cursor-pointer px-3 py-2 text-xs text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-700 outline-none"
              onSelect={() => onSelect(opt.value)}
            >
              {opt.label}
            </DropdownMenu.Item>
          ))}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}

// =============================================================================
// DESCRIPTION EDITOR (for request body node mapping)
// =============================================================================

interface DescriptionEditorProps {
  description: string | undefined;
  isEditing: boolean;
  onStartEdit: () => void;
  onCancel: () => void;
  onSave: (value: string) => void;
  draft: string;
  onDraftChange: (value: string) => void;
}

function DescriptionEditor({
  description,
  isEditing,
  onStartEdit,
  onCancel,
  onSave,
  draft,
  onDraftChange,
}: DescriptionEditorProps) {
  if (isEditing) {
    return (
      <div className="px-3 py-2 border-b border-gray-200 dark:border-gray-700 bg-gray-50/50 dark:bg-gray-800/50" onClick={(e) => e.stopPropagation()}>
        <label className="text-[10px] font-medium text-gray-500 dark:text-gray-400 block mb-1">Description</label>
        <textarea
          value={draft}
          onChange={(e) => onDraftChange(e.target.value)}
          placeholder="Describe the request body..."
          className="w-full px-2 py-1.5 text-xs rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 placeholder-gray-400 min-h-[60px] resize-y"
          rows={2}
        />
        <div className="flex justify-end gap-1 mt-2">
          <button
            type="button"
            onClick={onCancel}
            className="px-2 py-1 text-[10px] rounded border border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => onSave(draft.trim())}
            className="px-2 py-1 text-[10px] rounded bg-indigo-600 text-white hover:bg-indigo-700"
          >
            Save
          </button>
        </div>
      </div>
    );
  }

  if (description) {
    return (
      <div
        className="px-3 py-1.5 border-b border-gray-200 dark:border-gray-700 flex items-start justify-between gap-2 group"
        onClick={(e) => e.stopPropagation()}
      >
        <p className="text-xs text-gray-600 dark:text-gray-400 flex-1 min-w-0 break-words line-clamp-3">{description}</p>
        <button
          type="button"
          onClick={onStartEdit}
          className="flex-shrink-0 p-1 rounded hover:bg-gray-200 dark:hover:bg-gray-600 text-gray-500 dark:text-gray-400"
          title="Edit description"
        >
          <Pencil className="w-3 h-3" />
        </button>
      </div>
    );
  }

  return (
    <div className="px-3 py-1.5 border-b border-gray-200 dark:border-gray-700" onClick={(e) => e.stopPropagation()}>
      <button
        type="button"
        onClick={onStartEdit}
        className="text-[10px] text-indigo-600 dark:text-indigo-400 hover:underline flex items-center gap-1"
      >
        <Plus className="w-3 h-3" />
        Add description
      </button>
    </div>
  );
}

// =============================================================================
// REQUEST BODY EXAMPLES PANEL (per content type)
// =============================================================================

type ExampleEntry = { summary?: string; value: unknown };

interface RequestBodyExamplesPanelProps {
  contentId: string;
  content: ContentTypeInfo;
  examples: ExampleEntry[] | null | undefined;
  onSave: (examples: ExampleEntry[]) => void;
}

/** Generate a single example value from inline schema using json-schema-faker */
function generateExampleFromSchema(inlineSchema: InlineSchema | null | undefined): unknown {
  const schema = buildSchemaFromInlineProperties(inlineSchema || null);
  if (!schema || typeof schema !== 'object') {
    return {};
  }
  return jsf.generate(schema);
}

function RequestBodyExamplesPanel({ contentId, content, examples, onSave }: RequestBodyExamplesPanelProps) {
  const [expanded, setExpanded] = useState(false);
  const [editingIndex, setEditingIndex] = useState<number | null>(null);
  const [editSummary, setEditSummary] = useState('');
  const [editValueStr, setEditValueStr] = useState('{}');
  const [editError, setEditError] = useState<string | null>(null);
  const [generateError, setGenerateError] = useState<string | null>(null);

  const list = Array.isArray(examples) ? examples : [];

  const hasInlineSchema = !!(
    content.inline_schema &&
    typeof content.inline_schema === 'object'
  );

  const handleGenerateFromSchema = () => {
    setGenerateError(null);
    try {
      const value = generateExampleFromSchema(content.inline_schema as InlineSchema | null);
      const newExamples = [...list, { summary: 'Generated from schema', value }];
      onSave(newExamples);
    } catch (err) {
      setGenerateError(err instanceof Error ? err.message : 'Failed to generate example');
    }
  };

  const startAdd = () => {
    setEditingIndex(-1);
    setEditSummary('');
    setEditValueStr('{}');
    setEditError(null);
  };

  const startEdit = (index: number) => {
    const ex = list[index];
    setEditingIndex(index);
    setEditSummary((ex && typeof ex.summary === 'string') ? ex.summary : '');
    try {
      setEditValueStr(typeof ex?.value !== 'undefined' ? JSON.stringify(ex.value, null, 2) : '{}');
    } catch {
      setEditValueStr('{}');
    }
    setEditError(null);
  };

  const cancelEdit = () => {
    setEditingIndex(null);
    setEditError(null);
  };

  const saveEdit = () => {
    let value: unknown;
    try {
      value = JSON.parse(editValueStr || '{}');
    } catch {
      setEditError('Invalid JSON');
      return;
    }
    const newExamples = [...list];
    const entry: ExampleEntry = { summary: editSummary.trim() || undefined, value };
    if (editingIndex === -1) {
      newExamples.push(entry);
    } else if (editingIndex !== null) {
      newExamples[editingIndex] = entry;
    }
    onSave(newExamples);
    setEditingIndex(null);
    setEditError(null);
  };

  const removeExample = (index: number) => {
    const newExamples = list.filter((_, i) => i !== index);
    onSave(newExamples);
    if (editingIndex === index) setEditingIndex(null);
    else if (editingIndex !== null && editingIndex > index) setEditingIndex(editingIndex - 1);
  };

  const valuePreview = (val: unknown): string => {
    try {
      const s = typeof val === 'string' ? val : JSON.stringify(val);
      return s.length > 36 ? s.slice(0, 33) + '...' : s;
    } catch {
      return '...';
    }
  };

  return (
    <div className="border-t border-gray-200 dark:border-gray-700 pt-2 mt-2" onClick={(e) => e.stopPropagation()}>
      <button
        type="button"
        onClick={() => setExpanded((e) => !e)}
        className="flex items-center justify-between w-full text-left text-[10px] font-medium text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-gray-200"
      >
        <span>Examples ({list.length})</span>
        <ChevronDown className={`w-3 h-3 transition-transform ${expanded ? '' : '-rotate-90'}`} />
      </button>
      {expanded && (
        <div className="mt-2 space-y-2">
          {editingIndex !== null ? (
            <div className="p-2 rounded border border-gray-200 dark:border-gray-600 bg-gray-50 dark:bg-gray-800/50 space-y-2">
              <input
                type="text"
                value={editSummary}
                onChange={(e) => setEditSummary(e.target.value)}
                placeholder="Summary (optional)"
                className="w-full px-2 py-1 text-xs rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800"
              />
              <textarea
                value={editValueStr}
                onChange={(e) => setEditValueStr(e.target.value)}
                placeholder='{"key": "value"}'
                className="w-full px-2 py-1 text-xs font-mono rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 min-h-[80px] resize-y"
                rows={3}
              />
              {editError && <p className="text-[10px] text-red-500">{editError}</p>}
              <div className="flex justify-end gap-1">
                <button type="button" onClick={cancelEdit} className="px-2 py-1 text-[10px] rounded border border-gray-300 dark:border-gray-600">Cancel</button>
                <button type="button" onClick={saveEdit} className="px-2 py-1 text-[10px] rounded bg-indigo-600 text-white hover:bg-indigo-700">Save</button>
              </div>
            </div>
          ) : (
            <div className="flex flex-col gap-1">
              <div className="flex gap-1 flex-wrap">
                <button
                  type="button"
                  onClick={startAdd}
                  className="flex items-center gap-1 px-2 py-1 text-[10px] text-indigo-600 dark:text-indigo-400 hover:bg-indigo-50 dark:hover:bg-indigo-900/20 rounded"
                >
                  <Plus className="w-3 h-3" />
                  Add example
                </button>
                <button
                  type="button"
                  onClick={handleGenerateFromSchema}
                  disabled={!hasInlineSchema}
                  title={hasInlineSchema ? 'Generate example from schema using json-schema-faker' : 'Switch to inline schema (or add one) to generate an example'}
                  className="flex items-center gap-1 px-2 py-1 text-[10px] rounded disabled:opacity-50 disabled:cursor-not-allowed text-amber-700 dark:text-amber-400 hover:bg-amber-50 dark:hover:bg-amber-900/20"
                >
                  <Sparkles className="w-3 h-3" />
                  Generate from schema
                </button>
              </div>
              {generateError && (
                <p className="text-[10px] text-red-500">{generateError}</p>
              )}
            </div>
          )}
          {list.length > 0 && (
            <ul className="space-y-1 max-h-[160px] overflow-y-auto">
              {list.map((ex, i) => (
                <li key={i} className="flex items-center gap-2 px-2 py-1 rounded bg-gray-50 dark:bg-gray-800/50 text-[10px]">
                  <span className="flex-1 min-w-0 truncate text-gray-700 dark:text-gray-300">
                    {ex.summary || `Example ${i + 1}`}: {valuePreview(ex.value)}
                  </span>
                  {editingIndex === null && (
                    <>
                      <button type="button" onClick={() => startEdit(i)} className="p-0.5 rounded hover:bg-gray-200 dark:hover:bg-gray-600" title="Edit"><Pencil className="w-3 h-3 text-gray-500" /></button>
                      <button type="button" onClick={() => removeExample(i)} className="p-0.5 rounded hover:bg-red-100 dark:hover:bg-red-900/30" title="Delete"><Trash2 className="w-3 h-3 text-red-500" /></button>
                    </>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

// =============================================================================
// REQUEST BODY ENCODING PANEL (multipart/form-data, application/x-www-form-urlencoded)
// =============================================================================

const ENCODING_STYLE_OPTIONS = [
  { value: '', label: '(default)' },
  { value: 'form', label: 'form' },
  { value: 'spaceDelimited', label: 'spaceDelimited' },
  { value: 'pipeDelimited', label: 'pipeDelimited' },
  { value: 'deepObject', label: 'deepObject' },
] as const;

interface RequestBodyEncodingPanelProps {
  contentId: string;
  content: ContentTypeInfo;
  onSave: (encoding: Record<string, Record<string, unknown>> | null) => void;
}

function RequestBodyEncodingPanel({ contentId, content, onSave }: RequestBodyEncodingPanelProps) {
  const [expanded, setExpanded] = useState(false);

  const propertyNames = React.useMemo(() => {
    if (content.inline_schema?.properties && Array.isArray(content.inline_schema.properties)) {
      const tree = buildPropertyTreeFromInlineSchema(content.inline_schema);
      return tree.map((n) => n.name);
    }
    if (content.classProperties?.length) {
      return content.classProperties.map((p: ClassPropertyDisplay) => p.name);
    }
    return [];
  }, [content.inline_schema, content.classProperties]);

  const encoding = (content.encoding && typeof content.encoding === 'object') ? content.encoding as Record<string, Record<string, unknown>> : {};

  const updateEncodingForProperty = (propName: string, field: string, value: string | boolean) => {
    const next = { ...encoding };
    const current = next[propName] ? { ...next[propName] } : {};
    if (value === '' || value === false) {
      delete (current as any)[field];
    } else {
      (current as any)[field] = value;
    }
    if (Object.keys(current).length === 0) {
      delete next[propName];
    } else {
      next[propName] = current;
    }
    const toSave = Object.keys(next).length === 0 ? null : next;
    onSave(toSave);
  };

  const getEnc = (propName: string, field: string): string | boolean => {
    const enc = encoding[propName];
    if (!enc || typeof enc !== 'object') return field === 'explode' ? false : '';
    const v = (enc as any)[field];
    if (field === 'explode' || field === 'allowReserved') return v === true;
    return typeof v === 'string' ? v : '';
  };

  const showEncoding = content.media_type === 'multipart/form-data' || content.media_type === 'application/x-www-form-urlencoded';

  if (!showEncoding) return null;

  return (
    <div className="border-t border-gray-200 dark:border-gray-700 pt-2 mt-2" onClick={(e) => e.stopPropagation()}>
      <button
        type="button"
        onClick={() => setExpanded((e) => !e)}
        className="flex items-center justify-between w-full text-left text-[10px] font-medium text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-gray-200"
      >
        <span>Encoding options</span>
        <ChevronDown className={`w-3 h-3 transition-transform ${expanded ? '' : '-rotate-90'}`} />
      </button>
      {expanded && (
        <div className="mt-2 space-y-2">
          {propertyNames.length === 0 ? (
            <p className="text-[10px] text-gray-500 dark:text-gray-400">Add properties to the schema to set encoding per property.</p>
          ) : (
            <div className="space-y-2 max-h-[220px] overflow-y-auto">
              {propertyNames.map((propName) => (
                <div key={propName} className="p-2 rounded border border-gray-200 dark:border-gray-600 bg-gray-50/50 dark:bg-gray-800/30 space-y-1.5">
                  <div className="text-[10px] font-medium text-gray-700 dark:text-gray-300">{propName}</div>
                  <div className="grid gap-1.5">
                    <div className="flex items-center gap-2">
                      <label className="text-[10px] text-gray-500 dark:text-gray-400 w-20 shrink-0">Content-Type</label>
                      <input
                        type="text"
                        value={getEnc(propName, 'contentType') as string}
                        onChange={(e) => updateEncodingForProperty(propName, 'contentType', e.target.value.trim())}
                        placeholder="e.g. image/png"
                        className="flex-1 min-w-0 px-2 py-1 text-[10px] rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800"
                      />
                    </div>
                    <div className="flex items-center gap-2">
                      <label className="text-[10px] text-gray-500 dark:text-gray-400 w-20 shrink-0">Style</label>
                      <select
                        value={(getEnc(propName, 'style') as string) || ''}
                        onChange={(e) => updateEncodingForProperty(propName, 'style', e.target.value)}
                        className="flex-1 min-w-0 px-2 py-1 text-[10px] rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800"
                      >
                        {ENCODING_STYLE_OPTIONS.map((opt) => (
                          <option key={opt.value || '_'} value={opt.value}>{opt.label}</option>
                        ))}
                      </select>
                    </div>
                    <div className="flex items-center gap-2">
                      <label className="text-[10px] text-gray-500 dark:text-gray-400 w-20 shrink-0">Explode</label>
                      <input
                        type="checkbox"
                        checked={getEnc(propName, 'explode') as boolean}
                        onChange={(e) => updateEncodingForProperty(propName, 'explode', e.target.checked)}
                        className="rounded border-gray-300 dark:border-gray-600"
                      />
                    </div>
                    <div className="flex items-center gap-2">
                      <label className="text-[10px] text-gray-500 dark:text-gray-400 w-20 shrink-0">Allow reserved</label>
                      <input
                        type="checkbox"
                        checked={getEnc(propName, 'allowReserved') as boolean}
                        onChange={(e) => updateEncodingForProperty(propName, 'allowReserved', e.target.checked)}
                        className="rounded border-gray-300 dark:border-gray-600"
                      />
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// =============================================================================
// MAIN COMPONENT
// =============================================================================

export default function PathRequestBodyNode({ data }: { data: PathRequestBodyData }) {
  const [selectedContentIndex, setSelectedContentIndex] = useState(0);
  const [descriptionEditing, setDescriptionEditing] = useState(false);
  const [descriptionDraft, setDescriptionDraft] = useState(data.description ?? '');

  useEffect(() => {
    if (selectedContentIndex >= data.contentTypes.length) {
      setSelectedContentIndex(0);
    }
  }, [data.contentTypes.length, selectedContentIndex]);

  // Sync draft when data.description changes (e.g. after save from parent)
  useEffect(() => {
    if (!descriptionEditing) {
      setDescriptionDraft(data.description ?? '');
    }
  }, [data.description, descriptionEditing]);

  const selectedContent = data.contentTypes[selectedContentIndex];

  // Schema summary for header (match response body: "$ref: ClassName" or "N props")
  const schemaLabel = selectedContent
    ? (selectedContent.class_id
        ? `$ref: ${selectedContent.class_name || 'Unknown'}`
        : (selectedContent.inline_schema?.properties?.length ?? 0) > 0
          ? `${selectedContent.inline_schema!.properties!.length} props`
          : 'Object')
    : null;

  const requestAccent = '#6366f1';
  return (
    <>
      <NodeHandleDot
        type="target"
        position={Position.Top}
        id="request-body-input"
        isConnectable={false}
        color={requestAccent}
        style={{ cursor: 'not-allowed', opacity: 0.55 }}
      />

      <NodeCard role="request" minWidth={NODE_BODY_MIN_WIDTH_PX} maxWidth={NODE_BODY_MAX_WIDTH_PX} customBorderColor={requestAccent}>
        <NodeHeader
          role="request"
          customBackground={requestAccent}
          customTextColor="#ffffff"
          icon={<FileInput size={14} />}
          iconSize={26}
          compact
          title={
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
              {data.required && <NodeBadge variant="overlay">REQ</NodeBadge>}
              <span style={{ fontWeight: 600 }}>Request</span>
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
          subtitle={
            data.description && !data.onDescriptionChange ? (
              <span title={data.description}>{data.description}</span>
            ) : undefined
          }
          badges={
            data.onDelete && (
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  data.onDelete?.();
                }}
                title="Delete request body"
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

        {/* Description: editable when onDescriptionChange is provided */}
        {data.onDescriptionChange && (
          <DescriptionEditor
            description={data.description}
            isEditing={descriptionEditing}
            onStartEdit={() => setDescriptionEditing(true)}
            onCancel={() => { setDescriptionEditing(false); setDescriptionDraft(data.description ?? ''); }}
            onSave={(value) => {
              data.onDescriptionChange?.(value);
              setDescriptionEditing(false);
              setDescriptionDraft(value);
            }}
            draft={descriptionDraft}
            onDraftChange={setDescriptionDraft}
          />
        )}

        {/* Content type tabs with schema binding hint (#387) */}
        {data.contentTypes.length > 1 && (
          <div className="px-3 pt-2 flex gap-1 overflow-x-auto">
            {data.contentTypes.map((ct, index) => {
              const schemaHint = ct.class_id && ct.class_name
                ? ct.class_name
                : (ct.inline_schema?.properties?.length != null ? `${ct.inline_schema.properties.length} props` : null);
              const label = schemaHint ? `${ct.media_type.replace(/^[^/]+\//, '')} → ${schemaHint}` : ct.media_type;
              return (
                <button
                  key={ct.id}
                  onClick={(e) => {
                    e.stopPropagation();
                    setSelectedContentIndex(index);
                  }}
                  title={ct.media_type + (schemaHint ? ` (${schemaHint})` : '')}
                  className={`
                    px-2 py-1 text-[10px] rounded-t transition-colors whitespace-nowrap truncate max-w-[140px]
                    ${selectedContentIndex === index
                      ? 'bg-gray-100 dark:bg-gray-700 text-gray-900 dark:text-white font-medium'
                      : 'text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700/50'
                    }
                  `}
                >
                  {label}
                </button>
              );
            })}
          </div>
        )}

        {/* Content: badge (e.g. $ref: BlogPost json) + panel with drop zone */}
        <div className="p-3 space-y-2">
          {data.contentTypes.length === 0 ? (
            <div className="flex flex-col items-center gap-2 text-xs text-gray-500 dark:text-gray-400 py-4">
              <AlertCircle className="w-4 h-4" />
              <span>No content types defined</span>
              {data.onAddContentType && (
                <AddContentTypeDropdown
                  existingMediaTypes={[]}
                  onSelect={data.onAddContentType}
                  triggerClassName="mt-2 px-3 py-1.5 text-xs bg-emerald-500 text-white rounded hover:bg-emerald-600 transition-colors"
                />
              )}
            </div>
          ) : selectedContent ? (
            <>
              <ContentTypeBadge content={selectedContent} />
              <RequestBodyContentTypePanel
                content={selectedContent}
                onPropertyDrop={
                  data.onPropertyDrop && selectedContent.id
                    ? (propData, parentId) => data.onPropertyDrop!(selectedContent.id, propData, parentId)
                    : undefined
                }
                onClassDrop={
                  data.onClassDrop && selectedContent.id
                    ? (classData, action) => data.onClassDrop!(selectedContent.id, classData, action)
                    : undefined
                }
                onShowClassDropDialog={data.onShowClassDropDialog}
                onPropertyEdit={
                  data.onPropertyEdit
                    ? (propId) => data.onPropertyEdit?.(selectedContent.id, propId)
                    : undefined
                }
                onPropertyDelete={
                  data.onPropertyDelete
                    ? (propId) => data.onPropertyDelete?.(selectedContent.id, propId)
                    : undefined
                }
              />
              {data.onExamplesChange && selectedContent.id && (
                <RequestBodyExamplesPanel
                  contentId={selectedContent.id}
                  content={selectedContent}
                  examples={selectedContent.examples}
                  onSave={(examples) => data.onExamplesChange!(selectedContent.id, examples)}
                />
              )}
              {data.onEncodingChange && selectedContent.id && (
                <RequestBodyEncodingPanel
                  contentId={selectedContent.id}
                  content={selectedContent}
                  onSave={(encoding) => data.onEncodingChange!(selectedContent.id, encoding)}
                />
              )}
            </>
          ) : null}
        </div>

        {/* Footer: content type count, Add content type dropdown, Edit */}
        <div className="px-3 pb-2 flex items-center justify-between gap-2 text-[10px] text-gray-500 dark:text-gray-400">
          <span>{data.contentTypes.length} content type(s)</span>
          <div className="flex items-center gap-1">
            {data.onAddContentType && (
              <AddContentTypeDropdown
                existingMediaTypes={data.contentTypes.map((ct) => ct.media_type)}
                onSelect={data.onAddContentType}
              />
            )}
            {data.onEdit && (
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  data.onEdit?.();
                }}
                className="flex items-center gap-1 px-2 py-1 hover:bg-gray-100 dark:hover:bg-gray-700 rounded transition-colors"
              >
                <Pencil className="w-3 h-3" />
                Edit
              </button>
            )}
          </div>
        </div>
      </NodeCard>

      <NodeHandleDot
        type="source"
        position={Position.Bottom}
        id="request-body-output"
        color={requestAccent}
      />
    </>
  );
}
