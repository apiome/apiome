'use client';

import React, { useState, useEffect, useRef } from 'react';
import Box from '@mui/material/Box';
import TextField from '@mui/material/TextField';
import Button from '@mui/material/Button';
import IconButton from '@mui/material/IconButton';
import { Close, Save } from '@mui/icons-material';
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
  deleteResponseContentType,
} from '../../../../../../lib/db/helper-shared-path-responses-content';
import SchemaBuilder from './SchemaBuilder';
import { useStudio } from '../../StudioContext';

interface ResponsePropertiesPanelProps {
  responseId: string | null;
  statusCode: string;
  initialDescription?: string;
  versionPathId?: string | null;
  refreshKey?: number; // Key from parent to force reload
  onClose: () => void;
  onRefresh?: () => void;
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
  const [responseSchema, setResponseSchema] = useState<any>(null);
  const [currentResponse, setCurrentResponse] = useState<any>(null); // Store full response data
  const [isLoading, setIsLoading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saved'>('idle');
  const refreshCounterRef = useRef(0);
  const previousSchemaRef = useRef<any>(null); // Store previous schema for rollback on cancel

  // Load response data when responseId changes
  useEffect(() => {
    if (!responseId || !versionPathId) {
      setDescription('');
      setResponseSchema(null);
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
            
            // Update description
            setDescription(response.description || initialDescription);

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
              // Object mode - use inline_schema
              if (response.inline_schema) {
                try {
                  const inlineSchema = typeof response.inline_schema === 'string'
                    ? JSON.parse(response.inline_schema)
                    : response.inline_schema;
                  // For object mode, just indicate it's an object type
                  schema = { type: 'object' };
                  console.log('[ResponsePropertiesPanel] Loaded object schema');
                } catch (error) {
                  console.error('Error parsing inline_schema:', error);
                }
              } else {
                // Default to object type
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
      } catch (e) {
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

  const handleSave = async () => {
    if (!responseId) return;

    setIsSaving(true);
    setSaveStatus('idle');
    try {
      const updateData: any = {
        description: description.trim() || undefined,
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

      setSaveStatus('saved');
      setTimeout(() => setSaveStatus('idle'), 2000);
      
      // Force canvas refresh to update node connections and remove class nodes
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

  return (
    <Box
      sx={{
        width: 360,
        height: '100%',
        backgroundColor: isDark ? '#1e293b' : '#ffffff',
        borderLeft: isDark ? '1px solid #334155' : '1px solid #e2e8f0',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
      }}
    >
      {/* Header */}
      <Box
        sx={{
          p: 2,
          borderBottom: isDark ? '1px solid #334155' : '1px solid #e2e8f0',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          backgroundColor: isDark ? '#0f172a' : '#f8fafc',
        }}
      >
        <Box>
          <h3 className="text-sm font-semibold text-gray-900 dark:text-white">Response Properties</h3>
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
            Status Code: {statusCode}
          </p>
        </Box>
        <IconButton
          size="small"
          onClick={onClose}
          sx={{
            color: isDark ? '#9ca3af' : '#6b7280',
            '&:hover': {
              backgroundColor: isDark ? 'rgba(148, 163, 184, 0.1)' : 'rgba(107, 114, 128, 0.1)',
            },
          }}
        >
          <Close fontSize="small" />
        </IconButton>
      </Box>

      {/* Content */}
      <Box
        sx={{
          flex: 1,
          overflowY: 'auto',
          p: 2,
        }}
      >
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          {/* Description */}
          <Box>
            <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
              Description
            </label>
            <TextField
              fullWidth
              multiline
              rows={4}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Describe this response..."
              variant="outlined"
              size="small"
              sx={{
                '& .MuiOutlinedInput-root': {
                  backgroundColor: isDark ? '#0f172a' : '#ffffff',
                  fontSize: '0.875rem',
                  '& fieldset': {
                    borderColor: isDark ? '#334155' : '#e2e8f0',
                  },
                  '&:hover fieldset': {
                    borderColor: isDark ? '#475569' : '#cbd5e1',
                  },
                  '&.Mui-focused fieldset': {
                    borderColor: '#6366f1',
                  },
                },
                '& .MuiInputBase-input': {
                  color: isDark ? '#f1f5f9' : '#1e293b',
                },
              }}
            />
          </Box>

          {/* Response Schema Builder */}
          <Box sx={{ mt: 3, pt: 3, borderTop: isDark ? '1px solid #334155' : '1px solid #e2e8f0' }}>
            {isLoading ? (
              <Box sx={{ py: 2, textAlign: 'center' }}>
                <span className="text-xs text-gray-500 dark:text-gray-400">Loading schema...</span>
              </Box>
            ) : (
              <SchemaBuilder
                value={responseSchema}
                onChange={handleSchemaChange}
                label="Response Schema"
                description="Define the response body schema using existing classes or create inline schemas"
                allowInline={true}
              />
            )}
          </Box>

          {/* Save Button */}
          <Box sx={{ display: 'flex', gap: 1 }}>
            <Button
              fullWidth
              variant="contained"
              startIcon={<Save />}
              onClick={handleSave}
              disabled={isSaving || !responseId}
              sx={{
                textTransform: 'none',
                backgroundColor: '#6366f1',
                '&:hover': {
                  backgroundColor: '#4f46e5',
                },
                '&:disabled': {
                  backgroundColor: isDark ? '#334155' : '#e2e8f0',
                  color: isDark ? '#64748b' : '#94a3b8',
                },
              }}
            >
              {isSaving ? 'Saving...' : saveStatus === 'saved' ? 'Saved!' : 'Save Changes'}
            </Button>
          </Box>
        </Box>
      </Box>
    </Box>
  );
}

