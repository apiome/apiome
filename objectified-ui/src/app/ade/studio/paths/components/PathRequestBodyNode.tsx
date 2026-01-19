// Path Request Body Node Component for React Flow Canvas
'use client';

import React, { useState, useEffect } from 'react';
import { FileJson, Link2, Pencil, Trash2, ChevronRight, ChevronDown, Plus, AlertCircle } from 'lucide-react';
import { Handle, Position } from '@xyflow/react';
import {
  buildPropertyTreeFromInlineSchema,
  type InlineSchema,
  type PropertyTreeNode,
} from '../../../../../../lib/utils/inline-schema-utils';

// =============================================================================
// TYPES
// =============================================================================

export interface ContentTypeInfo {
  id: string;
  media_type: string;
  class_id?: string | null;
  class_name?: string | null;
  inline_schema?: InlineSchema | null;
  encoding?: Record<string, any> | null;
  examples?: any[] | null;
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
  onPropertyEdit?: (contentId: string, propertyId: string) => void;
  onPropertyDelete?: (contentId: string, propertyId: string) => void;
  onAddContentType?: () => void;
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
// INLINE SCHEMA VIEWER
// =============================================================================

interface InlineSchemaViewerProps {
  content: ContentTypeInfo;
  onPropertyDrop?: (propertyData: any, parentId?: string) => void;
  onPropertyEdit?: (propertyId: string) => void;
  onPropertyDelete?: (propertyId: string) => void;
}

function InlineSchemaViewer({
  content,
  onPropertyDrop,
  onPropertyEdit,
  onPropertyDelete,
}: InlineSchemaViewerProps) {
  const [expandedProps, setExpandedProps] = useState<Set<string>>(new Set());
  const [isDragOver, setIsDragOver] = useState(false);
  const dragCounterRef = React.useRef(0);

  const propertyTree = buildPropertyTreeFromInlineSchema(content.inline_schema || null);

  const toggleExpanded = (propId: string) => {
    setExpandedProps((prev) => {
      const next = new Set(prev);
      if (next.has(propId)) {
        next.delete(propId);
      } else {
        next.add(propId);
      }
      return next;
    });
  };

  // Handle root-level drop
  const handleDragEnter = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounterRef.current++;
    setIsDragOver(true);
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
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

    if (!onPropertyDrop) return;

    const dataStr = e.dataTransfer.getData('application/json');
    if (dataStr) {
      try {
        const dropData = JSON.parse(dataStr);
        if (dropData.type === 'property') {
          onPropertyDrop(dropData, undefined);
        }
      } catch (err) {
        console.error('Failed to parse drop data:', err);
      }
    }
  };

  if (propertyTree.length === 0) {
    return (
      <div
        className={`p-3 text-center text-xs text-gray-400 dark:text-gray-500 border border-dashed rounded transition-colors ${
          isDragOver 
            ? 'border-green-400 bg-green-50 dark:bg-green-900/20' 
            : 'border-gray-300 dark:border-gray-600'
        }`}
        onDragEnter={handleDragEnter}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
      >
        <Plus className="w-4 h-4 mx-auto mb-1 opacity-50" />
        Drop properties here
      </div>
    );
  }

  return (
    <div
      className={`rounded border transition-colors ${
        isDragOver 
          ? 'border-green-400 bg-green-50 dark:bg-green-900/20' 
          : 'border-gray-200 dark:border-gray-700'
      }`}
      onDragEnter={handleDragEnter}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      <div className="py-1 max-h-[200px] overflow-y-auto">
        {propertyTree.map((prop) => (
          <PropertyTreeItem
            key={prop.id}
            property={prop}
            depth={0}
            expanded={expandedProps.has(prop.id)}
            onToggle={() => toggleExpanded(prop.id)}
            onEdit={onPropertyEdit ? () => onPropertyEdit(prop.id) : undefined}
            onDelete={onPropertyDelete ? () => onPropertyDelete(prop.id) : undefined}
            onDrop={onPropertyDrop}
          />
        ))}
      </div>
    </div>
  );
}

// =============================================================================
// MAIN COMPONENT
// =============================================================================

export default function PathRequestBodyNode({ data }: { data: PathRequestBodyData }) {
  const [selectedContentIndex, setSelectedContentIndex] = useState(0);

  // Reset selected content when content types change
  useEffect(() => {
    if (selectedContentIndex >= data.contentTypes.length) {
      setSelectedContentIndex(0);
    }
  }, [data.contentTypes.length, selectedContentIndex]);

  const selectedContent = data.contentTypes[selectedContentIndex];
  const hasMultipleContentTypes = data.contentTypes.length > 1;

  return (
    <>
      {/* Input handle at TOP - not connectable (request bodies don't have inputs) */}
      <Handle
        type="target"
        position={Position.Top}
        id="request-body-input"
        isConnectable={false}
        className="!w-3 !h-2 !rounded-t-md !rounded-b-none bg-indigo-500 !cursor-not-allowed opacity-50"
      />

      <div className="bg-white dark:bg-gray-800 rounded-xl border-2 border-indigo-500 shadow-xl min-w-[240px] max-w-[320px] cursor-pointer relative group">
        {/* Delete button */}
        {data.onDelete && (
          <button
            onClick={(e) => {
              e.stopPropagation();
              data.onDelete?.();
            }}
            className="absolute -top-2 -right-2 bg-red-500 text-white rounded-full p-1.5 opacity-0 group-hover:opacity-100 transition-opacity shadow-lg hover:bg-red-600 z-10"
            title="Delete request body"
          >
            <Trash2 size={14} />
          </button>
        )}

        {/* Header */}
        <div className="bg-gradient-to-r from-indigo-500 to-purple-500 text-white px-4 py-2.5 rounded-t-lg">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <FileJson className="w-4 h-4" />
              <span className="font-bold text-sm truncate">{data.name}</span>
            </div>
            <div className="flex items-center gap-1">
              {data.required && (
                <div className="px-1.5 py-0.5 bg-red-500/80 rounded text-[10px] font-bold">
                  REQ
                </div>
              )}
              {data.onEdit && (
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    data.onEdit?.();
                  }}
                  className="p-1 hover:bg-white/20 rounded"
                  title="Edit request body"
                >
                  <Pencil className="w-3 h-3" />
                </button>
              )}
            </div>
          </div>
          {data.description && (
            <div className="text-xs text-white/80 mt-1 line-clamp-2">
              {data.description}
            </div>
          )}
        </div>

        {/* Content Types */}
        <div className="p-3">
          {data.contentTypes.length === 0 ? (
            <div className="flex items-center gap-2 text-xs text-gray-400 dark:text-gray-500">
              <AlertCircle className="w-4 h-4" />
              <span>No content types defined</span>
            </div>
          ) : (
            <>
              {/* Content type tabs/badges */}
              <div className="flex flex-wrap gap-1.5 mb-3">
                {data.contentTypes.map((content, index) => (
                  <button
                    key={content.id}
                    onClick={(e) => {
                      e.stopPropagation();
                      setSelectedContentIndex(index);
                    }}
                    className={`transition-all ${
                      selectedContentIndex === index
                        ? 'ring-2 ring-indigo-400 ring-offset-1'
                        : 'opacity-70 hover:opacity-100'
                    }`}
                  >
                    <ContentTypeBadge content={content} />
                  </button>
                ))}
                {data.onAddContentType && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      data.onAddContentType?.();
                    }}
                    className="flex items-center gap-1 px-2 py-1 rounded-full text-[10px] font-medium bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-600"
                    title="Add content type"
                  >
                    <Plus className="w-3 h-3" />
                    <span>Add</span>
                  </button>
                )}
              </div>

              {/* Selected content type details */}
              {selectedContent && (
                <div>
                  {selectedContent.class_id ? (
                    // Class reference view
                    <div className="p-3 bg-gray-50 dark:bg-gray-700/50 rounded-lg">
                      <div className="flex items-center gap-2 text-xs">
                        <Link2 className="w-4 h-4 text-indigo-500" />
                        <span className="text-gray-600 dark:text-gray-400">References:</span>
                        <code className="px-2 py-0.5 bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-300 rounded font-mono text-[11px]">
                          {selectedContent.class_name || 'Unknown Class'}
                        </code>
                      </div>
                    </div>
                  ) : selectedContent.inline_schema ? (
                    // Inline schema view with property tree
                    <InlineSchemaViewer
                      content={selectedContent}
                      onPropertyDrop={
                        data.onPropertyDrop
                          ? (propData, parentId) =>
                              data.onPropertyDrop?.(selectedContent.id, propData, parentId)
                          : undefined
                      }
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
                  ) : (
                    // Empty state
                    <div className="p-3 text-center text-xs text-gray-400 dark:text-gray-500">
                      No schema defined
                    </div>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      </div>

      {/* Output handle at BOTTOM - connects TO operations for vertical flow */}
      <Handle
        type="source"
        position={Position.Bottom}
        id="request-body-output"
        className="!w-3 !h-2 !rounded-b-md !rounded-t-none bg-indigo-500"
      />
    </>
  );
}
