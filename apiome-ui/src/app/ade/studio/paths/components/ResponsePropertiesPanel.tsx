'use client';

import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { Save, Plus, Trash2, FileJson, Link2, LayoutList, MessageSquareReply } from 'lucide-react';
import { Button } from '../../../../components/ui/Button';
import PropertiesPanelShell from './PropertiesPanelShell';
import PropertiesPanelSection from './PropertiesPanelSection';
import { STATUS_ROLE_CHIP, statusRoleForCode } from './paths-theme';
import { Textarea } from '../../../../components/ui/Textarea';
import { Input } from '../../../../components/ui/Input';
import { useDarkMode } from '../../../../hooks/useDarkMode';
import { useDialog } from '../../../../components/providers/DialogProvider';
import {
  updateSharedPathResponse,
  getSharedPathResponses,
} from '../../../../../../lib/db/helper-shared-path-responses';
import {
  getClassesWithPropertiesAndTags,
} from '../../../../../../lib/db/helper';
import {
  getHttpStatusDescription,
  isValidStatusCode,
  COMMON_STATUS_CODES,
  STATUS_RANGE_AND_DEFAULT,
} from '../../../../../../lib/utils/http-status-codes';
import {
  addResponseContentType,
  deleteResponseContentType,
  setResponseContentTypeClassReference,
  updateResponseContentType,
} from '../../../../../../lib/db/helper-shared-path-responses-content';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../../../../components/ui/Select';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '../../../../components/ui/Tabs';
import SchemaBuilder from './SchemaBuilder';
import ReuseSearchCombobox, { type ReuseSearchItem } from './ReuseSearchCombobox';
import { createPathsVersionRefRegistry } from '../../../../../../lib/utils/paths-version-ref-registry';
import { useStudio } from '../../StudioContext';

/** Content type with schema binding (class or inline) - matches API shape */
export interface ContentTypeMapItem {
  id: string;
  media_type: string;
  class_id?: string | null;
  class_name?: string | null;
  inline_schema?: { type?: string; properties?: any[]; items?: any; $ref?: string } | null;
  examples?: ResponseExampleItem[] | null;
}

/** Single example per content type (OpenAPI: name/summary/value) */
export interface ResponseExampleItem {
  name?: string;
  summary?: string;
  value?: unknown;
}

/** Single response header (OpenAPI: name, description, schema) */
export interface ResponseHeaderItem {
  name: string;
  description?: string;
  schema?: { type?: string; format?: string };
}

/** Header templates for common patterns (#401): pagination, rate limiting, CORS */
const HEADER_TEMPLATES: Array<{ id: string; label: string; description: string; headers: ResponseHeaderItem[] }> = [
  {
    id: 'pagination',
    label: 'Pagination',
    description: 'Page info and Link header (RFC 5988)',
    headers: [
      { name: 'X-Total-Count', description: 'Total number of items across all pages', schema: { type: 'integer' } },
      { name: 'X-Page', description: 'Current page number (1-based)', schema: { type: 'integer' } },
      { name: 'X-Per-Page', description: 'Number of items per page', schema: { type: 'integer' } },
      { name: 'Link', description: 'RFC 5988 link header for prev, next, first, last', schema: { type: 'string' } },
    ],
  },
  {
    id: 'rate-limiting',
    label: 'Rate limiting',
    description: 'Rate limit and retry headers',
    headers: [
      { name: 'X-RateLimit-Limit', description: 'Maximum requests allowed per window', schema: { type: 'integer' } },
      { name: 'X-RateLimit-Remaining', description: 'Remaining requests in current window', schema: { type: 'integer' } },
      { name: 'X-RateLimit-Reset', description: 'Unix timestamp or seconds when the limit resets', schema: { type: 'integer' } },
      { name: 'Retry-After', description: 'Seconds until client can retry (e.g. 429)', schema: { type: 'integer' } },
    ],
  },
  {
    id: 'cors',
    label: 'CORS',
    description: 'Cross-Origin response headers',
    headers: [
      { name: 'Access-Control-Allow-Origin', description: 'Allowed origin(s) or *', schema: { type: 'string' } },
      { name: 'Access-Control-Expose-Headers', description: 'Headers exposed to the client', schema: { type: 'string' } },
      { name: 'Access-Control-Allow-Methods', description: 'Allowed methods for preflight', schema: { type: 'string' } },
      { name: 'Access-Control-Allow-Headers', description: 'Allowed request headers', schema: { type: 'string' } },
      { name: 'Access-Control-Max-Age', description: 'Seconds to cache preflight result', schema: { type: 'integer' } },
    ],
  },
];

/** Single response link (OpenAPI 3.1 Link Object - HATEOAS) */
export interface ResponseLinkItem {
  name: string;
  operationId?: string;
  operationRef?: string;
  description?: string;
  parameters?: Record<string, string>;
}

interface ResponsePropertiesPanelProps {
  responseId: string | null;
  statusCode: string;
  initialDescription?: string;
  versionPathId?: string | null;
  refreshKey?: number; // Key from parent to force reload
  onClose: () => void;
  onRefresh?: () => void;
}

function dataHeadersToArray(data: any): ResponseHeaderItem[] {
  if (!data?.headers || typeof data.headers !== 'object' || Array.isArray(data.headers)) return [];
  return Object.entries(data.headers).map(([name, def]: [string, any]) => ({
    name,
    description: def?.description,
    schema: def?.schema && typeof def.schema === 'object' ? { type: def.schema.type, format: def.schema.format } : undefined,
  }));
}

function headersArrayToDataMap(headers: ResponseHeaderItem[]): Record<string, { description?: string; schema?: { type?: string; format?: string } }> {
  const map: Record<string, { description?: string; schema?: { type?: string; format?: string } }> = {};
  for (const h of headers) {
    if (!h.name.trim()) continue;
    const key = h.name.trim();
    map[key] = {};
    if (h.description?.trim()) map[key].description = h.description.trim();
    if (h.schema?.type) map[key].schema = { type: h.schema.type, format: h.schema.format };
  }
  return map;
}

function dataLinksToArray(data: any): ResponseLinkItem[] {
  if (!data?.links || typeof data.links !== 'object' || Array.isArray(data.links)) return [];
  return Object.entries(data.links).map(([name, link]: [string, any]) => ({
    name,
    operationId: link?.operationId,
    operationRef: link?.operationRef,
    description: link?.description,
    parameters: link?.parameters && typeof link.parameters === 'object' ? link.parameters : undefined,
  }));
}

function linksArrayToDataMap(links: ResponseLinkItem[]): Record<string, { operationId?: string; operationRef?: string; description?: string; parameters?: Record<string, string> }> {
  const map: Record<string, { operationId?: string; operationRef?: string; description?: string; parameters?: Record<string, string> }> = {};
  for (const link of links) {
    if (!link.name.trim()) continue;
    const key = link.name.trim();
    map[key] = {};
    if (link.operationId?.trim()) map[key].operationId = link.operationId.trim();
    if (link.operationRef?.trim()) map[key].operationRef = link.operationRef.trim();
    if (link.description?.trim()) map[key].description = link.description.trim();
    if (link.parameters && typeof link.parameters === 'object') {
      const filtered = Object.fromEntries(
        Object.entries(link.parameters).filter(
          ([k, v]) => k.trim() !== '' && v.trim() !== '' && !String(k).startsWith('__new_')
        )
      );
      if (Object.keys(filtered).length > 0) map[key].parameters = filtered;
    }
  }
  return map;
}

export default function ResponsePropertiesPanel({
  responseId,
  statusCode,
  initialDescription = '',
  versionPathId,
  refreshKey = 0,
  onClose,
  onRefresh,
}: ResponsePropertiesPanelProps) {
  const isDark = useDarkMode();
  const { alert: alertDialog, confirm: confirmDialog } = useDialog();
  const { selectedVersionId } = useStudio();

  const [description, setDescription] = useState(initialDescription);
  const [statusCodeEdit, setStatusCodeEdit] = useState(statusCode);
  const [responseSchema, setResponseSchema] = useState<any>(null);
  const [currentResponse, setCurrentResponse] = useState<any>(null); // Store full response data
  const [headers, setHeaders] = useState<ResponseHeaderItem[]>([]);
  const [links, setLinks] = useState<ResponseLinkItem[]>([]);
  const [contentTypes, setContentTypes] = useState<ContentTypeMapItem[]>([]);
  const [selectedContentTypeIndex, setSelectedContentTypeIndex] = useState(0);
  const [classes, setClasses] = useState<Array<{ id: string; name: string }>>([]);
  const refRegistry = useMemo(() => createPathsVersionRefRegistry(classes), [classes]);
  const [newMediaType, setNewMediaType] = useState('application/json');
  const [showAddContentType, setShowAddContentType] = useState(false);
  const [isSavingContentType, setIsSavingContentType] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saved'>('idle');
  const previousSchemaRef = useRef<any>(null); // Store previous schema for rollback on cancel

  // Load response data when responseId changes
  useEffect(() => {
    if (!responseId || !versionPathId) {
      setDescription('');
      setResponseSchema(null);
      setHeaders([]);
      setLinks([]);
      setContentTypes([]);
      setCurrentResponse(null);
      return;
    }

    const loadResponse = async () => {
      setIsLoading(true);
      try {
        // Get all responses for this path and find the one we need
        const responsesResponse = await getSharedPathResponses(versionPathId);
        const responsesData = JSON.parse(responsesResponse);

        if (responsesData.success && responsesData.responses) {
          const response = responsesData.responses.find((r: any) => r.id === responseId);
          
          if (response) {
            // Store full response data for validation
            setCurrentResponse(response);
            // Sync status code (capture value) from DB for editing / catch-all (default, 2XX, etc.)
            setStatusCodeEdit(response.status_code ?? statusCode);
            
            // Update description
            setDescription(response.description || initialDescription);

            // Load response headers from data.headers (OpenAPI format: map of name -> { description?, schema? })
            const rawData = response.data ? (typeof response.data === 'string' ? JSON.parse(response.data) : response.data) : null;
            setHeaders(dataHeadersToArray(rawData));
            setLinks(dataLinksToArray(rawData));

            // Content type map: each content type has its own schema binding (class_id or inline_schema)
            const cts = (response.content_types || []).map((ct: any) => ({
              id: ct.id,
              media_type: ct.media_type,
              class_id: ct.class_id,
              class_name: ct.class_name,
              inline_schema: typeof ct.inline_schema === 'string' ? (ct.inline_schema ? JSON.parse(ct.inline_schema) : null) : ct.inline_schema,
              examples: typeof ct.examples === 'string' ? (ct.examples ? JSON.parse(ct.examples) : null) : ct.examples,
            }));
            setContentTypes(cts);
            setSelectedContentTypeIndex(0);

            // Load schema based on schema_mode
            let schema: any = null;
            const schemaMode = response.schema_mode;
            
            console.log('[ResponsePropertiesPanel] Loading response, schema_mode:', schemaMode);
            
            if (schemaMode === 'class' && response.class_id) {
              // Class reference mode - build $ref schema
              const className = response.class_name || 'Unknown';
              schema = { $ref: `#/components/schemas/${className}` };
              console.log('[ResponsePropertiesPanel] Loaded class reference schema:', schema);
            } else if (schemaMode === 'primitive' || schemaMode === 'array') {
              // Primitive or array mode - schema is directly in data field
              if (response.data) {
                try {
                  schema = typeof response.data === 'string' 
                    ? JSON.parse(response.data) 
                    : response.data;
                  console.log('[ResponsePropertiesPanel] Loaded primitive/array schema:', schema);
                } catch (error) {
                  console.error('Error parsing primitive/array data:', error);
                }
              }
            } else if (schemaMode === 'object') {
              // Object mode - use full inline_schema (type + properties) so SchemaBuilder shows them
              if (response.inline_schema) {
                try {
                  const inlineSchema = typeof response.inline_schema === 'string'
                    ? JSON.parse(response.inline_schema)
                    : response.inline_schema;
                  schema = inlineSchema && typeof inlineSchema === 'object'
                    ? { type: 'object', ...inlineSchema }
                    : { type: 'object' };
                } catch (error) {
                  console.error('Error parsing inline_schema:', error);
                  schema = { type: 'object' };
                }
              } else {
                schema = { type: 'object' };
              }
            } else {
              // Legacy/fallback - try to extract from data field (old OpenAPI format)
              if (response.data) {
                try {
                  const responseData = typeof response.data === 'string' 
                    ? JSON.parse(response.data) 
                    : response.data;
                  
                  // Extract schema from the data structure
                  // OpenAPI format: content['application/json'].schema
                  schema = responseData?.content?.['application/json']?.schema || responseData?.schema || null;
                  console.log('[ResponsePropertiesPanel] Loaded legacy schema:', schema);
                } catch (error) {
                  console.error('Error parsing response data:', error);
                }
              }
            }

            setResponseSchema(schema);
            previousSchemaRef.current = schema;
          }
        }
      } catch (error) {
        console.error('Error loading response:', error);
      } finally {
        setIsLoading(false);
      }
    };

    loadResponse();
  }, [responseId, versionPathId, initialDescription, refreshKey]); // Include refreshKey to reload when canvas refreshes

  // Load classes for content type schema binding (class reference dropdown)
  useEffect(() => {
    if (!selectedVersionId) {
      setClasses([]);
      return;
    }
    const loadClasses = async () => {
      try {
        const res = await getClassesWithPropertiesAndTags(selectedVersionId);
        const data: any[] = JSON.parse(res as string);
        setClasses((data || []).map((c: any) => ({ id: c.id, name: c.name })));
      } catch {
        setClasses([]);
      }
    };
    loadClasses();
  }, [selectedVersionId]);

  // Reload content types from server (after add/delete/class change)
  const reloadContentTypes = useCallback(async () => {
    if (!responseId || !versionPathId) return;
    try {
      const responsesResponse = await getSharedPathResponses(versionPathId);
      const parsed = JSON.parse(responsesResponse);
      if (parsed.success && parsed.responses) {
        const response = parsed.responses.find((r: any) => r.id === responseId);
        if (response?.content_types) {
          const cts = response.content_types.map((ct: any) => ({
            id: ct.id,
            media_type: ct.media_type,
            class_id: ct.class_id,
            class_name: ct.class_name,
            inline_schema: typeof ct.inline_schema === 'string' ? (ct.inline_schema ? JSON.parse(ct.inline_schema) : null) : ct.inline_schema,
            examples: typeof ct.examples === 'string' ? (ct.examples ? JSON.parse(ct.examples) : null) : ct.examples,
          }));
          setContentTypes(cts);
          setCurrentResponse((prev: any) => (prev ? { ...prev, content_types: response.content_types } : null));
        }
      }
      if (onRefresh) onRefresh();
    } catch (e) {
      console.error('Error reloading content types:', e);
    }
  }, [responseId, versionPathId, onRefresh]);

  // Listen for onRefresh callback and reload when it's called
  // This happens when a class is dropped on a response
  const prevOnRefreshRef = useRef(onRefresh);
  useEffect(() => {
    if (prevOnRefreshRef.current !== onRefresh) {
      prevOnRefreshRef.current = onRefresh;
      // onRefresh changed, but we can't call it directly
      // Instead, we'll reload when responseId or versionPathId changes
    }
  }, [onRefresh]);

    // Also reload when canvas refresh happens (detected via a small delay after responseId is set)
    // This ensures we get fresh data after drag-drop operations
    useEffect(() => {
      if (!responseId || !versionPathId) return;
      
      // Longer delay to ensure database is updated after drag-drop
      const timeoutId = setTimeout(() => {
        const loadResponse = async () => {
          try {
            const responsesResponse = await getSharedPathResponses(versionPathId);
            const responsesData = JSON.parse(responsesResponse);

            if (responsesData.success && responsesData.responses) {
              const response = responsesData.responses.find((r: any) => r.id === responseId);
              
              if (response) {
                // Store full response data
                setCurrentResponse(response);
                
                setDescription(response.description || initialDescription);

                const rawData = response.data ? (typeof response.data === 'string' ? JSON.parse(response.data) : response.data) : null;
                setHeaders(dataHeadersToArray(rawData));
                setLinks(dataLinksToArray(rawData));

                const cts = (response.content_types || []).map((ct: any) => ({
                  id: ct.id,
                  media_type: ct.media_type,
                  class_id: ct.class_id,
                  class_name: ct.class_name,
                  inline_schema: typeof ct.inline_schema === 'string' ? (ct.inline_schema ? JSON.parse(ct.inline_schema) : null) : ct.inline_schema,
                  examples: typeof ct.examples === 'string' ? (ct.examples ? JSON.parse(ct.examples) : null) : ct.examples,
                }));
                setContentTypes(cts);

                // Load schema based on schema_mode (same logic as main useEffect)
                let schema: any = null;
                const schemaMode = response.schema_mode;
                
                if (schemaMode === 'class' && response.class_id) {
                  const className = response.class_name || 'Unknown';
                  schema = { $ref: `#/components/schemas/${className}` };
                } else if (schemaMode === 'primitive' || schemaMode === 'array') {
                  if (response.data) {
                    try {
                      schema = typeof response.data === 'string' 
                        ? JSON.parse(response.data) 
                        : response.data;
                    } catch (error) {
                      console.error('Error parsing primitive/array data:', error);
                    }
                  }
                } else if (schemaMode === 'object') {
                  schema = { type: 'object' };
                } else {
                  // Legacy/fallback
                  if (response.data) {
                    try {
                      const responseData = typeof response.data === 'string' 
                        ? JSON.parse(response.data) 
                        : response.data;
                      schema = responseData?.content?.['application/json']?.schema || responseData?.schema || null;
                    } catch (error) {
                      console.error('Error parsing response data:', error);
                    }
                  }
                }

                setResponseSchema(schema);
                previousSchemaRef.current = schema;
              }
            }
          } catch (error) {
            console.error('Error reloading response:', error);
          }
        };
        
        loadResponse();
      }, 800);

      return () => clearTimeout(timeoutId);
    }, [responseId, versionPathId, initialDescription]);

  // Handle schema changes with validation
  const handleSchemaChange = async (newSchema: any) => {
    if (!currentResponse || !responseId) {
      previousSchemaRef.current = responseSchema;
      setResponseSchema(newSchema);
      return;
    }

    console.log('[ResponsePropertiesPanel] handleSchemaChange called');
    console.log('[ResponsePropertiesPanel] Current schema:', responseSchema);
    console.log('[ResponsePropertiesPanel] New schema:', newSchema);
    console.log('[ResponsePropertiesPanel] Current response:', currentResponse);

    // Store the current schema in case we need to rollback
    previousSchemaRef.current = responseSchema;

    // Temporarily set the new schema so the UI updates
    setResponseSchema(newSchema);

    const contentTypes = currentResponse.content_types || [];
    
    // Determine what type we're switching TO
    const newSchemaType = newSchema?.type;
    const isNewSchemaClass = !!newSchema?.$ref;
    const isNewSchemaObject = newSchemaType === 'object';
    const isNewSchemaPrimitive = newSchemaType === 'string' || newSchemaType === 'number' || newSchemaType === 'integer' || newSchemaType === 'boolean';
    const isNewSchemaArray = newSchemaType === 'array';
    
    // Determine new schema mode
    let newSchemaMode: 'class' | 'object' | 'primitive' | 'array' = 'object';
    if (isNewSchemaClass) {
      newSchemaMode = 'class';
    } else if (isNewSchemaArray) {
      newSchemaMode = 'array';
    } else if (isNewSchemaPrimitive) {
      newSchemaMode = 'primitive';
    } else if (isNewSchemaObject) {
      newSchemaMode = 'object';
    }
    
    // Check what we're switching FROM by looking at actual response state
    const currentSchemaMode = currentResponse.schema_mode || 'object';
    const hasClassReference = currentResponse.class_id || currentResponse.class_name;
    
    console.log('[ResponsePropertiesPanel] Current schema_mode:', currentSchemaMode);
    console.log('[ResponsePropertiesPanel] New schema_mode:', newSchemaMode);
    console.log('[ResponsePropertiesPanel] Schema mode changing:', currentSchemaMode !== newSchemaMode);
    
    // Check if we're actually changing schema modes
    const isChangingMode = currentSchemaMode !== newSchemaMode;
    
    if (!isChangingMode) {
      // Not changing modes, allow the schema update without warning
      console.log('[ResponsePropertiesPanel] Same schema mode, no warning needed');
      setResponseSchema(newSchema);
      previousSchemaRef.current = newSchema;
      return;
    }

    // We are changing schema modes - build warning message based on what will be lost
    console.log('[ResponsePropertiesPanel] Schema mode changing from', currentSchemaMode, 'to', newSchemaMode);
    
    // hasClassReference is already declared above, so we can use it directly
    
    // Check for inline properties in content types
    const contentTypesWithSchemas = contentTypes.filter((ct: any) => {
      const schema = typeof ct.inline_schema === 'string' 
        ? JSON.parse(ct.inline_schema) 
        : ct.inline_schema;
      return schema?.type === 'object' || (schema?.properties && schema.properties.length > 0);
    });

    // Count properties
    const propertyCount = contentTypes.reduce((count: number, ct: any) => {
      const schema = typeof ct.inline_schema === 'string' 
        ? JSON.parse(ct.inline_schema) 
        : ct.inline_schema;
      return count + (schema?.properties?.length || 0);
    }, 0);
    
    // Check for inline schema at response level
    let hasResponseInlineSchema = false;
    if (currentResponse.inline_schema) {
      try {
        const schema = typeof currentResponse.inline_schema === 'string'
          ? JSON.parse(currentResponse.inline_schema)
          : currentResponse.inline_schema;
        hasResponseInlineSchema = schema?.type === 'object' && 
          schema?.properties && 
          schema.properties.length > 0;
      } catch {
        // Ignore parse errors
      }
    }

    // Build appropriate warning message
    let warningTitle = 'Change Schema Type?';
    let warningMessage = '';
    let warningVariant: 'warning' | 'danger' = 'warning';
    
    const newModeName = newSchemaMode === 'class' ? 'Class Reference' 
      : newSchemaMode === 'array' ? 'Array'
      : newSchemaMode === 'primitive' ? 'Primitive'
      : 'Object';
    
    const currentModeName = currentSchemaMode === 'class' ? 'Class Reference'
      : currentSchemaMode === 'array' ? 'Array'
      : currentSchemaMode === 'primitive' ? 'Primitive'
      : 'Object';
    
    if (hasClassReference) {
      warningTitle = 'Remove Class Reference?';
      warningMessage = `This response currently uses the "${currentResponse.class_name || 'Unknown'}" class. Switching from ${currentModeName} to ${newModeName} will remove this class reference. Continue?`;
      warningVariant = 'warning';
    } else if (propertyCount > 0 || hasResponseInlineSchema) {
      warningTitle = 'Delete Inline Properties?';
      warningMessage = `This response currently has ${propertyCount} inline ${propertyCount === 1 ? 'property' : 'properties'}. Switching from ${currentModeName} to ${newModeName} will delete ${propertyCount === 1 ? 'this property' : 'these properties'}. This action cannot be undone. Continue?`;
      warningVariant = 'danger';
    } else if (currentSchemaMode === 'primitive' || currentSchemaMode === 'array') {
      warningTitle = 'Change Schema Type?';
      warningMessage = `Switching from ${currentModeName} to ${newModeName} will change the fundamental structure of this response. Continue?`;
      warningVariant = 'warning';
    } else {
      // Generic warning for other mode changes
      warningTitle = 'Change Schema Type?';
      warningMessage = `Switching from ${currentModeName} to ${newModeName} will change how this response is defined. Continue?`;
      warningVariant = 'warning';
    }
    
    const confirmed = await confirmDialog({
      title: warningTitle,
      message: warningMessage,
      variant: warningVariant,
      confirmLabel: 'Switch Type',
      cancelLabel: 'Cancel',
    });

    if (!confirmed) {
      console.log('[ResponsePropertiesPanel] User cancelled schema mode change, rolling back');
      // Restore previous schema
      setResponseSchema(previousSchemaRef.current);
      return;
    }

    // User confirmed - proceed with the change
    console.log('[ResponsePropertiesPanel] User confirmed schema mode change');
    
    // Delete content types with inline schemas if switching away from object mode
    if (contentTypesWithSchemas.length > 0) {
      console.log('[ResponsePropertiesPanel] Deleting content types with inline schemas');
      for (const ct of contentTypesWithSchemas) {
        try {
          await deleteResponseContentType(ct.id);
          console.log('[ResponsePropertiesPanel] Deleted content type:', ct.id);
        } catch (error) {
          console.error('Error deleting content type:', error);
        }
      }

      // Update current response to reflect deletions
      setCurrentResponse({
        ...currentResponse,
        content_types: contentTypes.filter((ct: any) => !contentTypesWithSchemas.some((deleted: any) => deleted.id === ct.id)),
      });
    }

    // Update the response in the database with the new schema mode
    console.log('[ResponsePropertiesPanel] Updating response schema mode in database');
    const updateData: any = {
      schemaMode: newSchemaMode,
      inlineSchema: null,
      classId: null,
    };

    // Set data field based on target mode
    if (newSchemaMode === 'class') {
      // For class reference, set an empty object to satisfy the constraint
      // The actual class reference will be set when user selects a class
      updateData.data = {};
    } else if (newSchemaMode === 'object') {
      // For object mode, use inline_schema instead of data
      updateData.data = null;
      updateData.inlineSchema = { type: 'object', properties: [] };
    } else {
      // For primitive/array modes, store schema in data
      updateData.data = newSchema || { type: 'string' };
    }

    try {
      const result = await updateSharedPathResponse(responseId, updateData);
      const data = JSON.parse(result);
      
      if (!data.success) {
        await alertDialog({
          message: data.error || 'Failed to update response schema',
          variant: 'error',
        });
        // Rollback schema on error
        setResponseSchema(previousSchemaRef.current);
        return;
      }

      console.log('[ResponsePropertiesPanel] Response schema mode updated successfully');

      // Update current response state
      setCurrentResponse({
        ...currentResponse,
        schema_mode: newSchemaMode,
        class_id: newSchemaMode === 'class' ? currentResponse.class_id : null,
        class_name: newSchemaMode === 'class' ? currentResponse.class_name : null,
      });

      // Update previousSchemaRef to the new value
      previousSchemaRef.current = newSchema;

      // Refresh canvas to update visual representation
      if (onRefresh) {
        onRefresh();
      }
    } catch (error) {
      console.error('Error updating response schema mode:', error);
      await alertDialog({
        message: 'Failed to update response schema',
        variant: 'error',
      });
      // Rollback schema on error
      setResponseSchema(previousSchemaRef.current);
      return;
    }

    // This line should not be reached if mode is changing (handled above)
    // But if we get here without mode change, just update normally
    console.log('[ResponsePropertiesPanel] Schema updated without mode change');
    setResponseSchema(newSchema);
    previousSchemaRef.current = newSchema;
  };

  const handleAddContentType = async () => {
    if (!responseId || !newMediaType.trim()) return;
    setIsSavingContentType(true);
    try {
      const result = await addResponseContentType(
        responseId,
        newMediaType.trim(),
        undefined,
        { type: 'object', properties: [] },
        undefined
      );
      const parsed = JSON.parse(result);
      if (parsed.success) {
        setNewMediaType('application/json');
        setShowAddContentType(false);
        await reloadContentTypes();
      } else {
        await alertDialog({ message: parsed.error || 'Failed to add content type', variant: 'error' });
      }
    } catch {
      await alertDialog({ message: 'Failed to add content type', variant: 'error' });
    } finally {
      setIsSavingContentType(false);
    }
  };

  const handleDeleteContentType = async (contentTypeId: string) => {
    if (!confirm('Remove this content type and its schema binding?')) return;
    try {
      await deleteResponseContentType(contentTypeId);
      await reloadContentTypes();
      setSelectedContentTypeIndex((i) => Math.max(0, i - 1));
    } catch {
      await alertDialog({ message: 'Failed to delete content type', variant: 'error' });
    }
  };

  const handleContentTypeClassChange = async (contentId: string, classId: string) => {
    try {
      if (!classId || classId === '__none__') {
        const result = await updateResponseContentType(contentId, { classId: null });
        const parsed = JSON.parse(result);
        if (!parsed.success) await alertDialog({ message: parsed.error || 'Failed to clear class', variant: 'error' });
        else await reloadContentTypes();
        return;
      }
      const result = await setResponseContentTypeClassReference(contentId, classId);
      const parsed = JSON.parse(result);
      if (!parsed.success) await alertDialog({ message: parsed.error || 'Failed to set class', variant: 'error' });
      else await reloadContentTypes();
    } catch {
      await alertDialog({ message: 'Failed to update schema binding', variant: 'error' });
    }
  };

  const handleContentTypeExamplesChange = async (contentId: string, examples: ResponseExampleItem[]) => {
    try {
      const result = await updateResponseContentType(contentId, { examples: examples.length ? examples : null });
      const parsed = JSON.parse(result);
      if (!parsed.success) await alertDialog({ message: parsed.error || 'Failed to update examples', variant: 'error' });
      else await reloadContentTypes();
    } catch {
      await alertDialog({ message: 'Failed to update examples', variant: 'error' });
    }
  };

  const handleSave = async () => {
    if (!responseId) return;

    const codeToSave = statusCodeEdit.trim();
    if (!codeToSave) {
      await alertDialog({ message: 'Status code (capture value) is required.', variant: 'error' });
      return;
    }
    if (!isValidStatusCode(codeToSave)) {
      await alertDialog({
        message: 'Enter a valid HTTP status code (e.g. 200, 404), a range (2XX, 4XX), or "default" for catch-all.',
        variant: 'error',
      });
      return;
    }

    setIsSaving(true);
    setSaveStatus('idle');
    try {
      const updateData: any = {
        description: description.trim() || undefined,
        statusCode: codeToSave,
      };

      // Determine schema mode based on the schema type
      const schemaType = responseSchema?.type;
      let schemaMode: 'object' | 'primitive' | 'array' | 'class' = 'object';
      
      console.log('[ResponsePropertiesPanel] Saving with schema:', responseSchema);
      
      if (responseSchema?.$ref) {
        // Class reference mode
        schemaMode = 'class';
        
        // Extract class name from $ref to look up class ID
        const className = responseSchema.$ref.split('/').pop();
        
        // Try to find the class ID from our loaded classes
        const classesResponse = await getClassesWithPropertiesAndTags(selectedVersionId || '');
        const classesData: any[] = JSON.parse(classesResponse as string);
        const classInfo = classesData.find((c: any) => c.name === className);
        
        if (classInfo) {
          updateData.classId = classInfo.id;
        }
        
        updateData.data = {
          content: {
            'application/json': {
              schema: responseSchema,
            },
          },
        };
        updateData.inlineSchema = null;
        
        console.log('[ResponsePropertiesPanel] Setting class mode, classId:', updateData.classId);
      } else if (schemaType === 'array') {
        // Array mode - clear class reference
        schemaMode = 'array';
        updateData.data = responseSchema || { type: 'array', items: { type: 'string' } };
        updateData.inlineSchema = null;
        updateData.classId = null; // CRITICAL: Clear class reference
        
        console.log('[ResponsePropertiesPanel] Setting array mode, clearing classId');
      } else if (schemaType === 'string' || schemaType === 'number' || schemaType === 'integer' || schemaType === 'boolean') {
        // Primitive mode - clear class reference
        schemaMode = 'primitive';
        updateData.data = responseSchema || { type: schemaType || 'string' };
        updateData.inlineSchema = null;
        updateData.classId = null; // CRITICAL: Clear class reference
        
        console.log('[ResponsePropertiesPanel] Setting primitive mode, clearing classId');
      } else if (schemaType === 'object') {
        // Object mode - clear class reference
        schemaMode = 'object';
        // For object mode, use inline_schema (not data) to satisfy constraint
        updateData.data = null;
        updateData.inlineSchema = { type: 'object', properties: [] };
        updateData.classId = null; // CRITICAL: Clear class reference
        
        console.log('[ResponsePropertiesPanel] Setting object mode, clearing classId');
      } else if (!responseSchema) {
        // No schema defined at all - set a default to satisfy constraint
        // The database requires at least one of: class_id, inline_schema, or data
        schemaMode = 'object';
        updateData.data = null;
        updateData.inlineSchema = { type: 'object', properties: [] };
        updateData.classId = null;
        
        console.log('[ResponsePropertiesPanel] No schema, setting default object');
      } else {
        // Fallback - treat as object
        schemaMode = 'object';
        updateData.data = null;
        updateData.inlineSchema = { type: 'object', properties: [] };
        updateData.classId = null;
        
        console.log('[ResponsePropertiesPanel] Unknown schema type, defaulting to object');
      }

      updateData.schemaMode = schemaMode;

      // Merge response headers into data (OpenAPI: data.headers = map of name -> { description?, schema? })
      const headersMap = headersArrayToDataMap(headers);
      const baseData =
        updateData.data !== undefined && updateData.data !== null && typeof updateData.data === 'object'
          ? updateData.data
          : currentResponse?.data && typeof currentResponse.data === 'object'
            ? (typeof currentResponse.data === 'string' ? JSON.parse(currentResponse.data) : currentResponse.data)
            : {};
      const linksMap = linksArrayToDataMap(links);
      updateData.data = { ...baseData, headers: headersMap, links: linksMap };

      console.log('[ResponsePropertiesPanel] Updating response with data:', updateData);
      
      const result = await updateSharedPathResponse(responseId, updateData);

      const data = JSON.parse(result);
      if (!data.success) {
        await alertDialog({
          message: data.error || 'Failed to update response',
          variant: 'error',
        });
        return;
      }

      console.log('[ResponsePropertiesPanel] Response updated successfully');

      setCurrentResponse((prev: any) => (prev ? { ...prev, status_code: codeToSave } : null));
      setStatusCodeEdit(codeToSave);
      setSaveStatus('saved');
      setTimeout(() => setSaveStatus('idle'), 2000);
      
      // Force canvas refresh to update node label and connections
      if (onRefresh) {
        console.log('[ResponsePropertiesPanel] Triggering canvas refresh');
        onRefresh();
      }
    } catch (error) {
      console.error('Error saving response:', error);
      await alertDialog({
        message: 'An error occurred while saving the response',
        variant: 'error',
      });
    } finally {
      setIsSaving(false);
    }
  };

  const statusSubtitle = getHttpStatusDescription(statusCodeEdit)
    ? `${statusCodeEdit} – ${getHttpStatusDescription(statusCodeEdit)}`
    : `Status: ${statusCodeEdit}`;

  return (
    <PropertiesPanelShell
      icon={<MessageSquareReply />}
      title="Response Properties"
      subtitle={statusSubtitle}
      onClose={onClose}
      bodyScroll={false}
      footer={
        <Button
          type="button"
          variant={saveStatus === 'saved' ? 'success' : 'default'}
          className="w-full"
          onClick={handleSave}
          disabled={isSaving || !responseId}
        >
          <Save className="w-4 h-4" />
          {isSaving ? 'Saving...' : saveStatus === 'saved' ? 'Saved' : 'Save Changes'}
        </Button>
      }
    >
      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4">
        <div className="flex flex-col gap-2.5">
          <PropertiesPanelSection title="Status" defaultOpen>
            <div className="flex flex-col gap-3">
          <div>
            <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
              Response status (capture value)
            </label>
            <div className="flex items-center gap-2">
              <span
                className={`px-2 py-0.5 rounded font-mono text-xs font-semibold tabular-nums ${
                  STATUS_ROLE_CHIP[statusRoleForCode(statusCodeEdit)]
                }`}
              >
                {statusCodeEdit || '—'}
              </span>
              <Input
                list="response-status-codes"
                value={statusCodeEdit}
                onChange={(e) => setStatusCodeEdit(e.target.value)}
                placeholder="e.g. 200, 2XX, default"
                className="flex-1 text-sm font-mono"
              />
            </div>
            <datalist id="response-status-codes">
              {STATUS_RANGE_AND_DEFAULT.map((c) => (
                <option key={c} value={c} />
              ))}
              {COMMON_STATUS_CODES.success.map((c) => (
                <option key={c} value={c} />
              ))}
              {COMMON_STATUS_CODES.client_error.map((c) => (
                <option key={c} value={c} />
              ))}
              {COMMON_STATUS_CODES.server_error.map((c) => (
                <option key={c} value={c} />
              ))}
              {COMMON_STATUS_CODES.redirection.map((c) => (
                <option key={c} value={c} />
              ))}
            </datalist>
            <p className="text-[11px] text-gray-500 dark:text-gray-400 mt-1">
              Use a specific code (e.g. 200), a range (2XX, 4XX), or <strong>default</strong> for catch-all.
            </p>
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
              Description
            </label>
            <Textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Describe this response..."
              rows={4}
              className="text-sm resize-none"
            />
          </div>
            </div>
          </PropertiesPanelSection>

          <PropertiesPanelSection
            title="Content types"
            count={contentTypes.length}
            defaultOpen={contentTypes.length > 0}
            actions={
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-7 px-2 text-xs text-indigo-600 dark:text-indigo-400"
                onClick={() => setShowAddContentType(true)}
              >
                <Plus className="w-3.5 h-3.5" />
                Add
              </Button>
            }
          >
          <div>
            <p className="text-[11px] text-gray-500 dark:text-gray-400 mb-2">
              Map each media type to a schema (class reference or inline).
            </p>

            {contentTypes.length > 0 ? (
              <>
                <Tabs
                  value={String(selectedContentTypeIndex)}
                  onValueChange={(v) => setSelectedContentTypeIndex(Number(v))}
                  className="w-full"
                >
                  <TabsList className={`h-8 w-full justify-start overflow-x-auto ${isDark ? 'bg-slate-800' : 'bg-slate-100'}`}>
                    {contentTypes.map((ct, idx) => (
                      <TabsTrigger key={ct.id} value={String(idx)} className="flex items-center gap-1.5 text-xs">
                        <FileJson className="w-3 h-3" />
                        {ct.media_type}
                      </TabsTrigger>
                    ))}
                  </TabsList>
                  {contentTypes.map((ct, idx) => (
                    <TabsContent key={ct.id} value={String(idx)} className="mt-3 space-y-3">
                      <div className="flex items-center justify-between">
                        <span className="text-[11px] font-mono text-slate-600 dark:text-slate-300">
                          {ct.media_type}
                        </span>
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          className="h-7 px-2 text-xs text-rose-600 hover:bg-rose-50 dark:text-rose-400 dark:hover:bg-rose-950/40"
                          onClick={() => handleDeleteContentType(ct.id)}
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                          Remove
                        </Button>
                      </div>
                      <div>
                        <span className="text-[11px] font-medium text-gray-500 dark:text-gray-400 block mb-1">
                          Schema binding (reuse class)
                        </span>
                        <ReuseSearchCombobox
                          aria-label="Response content type schema binding"
                          items={
                            [
                              { id: '__none__', label: '— None —' },
                              ...(ct.inline_schema && !ct.class_id
                                ? [
                                    {
                                      id: '__inline__',
                                      label: '— Inline schema —',
                                      description: 'Edit in Operation → Responses',
                                      disabled: true,
                                    } satisfies ReuseSearchItem,
                                  ]
                                : []),
                              ...classes.map((c) => ({ id: c.id, label: c.name })),
                            ] as ReuseSearchItem[]
                          }
                          value={
                            ct.class_id ? ct.class_id : ct.inline_schema ? '__inline__' : '__none__'
                          }
                          onValueChange={(v) => handleContentTypeClassChange(ct.id, v)}
                          placeholder="Search classes…"
                          searchPlaceholder="Filter by name…"
                          emptyText="No matches."
                          triggerClassName={`h-9 text-xs ${isDark ? 'bg-slate-800 border-slate-600' : ''}`}
                        />
                        {ct.class_id && refRegistry.isOrphanClassId(ct.class_id) && (
                          <p className="text-[10px] text-amber-600 dark:text-amber-400 mt-1">
                            This class is missing from the version (rename/delete). Fix the reference before export.
                          </p>
                        )}
                        {ct.inline_schema &&
                          refRegistry.findBrokenComponentSchemaRefs(ct.inline_schema).length > 0 && (
                            <p className="text-[10px] text-amber-600 dark:text-amber-400 mt-1">
                              Inline schema contains{' '}
                              <code className="font-mono">$ref</code> to a class not in this version.
                            </p>
                          )}
                        {ct.inline_schema && !ct.class_id && (
                          <p className="text-[10px] text-gray-500 dark:text-gray-400 mt-1">
                            Inline schema ({Array.isArray(ct.inline_schema?.properties) ? ct.inline_schema.properties.length : 0}{' '}
                            properties). Use Operation panel → Responses to edit inline schema.
                          </p>
                        )}
                      </div>

                      {/* Examples per content type */}
                      <div className={`pt-3 border-t ${isDark ? 'border-slate-700' : 'border-slate-200'}`}>
                        <div className="flex items-center justify-between mb-2">
                          <span className="text-[11px] font-medium text-gray-500 dark:text-gray-400">Examples</span>
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            className="h-6 text-[10px]"
                            onClick={() => {
                              const prev = (ct.examples || []) as ResponseExampleItem[];
                              const next = [...prev, { name: `Example ${prev.length + 1}`, summary: '', value: {} }];
                              handleContentTypeExamplesChange(ct.id, next);
                            }}
                          >
                            <Plus className="w-3 h-3 mr-1" />
                            Add example
                          </Button>
                        </div>
                        <p className="text-[10px] text-gray-500 dark:text-gray-400 mb-2">
                          Example responses for this content type (name, summary, value).
                        </p>
                        <div className="space-y-2">
                          {((ct.examples || []) as ResponseExampleItem[]).map((ex, exIdx) => (
                            <div
                              key={exIdx}
                              className={`p-2 rounded border ${isDark ? 'border-slate-600 bg-slate-800/50' : 'border-slate-200 bg-slate-50/50'}`}
                            >
                              <div className="flex gap-2 mb-1.5">
                                <Input
                                  placeholder="Name (optional)"
                                  value={ex.name ?? ''}
                                  onChange={(e) => {
                                    const prev = (ct.examples || []) as ResponseExampleItem[];
                                    const next = prev.map((x, i) => i === exIdx ? { ...x, name: e.target.value || undefined } : x);
                                    handleContentTypeExamplesChange(ct.id, next);
                                  }}
                                  className="text-xs h-7 flex-1"
                                />
                                <button
                                  type="button"
                                  onClick={() => {
                                    const prev = (ct.examples || []) as ResponseExampleItem[];
                                    handleContentTypeExamplesChange(ct.id, prev.filter((_, i) => i !== exIdx));
                                  }}
                                  className="p-1.5 rounded text-gray-500 hover:text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20"
                                  aria-label="Remove example"
                                >
                                  <Trash2 className="w-3 h-3" />
                                </button>
                              </div>
                              <Input
                                placeholder="Summary (optional)"
                                value={ex.summary ?? ''}
                                onChange={(e) => {
                                  const prev = (ct.examples || []) as ResponseExampleItem[];
                                  const next = prev.map((x, i) => i === exIdx ? { ...x, summary: e.target.value || undefined } : x);
                                  handleContentTypeExamplesChange(ct.id, next);
                                }}
                                className="mb-1.5 text-xs h-7"
                              />
                              <Textarea
                                key={`${ct.id}-${exIdx}-${JSON.stringify((ex as ResponseExampleItem).value ?? {})}`}
                                placeholder='Value (JSON, e.g. {"id": 1, "name": "..."})'
                                defaultValue={typeof (ex as ResponseExampleItem).value === 'object' && (ex as ResponseExampleItem).value !== null
                                  ? JSON.stringify((ex as ResponseExampleItem).value, null, 2)
                                  : (ex as ResponseExampleItem).value !== undefined && (ex as ResponseExampleItem).value !== null
                                    ? String((ex as ResponseExampleItem).value)
                                    : '{}'}
                                onBlur={(e) => {
                                  const raw = e.target.value.trim();
                                  let value: unknown = raw ? (() => { try { return JSON.parse(raw); } catch { return undefined; } })() : {};
                                  if (value === undefined) return;
                                  const prev = (ct.examples || []) as ResponseExampleItem[];
                                  const next = prev.map((x, i) => i === exIdx ? { ...x, value } : x);
                                  handleContentTypeExamplesChange(ct.id, next);
                                }}
                                rows={3}
                                className="text-[11px] font-mono resize-none"
                              />
                            </div>
                          ))}
                          {(ct.examples?.length ?? 0) === 0 && (
                            <p className="text-[10px] text-gray-500 dark:text-gray-400 italic">No examples. Add one to document sample responses.</p>
                          )}
                        </div>
                      </div>
                    </TabsContent>
                  ))}
                </Tabs>
              </>
            ) : (
              <p className="text-xs text-gray-500 dark:text-gray-400 italic">No content types. Add one to map a media type to a schema.</p>
            )}

            {showAddContentType && (
              <div className={`mt-3 p-3 rounded border ${isDark ? 'border-slate-600 bg-slate-800/50' : 'border-slate-200 bg-slate-50'}`}>
                <label className="block text-[11px] font-medium text-gray-600 dark:text-gray-400 mb-1">New media type</label>
                <div className="flex gap-2">
                  <Input
                    value={newMediaType}
                    onChange={(e) => setNewMediaType(e.target.value)}
                    placeholder="e.g. application/json"
                    className="text-xs h-8 font-mono flex-1"
                  />
                  <Button type="button" size="sm" className="h-8" onClick={handleAddContentType} disabled={isSavingContentType}>
                    {isSavingContentType ? 'Adding…' : 'Add'}
                  </Button>
                  <Button type="button" variant="ghost" size="sm" className="h-8" onClick={() => { setShowAddContentType(false); setNewMediaType('application/json'); }}>
                    Cancel
                  </Button>
                </div>
              </div>
            )}
          </div>
          </PropertiesPanelSection>

          <PropertiesPanelSection title="Schema" defaultOpen>
            {isLoading ? (
              <div className="py-4 text-center">
                <span className="text-xs text-gray-500 dark:text-gray-400">Loading schema...</span>
              </div>
            ) : (
              <SchemaBuilder
                value={responseSchema}
                onChange={handleSchemaChange}
                label="Response Schema"
                description="Define the response body schema using existing classes or create inline schemas"
                allowInline={true}
              />
            )}
          </PropertiesPanelSection>

          <PropertiesPanelSection
            title="Headers"
            count={headers.length}
            defaultOpen={headers.length > 0}
            actions={
              <>
                <Select
                  value=""
                  onValueChange={(value) => {
                    const template = HEADER_TEMPLATES.find((t) => t.id === value);
                    if (!template) return;
                    const existingNames = new Set(headers.map((h) => h.name.trim()).filter(Boolean));
                    const toAdd = template.headers.filter((h) => !existingNames.has(h.name));
                    if (toAdd.length > 0) setHeaders([...headers, ...toAdd]);
                  }}
                >
                  <SelectTrigger className="h-7 w-[130px] text-xs" aria-label="Add from template">
                    <LayoutList className="w-3 h-3 mr-1 shrink-0" />
                    <SelectValue placeholder="Template" />
                  </SelectTrigger>
                  <SelectContent>
                    {HEADER_TEMPLATES.map((t) => (
                      <SelectItem key={t.id} value={t.id} className="text-xs">
                        {t.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-7 px-2 text-xs text-indigo-600 dark:text-indigo-400"
                  onClick={() => setHeaders([...headers, { name: '' }])}
                >
                  <Plus className="w-3.5 h-3.5" />
                  Add
                </Button>
              </>
            }
          >
          <div>
            <p className="text-[11px] text-gray-500 dark:text-gray-400 mb-2">
              Headers returned with this response. Use templates for pagination, rate limiting, or CORS.
            </p>
            <div className="space-y-3">
              {headers.map((header, idx) => (
                <div
                  key={idx}
                  className={`p-2 rounded border ${isDark ? 'border-slate-600 bg-slate-800/50' : 'border-slate-200 bg-slate-50/50'}`}
                >
                  <div className="flex gap-2 mb-1.5">
                    <Input
                      placeholder="Header name (e.g. X-Rate-Limit)"
                      value={header.name}
                      onChange={(e) => {
                        const next = [...headers];
                        next[idx] = { ...next[idx], name: e.target.value };
                        setHeaders(next);
                      }}
                      className="flex-1 text-xs h-8 font-mono"
                    />
                    <button
                      type="button"
                      onClick={() => setHeaders(headers.filter((_, i) => i !== idx))}
                      className="p-1.5 rounded text-gray-500 hover:text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20"
                      aria-label="Remove header"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                  <Input
                    placeholder="Description (optional)"
                    value={header.description ?? ''}
                    onChange={(e) => {
                      const next = [...headers];
                      next[idx] = { ...next[idx], description: e.target.value };
                      setHeaders(next);
                    }}
                    className="mb-1.5 text-xs h-7"
                  />
                  <div className="flex gap-2">
                    <select
                      value={header.schema?.type ?? ''}
                      onChange={(e) => {
                        const next = [...headers];
                        const type = e.target.value || undefined;
                        next[idx] = {
                          ...next[idx],
                          schema: type ? { ...next[idx].schema, type } : undefined,
                        };
                        setHeaders(next);
                      }}
                      className={`text-xs h-7 rounded border flex-1 ${isDark ? 'border-slate-600 bg-slate-800 text-slate-200' : 'border-slate-300 bg-white'}`}
                    >
                      <option value="">No schema type</option>
                      <option value="string">string</option>
                      <option value="integer">integer</option>
                      <option value="number">number</option>
                      <option value="boolean">boolean</option>
                      <option value="array">array</option>
                      <option value="object">object</option>
                    </select>
                    <Input
                      placeholder="Format (e.g. int32)"
                      value={header.schema?.format ?? ''}
                      onChange={(e) => {
                        const next = [...headers];
                        const format = e.target.value || undefined;
                        next[idx] = {
                          ...next[idx],
                          schema: next[idx].schema ? { ...next[idx].schema!, format } : format ? { type: 'string', format } : undefined,
                        };
                        setHeaders(next);
                      }}
                      className="text-xs h-7 w-24 font-mono"
                    />
                  </div>
                </div>
              ))}
              {headers.length === 0 && (
                <p className="text-xs text-gray-500 dark:text-gray-400 italic">No headers defined.</p>
              )}
            </div>
          </div>
          </PropertiesPanelSection>

          <PropertiesPanelSection
            title="Links (HATEOAS)"
            count={links.length}
            defaultOpen={links.length > 0}
            icon={<Link2 />}
            actions={
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-7 px-2 text-xs text-indigo-600 dark:text-indigo-400"
                onClick={() => setLinks([...links, { name: '' }])}
              >
                <Plus className="w-3.5 h-3.5" />
                Add
              </Button>
            }
          >
          <div>
            <p className="text-[11px] text-gray-500 dark:text-gray-400 mb-2">
              Response-driven navigation: link relations to other operations (operationId or operationRef). Use parameters to pass values (e.g. <code className="text-[10px] bg-gray-200 dark:bg-gray-700 px-1 rounded">$request.path.id</code>, <code className="text-[10px] bg-gray-200 dark:bg-gray-700 px-1 rounded">$response.body#/uuid</code>).
            </p>
            <div className="space-y-3">
              {links.map((link, idx) => (
                <div
                  key={idx}
                  className={`p-2 rounded border ${isDark ? 'border-slate-600 bg-slate-800/50' : 'border-slate-200 bg-slate-50/50'}`}
                >
                  <div className="flex gap-2 mb-1.5">
                    <Input
                      placeholder="Link name (e.g. user, order)"
                      value={link.name}
                      onChange={(e) => {
                        const next = [...links];
                        next[idx] = { ...next[idx], name: e.target.value };
                        setLinks(next);
                      }}
                      className="flex-1 text-xs h-8 font-mono"
                    />
                    <button
                      type="button"
                      onClick={() => setLinks(links.filter((_, i) => i !== idx))}
                      className="p-1.5 rounded text-gray-500 hover:text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20"
                      aria-label="Remove link"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                  <Input
                    placeholder="operationId (e.g. getUserById)"
                    value={link.operationId ?? ''}
                    onChange={(e) => {
                      const next = [...links];
                      next[idx] = { ...next[idx], operationId: e.target.value || undefined };
                      setLinks(next);
                    }}
                    className="mb-1.5 text-xs h-7 font-mono"
                  />
                  <Input
                    placeholder="operationRef (URI) — optional if operationId set"
                    value={link.operationRef ?? ''}
                    onChange={(e) => {
                      const next = [...links];
                      next[idx] = { ...next[idx], operationRef: e.target.value || undefined };
                      setLinks(next);
                    }}
                    className="mb-1.5 text-xs h-7 font-mono"
                  />
                  <Input
                    placeholder="Description (optional)"
                    value={link.description ?? ''}
                    onChange={(e) => {
                      const next = [...links];
                      next[idx] = { ...next[idx], description: e.target.value || undefined };
                      setLinks(next);
                    }}
                    className="mb-1.5 text-xs h-7"
                  />
                  {/* Link parameters (OpenAPI 3.1: parameters map for response-driven navigation) */}
                  <div className="mt-2 pt-2 border-t border-slate-200 dark:border-slate-600">
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-[10px] font-medium text-gray-600 dark:text-gray-400">Parameters</span>
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="h-5 text-[10px] px-1.5"
                        onClick={() => {
                          const next = [...links];
                          const params = { ...(next[idx].parameters || {}) };
                          params[`__new_${Date.now()}__`] = '';
                          next[idx] = { ...next[idx], parameters: params };
                          setLinks(next);
                        }}
                      >
                        <Plus className="w-3 h-3 mr-0.5" />
                        Add
                      </Button>
                    </div>
                    <div className="space-y-1">
                      {Object.entries(link.parameters || {}).map(([paramKey, paramVal], pidx) => (
                        <div key={paramKey || pidx} className="flex gap-1 items-center">
                          <Input
                            placeholder="name (e.g. userId)"
                            value={paramKey.startsWith('__new_') ? '' : paramKey}
                            onChange={(e) => {
                              const next = [...links];
                              const params = { ...(next[idx].parameters || {}) };
                              delete params[paramKey];
                              const newKey = e.target.value.trim();
                              if (newKey) params[newKey] = paramVal;
                              next[idx] = { ...next[idx], parameters: Object.keys(params).length ? params : undefined };
                              setLinks(next);
                            }}
                            className="flex-1 min-w-0 text-[10px] h-6 font-mono"
                          />
                          <span className="text-gray-400 text-[10px]">→</span>
                          <Input
                            placeholder="$request.path.id"
                            value={paramVal}
                            onChange={(e) => {
                              const next = [...links];
                              const params = { ...(next[idx].parameters || {}) };
                              const val = e.target.value.trim();
                              if (val) params[paramKey] = val;
                              else delete params[paramKey];
                              next[idx] = { ...next[idx], parameters: Object.keys(params).length ? params : undefined };
                              setLinks(next);
                            }}
                            className="flex-1 min-w-0 text-[10px] h-6 font-mono"
                          />
                          <button
                            type="button"
                            onClick={() => {
                              const next = [...links];
                              const params = { ...(next[idx].parameters || {}) };
                              delete params[paramKey];
                              next[idx] = { ...next[idx], parameters: Object.keys(params).length ? params : undefined };
                              setLinks(next);
                            }}
                            className="p-1 rounded text-gray-400 hover:text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20"
                            aria-label="Remove parameter"
                          >
                            <Trash2 className="w-3 h-3" />
                          </button>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              ))}
              {links.length === 0 && (
                <p className="text-xs text-gray-500 dark:text-gray-400 italic">No links defined.</p>
              )}
            </div>
          </div>
          </PropertiesPanelSection>

        </div>
      </div>
    </PropertiesPanelShell>
  );
}

