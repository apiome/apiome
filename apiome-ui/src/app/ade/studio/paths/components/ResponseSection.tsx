'use client';

import React, { useState, useEffect, useCallback } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { FileJson, Plus, ChevronDown, ChevronRight, Trash2, Wand2, RefreshCw, ListChecks } from 'lucide-react';
import { Button } from '../../../../components/ui/Button';
import { Input } from '../../../../components/ui/Input';
import { Label } from '../../../../components/ui/Label';
import { Textarea } from '../../../../components/ui/Textarea';
import { Checkbox } from '../../../../components/ui/Checkbox';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../../../../components/ui/Select';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '../../../../components/ui/Tabs';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '../../../../components/ui/Tooltip';
import { useDarkMode } from '../../../../hooks/useDarkMode';
import { useStudio } from '../../StudioContext';
import { getHttpStatusDescription } from '../../../../../../lib/utils/http-status-codes';
import {
  getResponseContentTypes,
  addResponseContentType,
  deleteResponseContentType,
  updateResponseContentType,
  convertResponseClassToInlineSchema,
  setResponseContentTypeClassReference,
  addPropertyToResponseInlineSchema,
  deleteResponseInlineSchemaProperty,
} from '../../../../../../lib/db/helper-shared-path-responses-content';
import {
  updateSharedPathResponse,
} from '../../../../../../lib/db/helper-shared-path-responses';
import { getClassesWithPropertiesAndTags } from '../../../../../../lib/db/helper';
import {
  buildPropertyTreeFromInlineSchema,
  getActiveCompositionKind,
  type InlineSchema,
  type PropertyTreeNode,
} from '../../../../../../lib/utils/inline-schema-utils';
import ResponseSchemaComposition from './ResponseSchemaComposition';

// =============================================================================
// TYPES
// =============================================================================

interface ResponseExampleItem {
  name?: string;
  summary?: string;
  value?: unknown;
}

interface ContentTypeInfo {
  id: string;
  media_type: string;
  class_id?: string | null;
  class_name?: string | null;
  inline_schema?: InlineSchema | null;
  examples?: ResponseExampleItem[] | null;
}

interface ResponseInfo {
  id: string;
  status_code: string;
  description?: string;
  content_types: ContentTypeInfo[];
  schema_mode?: 'class' | 'object' | 'primitive' | 'array';
  data?: Record<string, any> | null;
  inline_schema?: InlineSchema | null;
  class_id?: string | null;
  class_name?: string | null;
}

interface ResponseSectionProps {
  response: ResponseInfo;
  onUpdate: () => void;
  onRefresh?: () => void; // Callback to refresh the canvas
}

// =============================================================================
// PROPERTY TREE NODE COMPONENT
// =============================================================================

interface PropertyTreeNodeComponentProps {
  node: PropertyTreeNode;
  depth: number;
  isDark: boolean;
  onDeleteProperty: (id: string) => void;
}

function PropertyTreeNodeComponent({
  node,
  depth,
  isDark,
  onDeleteProperty
}: PropertyTreeNodeComponentProps) {
  const [expanded, setExpanded] = useState(true);

  return (
    <div key={node.id} style={{ marginLeft: depth * 12 }}>
      <div
        className={`flex items-center gap-2 py-1 px-2 rounded hover:bg-black/5 dark:hover:bg-white/5`}
      >
        {node.children.length > 0 && (
          <button
            type="button"
            onClick={() => setExpanded(!expanded)}
            className="p-1 rounded hover:bg-gray-200 dark:hover:bg-gray-600"
          >
            {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
          </button>
        )}

        <FileJson size={14} />

        <div className="flex-1 text-sm">
          <strong>{node.name}</strong>
          {node.data?.type && (
            <span className="ml-2 opacity-70">
              {node.data.type}
              {node.data.format && ` (${node.data.format})`}
            </span>
          )}
        </div>

        <button
          type="button"
          onClick={() => onDeleteProperty(node.id)}
          className="p-1 rounded hover:bg-gray-200 dark:hover:bg-gray-600"
        >
          <Trash2 size={14} />
        </button>
      </div>

      {expanded && node.children.map((child) => (
        <PropertyTreeNodeComponent
          key={child.id}
          node={child}
          depth={depth + 1}
          isDark={isDark}
          onDeleteProperty={onDeleteProperty}
        />
      ))}
    </div>
  );
}

// =============================================================================
// RESPONSE SECTION COMPONENT
// =============================================================================

export default function ResponseSection({ response, onUpdate, onRefresh }: ResponseSectionProps) {
  const isDark = useDarkMode();
  const { selectedVersionId } = useStudio();

  const [contentTypes, setContentTypes] = useState<ContentTypeInfo[]>(response.content_types || []);
  const [selectedContentTypeIndex, setSelectedContentTypeIndex] = useState(0);
  const [classes, setClasses] = useState<any[]>([]);
  const [showAddPropertyDialog, setShowAddPropertyDialog] = useState(false);
  const [showAddContentTypeDialog, setShowAddContentTypeDialog] = useState(false);
  const [newPropertyName, setNewPropertyName] = useState('');
  const [newPropertyType, setNewPropertyType] = useState('string');
  const [newMediaType, setNewMediaType] = useState('application/json');
  // Updated to support all 4 schema modes: class, object (inline), primitive, array
  const [schemaMode, setSchemaMode] = useState<'class' | 'object' | 'primitive' | 'array'>('object');
  const [primitiveType, setPrimitiveType] = useState<'string' | 'number' | 'integer' | 'boolean'>('string');
  const [arrayItemType, setArrayItemType] = useState<'string' | 'number' | 'integer' | 'boolean'>('string');
  const [isSavingSchemaMode, setIsSavingSchemaMode] = useState(false);

  // Description state - auto-populate from status code or allow custom
  const [description, setDescription] = useState(response.description || '');
  const [autoPopulateDescription, setAutoPopulateDescription] = useState(!response.description);
  const [isSavingDescription, setIsSavingDescription] = useState(false);

  // Load content types
  const loadContentTypes = useCallback(async () => {
    if (!response.id) return;

    try {
      const result = await getResponseContentTypes(response.id);
      const data = JSON.parse(result);

      if (data.success && data.contentTypes) {
        setContentTypes(data.contentTypes);
      }
    } catch (error) {
      console.error('Error loading response content types:', error);
    }
  }, [response.id]);

  // Load classes
  const loadClasses = useCallback(async () => {
    if (!selectedVersionId) return;

    try {
      const result = await getClassesWithPropertiesAndTags(selectedVersionId);
      const data = JSON.parse(result);
      setClasses(data || []);
    } catch (error) {
      console.error('Error loading classes:', error);
    }
  }, [selectedVersionId]);

  useEffect(() => {
    loadContentTypes();
    loadClasses();
  }, [loadContentTypes, loadClasses]);

  // Initialize description from response or auto-populate from status code
  useEffect(() => {
    if (response.description) {
      setDescription(response.description);
      setAutoPopulateDescription(false);
    } else {
      // Auto-populate from status code if no description set
      const autoDesc = getHttpStatusDescription(response.status_code);
      setDescription(autoDesc);
      setAutoPopulateDescription(true);
    }
  }, [response.id, response.description, response.status_code]);

  // Handle auto-populate toggle
  const handleAutoPopulateToggle = async (checked: boolean) => {
    setAutoPopulateDescription(checked);
    if (checked) {
      const autoDesc = getHttpStatusDescription(response.status_code);
      setDescription(autoDesc);
      await saveDescription(autoDesc);
    }
  };

  // Save description to database
  const saveDescription = async (newDescription: string) => {
    setIsSavingDescription(true);
    try {
      const result = await updateSharedPathResponse(response.id, {
        description: newDescription,
      });
      const parsed = JSON.parse(result);
      if (parsed.success) {
        onUpdate();
        if (onRefresh) {
          onRefresh();
        }
      } else {
        console.error('Error saving description:', parsed.error);
      }
    } catch (error) {
      console.error('Error saving description:', error);
    } finally {
      setIsSavingDescription(false);
    }
  };

  // Handle description change (manual editing)
  const handleDescriptionChange = (value: string) => {
    setDescription(value);
    setAutoPopulateDescription(false);
  };

  // Handle description blur (save on blur)
  const handleDescriptionBlur = async () => {
    if (description !== response.description) {
      await saveDescription(description);
    }
  };

  // Get current content type
  const currentContentType = contentTypes[selectedContentTypeIndex];

  // Determine schema mode based on response.schema_mode or infer from data
  useEffect(() => {
    // First check if response has an explicit schema_mode
    if (response.schema_mode) {
      setSchemaMode(response.schema_mode);
      // If primitive, try to determine the type
      if (response.schema_mode === 'primitive' && response.data) {
        try {
          const data = typeof response.data === 'string'
            ? JSON.parse(response.data)
            : response.data;
          if (data?.type && ['string', 'number', 'integer', 'boolean'].includes(data.type)) {
            setPrimitiveType(data.type);
          }
        } catch (e) {
          // Ignore parse errors
        }
      }
      // If array, try to determine the item type
      if (response.schema_mode === 'array' && response.data) {
        try {
          const data = typeof response.data === 'string'
            ? JSON.parse(response.data)
            : response.data;
          if (data?.items?.type && ['string', 'number', 'integer', 'boolean'].includes(data.items.type)) {
            setArrayItemType(data.items.type);
          }
        } catch (e) {
          // Ignore parse errors
        }
      }
      return;
    }
    // Fall back to inferring from content type
    if (currentContentType) {
      if (currentContentType.class_id) {
        setSchemaMode('class');
      } else if (currentContentType.inline_schema) {
        setSchemaMode('object');
      }
    }
  }, [response, currentContentType]);

  // Add content type
  const handleAddContentType = async () => {
    try {
      const result = await addResponseContentType(
        response.id,
        newMediaType,
        undefined,
        { type: 'object', properties: [] },
        undefined
      );

      const data = JSON.parse(result);
      if (data.success) {
        await loadContentTypes();
        setShowAddContentTypeDialog(false);
        setNewMediaType('application/json');
        onUpdate();
      }
    } catch (error) {
      console.error('Error adding content type:', error);
    }
  };

  // Delete content type
  const handleDeleteContentType = async (contentTypeId: string) => {
    if (!window.confirm('Are you sure you want to delete this content type?')) {
      return;
    }

    try {
      await deleteResponseContentType(contentTypeId);
      await loadContentTypes();
      setSelectedContentTypeIndex(0);
      onUpdate();
    } catch (error) {
      console.error('Error deleting content type:', error);
    }
  };

  // Switch schema mode - updates the response's schema_mode in the database
  const handleSchemaModeChange = async (mode: 'class' | 'object' | 'primitive' | 'array') => {
    setIsSavingSchemaMode(true);

    try {
      let data: Record<string, any> | null = null;
      let inlineSchema: Record<string, any> | null = null;

      if (mode === 'primitive') {
        data = { type: primitiveType };
      } else if (mode === 'array') {
        let arrayItems: Record<string, any> = { type: arrayItemType };

        // Preserve existing object/class schema when converting object/class -> array.
        if (schemaMode === 'class') {
          const className = currentContentType?.class_name || response.class_name;
          if (className) {
            arrayItems = { $ref: `#/components/schemas/${className}` };
          }
        } else if (schemaMode === 'object') {
          let objectSchema: any = currentContentType?.inline_schema ?? null;
          if (!objectSchema && response.inline_schema) {
            try {
              objectSchema =
                typeof response.inline_schema === 'string'
                  ? JSON.parse(response.inline_schema)
                  : response.inline_schema;
            } catch {
              objectSchema = null;
            }
          }
          if (objectSchema && typeof objectSchema === 'object') {
            arrayItems = objectSchema.type === 'object'
              ? objectSchema
              : { type: 'object', ...objectSchema };
          }
        }

        data = { type: 'array', items: arrayItems };
      } else if (mode === 'object') {
        inlineSchema = { type: 'object', properties: [] };
      } else if (mode === 'class') {
        // For 'class' mode, provide a placeholder inline_schema until user selects a class
        // This satisfies the database constraint that requires at least one of:
        // class_id, inline_schema, or data to be NOT NULL
        inlineSchema = { type: 'object', properties: [] };
      }

      const result = await updateSharedPathResponse(response.id, {
        schemaMode: mode,
        classId: mode === 'class' ? undefined : null, // Only clear if not class mode
        data,
        inlineSchema,
      });

      const parsed = JSON.parse(result);
      if (parsed.success) {
        setSchemaMode(mode);
        onUpdate();
        // Refresh the canvas to show the updated schema type
        if (onRefresh) {
          onRefresh();
        }
      } else {
        console.error('Error updating schema mode:', parsed.error);
      }
    } catch (error) {
      console.error('Error updating schema mode:', error);
    } finally {
      setIsSavingSchemaMode(false);
    }
  };

  // Save primitive type change
  const handlePrimitiveTypeChange = async (type: 'string' | 'number' | 'integer' | 'boolean') => {
    setPrimitiveType(type);

    if (schemaMode === 'primitive') {
      try {
        const result = await updateSharedPathResponse(response.id, {
          schemaMode: 'primitive',
          data: { type },
          classId: null,
          inlineSchema: null,
        });

        const parsed = JSON.parse(result);
        if (parsed.success) {
          onUpdate();
          // Refresh the canvas to show the updated primitive type
          if (onRefresh) {
            onRefresh();
          }
        }
      } catch (error) {
        console.error('Error updating primitive type:', error);
      }
    }
  };

  // Save array item type change
  const handleArrayItemTypeChange = async (type: 'string' | 'number' | 'integer' | 'boolean') => {
    setArrayItemType(type);

    if (schemaMode === 'array') {
      try {
        const result = await updateSharedPathResponse(response.id, {
          schemaMode: 'array',
          data: { type: 'array', items: { type } },
          classId: null,
          inlineSchema: null,
        });

        const parsed = JSON.parse(result);
        if (parsed.success) {
          onUpdate();
          // Refresh the canvas to show the updated array type
          if (onRefresh) {
            onRefresh();
          }
        }
      } catch (error) {
        console.error('Error updating array item type:', error);
      }
    }
  };

  // Legacy schema mode handler for content type conversion
  const handleSchemaMode = async (mode: 'class' | 'inline') => {
    if (!currentContentType) return;

    if (mode === 'inline' && currentContentType.class_id) {
      // Convert class to inline
      if (!window.confirm('This will copy all properties from the class into an inline schema. Continue?')) {
        return;
      }

      try {
        await convertResponseClassToInlineSchema(currentContentType.id);
        await loadContentTypes();
        onUpdate();
      } catch (error) {
        console.error('Error converting to inline schema:', error);
      }
    } else if (mode === 'class' && currentContentType.inline_schema) {
      // User wants to use class reference - clear inline schema
      setSchemaMode('class');
    }
  };

  // Set class reference
  const handleSetClassReference = async (classId: string) => {
    if (!currentContentType) return;

    try {
      await setResponseContentTypeClassReference(currentContentType.id, classId);
      await loadContentTypes();
      onUpdate();
    } catch (error) {
      console.error('Error setting class reference:', error);
    }
  };

  // Add property to inline schema
  const handleAddProperty = async () => {
    if (!currentContentType || !newPropertyName) return;

    if (currentContentType.inline_schema && getActiveCompositionKind(currentContentType.inline_schema)) {
      window.alert(
        'Remove schema composition (allOf/anyOf/oneOf) before adding inline properties, or apply an empty object schema first.'
      );
      return;
    }

    try {
      await addPropertyToResponseInlineSchema(currentContentType.id, {
        name: newPropertyName,
        data: { type: newPropertyType },
        parent_id: null,
      });

      await loadContentTypes();
      setShowAddPropertyDialog(false);
      setNewPropertyName('');
      setNewPropertyType('string');
      onUpdate();
    } catch (error) {
      console.error('Error adding property:', error);
    }
  };

  // Delete property from inline schema
  const handleDeleteProperty = async (propertyId: string) => {
    if (!currentContentType) return;

    if (!window.confirm('Are you sure you want to delete this property?')) {
      return;
    }

    try {
      await deleteResponseInlineSchemaProperty(currentContentType.id, propertyId, true);
      await loadContentTypes();
      onUpdate();
    } catch (error) {
      console.error('Error deleting property:', error);
    }
  };

  // Build property tree
  const propertyTree: PropertyTreeNode[] = currentContentType?.inline_schema
    ? buildPropertyTreeFromInlineSchema(currentContentType.inline_schema)
    : [];

  const handleContentTypeExamplesChange = async (contentId: string, examples: ResponseExampleItem[]) => {
    try {
      const result = await updateResponseContentType(contentId, { examples: examples.length ? examples : null });
      const data = JSON.parse(result);
      if (data.success) {
        await loadContentTypes();
        onUpdate();
      }
    } catch (e) {
      console.error('Error updating examples:', e);
    }
  };

  return (
    <TooltipProvider>
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <FileJson size={20} />
          <span className="font-semibold">Response {response.status_code}</span>
        </div>

        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={() => setShowAddContentTypeDialog(true)}
        >
          <Plus className="w-4 h-4 mr-1.5" />
          Add Content Type
        </Button>
      </div>

      {/* Description Section */}
      <div className="mb-6">
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm font-semibold">Description</span>
          <Tooltip>
            <TooltipTrigger asChild>
              <label className="flex items-center gap-1.5 cursor-pointer text-xs">
                <Checkbox
                  checked={autoPopulateDescription}
                  onCheckedChange={(c) => handleAutoPopulateToggle(c === true)}
                  disabled={isSavingDescription}
                />
                <Wand2 size={14} />
                Auto
              </label>
            </TooltipTrigger>
            <TooltipContent>Auto-populate description from HTTP status code</TooltipContent>
          </Tooltip>
        </div>
        <Input
          placeholder={autoPopulateDescription ? 'Auto-populated from status code' : 'Enter response description...'}
          value={description}
          onChange={(e) => handleDescriptionChange(e.target.value)}
          onBlur={handleDescriptionBlur}
          disabled={isSavingDescription}
          className={`text-sm h-9 ${autoPopulateDescription ? 'bg-blue-500/10 dark:bg-blue-500/10' : ''}`}
        />
        {autoPopulateDescription && (
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
            Description is auto-populated from status code. Uncheck &quot;Auto&quot; to customize.
          </p>
        )}
      </div>

      {/* Content type map with schema bindings */}
      {contentTypes.length > 0 && (
        <div className="border-b border-gray-200 dark:border-gray-700 mb-4">
          <span className="text-xs font-medium text-gray-500 dark:text-gray-400 block mb-2">Content type map (schema bindings)</span>
          <Tabs value={String(selectedContentTypeIndex)} onValueChange={(v) => setSelectedContentTypeIndex(Number(v))}>
            <TabsList className="h-8 w-full justify-start overflow-x-auto">
              {contentTypes.map((ct, index) => (
                <TabsTrigger key={ct.id} value={String(index)} className="flex items-center gap-1.5 text-xs">
                  {ct.media_type}
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      handleDeleteContentType(ct.id);
                    }}
                    className="p-0.5 rounded hover:bg-gray-200 dark:hover:bg-gray-600"
                  >
                    <Trash2 size={12} />
                  </button>
                </TabsTrigger>
              ))}
            </TabsList>
          </Tabs>
        </div>
      )}

      {/* Examples for selected content type */}
      {contentTypes.length > 0 && currentContentType && (
        <div className={`mb-6 p-4 rounded-lg border ${isDark ? 'border-slate-700 bg-slate-800/30' : 'border-slate-200 bg-slate-50'}`}>
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm font-semibold flex items-center gap-1.5">
              <ListChecks size={16} />
              Examples for {currentContentType.media_type}
            </span>
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => {
                const prev = (currentContentType.examples || []) as ResponseExampleItem[];
                const next = [...prev, { name: `Example ${prev.length + 1}`, summary: '', value: {} }];
                handleContentTypeExamplesChange(currentContentType.id, next);
              }}
            >
              <Plus size={14} className="mr-1" />
              Add example
            </Button>
          </div>
          <p className="text-xs text-gray-500 dark:text-gray-400 mb-3">
            Sample response values for this content type (name, summary, value).
          </p>
          <div className="space-y-3">
            {((currentContentType.examples || []) as ResponseExampleItem[]).map((ex, exIdx) => (
              <div
                key={exIdx}
                className={`p-3 rounded border ${isDark ? 'border-slate-600 bg-slate-800/50' : 'border-slate-200 bg-white'}`}
              >
                <div className="flex gap-2 mb-2">
                  <Input
                    placeholder="Name (optional)"
                    value={ex.name ?? ''}
                    onChange={(e) => {
                      const prev = (currentContentType!.examples || []) as ResponseExampleItem[];
                      const next = prev.map((x, i) => i === exIdx ? { ...x, name: e.target.value || undefined } : x);
                      handleContentTypeExamplesChange(currentContentType!.id, next);
                    }}
                    className="text-xs h-8 flex-1"
                  />
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="h-8 text-red-600 hover:text-red-700"
                    onClick={() => {
                      const prev = (currentContentType!.examples || []) as ResponseExampleItem[];
                      handleContentTypeExamplesChange(currentContentType!.id, prev.filter((_, i) => i !== exIdx));
                    }}
                  >
                    <Trash2 size={14} />
                  </Button>
                </div>
                <Input
                  placeholder="Summary (optional)"
                  value={ex.summary ?? ''}
                  onChange={(e) => {
                    const prev = (currentContentType!.examples || []) as ResponseExampleItem[];
                    const next = prev.map((x, i) => i === exIdx ? { ...x, summary: e.target.value || undefined } : x);
                    handleContentTypeExamplesChange(currentContentType!.id, next);
                  }}
                  className="mb-2 text-xs h-8"
                />
                <Textarea
                  key={`${currentContentType.id}-${exIdx}-${JSON.stringify((ex as ResponseExampleItem).value ?? {})}`}
                  placeholder='Value (JSON, e.g. {"id": 1, "name": "..."})'
                  defaultValue={typeof (ex as ResponseExampleItem).value === 'object' && (ex as ResponseExampleItem).value !== null
                    ? JSON.stringify((ex as ResponseExampleItem).value, null, 2)
                    : (ex as ResponseExampleItem).value !== undefined && (ex as ResponseExampleItem).value !== null
                      ? String((ex as ResponseExampleItem).value)
                      : '{}'}
                  onBlur={(e) => {
                    const raw = e.target.value.trim();
                    const value: unknown = raw ? (() => { try { return JSON.parse(raw); } catch { return undefined; } })() : {};
                    if (value === undefined) return;
                    const prev = (currentContentType!.examples || []) as ResponseExampleItem[];
                    const next = prev.map((x, i) => i === exIdx ? { ...x, value } : x);
                    handleContentTypeExamplesChange(currentContentType!.id, next);
                  }}
                  rows={3}
                  className="text-xs font-mono resize-none"
                />
              </div>
            ))}
            {((currentContentType.examples || []).length) === 0 && (
              <p className="text-xs text-gray-500 dark:text-gray-400 italic">No examples. Add one to document sample responses.</p>
            )}
          </div>
        </div>
      )}

      {/* Response Schema Mode - This affects the response directly, not content types */}
      <div className={`mb-6 p-4 rounded-lg ${isDark ? 'bg-slate-800' : 'bg-slate-50'}`}>
        <span className="text-sm font-semibold block mb-3">Response Schema</span>
        <div className="flex flex-wrap gap-2 mb-4">
          <Button
            type="button"
            size="sm"
            variant={schemaMode === 'class' ? 'default' : 'outline'}
            onClick={() => handleSchemaModeChange('class')}
            disabled={isSavingSchemaMode}
          >
            Class
          </Button>
          <Button
            type="button"
            size="sm"
            variant={schemaMode === 'object' ? 'default' : 'outline'}
            onClick={() => handleSchemaModeChange('object')}
            disabled={isSavingSchemaMode}
          >
            Object
          </Button>
          <Button
            type="button"
            size="sm"
            variant={schemaMode === 'primitive' ? 'default' : 'outline'}
            onClick={() => handleSchemaModeChange('primitive')}
            disabled={isSavingSchemaMode}
          >
            Primitive
          </Button>
          <Button
            type="button"
            size="sm"
            variant={schemaMode === 'array' ? 'default' : 'outline'}
            onClick={() => handleSchemaModeChange('array')}
            disabled={isSavingSchemaMode}
          >
            Array
          </Button>
        </div>

        {/* Primitive Type Selector */}
        {schemaMode === 'primitive' && (
          <div className="mt-4">
            <Label className="text-xs font-medium mb-1 block">Primitive Type</Label>
            <Select value={primitiveType} onValueChange={(v) => handlePrimitiveTypeChange(v as typeof primitiveType)}>
              <SelectTrigger className="h-9 text-sm">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="string">String</SelectItem>
                <SelectItem value="number">Number</SelectItem>
                <SelectItem value="integer">Integer</SelectItem>
                <SelectItem value="boolean">Boolean</SelectItem>
              </SelectContent>
            </Select>
          </div>
        )}

        {/* Array Item Type Selector */}
        {schemaMode === 'array' && (
          <div className="mt-4">
            <Label className="text-xs font-medium mb-1 block">Array Item Type</Label>
            <Select value={arrayItemType} onValueChange={(v) => handleArrayItemTypeChange(v as typeof arrayItemType)}>
              <SelectTrigger className="h-9 text-sm">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="string">String</SelectItem>
                <SelectItem value="number">Number</SelectItem>
                <SelectItem value="integer">Integer</SelectItem>
                <SelectItem value="boolean">Boolean</SelectItem>
              </SelectContent>
            </Select>
          </div>
        )}
      </div>

      {/* Content Type Details - Only show for class and object modes */}
      {(schemaMode === 'class' || schemaMode === 'object') && currentContentType && (
        <div>
          {/* Legacy Schema Mode Toggle for content types */}
          <div className="mb-4">
            <span className="text-sm font-semibold block mb-2">Content Type Schema</span>
            <div className="flex gap-2">
              <Button
                type="button"
                size="sm"
                variant={schemaMode === 'class' ? 'default' : 'outline'}
                onClick={() => handleSchemaMode('class')}
              >
                Class Reference
              </Button>
              <Button
                type="button"
                size="sm"
                variant={schemaMode === 'object' ? 'default' : 'outline'}
                onClick={() => handleSchemaMode('inline')}
              >
                Inline Schema
              </Button>
            </div>
          </div>

          {/* Class Reference Mode */}
          {schemaMode === 'class' && (
            <div>
              <Label className="text-xs font-medium mb-1 block">Response Class</Label>
              <Select
                value={currentContentType.class_id || '__none__'}
                onValueChange={(v) => handleSetClassReference(v === '__none__' ? '' : v)}
              >
                <SelectTrigger className="h-9 text-sm">
                  <SelectValue placeholder="Select a class" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__none__">Select a class</SelectItem>
                  {classes.map((cls) => (
                    <SelectItem key={cls.id} value={cls.id}>
                      {cls.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>

              {currentContentType.class_id && (
                <div className="mt-4">
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={() => handleSchemaModeChange('object')}
                  >
                    <RefreshCw className="w-4 h-4 mr-1.5" />
                    Convert to Inline Schema
                  </Button>
                </div>
              )}
            </div>
          )}

          {/* Inline Schema Mode */}
          {schemaMode === 'object' && (
            <div>
              {!currentContentType.class_id && (
                <ResponseSchemaComposition
                  contentTypeId={currentContentType.id}
                  inlineSchema={currentContentType.inline_schema}
                  classes={classes.map((c: { id: string; name: string }) => ({ id: c.id, name: c.name }))}
                  isDark={isDark}
                  onUpdated={async () => {
                    await loadContentTypes();
                    onUpdate();
                  }}
                />
              )}

              <div className="flex items-center justify-between mb-2">
                <span className="text-sm font-semibold">Properties</span>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() => setShowAddPropertyDialog(true)}
                  disabled={
                    !!(
                      currentContentType.inline_schema &&
                      getActiveCompositionKind(currentContentType.inline_schema)
                    )
                  }
                  title={
                    currentContentType.inline_schema &&
                    getActiveCompositionKind(currentContentType.inline_schema)
                      ? 'Clear schema composition before adding properties'
                      : undefined
                  }
                >
                  <Plus size={16} className="mr-1.5" />
                  Add Property
                </Button>
              </div>

              {propertyTree.length > 0 ? (
                <div className="border border-gray-200 dark:border-gray-700 rounded-lg p-2 max-h-[400px] overflow-auto">
                  {propertyTree.map((node) => (
                    <PropertyTreeNodeComponent
                      key={node.id}
                      node={node}
                      depth={0}
                      isDark={isDark}
                      onDeleteProperty={handleDeleteProperty}
                    />
                  ))}
                </div>
              ) : (
                <div className="p-6 text-center border border-dashed border-gray-300 dark:border-gray-600 rounded-lg">
                  <span className="text-sm opacity-60">
                    No properties defined. Click &quot;Add Property&quot; to get started.
                  </span>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* No Content Types */}
      {contentTypes.length === 0 && (
        <div className="p-6 text-center border border-dashed border-gray-300 dark:border-gray-600 rounded-lg">
          <FileJson size={48} className="opacity-30 mb-2 mx-auto block" />
          <span className="text-sm opacity-60 block mb-4">
            No content types defined for this response.
          </span>
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => setShowAddContentTypeDialog(true)}
          >
            <Plus className="w-4 h-4 mr-1.5" />
            Add Content Type
          </Button>
        </div>
      )}

      {/* Add Content Type Dialog */}
      <Dialog.Root open={showAddContentTypeDialog} onOpenChange={setShowAddContentTypeDialog}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 bg-black/50 z-[9998]" />
          <Dialog.Content
            aria-describedby={undefined}
            className="fixed left-1/2 top-1/2 z-[9999] w-full max-w-sm -translate-x-1/2 -translate-y-1/2 rounded-lg bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 shadow-xl p-4"
          >
            <Dialog.Title className="text-lg font-semibold text-gray-900 dark:text-white mb-4">Add Content Type</Dialog.Title>
            <Label className="text-xs font-medium mb-1 block">Media Type</Label>
            <Select value={newMediaType} onValueChange={setNewMediaType}>
              <SelectTrigger className="h-9 text-sm mt-1">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="application/json">application/json</SelectItem>
                <SelectItem value="application/xml">application/xml</SelectItem>
                <SelectItem value="text/plain">text/plain</SelectItem>
                <SelectItem value="text/html">text/html</SelectItem>
                <SelectItem value="application/pdf">application/pdf</SelectItem>
              </SelectContent>
            </Select>
            <div className="flex justify-end gap-2 mt-4 pt-4 border-t border-gray-200 dark:border-gray-700">
              <Button type="button" variant="ghost" size="sm" onClick={() => setShowAddContentTypeDialog(false)}>Cancel</Button>
              <Button type="button" variant="default" size="sm" onClick={handleAddContentType}>Add</Button>
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>

      {/* Add Property Dialog */}
      <Dialog.Root open={showAddPropertyDialog} onOpenChange={setShowAddPropertyDialog}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 bg-black/50 z-[9998]" />
          <Dialog.Content
            aria-describedby={undefined}
            className="fixed left-1/2 top-1/2 z-[9999] w-full max-w-sm -translate-x-1/2 -translate-y-1/2 rounded-lg bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 shadow-xl p-4"
          >
            <Dialog.Title className="text-lg font-semibold text-gray-900 dark:text-white mb-4">Add Property</Dialog.Title>
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
                <SelectItem value="array">array</SelectItem>
                <SelectItem value="object">object</SelectItem>
              </SelectContent>
            </Select>
            <div className="flex justify-end gap-2 mt-4 pt-4 border-t border-gray-200 dark:border-gray-700">
              <Button type="button" variant="ghost" size="sm" onClick={() => setShowAddPropertyDialog(false)}>Cancel</Button>
              <Button type="button" variant="default" size="sm" onClick={handleAddProperty} disabled={!newPropertyName}>Add</Button>
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </div>
    </TooltipProvider>
  );
}
