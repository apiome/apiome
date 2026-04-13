'use client';

import React, { useState, useEffect, useCallback } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { FileJson, Link2, Pencil, Plus, ChevronDown, ChevronRight, Trash2, Link, Unlink, RefreshCw } from 'lucide-react';
import { Button } from '../../../../components/ui/Button';
import { Input } from '../../../../components/ui/Input';
import { Label } from '../../../../components/ui/Label';
import { Checkbox } from '../../../../components/ui/Checkbox';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../../../../components/ui/Select';
import ReuseSearchCombobox from './ReuseSearchCombobox';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '../../../../components/ui/Tabs';
import { useDarkMode } from '../../../../hooks/useDarkMode';
import { useDialog } from '../../../../components/providers/DialogProvider';
import { useStudio } from '../../StudioContext';
import {
  getSharedPathRequestBodies,
  getLinkedRequestBodyForOperation,
  createSharedPathRequestBody,
  linkRequestBodyToOperation,
  unlinkRequestBodyFromOperation,
  addRequestBodyContentType,
  updateRequestBodyContentType,
  deleteRequestBodyContentType,
  convertClassToInlineSchema,
  initializeInlineSchema,
  setContentTypeClassReference,
  addPropertyToInlineSchema,
  updateInlineSchemaProperty,
  deleteInlineSchemaProperty,
} from '../../../../../../lib/db/helper-shared-path-request-bodies';
import { getClassesWithPropertiesAndTags } from '../../../../../../lib/db/helper';
import {
  buildPropertyTreeFromInlineSchema,
  type InlineSchema,
  type PropertyTreeNode,
} from '../../../../../../lib/utils/inline-schema-utils';

// =============================================================================
// TYPES
// =============================================================================

interface ContentTypeInfo {
  id: string;
  media_type: string;
  class_id?: string | null;
  class_name?: string | null;
  inline_schema?: InlineSchema | null;
  encoding?: Record<string, unknown> | null;
  examples?: unknown[] | null;
}

interface RequestBodyInfo {
  id: string;
  name: string;
  description?: string;
  required?: boolean;
  content_types: ContentTypeInfo[];
}

interface RequestBodySectionProps {
  operationId: string;
  versionPathId: string;
  onRefresh?: () => void;
  /** When the Paths canvas (or parent) refreshes operation links, bump this to reload. */
  refreshKey?: number;
}

// =============================================================================
// MEDIA TYPE OPTIONS
// =============================================================================

const MEDIA_TYPE_OPTIONS = [
  { value: 'application/json', label: 'JSON (application/json)' },
  { value: 'application/xml', label: 'XML (application/xml)' },
  { value: 'multipart/form-data', label: 'Multipart (multipart/form-data)' },
  { value: 'application/x-www-form-urlencoded', label: 'Form URL Encoded' },
  { value: 'text/plain', label: 'Plain Text (text/plain)' },
  { value: 'application/octet-stream', label: 'Binary (application/octet-stream)' },
];

// =============================================================================
// INLINE PROPERTY TREE COMPONENT
// =============================================================================

interface PropertyTreeItemProps {
  property: PropertyTreeNode;
  depth: number;
  expanded: boolean;
  onToggle: () => void;
  onEdit?: () => void;
  onDelete?: () => void;
}

function PropertyTreeItem({ property, depth, expanded, onToggle, onEdit, onDelete }: PropertyTreeItemProps) {
  const hasChildren = property.children.length > 0;
  const canAcceptChildren = property.data?.type === 'object' || property.data?.type === 'array';

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
        className="flex items-center gap-1 px-2 py-1 text-xs cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700 rounded group"
        style={{ paddingLeft: `${8 + depth * 12}px` }}
      >
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

        <span className="font-medium text-gray-800 dark:text-gray-200 truncate">
          {property.name}
        </span>

        {isRequired && <span className="text-red-500 text-[10px]">*</span>}

        <span className="text-gray-500 dark:text-gray-400 text-[10px] ml-auto">
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
  inlineSchema: InlineSchema | null;
  contentId: string;
  onPropertyEdit?: (propertyId: string) => void;
  onPropertyDelete?: (propertyId: string) => void;
  onAddProperty?: () => void;
}

function InlineSchemaViewer({
  inlineSchema,
  contentId,
  onPropertyEdit,
  onPropertyDelete,
  onAddProperty,
}: InlineSchemaViewerProps) {
  const [expandedProps, setExpandedProps] = useState<Set<string>>(new Set());
  const propertyTree = buildPropertyTreeFromInlineSchema(inlineSchema);

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

  if (propertyTree.length === 0) {
    return (
      <div className="p-3 text-center text-xs text-gray-400 dark:text-gray-500 border border-dashed border-gray-300 dark:border-gray-600 rounded">
        <Plus className="w-4 h-4 mx-auto mb-1 opacity-50" />
        <div>No properties defined</div>
        {onAddProperty && (
          <button
            onClick={onAddProperty}
            className="mt-2 px-3 py-1 text-xs bg-indigo-500 text-white rounded hover:bg-indigo-600"
          >
            Add Property
          </button>
        )}
      </div>
    );
  }

  return (
    <div className="border border-gray-200 dark:border-gray-700 rounded">
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
          />
        ))}
      </div>
      {onAddProperty && (
        <div className="p-2 border-t border-gray-200 dark:border-gray-700">
          <button
            onClick={onAddProperty}
            className="flex items-center gap-1 text-xs text-indigo-500 hover:text-indigo-600"
          >
            <Plus className="w-3 h-3" />
            Add Property
          </button>
        </div>
      )}
    </div>
  );
}

// =============================================================================
// CONTENT TYPE EDITOR
// =============================================================================

interface ContentTypeEditorProps {
  content: ContentTypeInfo;
  classes: Array<{ id: string; name: string }>;
  onSchemaTypeChange: (type: 'reference' | 'inline') => void;
  onClassChange: (classId: string) => void;
  onConvertToInline: () => void;
  onPropertyEdit?: (propertyId: string) => void;
  onPropertyDelete?: (propertyId: string) => void;
  onAddProperty?: () => void;
  onDelete: () => void;
}

function ContentTypeEditor({
  content,
  classes,
  onSchemaTypeChange,
  onClassChange,
  onConvertToInline,
  onPropertyEdit,
  onPropertyDelete,
  onAddProperty,
  onDelete,
}: ContentTypeEditorProps) {
  const isDark = useDarkMode();
  const isReference = !!content.class_id;
  const isInline = !content.class_id && !!content.inline_schema;

  return (
    <div className={`p-4 rounded-lg border ${isDark ? 'border-slate-700' : 'border-slate-200'}`}>
      {/* Header */}
      <div className="flex justify-between items-center mb-4">
        <code className="text-xs font-mono px-2 py-1 bg-gray-100 dark:bg-gray-700 rounded">
          {content.media_type}
        </code>
        <button
          type="button"
          onClick={onDelete}
          className="p-1.5 rounded text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20"
          aria-label="Delete"
        >
          <Trash2 className="w-4 h-4" />
        </button>
      </div>

      {/* Schema Type Selector */}
      <div className="mb-4">
        <Label className="block text-[10px] font-medium text-gray-600 dark:text-gray-400 mb-1">
          Schema Type
        </Label>
        <div className="flex gap-2">
          <Button
            type="button"
            size="sm"
            variant={isReference ? 'default' : 'outline'}
            onClick={() => onSchemaTypeChange('reference')}
            className={`flex-1 text-xs ${isReference ? 'bg-indigo-600 hover:bg-indigo-700' : ''}`}
          >
            <Link2 className="w-3 h-3 mr-1" />
            Class Reference
          </Button>
          <Button
            type="button"
            size="sm"
            variant={isInline ? 'default' : 'outline'}
            onClick={() => onSchemaTypeChange('inline')}
            className={`flex-1 text-xs ${isInline ? 'bg-emerald-600 hover:bg-emerald-700' : ''}`}
          >
            <Pencil className="w-3 h-3 mr-1" />
            Inline Schema
          </Button>
        </div>
      </div>

      {/* Reference Mode: Class Selector */}
      {isReference && (
        <div>
          <Label className="text-[10px] font-medium text-gray-600 dark:text-gray-400 mb-1 block">
            Reuse class ($ref)
          </Label>
          <ReuseSearchCombobox
            aria-label="Select class for request body schema"
            items={classes.map((cls) => ({ id: cls.id, label: cls.name }))}
            value={content.class_id || ''}
            onValueChange={onClassChange}
            placeholder="Search classes…"
            searchPlaceholder="Filter by name…"
            emptyText="No classes match."
            triggerClassName="h-9 text-xs"
          />
          {content.class_id && (
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={onConvertToInline}
              className="mt-2 text-xs"
            >
              Convert to Inline (copy properties)
            </Button>
          )}
        </div>
      )}

      {/* Inline Mode: Property Tree */}
      {isInline && (
        <InlineSchemaViewer
          inlineSchema={content.inline_schema || null}
          contentId={content.id}
          onPropertyEdit={onPropertyEdit}
          onPropertyDelete={onPropertyDelete}
          onAddProperty={onAddProperty}
        />
      )}

      {/* Neither mode: Empty state */}
      {!isReference && !isInline && (
        <div className="p-3 text-center text-xs text-gray-400 dark:text-gray-500">
          Select a schema type above
        </div>
      )}
    </div>
  );
}

// =============================================================================
// MAIN COMPONENT
// =============================================================================

export default function RequestBodySection({
  operationId,
  versionPathId,
  onRefresh,
  refreshKey,
}: RequestBodySectionProps) {
  const isDark = useDarkMode();
  const { alert: alertDialog, confirm: confirmDialog } = useDialog();
  const { selectedVersionId } = useStudio();

  // State
  const [isLoading, setIsLoading] = useState(true);
  const [linkedRequestBody, setLinkedRequestBody] = useState<RequestBodyInfo | null>(null);
  const [availableRequestBodies, setAvailableRequestBodies] = useState<RequestBodyInfo[]>([]);
  const [classes, setClasses] = useState<Array<{ id: string; name: string }>>([]);
  const [selectedContentTab, setSelectedContentTab] = useState(0);

  // Dialogs
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [newName, setNewName] = useState('');
  const [newDescription, setNewDescription] = useState('');
  const [newRequired, setNewRequired] = useState(true);
  const [addContentDialogOpen, setAddContentDialogOpen] = useState(false);
  const [newMediaType, setNewMediaType] = useState('application/json');
  const [newContentSchemaType, setNewContentSchemaType] = useState<'reference' | 'inline'>('inline');
  const [newContentClassId, setNewContentClassId] = useState('');
  const [addPropertyDialogOpen, setAddPropertyDialogOpen] = useState(false);
  const [newPropertyName, setNewPropertyName] = useState('');
  const [newPropertyType, setNewPropertyType] = useState('string');
  const [currentContentId, setCurrentContentId] = useState<string | null>(null);

  // Load request-body / link data (does NOT include classes — see loadClasses below).
  // Keeping this separate means a refreshKey bump only refetches the persisted
  // request-body rows, not the full class list.
  const loadRequestBodyData = useCallback(async () => {
    setIsLoading(true);
    try {
      // Load linked request body
      const linkedResult = await getLinkedRequestBodyForOperation(operationId);
      const linkedData = JSON.parse(linkedResult);
      if (linkedData.success && linkedData.requestBody) {
        // Parse content types
        const contentTypes = (linkedData.requestBody.content_types || []).map((ct: ContentTypeInfo) => ({
          ...ct,
          inline_schema: typeof ct.inline_schema === 'string' ? JSON.parse(ct.inline_schema) : ct.inline_schema,
          encoding: typeof ct.encoding === 'string' ? JSON.parse(ct.encoding) : ct.encoding,
          examples: typeof ct.examples === 'string' ? JSON.parse(ct.examples) : ct.examples,
        }));
        setLinkedRequestBody({
          ...linkedData.requestBody,
          content_types: contentTypes,
        });
      } else {
        setLinkedRequestBody(null);
      }

      // Load available request bodies for this path
      const availableResult = await getSharedPathRequestBodies(versionPathId);
      const availableData = JSON.parse(availableResult);
      if (availableData.success) {
        setAvailableRequestBodies(availableData.requestBodies || []);
      }
    } catch (error) {
      console.error('Error loading request body data:', error);
    } finally {
      setIsLoading(false);
    }
  }, [operationId, versionPathId]);

  // Load classes for reference selection — only needs to run when the version changes.
  const loadClasses = useCallback(async () => {
    if (!selectedVersionId) return;
    try {
      const classesResult = await getClassesWithPropertiesAndTags(selectedVersionId);
      const classesData = JSON.parse(classesResult as string);
      const uniqueClasses = classesData.reduce(
        (acc: Array<{ id: string; name: string }>, cls: { id: string; name: string }) => {
          if (!acc.find((c) => c.id === cls.id)) {
            acc.push({ id: cls.id, name: cls.name });
          }
          return acc;
        },
        []
      );
      setClasses(uniqueClasses);
    } catch (error) {
      console.error('Error loading classes:', error);
    }
  }, [selectedVersionId]);

  // Reload request-body/link data whenever the operation/path changes OR when the
  // parent signals a canvas refresh via refreshKey.  Classes are intentionally
  // excluded here to avoid an extra round-trip on every canvas refresh.
  useEffect(() => {
    loadRequestBodyData();
  }, [loadRequestBodyData, refreshKey]);

  // Classes only need to reload when the version changes.
  useEffect(() => {
    loadClasses();
  }, [loadClasses]);

  // Handlers
  const handleCreateRequestBody = async () => {
    if (!newName.trim()) {
      await alertDialog({
        title: 'Error',
        message: 'Please enter a name for the request body',
        variant: 'error',
      });
      return;
    }

    try {
      const result = await createSharedPathRequestBody(
        versionPathId,
        newName.trim(),
        newDescription.trim() || undefined,
        newRequired
      );
      const data = JSON.parse(result);

      if (data.success) {
        // Link to operation
        await linkRequestBodyToOperation(operationId, data.requestBody.id);

        // Add default content type
        await addRequestBodyContentType(
          data.requestBody.id,
          'application/json',
          undefined,
          { type: 'object', properties: [] }
        );

        setCreateDialogOpen(false);
        setNewName('');
        setNewDescription('');
        setNewRequired(true);
        onRefresh?.();
      } else {
        await alertDialog({
          title: 'Error',
          message: data.error || 'Failed to create request body',
          variant: 'error',
        });
      }
    } catch (error) {
      console.error('Error creating request body:', error);
      await alertDialog({
        title: 'Error',
        message: 'Failed to create request body',
        variant: 'error',
      });
    }
  };

  const handleLinkRequestBody = async (requestBodyId: string) => {
    try {
      const result = await linkRequestBodyToOperation(operationId, requestBodyId);
      const data = JSON.parse(result);

      if (data.success) {
        onRefresh?.();
      } else {
        await alertDialog({
          title: 'Error',
          message: data.error || 'Failed to link request body',
          variant: 'error',
        });
      }
    } catch (error) {
      console.error('Error linking request body:', error);
    }
  };

  const handleUnlinkRequestBody = async () => {
    const confirmed = await confirmDialog({
      title: 'Unlink Request Body',
      message: 'Are you sure you want to unlink this request body from the operation?',
      variant: 'warning',
      confirmLabel: 'Unlink',
      cancelLabel: 'Cancel',
    });

    if (!confirmed) return;

    try {
      const result = await unlinkRequestBodyFromOperation(operationId);
      const data = JSON.parse(result);

      if (data.success) {
        setLinkedRequestBody(null);
        onRefresh?.();
      }
    } catch (error) {
      console.error('Error unlinking request body:', error);
    }
  };

  const handleSchemaTypeChange = async (contentId: string, type: 'reference' | 'inline') => {
    try {
      if (type === 'inline') {
        await initializeInlineSchema(contentId);
      } else {
        // For reference, we'll need to select a class first
        if (classes.length > 0) {
          await setContentTypeClassReference(contentId, classes[0].id);
        }
      }
      onRefresh?.();
    } catch (error) {
      console.error('Error changing schema type:', error);
    }
  };

  const handleClassChange = async (contentId: string, classId: string) => {
    try {
      await setContentTypeClassReference(contentId, classId);
      onRefresh?.();
    } catch (error) {
      console.error('Error changing class reference:', error);
    }
  };

  const handleConvertToInline = async (contentId: string) => {
    const confirmed = await confirmDialog({
      title: 'Convert to Inline Schema',
      message: 'This will copy all properties from the referenced class into an inline schema. Continue?',
      variant: 'info',
      confirmLabel: 'Convert',
      cancelLabel: 'Cancel',
    });

    if (!confirmed) return;

    try {
      const result = await convertClassToInlineSchema(contentId);
      const data = JSON.parse(result);

      if (data.success) {
        onRefresh?.();
      } else {
        await alertDialog({
          title: 'Error',
          message: data.error || 'Failed to convert to inline schema',
          variant: 'error',
        });
      }
    } catch (error) {
      console.error('Error converting to inline:', error);
    }
  };

  const handleAddContentType = async () => {
    if (!linkedRequestBody) return;

    if (newContentSchemaType === 'reference' && !newContentClassId) {
      await alertDialog({
        title: 'Select a class',
        message: 'Please select a class for the schema reference.',
        variant: 'error',
      });
      return;
    }

    try {
      const result = await addRequestBodyContentType(
        linkedRequestBody.id,
        newMediaType,
        newContentSchemaType === 'reference' ? newContentClassId : undefined,
        newContentSchemaType === 'inline' ? { type: 'object', properties: [] } : undefined
      );
      const data = JSON.parse(result);

      if (data.success) {
        setAddContentDialogOpen(false);
        setNewMediaType('application/json');
        setNewContentSchemaType('inline');
        setNewContentClassId('');
        onRefresh?.();
      } else {
        await alertDialog({
          title: 'Error',
          message: data.error || 'Failed to add content type',
          variant: 'error',
        });
      }
    } catch (error) {
      console.error('Error adding content type:', error);
    }
  };

  const handleDeleteContentType = async (contentId: string) => {
    const confirmed = await confirmDialog({
      title: 'Delete Content Type',
      message: 'Are you sure you want to delete this content type?',
      variant: 'danger',
      confirmLabel: 'Delete',
      cancelLabel: 'Cancel',
    });

    if (!confirmed) return;

    try {
      const result = await deleteRequestBodyContentType(contentId);
      const data = JSON.parse(result);

      if (data.success) {
        onRefresh?.();
      }
    } catch (error) {
      console.error('Error deleting content type:', error);
    }
  };

  const handleAddProperty = async () => {
    if (!currentContentId || !newPropertyName.trim()) return;

    try {
      const result = await addPropertyToInlineSchema(
        currentContentId,
        {
          name: newPropertyName.trim(),
          data: { type: newPropertyType },
        }
      );
      const data = JSON.parse(result);

      if (data.success) {
        setAddPropertyDialogOpen(false);
        setNewPropertyName('');
        setNewPropertyType('string');
        setCurrentContentId(null);
        onRefresh?.();
      } else {
        await alertDialog({
          title: 'Error',
          message: data.error || 'Failed to add property',
          variant: 'error',
        });
      }
    } catch (error) {
      console.error('Error adding property:', error);
    }
  };

  const handleDeleteProperty = async (contentId: string, propertyId: string) => {
    const confirmed = await confirmDialog({
      title: 'Delete Property',
      message: 'Are you sure you want to delete this property?',
      variant: 'danger',
      confirmLabel: 'Delete',
      cancelLabel: 'Cancel',
    });

    if (!confirmed) return;

    try {
      const result = await deleteInlineSchemaProperty(contentId, propertyId, true);
      const data = JSON.parse(result);

      if (data.success) {
        onRefresh?.();
      }
    } catch (error) {
      console.error('Error deleting property:', error);
    }
  };

  // Render loading state
  if (isLoading) {
    return (
      <div className="py-4 text-center">
        <span className="text-xs text-gray-500 dark:text-gray-400">Loading...</span>
      </div>
    );
  }

  // Render linked request body
  if (linkedRequestBody) {
    const contentTypes = linkedRequestBody.content_types || [];

    return (
      <div>
        {/* Header with unlink button */}
        <div className="flex justify-between items-center mb-4">
          <div className="flex items-center gap-2">
            <FileJson className="w-4 h-4 text-indigo-500" />
            <span className="text-xs font-semibold text-gray-700 dark:text-gray-300">
              {linkedRequestBody.name}
            </span>
            {linkedRequestBody.required && (
              <span className="px-1.5 py-0.5 text-[10px] font-medium bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-300 rounded">
                Required
              </span>
            )}
          </div>
          <div className="flex gap-1">
            <button
              type="button"
              onClick={loadRequestBodyData}
              className="p-1.5 rounded hover:bg-gray-100 dark:hover:bg-gray-700"
              title="Refresh"
            >
              <RefreshCw className="w-4 h-4" />
            </button>
            <button
              type="button"
              onClick={handleUnlinkRequestBody}
              className="p-1.5 rounded text-amber-500 hover:bg-amber-50 dark:hover:bg-amber-900/20"
              title="Unlink"
            >
              <Unlink className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Description */}
        {linkedRequestBody.description && (
          <div className="text-xs text-gray-500 dark:text-gray-400 mb-3">
            {linkedRequestBody.description}
          </div>
        )}

        {/* Content Types Tabs */}
        {contentTypes.length > 0 ? (
          <div>
            <div className="flex justify-between items-center mb-2">
              <Tabs
                value={String(Math.min(selectedContentTab, contentTypes.length - 1))}
                onValueChange={(v) => setSelectedContentTab(Number(v))}
              >
                <TabsList className="h-8 min-h-8 text-xs">
                  {contentTypes.map((ct, index) => (
                    <TabsTrigger key={ct.id} value={String(index)} className="text-xs py-1">
                      {ct.media_type.replace('application/', '')}
                    </TabsTrigger>
                  ))}
                </TabsList>
              </Tabs>
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() => setAddContentDialogOpen(true)}
                className="text-xs"
              >
                <Plus className="w-3.5 h-3.5 mr-1" />
                Add
              </Button>
            </div>

            {/* Selected Content Type Editor */}
            {contentTypes.map((ct, index) => (
              <TabsContent key={ct.id} value={String(index)} className="mt-2">
                <ContentTypeEditor
                  content={ct}
                  classes={classes}
                  onSchemaTypeChange={(type) => handleSchemaTypeChange(ct.id, type)}
                  onClassChange={(classId) => handleClassChange(ct.id, classId)}
                  onConvertToInline={() => handleConvertToInline(ct.id)}
                  onPropertyEdit={(propId) => {
                    console.log('Edit property:', propId);
                  }}
                  onPropertyDelete={(propId) => handleDeleteProperty(ct.id, propId)}
                  onAddProperty={() => {
                    setCurrentContentId(ct.id);
                    setAddPropertyDialogOpen(true);
                  }}
                  onDelete={() => handleDeleteContentType(ct.id)}
                />
              </TabsContent>
            ))}
          </div>
        ) : (
          <div className={`py-6 px-4 text-center rounded-lg border border-dashed ${isDark ? 'border-slate-700' : 'border-slate-300'}`}>
            <span className="text-xs text-gray-500 dark:text-gray-400">No content types defined</span>
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => setAddContentDialogOpen(true)}
              className="mt-2 text-xs"
            >
              <Plus className="w-3.5 h-3.5 mr-1" />
              Add Content Type
            </Button>
          </div>
        )}

        {/* Add Content Type Dialog — schema binding per content type (#387) */}
        <Dialog.Root
          open={addContentDialogOpen}
          onOpenChange={(open) => {
            setAddContentDialogOpen(open);
            if (!open) {
              setNewContentSchemaType('inline');
              setNewContentClassId('');
            }
          }}
        >
          <Dialog.Portal>
            <Dialog.Overlay className="fixed inset-0 bg-black/50 z-[9998]" />
            <Dialog.Content
              aria-describedby={undefined}
              className="fixed left-1/2 top-1/2 z-[9999] w-full max-w-sm -translate-x-1/2 -translate-y-1/2 rounded-lg bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 shadow-xl p-4"
            >
              <Dialog.Title className="text-sm font-semibold text-gray-900 dark:text-white mb-4">Add Content Type</Dialog.Title>

              <Label className="text-xs font-medium mb-1 block">Media Type</Label>
              <Select value={newMediaType} onValueChange={setNewMediaType}>
                <SelectTrigger className="h-9 text-sm mt-1">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {MEDIA_TYPE_OPTIONS.map((opt) => (
                    <SelectItem key={opt.value} value={opt.value}>
                      {opt.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>

              <Label className="text-xs font-medium mb-1 block mt-4">Schema binding</Label>
              <div className="flex gap-2 mt-1">
                <Button
                  type="button"
                  size="sm"
                  variant={newContentSchemaType === 'reference' ? 'default' : 'outline'}
                  onClick={() => setNewContentSchemaType('reference')}
                  className={`flex-1 text-xs ${newContentSchemaType === 'reference' ? 'bg-indigo-600 hover:bg-indigo-700' : ''}`}
                >
                  <Link2 className="w-3 h-3 mr-1" />
                  Class Reference
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant={newContentSchemaType === 'inline' ? 'default' : 'outline'}
                  onClick={() => setNewContentSchemaType('inline')}
                  className={`flex-1 text-xs ${newContentSchemaType === 'inline' ? 'bg-emerald-600 hover:bg-emerald-700' : ''}`}
                >
                  <Pencil className="w-3 h-3 mr-1" />
                  Inline Schema
                </Button>
              </div>

              {newContentSchemaType === 'reference' && (
                <div className="mt-3">
                  <Label className="text-xs font-medium mb-1 block">Class</Label>
                  <div className="mt-1">
                    <ReuseSearchCombobox
                      aria-label="Class for new content type"
                      items={classes.map((cls) => ({ id: cls.id, label: cls.name }))}
                      value={newContentClassId}
                      onValueChange={setNewContentClassId}
                      placeholder="Search classes…"
                      searchPlaceholder="Filter by name…"
                      emptyText="No classes match."
                      triggerClassName="h-9 text-sm"
                    />
                  </div>
                </div>
              )}

              <div className="flex justify-end gap-2 mt-4 pt-4 border-t border-gray-200 dark:border-gray-700">
                <Button type="button" variant="ghost" size="sm" onClick={() => setAddContentDialogOpen(false)}>Cancel</Button>
                <Button
                  type="button"
                  variant="default"
                  size="sm"
                  onClick={handleAddContentType}
                  disabled={newContentSchemaType === 'reference' && !newContentClassId}
                >
                  Add
                </Button>
              </div>
            </Dialog.Content>
          </Dialog.Portal>
        </Dialog.Root>

        {/* Add Property Dialog */}
        <Dialog.Root open={addPropertyDialogOpen} onOpenChange={setAddPropertyDialogOpen}>
          <Dialog.Portal>
            <Dialog.Overlay className="fixed inset-0 bg-black/50 z-[9998]" />
            <Dialog.Content
              aria-describedby={undefined}
              className="fixed left-1/2 top-1/2 z-[9999] w-full max-w-xs -translate-x-1/2 -translate-y-1/2 rounded-lg bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 shadow-xl p-4"
            >
              <Dialog.Title className="text-sm font-semibold text-gray-900 dark:text-white mb-4">Add Property</Dialog.Title>
              <Label className="text-xs font-medium mb-1 block">Property Name</Label>
              <Input
                value={newPropertyName}
                onChange={(e) => setNewPropertyName(e.target.value)}
                className="h-9 text-sm mt-1 mb-4"
              />
              <Label className="text-xs font-medium mb-1 block">Type</Label>
              <Select value={newPropertyType} onValueChange={setNewPropertyType}>
                <SelectTrigger className="h-9 text-sm mt-1">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="string">string</SelectItem>
                  <SelectItem value="number">number</SelectItem>
                  <SelectItem value="integer">integer</SelectItem>
                  <SelectItem value="boolean">boolean</SelectItem>
                  <SelectItem value="object">object</SelectItem>
                  <SelectItem value="array">array</SelectItem>
                </SelectContent>
              </Select>
              <div className="flex justify-end gap-2 mt-4 pt-4 border-t border-gray-200 dark:border-gray-700">
                <Button type="button" variant="ghost" size="sm" onClick={() => setAddPropertyDialogOpen(false)}>Cancel</Button>
                <Button type="button" variant="default" size="sm" onClick={handleAddProperty} disabled={!newPropertyName.trim()}>Add</Button>
              </div>
            </Dialog.Content>
          </Dialog.Portal>
        </Dialog.Root>
      </div>
    );
  }

  // Render no linked request body - show link options
  return (
    <div>
      <div className={`py-6 px-4 text-center rounded-lg border border-dashed ${isDark ? 'border-slate-700' : 'border-slate-300'}`}>
        <FileJson className="w-6 h-6 mx-auto mb-2 text-gray-400" />
        <span className="text-xs text-gray-500 dark:text-gray-400 block mb-4">
          No request body linked
        </span>

        {/* Available request bodies to link */}
        {availableRequestBodies.length > 0 && (
          <div className="mb-4">
            <Label className="block text-[10px] font-medium text-gray-600 dark:text-gray-400 mb-2">
              Link Existing
            </Label>
            <div className="flex flex-col gap-1">
              {availableRequestBodies.map((rb) => (
                <Button
                  key={rb.id}
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() => handleLinkRequestBody(rb.id)}
                  className="text-xs justify-start"
                >
                  <Link className="w-3.5 h-3.5 mr-1.5" />
                  {rb.name}
                </Button>
              ))}
            </div>
          </div>
        )}

        <Button
          type="button"
          size="sm"
          variant="default"
          onClick={() => setCreateDialogOpen(true)}
          className="text-sm bg-indigo-600 hover:bg-indigo-700"
        >
          <Plus className="w-4 h-4 mr-1.5" />
          Create New Request Body
        </Button>
      </div>

      {/* Create Request Body Dialog */}
      <Dialog.Root open={createDialogOpen} onOpenChange={setCreateDialogOpen}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 bg-black/50 z-[9998]" />
          <Dialog.Content
            aria-describedby={undefined}
            className="fixed left-1/2 top-1/2 z-[9999] w-full max-w-xs -translate-x-1/2 -translate-y-1/2 rounded-lg bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 shadow-xl p-4"
          >
            <Dialog.Title className="text-sm font-semibold text-gray-900 dark:text-white mb-4">Create Request Body</Dialog.Title>
            <Label className="text-xs font-medium mb-1 block">Name</Label>
            <Input
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="e.g., CreateUserRequest"
              className="h-9 text-sm mt-1 mb-4"
            />
            <Label className="text-xs font-medium mb-1 block">Description (optional)</Label>
            <Input
              value={newDescription}
              onChange={(e) => setNewDescription(e.target.value)}
              className="h-9 text-sm mt-1 mb-4"
            />
            <label className="flex items-center gap-2 cursor-pointer mt-2">
              <Checkbox
                checked={newRequired}
                onCheckedChange={(c) => setNewRequired(c === true)}
              />
              <span className="text-xs">Required</span>
            </label>
            <div className="flex justify-end gap-2 mt-4 pt-4 border-t border-gray-200 dark:border-gray-700">
              <Button type="button" variant="ghost" size="sm" onClick={() => setCreateDialogOpen(false)}>Cancel</Button>
              <Button type="button" variant="default" size="sm" onClick={handleCreateRequestBody} disabled={!newName.trim()}>Create</Button>
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </div>
  );
}
