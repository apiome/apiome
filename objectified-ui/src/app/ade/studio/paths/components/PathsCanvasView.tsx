'use client';

import React, { useCallback, useState, useEffect, useRef } from 'react';
import {
  ReactFlow,
  Background,
  BackgroundVariant,
  Controls,
  useNodesState,
  useEdgesState,
  Node,
  Edge,
  ReactFlowProvider,
  useReactFlow,
  Handle,
  Position,
  addEdge,
  Connection,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { useStudio } from '../../StudioContext';
import { useDialog } from '../../../../components/providers/DialogProvider';
import SmartEdge from '../../../../components/ade/studio/SmartEdge';
import {
  getOperationsForPath,
  createOperation,
  deleteOperation,
} from '../../../../../../lib/db/helper-path-operations';
import {
  getPathById,
} from '../../../../../../lib/db/helper-paths';
import {
  getOperationDescription,
} from '../../../../../../lib/db/helper-path-operation-descriptions';
import {
  getLinkedParametersForOperation,
  linkParameterToOperation,
  unlinkParameterFromOperation,
  getSharedPathParameters,
  deleteSharedPathParameter,
} from '../../../../../../lib/db/helper-shared-path-parameters';
import {
  getLinkedResponsesForOperation,
  getSharedPathResponses,
  deleteSharedPathResponse,
  unlinkResponseFromOperation,
  linkResponseToOperation,
  updateSharedPathResponse,
} from '../../../../../../lib/db/helper-shared-path-responses';
import PathParameterNode from './PathParameterNode';
import PathResponseNode from './PathResponseNode';
import PathClassNode, { PathClassNodeData } from './PathClassNode';
import PathRequestBodyNode, { PathRequestBodyData } from './PathRequestBodyNode';
import PathResponseBodyNode, { PathResponseBodyData } from './PathResponseBodyNode';
import { Trash2 } from 'lucide-react';
import {
  getClassesWithPropertiesAndTags,
} from '../../../../../../lib/db/helper';
import {
  getSharedPathRequestBodies,
  getLinkedRequestBodyForOperation,
  createSharedPathRequestBody,
  linkRequestBodyToOperation,
  unlinkRequestBodyFromOperation,
  deleteSharedPathRequestBody,
  addRequestBodyContentType,
  addPropertyToInlineSchema,
  updateInlineSchemaProperty,
  deleteInlineSchemaProperty,
} from '../../../../../../lib/db/helper-shared-path-request-bodies';
import {
  getResponseContentTypes,
  addResponseContentType,
  addPropertyToResponseInlineSchema,
  updateResponseInlineSchemaProperty,
  deleteResponseInlineSchemaProperty,
  deleteResponseContentType,
} from '../../../../../../lib/db/helper-shared-path-responses-content';

// Enhanced Operation Node Component with Schema Drop Zones - Vertical Layout
function OperationNode({ data }: {
  data: { 
    operation: string; 
    color: string; 
    dbOperationId?: string;
    operationId?: string; // OpenAPI operationId (e.g., "createUser", "listOrders")
    parameters?: Array<{ id: string; name: string; in: string; required?: boolean }>;
    onDelete?: () => void;
    onSchemaDrop?: (operationId: string, schemaType: 'request' | 'response', schemaData: any) => void;
  } 
}) {
  const [dragOverRequest, setDragOverRequest] = useState(false);
  const [dragOverResponse, setDragOverResponse] = useState(false);

  const handleDragOver = (e: React.DragEvent<HTMLDivElement>, type: 'request' | 'response') => {
    e.preventDefault();
    e.stopPropagation();
    if (type === 'request') {
      setDragOverRequest(true);
    } else {
      setDragOverResponse(true);
    }
    e.dataTransfer.dropEffect = 'copy';
  };

  const handleDragLeave = (e: React.DragEvent<HTMLDivElement>, type: 'request' | 'response') => {
    e.preventDefault();
    e.stopPropagation();
    if (type === 'request') {
      setDragOverRequest(false);
    } else {
      setDragOverResponse(false);
    }
  };

  const handleDrop = (e: React.DragEvent<HTMLDivElement>, type: 'request' | 'response') => {
    e.preventDefault();
    e.stopPropagation();
    
    if (type === 'request') {
      setDragOverRequest(false);
    } else {
      setDragOverResponse(false);
    }

    const dataStr = e.dataTransfer.getData('application/json');
    if (!dataStr || !data.dbOperationId || !data.onSchemaDrop) return;

    try {
      const dropData = JSON.parse(dataStr);
      if (dropData.type === 'class' || dropData.type === 'property') {
        data.onSchemaDrop(data.dbOperationId, type, dropData);
      }
    } catch (error) {
      console.error('Error parsing drop data:', error);
    }
  };

  const needsRequestBody = ['POST', 'PUT', 'PATCH'].includes(data.operation);

  return (
    <>
      {/* Input handle at TOP */}
      <Handle
        type="target"
        position={Position.Top}
        id="operation-input"
        className="!w-3 !h-2 !rounded-t-md !rounded-b-none"
        style={{ backgroundColor: data.color }}
      />

      <div className="bg-white dark:bg-gray-800 rounded-xl border-2 shadow-xl min-w-[220px] max-w-[280px] cursor-pointer relative group"
        style={{ borderColor: data.color }}
      >
        {/* Delete button */}
        {data.onDelete && (
          <button
            onClick={(e) => {
              e.stopPropagation();
              data.onDelete?.();
            }}
            className="absolute -top-2 -right-2 bg-red-500 text-white rounded-full p-1.5 opacity-0 group-hover:opacity-100 transition-opacity shadow-lg hover:bg-red-600 z-20"
            title="Delete operation"
          >
            <Trash2 size={14} />
          </button>
        )}

        {/* Header - Only this part has color */}
        <div
          className="text-white px-4 py-3 rounded-t-xl"
          style={{ backgroundColor: data.color }}
        >
          <div className="text-xs font-medium opacity-90">HTTP Method</div>
          <div className="font-bold text-lg">{data.operation}</div>
          {data.operationId && (
            <div className="text-xs opacity-80 font-mono mt-1">{data.operationId}</div>
          )}
        </div>

        {/* Content - White/dark background */}
        <div className="p-3 space-y-3">
          {/* Request Body Section (for POST/PUT/PATCH) */}
          {needsRequestBody && (
            <div>
              <div className="text-[10px] font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-1">Request</div>
              <div
                onDragOver={(e) => handleDragOver(e, 'request')}
                onDragLeave={(e) => handleDragLeave(e, 'request')}
                onDrop={(e) => handleDrop(e, 'request')}
                className={`border rounded-md px-2 py-2 min-h-[32px] transition-all cursor-pointer ${
                  dragOverRequest
                    ? 'border-blue-400 bg-blue-50 dark:bg-blue-900/30'
                    : 'border-gray-200 dark:border-gray-700 hover:border-gray-300 dark:hover:border-gray-600'
                }`}
              >
                <div className="text-[10px] text-gray-500 dark:text-gray-400 italic">
                  {dragOverRequest ? 'Drop schema here' : '(No request body)'}
                </div>
              </div>
            </div>
          )}

          {/* Parameters Section */}
          <div>
            <div className="text-[10px] font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-1">Parameters</div>
            <div className="border border-gray-200 dark:border-gray-700 rounded-md px-2 py-2 min-h-[32px] space-y-1">
              {data.parameters && data.parameters.length > 0 ? (
                data.parameters.map((param) => (
                  <div key={param.id} className="flex items-center gap-1.5">
                    <span className="text-gray-400 dark:text-gray-500 text-[10px] font-mono">
                      {param.in === 'path' ? ':' : param.in === 'query' ? '?' : param.in === 'header' ? 'H' : '🍪'}
                    </span>
                    <span className="text-gray-700 dark:text-gray-300 text-[10px] font-mono">{param.name}</span>
                    {param.required && <span className="text-red-500 text-[8px]">*</span>}
                  </div>
                ))
              ) : (
                <div className="text-[10px] text-gray-400 dark:text-gray-500 italic">(No parameters)</div>
              )}
            </div>
          </div>

          {/* Response Section */}
          <div>
            <div className="text-[10px] font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-1">Responses</div>
            <div
              onDragOver={(e) => handleDragOver(e, 'response')}
              onDragLeave={(e) => handleDragLeave(e, 'response')}
              onDrop={(e) => handleDrop(e, 'response')}
              className={`border rounded-md px-2 py-2 min-h-[32px] transition-all cursor-pointer ${
                dragOverResponse
                  ? 'border-blue-400 bg-blue-50 dark:bg-blue-900/30'
                  : 'border-gray-200 dark:border-gray-700 hover:border-gray-300 dark:hover:border-gray-600'
              }`}
            >
              <div className="text-[10px] text-gray-400 dark:text-gray-500 italic">
                {dragOverResponse ? 'Drop schema here' : '(No responses)'}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Output handle at BOTTOM */}
      <Handle
        type="source"
        position={Position.Bottom}
        id="operation-output"
        className="!w-3 !h-2 !rounded-b-md !rounded-t-none"
        style={{ backgroundColor: data.color }}
      />
    </>
  );
}

const nodeTypes = {
  operation: OperationNode,
  parameter: PathParameterNode,
  response: PathResponseNode,
  class: PathClassNode,
  requestBody: PathRequestBodyNode,
  responseBody: PathResponseBodyNode,
};

// Define custom edge types
const edgeTypes = {
  smart: SmartEdge,
};

// Operation color mapping - Updated to match section 9.3.1 specification
const OPERATION_COLORS: Record<string, string> = {
  'GET': '#48BB78',
  'POST': '#4299E1',
  'PUT': '#ED8936',
  'PATCH': '#9F7AEA',
  'DELETE': '#F56565',
  'HEAD': '#718096',
  'OPTIONS': '#718096',
};

interface PathsCanvasInnerProps {
  selectedPathId: string | null;
  onOperationSelect: (operation: { id: string; operation: string } | null) => void;
  onParameterSelect?: (parameter: { id: string; name: string; operationId: string } | null) => void;
  onResponseSelect?: (response: { id: string; statusCode: string; description: string } | null) => void;
  refreshKey?: number;
  onRefresh?: () => void;
}

function PathsCanvasInner({ selectedPathId, onOperationSelect, onParameterSelect, onResponseSelect, refreshKey, onRefresh }: PathsCanvasInnerProps) {
  const {
    gridSize,
    gridStyle,
    snapToGrid,
    edgeRouting,
    edgeAnimation,
    selectedVersionId,
  } = useStudio();

  const { alert: alertDialog, confirm: confirmDialog } = useDialog();
  const reactFlowWrapper = useRef<HTMLDivElement>(null);
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [isDark, setIsDark] = useState(false);
  const { screenToFlowPosition, getNodes } = useReactFlow();

  // Refs to hold the latest handler functions
  // This prevents stale closures when nodes are moved or canvas is refreshed
  const handleResponseBodyPropertyDropRef = useRef<(contentId: string, propertyData: any, parentId?: string) => void>(() => {});
  const handleResponseBodyPropertyDeleteRef = useRef<(contentId: string, propertyId: string) => void>(() => {});
  const handleCreateContentTypeWithPropertyRef = useRef<(responseId: string, propertyData: any) => void>(() => {});
  const handleRequestBodyPropertyDropRef = useRef<(contentId: string, propertyData: any, parentId?: string) => void>(() => {});
  const handleRequestBodyPropertyDeleteRef = useRef<(contentId: string, propertyId: string) => void>(() => {});

  // Handle delete operation
  const handleDeleteOperation = useCallback(async (operationId: string, operationName: string) => {
    const confirmed = await confirmDialog({
      title: 'Delete Operation',
      message: `Are you sure you want to delete the ${operationName} operation? This will also unlink all parameters from it.`,
      variant: 'danger',
      confirmLabel: 'Delete',
      cancelLabel: 'Cancel',
    });

    if (!confirmed) return;

    try {
      await deleteOperation(operationId);

      // Remove from UI
      setNodes((nds) => nds.filter((n) => n.id !== operationId));
      setEdges((eds) => eds.filter((e) => e.source !== operationId && e.target !== operationId));

      if (onRefresh) {
        onRefresh();
      }
    } catch (error) {
      console.error('Error deleting operation:', error);
      await alertDialog({
        title: 'Error',
        message: 'Failed to delete operation',
        variant: 'error',
      });
    }
  }, [confirmDialog, alertDialog, setNodes, setEdges, onRefresh]);

  // Handle class drop on response
  const handleClassDropOnResponse = useCallback(async (responseId: string, classData: any) => {
    if (!selectedPathId || !classData.classId) return;

    try {
      // Get class name from classes
      const classesResponse = await getClassesWithPropertiesAndTags(selectedVersionId || '');
      const classesData: any[] = JSON.parse(classesResponse as string);
      const classInfo = classesData.find((c: any) => c.id === classData.classId);

      if (!classInfo) {
        await alertDialog({
          title: 'Error',
          message: 'Class not found',
          variant: 'error',
        });
        return;
      }

      // Update response data with class reference
      const schemaData = {
        content: {
          'application/json': {
            schema: {
              $ref: `#/components/schemas/${classInfo.name}`,
            },
          },
        },
      };

      const result = await updateSharedPathResponse(responseId, {
        data: schemaData,
      });

      const parsed = JSON.parse(result);
      
      if (parsed.success) {
        // Refresh canvas to show updated connections
        if (onRefresh) {
          onRefresh();
        }
        
        // Also trigger a small delay to ensure database is updated
        // This helps the properties panel reload the data
        setTimeout(() => {
          if (onRefresh) {
            onRefresh();
          }
        }, 500);
      } else {
        await alertDialog({
          title: 'Error',
          message: parsed.error || 'Failed to attach class to response',
          variant: 'error',
        });
      }
    } catch (error) {
      console.error('Error attaching class to response:', error);
      await alertDialog({
        title: 'Error',
        message: 'Failed to attach class to response',
        variant: 'error',
      });
    }
  }, [selectedPathId, selectedVersionId, alertDialog, onRefresh]);

  // Handle unlink class from response
  const handleClassUnlinkFromResponse = useCallback(async (responseId: string) => {
    const confirmed = await confirmDialog({
      title: 'Unlink Class',
      message: 'Are you sure you want to remove the class reference from this response?',
      variant: 'warning',
      confirmLabel: 'Unlink',
      cancelLabel: 'Cancel',
    });

    if (!confirmed) return;

    try {
      // Clear the class reference and reset to object mode
      const result = await updateSharedPathResponse(responseId, {
        classId: null, // Clear class reference
        schemaMode: 'object', // Reset to object mode
        data: null, // Clear any data
        inlineSchema: { type: 'object', properties: [] }, // Reset to empty object schema
      });

      const parsed = JSON.parse(result);

      if (parsed.success) {
        // Refresh canvas to update the display
        if (onRefresh) {
          onRefresh();
        }
      } else {
        await alertDialog({
          title: 'Error',
          message: parsed.error || 'Failed to unlink class from response',
          variant: 'error',
        });
      }
    } catch (error) {
      console.error('Error unlinking class from response:', error);
      await alertDialog({
        title: 'Error',
        message: 'Failed to unlink class from response',
        variant: 'error',
      });
    }
  }, [confirmDialog, alertDialog, onRefresh]);

  // Handle changing response schema type
  const handleSchemaTypeChange = useCallback(async (
    responseId: string,
    schemaMode: 'object' | 'primitive' | 'array',
    schemaType?: string
  ) => {
    try {
      let contentTypesToDelete: string[] = [];
      
      // Load the current response to check for inline properties and class references
      const responsesResponse = await getSharedPathResponses(selectedPathId || '');
      const responsesData = JSON.parse(responsesResponse);

      if (responsesData.success && responsesData.responses) {
        const response = responsesData.responses.find((r: any) => r.id === responseId);
        
        if (response) {
          // Check if switching away from class mode
          if (schemaMode !== 'object' && response.schema_mode === 'class' && response.class_id) {
            const confirmed = await confirmDialog({
              title: 'Remove Class Reference?',
              message: `This response currently references the class "${response.class_name || 'Unknown'}". Switching to ${schemaMode} type will remove this class reference. Continue?`,
              variant: 'warning',
              confirmLabel: 'Switch Type',
              cancelLabel: 'Cancel',
            });

            if (!confirmed) return;
          }

          // Check if switching away from object mode with inline properties
          if (schemaMode !== 'object') {
            const contentTypes = response.content_types || [];
            
            // Check if any content type has inline properties or object schemas
            const contentTypesWithSchemas = contentTypes.filter((ct: any) => {
              const schema = typeof ct.inline_schema === 'string' 
                ? JSON.parse(ct.inline_schema) 
                : ct.inline_schema;
              // Check for object schemas with or without properties
              return schema?.type === 'object' || (schema?.properties && schema.properties.length > 0);
            });

            // Also check response-level inline_schema
            let responseHasInlineProperties = false;
            if (response.inline_schema) {
              try {
                const schema = typeof response.inline_schema === 'string'
                  ? JSON.parse(response.inline_schema)
                  : response.inline_schema;
                responseHasInlineProperties = schema?.type === 'object' && 
                  schema?.properties && 
                  schema.properties.length > 0;
              } catch (e) {
                // Ignore parse errors
              }
            }

            if (contentTypesWithSchemas.length > 0 || responseHasInlineProperties) {
              // Count actual properties
              const propertyCount = contentTypes.reduce((count: number, ct: any) => {
                const schema = typeof ct.inline_schema === 'string' 
                  ? JSON.parse(ct.inline_schema) 
                  : ct.inline_schema;
                return count + (schema?.properties?.length || 0);
              }, 0);

              // Build warning message
              let warningMessage = '';
              if (propertyCount > 0) {
                warningMessage = `This response currently has ${propertyCount} inline ${propertyCount === 1 ? 'property' : 'properties'}. Switching to ${schemaMode} type will delete ${propertyCount === 1 ? 'this property' : 'these properties'}. This action cannot be undone. Continue?`;
              } else {
                warningMessage = `This response currently has an object schema. Switching to ${schemaMode} type will remove the object schema. Continue?`;
              }

              const confirmed = await confirmDialog({
                title: 'Delete Inline Schema?',
                message: warningMessage,
                variant: 'danger',
                confirmLabel: 'Switch Type',
                cancelLabel: 'Cancel',
              });

              if (!confirmed) return;
              
              // Mark these content types for deletion
              contentTypesToDelete = contentTypesWithSchemas.map((ct: any) => ct.id);
            }
          }
        }
      } else {
        // Failed to load responses, but continue with the type change
        console.warn('Could not load response data for validation');
      }

      // Delete content types with inline schemas BEFORE updating the response
      for (const contentTypeId of contentTypesToDelete) {
        try {
          await deleteResponseContentType(contentTypeId);
        } catch (error) {
          console.error('Error deleting content type:', contentTypeId, error);
        }
      }

      let data: Record<string, any> | null = null;
      let inlineSchema: Record<string, any> | null = null;

      if (schemaMode === 'primitive') {
        // Set primitive type in data field
        data = { type: schemaType || 'string' };
        // Clear inline_schema
        inlineSchema = null;
      } else if (schemaMode === 'array') {
        // Set array type in data field
        data = { type: 'array', items: { type: schemaType || 'string' } };
        // Clear inline_schema
        inlineSchema = null;
      } else {
        // Object mode - clear data and initialize empty inline_schema
        data = null;
        inlineSchema = { type: 'object', properties: [] };
      }

      const result = await updateSharedPathResponse(responseId, {
        schemaMode,
        classId: null, // Clear any class reference
        data,
        inlineSchema,
      });

      const parsed = JSON.parse(result);

      if (parsed.success) {
        if (onRefresh) {
          onRefresh();
        }
      } else {
        await alertDialog({
          title: 'Error',
          message: parsed.error || 'Failed to change schema type',
          variant: 'error',
        });
      }
    } catch (error) {
      console.error('Error changing schema type:', error);
      await alertDialog({
        title: 'Error',
        message: 'Failed to change schema type',
        variant: 'error',
      });
    }
  }, [selectedPathId, alertDialog, confirmDialog, onRefresh]);

  // Handle delete class from canvas (remove from all responses using it)
  const handleDeleteClassFromCanvas = useCallback(async (classId: string) => {
    const confirmed = await confirmDialog({
      title: 'Remove Class from Canvas',
      message: 'This will remove the class reference from all responses using it. The class itself will not be deleted.',
      variant: 'warning',
      confirmLabel: 'Remove',
      cancelLabel: 'Cancel',
    });

    if (!confirmed) return;

    try {
      // Get all responses for this path
      const responsesResponse = await getSharedPathResponses(selectedPathId || '');
      const responsesData = JSON.parse(responsesResponse);

      if (responsesData.success && responsesData.responses) {
        // Get class name
        const classesResponse = await getClassesWithPropertiesAndTags(selectedVersionId || '');
        const classesData: any[] = JSON.parse(classesResponse as string);
        const classInfo = classesData.find((c: any) => c.id === classId);

        if (classInfo) {
          // Remove class reference from all responses that use it
          for (const response of responsesData.responses) {
            if (response.data) {
              try {
                const responseData = typeof response.data === 'string' 
                  ? JSON.parse(response.data) 
                  : response.data;
                
                const schema = responseData?.content?.['application/json']?.schema || responseData?.schema;
                if (schema?.$ref && schema.$ref.includes(classInfo.name)) {
                  // Remove the class reference
                  await updateSharedPathResponse(response.id, {
                    data: {},
                  });
                }
              } catch (error) {
                console.error('Error processing response:', error);
              }
            }
          }
        }
      }

      if (onRefresh) {
        onRefresh();
      }
    } catch (error) {
      console.error('Error removing class from canvas:', error);
      await alertDialog({
        title: 'Error',
        message: 'Failed to remove class from canvas',
        variant: 'error',
      });
    }
  }, [selectedPathId, selectedVersionId, confirmDialog, alertDialog, onRefresh]);

  // Handle delete parameter
  const handleDeleteParameter = useCallback(async (parameterId: string, parameterName: string) => {
    const confirmed = await confirmDialog({
      title: 'Delete Parameter',
      message: `Are you sure you want to delete the parameter "${parameterName}"? This will remove it from all operations.`,
      variant: 'danger',
      confirmLabel: 'Delete',
      cancelLabel: 'Cancel',
    });

    if (!confirmed) return;

    try {
      const result = await deleteSharedPathParameter(parameterId);
      const parsed = JSON.parse(result);

      if (parsed.success) {
        // Remove from UI
        setNodes((nds) => nds.filter((n) => n.id !== `param-${parameterId}`));
        setEdges((eds) => eds.filter((e) => e.target !== `param-${parameterId}` && e.source !== `param-${parameterId}`));

        if (onRefresh) {
          onRefresh();
        }
      } else {
        await alertDialog({
          title: 'Error',
          message: parsed.error || 'Failed to delete parameter',
          variant: 'error',
        });
      }
    } catch (error) {
      console.error('Error deleting parameter:', error);
      await alertDialog({
        title: 'Error',
        message: 'Failed to delete parameter',
        variant: 'error',
      });
    }
  }, [confirmDialog, alertDialog, setNodes, setEdges, onRefresh]);

  // Handle delete response
  const handleDeleteResponse = useCallback(async (responseId: string, statusCode: string, operationId: string) => {
    const confirmed = await confirmDialog({
      title: 'Unlink Response',
      message: `Are you sure you want to unlink the ${statusCode} response from this operation? The response will still be available for other operations.`,
      variant: 'danger',
      confirmLabel: 'Unlink',
      cancelLabel: 'Cancel',
    });

    if (!confirmed) return;

    try {
      const result = await unlinkResponseFromOperation(operationId, responseId);
      const parsed = JSON.parse(result);

      if (parsed.success) {
        // Refresh the canvas to reload all data
        if (onRefresh) {
          onRefresh();
        }
      } else {
        await alertDialog({
          title: 'Error',
          message: parsed.error || 'Failed to unlink response',
          variant: 'error',
        });
      }
    } catch (error) {
      console.error('Error unlinking response:', error);
      await alertDialog({
        title: 'Error',
        message: 'Failed to unlink response',
        variant: 'error',
      });
    }
  }, [confirmDialog, alertDialog, onRefresh]);

  // Handle delete shared response (delete the response entirely, not just unlink)
  const handleDeleteSharedResponse = useCallback(async (responseId: string, statusCode?: string) => {
    const confirmed = await confirmDialog({
      title: 'Delete Response',
      message: `Are you sure you want to delete the ${statusCode || ''} response? This will unlink it from all operations and delete it permanently.`,
      variant: 'danger',
      confirmLabel: 'Delete',
      cancelLabel: 'Cancel',
    });

    if (!confirmed) return;

    try {
      const result = await deleteSharedPathResponse(responseId);
      const parsed = JSON.parse(result);

      if (parsed.success) {
        // Remove from UI
        setNodes((nds) => nds.filter((n) =>
          n.id !== `response-${responseId}` && n.id !== `response-body-${responseId}`
        ));
        setEdges((eds) => eds.filter((e) =>
          !e.id.includes(responseId)
        ));
        // Refresh the canvas to reload all data
        if (onRefresh) {
          onRefresh();
        }
      } else {
        await alertDialog({
          title: 'Error',
          message: parsed.error || 'Failed to delete response',
          variant: 'error',
        });
      }
    } catch (error) {
      console.error('Error deleting response:', error);
      await alertDialog({
        title: 'Error',
        message: 'Failed to delete response',
        variant: 'error',
      });
    }
  }, [confirmDialog, alertDialog, setNodes, setEdges, onRefresh]);

  // Handle unlink response from specific operation
  const handleUnlinkResponse = useCallback(async (responseId: string, operationId: string, operationName?: string) => {
    const confirmed = await confirmDialog({
      title: 'Unlink Response',
      message: `Are you sure you want to unlink this response from the ${operationName || 'operation'}? The response will still be available for other operations.`,
      variant: 'warning',
      confirmLabel: 'Unlink',
      cancelLabel: 'Cancel',
    });

    if (!confirmed) return;

    try {
      const result = await unlinkResponseFromOperation(operationId, responseId);
      const parsed = JSON.parse(result);

      if (parsed.success) {
        // Remove the edge from the canvas
        setEdges((eds) => eds.filter((e) =>
          !(e.source === operationId && e.target === `response-${responseId}`)
        ));
        // Refresh the canvas to reload all data
        if (onRefresh) {
          onRefresh();
        }
      } else {
        await alertDialog({
          title: 'Error',
          message: parsed.error || 'Failed to unlink response',
          variant: 'error',
        });
      }
    } catch (error) {
      console.error('Error unlinking response:', error);
      await alertDialog({
        title: 'Error',
        message: 'Failed to unlink response',
        variant: 'error',
      });
    }
  }, [confirmDialog, alertDialog, setEdges, onRefresh]);

  // Handle delete request body
  const handleDeleteRequestBody = useCallback(async (requestBodyId: string, requestBodyName: string) => {
    const confirmed = await confirmDialog({
      title: 'Delete Request Body',
      message: `Are you sure you want to delete the request body "${requestBodyName}"? This will unlink it from all operations.`,
      variant: 'danger',
      confirmLabel: 'Delete',
      cancelLabel: 'Cancel',
    });

    if (!confirmed) return;

    try {
      const result = await deleteSharedPathRequestBody(requestBodyId);
      const parsed = JSON.parse(result);

      if (parsed.success) {
        // Remove from UI
        setNodes((nds) => nds.filter((n) => n.id !== `request-body-${requestBodyId}`));
        setEdges((eds) => eds.filter((e) =>
          e.target !== `request-body-${requestBodyId}` && e.source !== `request-body-${requestBodyId}`
        ));

        if (onRefresh) {
          onRefresh();
        }
      } else {
        await alertDialog({
          title: 'Error',
          message: parsed.error || 'Failed to delete request body',
          variant: 'error',
        });
      }
    } catch (error) {
      console.error('Error deleting request body:', error);
      await alertDialog({
        title: 'Error',
        message: 'Failed to delete request body',
        variant: 'error',
      });
    }
  }, [confirmDialog, alertDialog, setNodes, setEdges, onRefresh]);

  // Handle request body property drop
  const handleRequestBodyPropertyDrop = useCallback(async (
    contentId: string,
    propertyData: any,
    parentId?: string
  ) => {
    try {
      // Extract the actual property from the drop data
      // The sidebar wraps it as { type: 'property', property: {...} }
      const actualProperty = propertyData.property || propertyData;

      const result = await addPropertyToInlineSchema(
        contentId,
        {
          name: actualProperty.propertyName || actualProperty.name || 'newProperty',
          description: actualProperty.description,
          data: actualProperty.data || { type: 'string' },
        },
        parentId
      );
      const parsed = JSON.parse(result);

      if (parsed.success) {
        if (onRefresh) {
          onRefresh();
        }
      } else {
        await alertDialog({
          title: 'Error',
          message: parsed.error || 'Failed to add property',
          variant: 'error',
        });
      }
    } catch (error) {
      console.error('Error adding property to inline schema:', error);
      await alertDialog({
        title: 'Error',
        message: 'Failed to add property',
        variant: 'error',
      });
    }
  }, [alertDialog, onRefresh]);

  // Handle request body property delete
  const handleRequestBodyPropertyDelete = useCallback(async (
    contentId: string,
    propertyId: string
  ) => {
    const confirmed = await confirmDialog({
      title: 'Delete Property',
      message: 'Are you sure you want to delete this property? This action cannot be undone.',
      variant: 'danger',
      confirmLabel: 'Delete',
      cancelLabel: 'Cancel',
    });

    if (!confirmed) return;

    try {
      const result = await deleteInlineSchemaProperty(contentId, propertyId, true);
      const parsed = JSON.parse(result);

      if (parsed.success) {
        if (onRefresh) {
          onRefresh();
        }
      } else {
        await alertDialog({
          title: 'Error',
          message: parsed.error || 'Failed to delete property',
          variant: 'error',
        });
      }
    } catch (error) {
      console.error('Error deleting inline schema property:', error);
      await alertDialog({
        title: 'Error',
        message: 'Failed to delete property',
        variant: 'error',
      });
    }
  }, [confirmDialog, alertDialog, onRefresh]);

  // Handle response body property drop
  const handleResponseBodyPropertyDrop = useCallback(async (
    contentId: string,
    propertyData: any,
    parentId?: string
  ) => {
    console.log('[handleResponseBodyPropertyDrop] Called with:', { contentId, propertyData, parentId });

    try {
      // Extract the actual property from the drop data
      // The sidebar wraps it as { type: 'property', property: {...} }
      const actualProperty = propertyData.property || propertyData;
      console.log('[handleResponseBodyPropertyDrop] Extracted property:', actualProperty);

      const result = await addPropertyToResponseInlineSchema(
        contentId,
        {
          name: actualProperty.propertyName || actualProperty.name || 'newProperty',
          description: actualProperty.description,
          data: actualProperty.data || { type: 'string' },
          parent_id: parentId || null,
        }
      );
      console.log('[handleResponseBodyPropertyDrop] Result:', result);
      const parsed = JSON.parse(result);

      if (parsed.success) {
        if (onRefresh) {
          onRefresh();
        }
      } else {
        await alertDialog({
          title: 'Error',
          message: parsed.error || 'Failed to add property',
          variant: 'error',
        });
      }
    } catch (error) {
      console.error('Error adding property to response inline schema:', error);
      await alertDialog({
        title: 'Error',
        message: 'Failed to add property',
        variant: 'error',
      });
    }
  }, [alertDialog, onRefresh]);

  // Handle response body property delete
  const handleResponseBodyPropertyDelete = useCallback(async (
    contentId: string,
    propertyId: string
  ) => {
    const confirmed = await confirmDialog({
      title: 'Delete Property',
      message: 'Are you sure you want to delete this property? This action cannot be undone.',
      variant: 'danger',
      confirmLabel: 'Delete',
      cancelLabel: 'Cancel',
    });

    if (!confirmed) return;

    try {
      const result = await deleteResponseInlineSchemaProperty(contentId, propertyId, true);
      const parsed = JSON.parse(result);

      if (parsed.success) {
        if (onRefresh) {
          onRefresh();
        }
      } else {
        await alertDialog({
          title: 'Error',
          message: parsed.error || 'Failed to delete property',
          variant: 'error',
        });
      }
    } catch (error) {
      console.error('Error deleting response inline schema property:', error);
      await alertDialog({
        title: 'Error',
        message: 'Failed to delete property',
        variant: 'error',
      });
    }
  }, [confirmDialog, alertDialog, onRefresh]);

  // Handle creating content type and adding first property in one operation
  const handleCreateContentTypeWithProperty = useCallback(async (
    responseId: string,
    propertyData: any
  ) => {
    console.log('[PathsCanvasView] handleCreateContentTypeWithProperty called');
    console.log('[PathsCanvasView] responseId:', responseId);
    console.log('[PathsCanvasView] propertyData:', propertyData);

    try {
      // First create a default content type (application/json)
      console.log('[PathsCanvasView] Creating content type for response:', responseId);
      const createResult = await addResponseContentType(
        responseId,
        'application/json',
        undefined, // no class_id
        { type: 'object', properties: [] }, // empty inline schema
        undefined // no examples
      );
      console.log('[PathsCanvasView] addResponseContentType result:', createResult);
      const createParsed = JSON.parse(createResult);

      if (!createParsed.success) {
        await alertDialog({
          title: 'Error',
          message: createParsed.error || 'Failed to create content type',
          variant: 'error',
        });
        return;
      }

      const contentId = createParsed.content.id;

      // Extract the actual property from the drop data
      // The sidebar wraps it as { type: 'property', property: {...} }
      const actualProperty = propertyData.property || propertyData;

      // Now add the property
      const propResult = await addPropertyToResponseInlineSchema(
        contentId,
        {
          name: actualProperty.propertyName || actualProperty.name || 'newProperty',
          description: actualProperty.description,
          data: actualProperty.data || { type: 'string' },
          parent_id: null,
        }
      );
      console.log('[PathsCanvasView] addPropertyToResponseInlineSchema result:', propResult);
      const propParsed = JSON.parse(propResult);

      if (propParsed.success) {
        console.log('[PathsCanvasView] Property added successfully, calling onRefresh');
        if (onRefresh) {
          onRefresh();
        }
      } else {
        await alertDialog({
          title: 'Error',
          message: propParsed.error || 'Failed to add property',
          variant: 'error',
        });
      }
    } catch (error) {
      console.error('Error creating content type with property:', error);
      await alertDialog({
        title: 'Error',
        message: 'Failed to create response schema',
        variant: 'error',
      });
    }
  }, [alertDialog, onRefresh]);

  // Handle property drop directly on response node (NEW FUNCTIONALITY)
  const handlePropertyDropOnResponse = useCallback(async (
    responseId: string,
    propertyData: any
  ) => {
    console.log('[PathsCanvasView] handlePropertyDropOnResponse called');
    console.log('[PathsCanvasView] responseId:', responseId);
    console.log('[PathsCanvasView] propertyData:', propertyData);

    try {
      // First, get the response to check its content types
      const responsesResponse = await getSharedPathResponses(selectedPathId || '');
      const responsesData = JSON.parse(responsesResponse);

      if (!responsesData.success || !responsesData.responses) {
        await alertDialog({
          title: 'Error',
          message: 'Failed to load response data',
          variant: 'error',
        });
        return;
      }

      const response = responsesData.responses.find((r: any) => r.id === responseId);
      if (!response) {
        await alertDialog({
          title: 'Error',
          message: 'Response not found',
          variant: 'error',
        });
        return;
      }

      const contentTypes = response.content_types || [];

      // Check if response is in class mode - if so, warn and switch to object mode
      if (response.schema_mode === 'class' && response.class_id) {
        const confirmed = await confirmDialog({
          title: 'Switch to Inline Schema',
          message: 'This response currently uses a class reference. Switching to an inline schema will remove the class reference. Continue?',
          variant: 'warning',
          confirmLabel: 'Switch to Inline',
          cancelLabel: 'Cancel',
        });

        if (!confirmed) return;

        // Clear the class reference and switch to object mode
        await updateSharedPathResponse(responseId, {
          classId: null,
          schemaMode: 'object',
          data: null,
        });
      }

      // Check if response is in primitive or array mode with properties
      if ((response.schema_mode === 'primitive' || response.schema_mode === 'array')) {
        const confirmed = await confirmDialog({
          title: 'Switch to Object Schema',
          message: `This response is currently set to ${response.schema_mode} type. Switching to object type will allow you to add properties. Continue?`,
          variant: 'warning',
          confirmLabel: 'Switch to Object',
          cancelLabel: 'Cancel',
        });

        if (!confirmed) return;

        // Switch to object mode
        await updateSharedPathResponse(responseId, {
          schemaMode: 'object',
          classId: null,
          data: null,
        });
      }

      // Extract the actual property from the drop data
      const actualProperty = propertyData.property || propertyData;

      // Check if there's an existing content type with object schema
      const objectContentType = contentTypes.find((ct: any) => {
        const schema = typeof ct.inline_schema === 'string' 
          ? JSON.parse(ct.inline_schema) 
          : ct.inline_schema;
        return ct.media_type === 'application/json' && schema?.type === 'object';
      });

      if (objectContentType) {
        // Add property to existing content type
        console.log('[PathsCanvasView] Adding property to existing content type:', objectContentType.id);
        const propResult = await addPropertyToResponseInlineSchema(
          objectContentType.id,
          {
            name: actualProperty.propertyName || actualProperty.name || 'newProperty',
            description: actualProperty.description,
            data: actualProperty.data || { type: 'string' },
            parent_id: null,
          }
        );
        const propParsed = JSON.parse(propResult);

        if (!propParsed.success) {
          await alertDialog({
            title: 'Error',
            message: propParsed.error || 'Failed to add property',
            variant: 'error',
          });
          return;
        }
      } else {
        // Create new content type with the property
        console.log('[PathsCanvasView] Creating new content type with property');
        const createResult = await addResponseContentType(
          responseId,
          'application/json',
          undefined, // no class_id
          { type: 'object', properties: [] }, // empty inline schema
          undefined // no examples
        );
        const createParsed = JSON.parse(createResult);

        if (!createParsed.success) {
          await alertDialog({
            title: 'Error',
            message: createParsed.error || 'Failed to create content type',
            variant: 'error',
          });
          return;
        }

        const contentId = createParsed.content.id;

        // Add the property to the new content type
        const propResult = await addPropertyToResponseInlineSchema(
          contentId,
          {
            name: actualProperty.propertyName || actualProperty.name || 'newProperty',
            description: actualProperty.description,
            data: actualProperty.data || { type: 'string' },
            parent_id: null,
          }
        );
        const propParsed = JSON.parse(propResult);

        if (!propParsed.success) {
          await alertDialog({
            title: 'Error',
            message: propParsed.error || 'Failed to add property',
            variant: 'error',
          });
          return;
        }
      }

      // Refresh the canvas to show the updated response
      if (onRefresh) {
        onRefresh();
      }
    } catch (error) {
      console.error('Error handling property drop on response:', error);
      await alertDialog({
        title: 'Error',
        message: 'Failed to add property to response',
        variant: 'error',
      });
    }
  }, [selectedPathId, alertDialog, confirmDialog, onRefresh]);

  // Keep refs updated with latest handler implementations
  // Update synchronously (not in useEffect) to avoid render loops
  handleResponseBodyPropertyDropRef.current = handleResponseBodyPropertyDrop;
  handleResponseBodyPropertyDeleteRef.current = handleResponseBodyPropertyDelete;
  handleCreateContentTypeWithPropertyRef.current = handleCreateContentTypeWithProperty;
  handleRequestBodyPropertyDropRef.current = handleRequestBodyPropertyDrop;
  handleRequestBodyPropertyDeleteRef.current = handleRequestBodyPropertyDelete;

  // Stable wrapper functions that delegate to refs
  // These never change identity, so they won't cause node recreation
  const stableHandleResponseBodyPropertyDrop = useCallback((contentId: string, propertyData: any, parentId?: string) => {
    console.log('[stableHandleResponseBodyPropertyDrop] Called, delegating to ref');
    handleResponseBodyPropertyDropRef.current?.(contentId, propertyData, parentId);
  }, []);

  const stableHandleResponseBodyPropertyDelete = useCallback((contentId: string, propertyId: string) => {
    handleResponseBodyPropertyDeleteRef.current?.(contentId, propertyId);
  }, []);

  const stableHandleCreateContentTypeWithProperty = useCallback((responseId: string, propertyData: any) => {
    console.log('[stableHandleCreateContentTypeWithProperty] Called, delegating to ref');
    handleCreateContentTypeWithPropertyRef.current?.(responseId, propertyData);
  }, []);

  const stableHandleRequestBodyPropertyDrop = useCallback((contentId: string, propertyData: any, parentId?: string) => {
    handleRequestBodyPropertyDropRef.current?.(contentId, propertyData, parentId);
  }, []);

  const stableHandleRequestBodyPropertyDelete = useCallback((contentId: string, propertyId: string) => {
    handleRequestBodyPropertyDeleteRef.current?.(contentId, propertyId);
  }, []);

  // Load operations and parameters when path is selected
  useEffect(() => {
    if (!selectedPathId) {
      setNodes([]);
      setEdges([]);
      return;
    }

    console.log('[PathsCanvasView] useEffect triggered - loading nodes. refreshKey:', refreshKey);

    const loadOperationsAndParameters = async () => {
      try {
        console.log('[PathsCanvasView] loadOperationsAndParameters starting...');
        // Load operations
        const operationsResponse = await getOperationsForPath(selectedPathId);
        const operations = JSON.parse(operationsResponse);

        // First, load linked parameters and operationId for each operation to include in node data
        const operationParamsMap = new Map<string, Array<{ id: string; name: string; in: string; required?: boolean }>>();
        const operationIdMap = new Map<string, string>(); // Maps db operation id to OpenAPI operationId

        for (const op of operations) {
          // Load linked parameters
          const paramsResponse = await getLinkedParametersForOperation(op.id);
          const paramsData = JSON.parse(paramsResponse);
          if (paramsData.success && paramsData.parameters) {
            operationParamsMap.set(op.id, paramsData.parameters.map((param: any) => ({
              id: param.id,
              name: param.name,
              in: param.in_location,
              required: param.data?.required ?? (param.in_location === 'path'),
            })));
          } else {
            operationParamsMap.set(op.id, []);
          }

          // Load operation description to get operationId
          try {
            const descResponse = await getOperationDescription(op.id);
            const descData = JSON.parse(descResponse);
            if (descData && descData.operation_id) {
              operationIdMap.set(op.id, descData.operation_id);
            }
          } catch (descError) {
            console.log('[PathsCanvasView] No description found for operation:', op.id);
          }
        }

        // Convert operations to nodes with delete callback and schema drop handler
        // Arrange operations HORIZONTALLY at the top for vertical flow
        const operationNodes: Node[] = operations.map((op: any, index: number) => {
          const spacingX = 300; // Horizontal spacing between operations (increased for larger nodes)
          const startX = 100; // Starting X position
          return {
            id: op.id,
            type: 'operation',
            position: { 
              x: startX + (index * spacingX),
              y: 50 // All operations at the top
            },
          data: {
            operation: op.operation,
            color: OPERATION_COLORS[op.operation] || '#64748b',
            dbOperationId: op.id,
            operationId: operationIdMap.get(op.id), // OpenAPI operationId from description
            parameters: operationParamsMap.get(op.id) || [],
            onDelete: () => handleDeleteOperation(op.id, op.operation),
            onSchemaDrop: async (operationId: string, schemaType: 'request' | 'response', schemaData: any) => {
              // Handle schema drop - this will be handled by opening the properties panel
              // For now, we'll select the operation to open the properties panel
              onOperationSelect({
                id: operationId,
                operation: op.operation,
              });
              
              // Show alert to guide user to properties panel
              await alertDialog({
                title: 'Schema Added',
                message: schemaType === 'request' 
                  ? 'Please configure the request body schema in the Operation Details panel.'
                  : 'Please configure the response schema in the Response Properties panel.',
                variant: 'info',
              });
            },
          },
          };
        });

        // Load ALL shared parameters for this path (not just linked ones)
        const allParamsResponse = await getSharedPathParameters(selectedPathId);
        const allParamsData = JSON.parse(allParamsResponse);

        const allParameterNodes: Node[] = [];
        const allEdges: Edge[] = [];

        if (allParamsData.success && allParamsData.parameters) {
          // Create nodes for all parameters - positioned BELOW operations
          allParamsData.parameters.forEach((param: any, paramIndex: number) => {
            const paramNodeId = `param-${param.id}`;
            const paramData = param.data || {};

            allParameterNodes.push({
              id: paramNodeId,
              type: 'parameter',
              position: {
                x: 100 + (paramIndex * 250), // Horizontal arrangement (increased spacing)
                y: 350, // Below operations (increased gap)
              },
              data: {
                name: param.name,
                inLocation: param.in_location,
                summary: param.summary,
                description: param.description,
                required: paramData.required ?? (param.in_location === 'path'),
                type: paramData.type || 'string',
                format: paramData.format,
                defaultValue: paramData.default,
                dbParameterId: param.id,
                onDelete: () => handleDeleteParameter(param.id, param.name),
              },
            });
          });
        }

        // Now load linked parameters to create edges
        for (const op of operations) {
          const paramsResponse = await getLinkedParametersForOperation(op.id);
          const paramsData = JSON.parse(paramsResponse);

          if (paramsData.success && paramsData.parameters) {
            paramsData.parameters.forEach((param: any) => {
              const paramNodeId = `param-${param.id}`;

              // Create edge from operation to parameter
              const edgeType = edgeRouting === 'straight' ? 'straight'
                : edgeRouting === 'bezier' ? 'default'
                : edgeRouting === 'smart' ? 'smart'
                : 'smoothstep';

              allEdges.push({
                id: `edge-${op.id}-${param.id}`,
                source: op.id,
                sourceHandle: 'operation-output',
                target: paramNodeId,
                targetHandle: 'parameter-input',
                type: edgeType,
                animated: edgeAnimation !== 'none',
                style: {
                  stroke: '#9ca3af',
                  strokeWidth: 2,
                  strokeDasharray: edgeAnimation === 'dash' ? '5,5' : undefined,
                },
                data: {
                  sourceNodeId: op.id,
                  targetNodeId: paramNodeId,
                },
              });
            });
          }
        }

        // Load classes for this version to map class IDs to names
        let classesMap = new Map<string, { id: string; name: string; description?: string }>();
        if (selectedVersionId) {
          try {
            const classesResponse = await getClassesWithPropertiesAndTags(selectedVersionId);
            const classesData: any[] = JSON.parse(classesResponse as string);
            classesData.forEach((cls: any) => {
              if (!classesMap.has(cls.id)) {
                classesMap.set(cls.id, {
                  id: cls.id,
                  name: cls.name,
                  description: cls.description,
                });
              }
            });
          } catch (error) {
            console.error('Error loading classes:', error);
          }
        }

        // Now load responses for all operations and create response nodes
        // Load ALL shared responses for this path (not just linked ones)
        const allResponsesResponse = await getSharedPathResponses(selectedPathId);
        const allResponsesData = JSON.parse(allResponsesResponse);

        // Build a map of response ID -> linked operations
        const responseLinkedOpsMap = new Map<string, Array<{ id: string; operation: string }>>();
        for (const op of operations) {
          const linkedResponsesResponse = await getLinkedResponsesForOperation(op.id);
          const linkedResponsesData = JSON.parse(linkedResponsesResponse);
          if (linkedResponsesData.success && linkedResponsesData.responses) {
            for (const resp of linkedResponsesData.responses) {
              if (!responseLinkedOpsMap.has(resp.id)) {
                responseLinkedOpsMap.set(resp.id, []);
              }
              responseLinkedOpsMap.get(resp.id)!.push({ id: op.id, operation: op.operation });
            }
          }
        }

        const allResponseNodes: Node[] = [];
        const allClassNodes: Node[] = [];
        const classNodesMap = new Map<string, Node>(); // Track class nodes by classId

        if (allResponsesData.success && allResponsesData.responses) {
          // Create nodes for all responses
          allResponsesData.responses.forEach((response: any, responseIndex: number) => {
            const responseNodeId = `response-${response.id}`;

            // Initialize class reference variables
            let attachedClassId: string | undefined;
            let attachedClassName: string | undefined;

            // Parse content types
            const contentTypes = (response.content_types || []).map((ct: any) => ({
              id: ct.id,
              media_type: ct.media_type,
              class_id: ct.class_id,
              class_name: ct.class_name,
              inline_schema: typeof ct.inline_schema === 'string'
                ? JSON.parse(ct.inline_schema)
                : ct.inline_schema,
              examples: typeof ct.examples === 'string'
                ? JSON.parse(ct.examples)
                : ct.examples,
            }));

            // Use schema_mode to definitively determine how to display the response
            // This eliminates ambiguity when determining response schema type
            const schemaMode = response.schema_mode || 'object';
            console.log('[PathsCanvasView] Response', response.status_code, 'schema_mode:', schemaMode);

            let inlineSchema = null;

            // Based on schema_mode, extract the appropriate schema
            if (schemaMode === 'class') {
              // Class reference - get from class_id
              if (response.class_id) {
                attachedClassId = response.class_id;
                attachedClassName = response.class_name;
              }
              console.log('[PathsCanvasView] Response', response.status_code, 'is CLASS mode, class:', attachedClassName);
            } else if (schemaMode === 'primitive' || schemaMode === 'array') {
              // Primitive or array - get from data field, NO class reference
              attachedClassId = undefined;
              attachedClassName = undefined;
              if (response.data) {
                try {
                  const responseData = typeof response.data === 'string'
                    ? JSON.parse(response.data)
                    : response.data;
                  inlineSchema = responseData;
                  console.log('[PathsCanvasView] Response', response.status_code, 'is', schemaMode.toUpperCase(), 'mode, schema:', inlineSchema);
                } catch (error) {
                  console.error('Error parsing response data:', error);
                }
              }
            } else {
              // Object mode - check inline_schema, NO class reference
              attachedClassId = undefined;
              attachedClassName = undefined;
              if (response.inline_schema) {
                try {
                  inlineSchema = typeof response.inline_schema === 'string'
                    ? JSON.parse(response.inline_schema)
                    : response.inline_schema;
                  console.log('[PathsCanvasView] Response', response.status_code, 'is OBJECT mode, inline_schema:', inlineSchema);
                } catch (error) {
                  console.error('Error parsing inline_schema:', error);
                }
              }
            }

            // Also log content types with inline schemas
            if (contentTypes.length > 0) {
              console.log('[PathsCanvasView] Response', response.status_code, 'has', contentTypes.length, 'content types');
            }

            allResponseNodes.push({
              id: responseNodeId,
              type: 'response',
              position: {
                x: 100 + (responseIndex * 250), // Horizontal arrangement (increased spacing)
                y: 500, // Below parameters (increased gap)
              },
              data: {
                statusCode: response.status_code,
                description: response.description,
                dbResponseId: response.id,
                schemaMode,
                attachedClassId,
                attachedClassName,
                contentTypes,
                inlineSchema,
                linkedOperations: responseLinkedOpsMap.get(response.id) || [],
                onDelete: () => handleDeleteSharedResponse(response.id, response.status_code),
                onUnlink: (operationId: string) => {
                  const linkedOp = responseLinkedOpsMap.get(response.id)?.find(op => op.id === operationId);
                  handleUnlinkResponse(response.id, operationId, linkedOp?.operation);
                },
                onClassDrop: handleClassDropOnResponse,
                onPropertyDrop: handlePropertyDropOnResponse, // NEW: Add property drop handler
                onSchemaTypeChange: handleSchemaTypeChange,
                onClassUnlink: handleClassUnlinkFromResponse,
              },
            });

            // Create class node if attached and not already created
            if (attachedClassId && !classNodesMap.has(attachedClassId)) {
              const classInfo = classesMap.get(attachedClassId);
              if (classInfo) {
                const classNodeId = `class-${attachedClassId}`;
                const classNode: Node = {
                  id: classNodeId,
                  type: 'class',
                  position: {
                    x: 100 + (allClassNodes.length * 320), // Horizontal arrangement (increased spacing)
                    y: 700, // Below responses (increased gap)
                  },
                  data: {
                    className: classInfo.name,
                    classId: attachedClassId,
                    description: classInfo.description,
                    dbClassId: attachedClassId,
                    onDelete: () => handleDeleteClassFromCanvas(attachedClassId),
                  },
                };
                allClassNodes.push(classNode);
                classNodesMap.set(attachedClassId, classNode);
              }
            }
          });
        }

        // Create response body nodes for responses with content types (for inline schema editing)
        const allResponseBodyNodes: Node[] = [];
        if (allResponsesData.success && allResponsesData.responses) {
          allResponsesData.responses.forEach((response: any, responseIndex: number) => {
            // Get content types for this response
            const contentTypes = (response.content_types || []).map((ct: any) => ({
              id: ct.id,
              media_type: ct.media_type,
              class_id: ct.class_id,
              class_name: ct.class_name,
              inline_schema: typeof ct.inline_schema === 'string'
                ? JSON.parse(ct.inline_schema)
                : ct.inline_schema,
              examples: typeof ct.examples === 'string'
                ? JSON.parse(ct.examples)
                : ct.examples,
            }));

            // Check if response itself has an object schema (from inline_schema column)
            let responseInlineSchema = null;
            if (response.inline_schema) {
              try {
                responseInlineSchema = typeof response.inline_schema === 'string'
                  ? JSON.parse(response.inline_schema)
                  : response.inline_schema;
              } catch (e) {
                // Ignore parse errors
              }
            }

            // Create response body node if:
            // 1. There are content types with object schemas or class references
            // 2. OR the response itself has an object type schema
            const hasContentTypeWithObjectSchema = contentTypes.some((ct: any) =>
              ct.inline_schema?.type === 'object' || ct.class_id
            );
            const hasResponseObjectSchema = responseInlineSchema?.type === 'object';

            if (contentTypes.length > 0 || hasContentTypeWithObjectSchema || hasResponseObjectSchema) {
              const responseBodyNodeId = `response-body-${response.id}`;
              allResponseBodyNodes.push({
                id: responseBodyNodeId,
                type: 'responseBody',
                position: {
                  x: 400 + (responseIndex * 300), // Offset to the right of response nodes
                  y: 550 + (responseIndex * 50), // Slightly below and staggered
                },
                data: {
                  id: response.id,
                  status_code: response.status_code,
                  description: response.description,
                  contentTypes,
                  onDelete: () => handleDeleteSharedResponse(response.id, response.status_code),
                  onPropertyDrop: stableHandleResponseBodyPropertyDrop,
                  onPropertyDelete: stableHandleResponseBodyPropertyDelete,
                  onCreateContentTypeWithProperty: stableHandleCreateContentTypeWithProperty,
                } as PathResponseBodyData,
              });
            }
          });
        }

        // Create edges from response nodes to response body nodes
        allResponseBodyNodes.forEach((responseBodyNode) => {
          const responseId = (responseBodyNode.data as any).id;
          const responseNodeId = `response-${responseId}`;

          // Only create edge if response node exists
          if (allResponseNodes.some(n => n.id === responseNodeId)) {
            const edgeType = edgeRouting === 'straight' ? 'straight'
              : edgeRouting === 'bezier' ? 'default'
              : edgeRouting === 'smart' ? 'smart'
              : 'smoothstep';

            allEdges.push({
              id: `edge-resp-body-${responseId}`,
              source: responseNodeId,
              sourceHandle: 'response-class-output', // Use existing output handle
              target: responseBodyNode.id,
              targetHandle: 'response-input', // PathResponseBodyNode uses this
              type: edgeType,
              animated: edgeAnimation !== 'none',
              style: {
                stroke: '#60a5fa', // Blue for response-to-body edges
                strokeWidth: 2,
                strokeDasharray: edgeAnimation === 'dash' ? '5,5' : undefined,
              },
            });
          }
        });

        // Create edges from operations to responses using the already-collected linked operations
        responseLinkedOpsMap.forEach((linkedOps, responseId) => {
          const responseNodeId = `response-${responseId}`;
          linkedOps.forEach((op) => {
            console.log('[PathsCanvasView] Creating edge from', op.id, 'to', responseNodeId);

            // Create edge from operation to response
            const edgeType = edgeRouting === 'straight' ? 'straight'
              : edgeRouting === 'bezier' ? 'default'
              : edgeRouting === 'smart' ? 'smart'
              : 'smoothstep';

            allEdges.push({
              id: `edge-op-resp-${op.id}-${responseId}`,
              source: op.id,
              sourceHandle: 'operation-output',
              target: responseNodeId,
              targetHandle: 'response-input',
              type: edgeType,
              animated: edgeAnimation !== 'none',
              style: {
                stroke: '#a78bfa',
                strokeWidth: 2,
                strokeDasharray: edgeAnimation === 'dash' ? '5,5' : undefined,
              },
              data: {
                sourceNodeId: op.id,
                targetNodeId: responseNodeId,
              },
            });
          });
        });

        // Create edges from response nodes to class nodes
        // Make sure we create edges for ALL responses that have the same class
        allResponseNodes.forEach((responseNode) => {
          const responseData = responseNode.data as any;
          if (responseData.attachedClassId) {
            const classNodeId = `class-${responseData.attachedClassId}`;
            const classNode = classNodesMap.get(responseData.attachedClassId);
            
            if (classNode) {
              // Check if edge already exists to avoid duplicates
              const edgeId = `edge-resp-class-${responseNode.id}-${classNode.id}`;
              const edgeExists = allEdges.some(e => e.id === edgeId);
              
              if (!edgeExists) {
                const edgeType = edgeRouting === 'straight' ? 'straight'
                  : edgeRouting === 'bezier' ? 'default'
                  : edgeRouting === 'smart' ? 'smart'
                  : 'smoothstep';

                allEdges.push({
                  id: edgeId,
                  source: responseNode.id,
                  sourceHandle: 'response-class-output',
                  target: classNode.id,
                  targetHandle: 'class-input',
                  type: edgeType,
                  animated: edgeAnimation !== 'none',
                  style: {
                    stroke: '#6366f1',
                    strokeWidth: 2.5,
                    strokeDasharray: undefined,
                  },
                  data: {
                    sourceNodeId: responseNode.id,
                    targetNodeId: classNode.id,
                  },
                });
              }
            }
          }
        });

        // =================================================================
        // LOAD REQUEST BODIES
        // =================================================================
        const allRequestBodyNodes: Node[] = [];

        // Load shared request bodies for this path
        const requestBodiesResponse = await getSharedPathRequestBodies(selectedPathId);
        const requestBodiesData = JSON.parse(requestBodiesResponse);

        if (requestBodiesData.success && requestBodiesData.requestBodies) {
          requestBodiesData.requestBodies.forEach((rb: any, rbIndex: number) => {
            const requestBodyNodeId = `request-body-${rb.id}`;

            // Parse content types
            const contentTypes = (rb.content_types || []).map((ct: any) => ({
              id: ct.id,
              media_type: ct.media_type,
              class_id: ct.class_id,
              class_name: ct.class_name,
              inline_schema: typeof ct.inline_schema === 'string'
                ? JSON.parse(ct.inline_schema)
                : ct.inline_schema,
              encoding: typeof ct.encoding === 'string'
                ? JSON.parse(ct.encoding)
                : ct.encoding,
              examples: typeof ct.examples === 'string'
                ? JSON.parse(ct.examples)
                : ct.examples,
            }));

            allRequestBodyNodes.push({
              id: requestBodyNodeId,
              type: 'requestBody',
              position: {
                x: -200, // Left side for request bodies (moved further left)
                y: 50 + rbIndex * 280, // Aligned with operations row (increased vertical spacing)
              },
              data: {
                id: rb.id,
                name: rb.name,
                description: rb.description,
                required: rb.required,
                contentTypes: contentTypes,
                onDelete: () => handleDeleteRequestBody(rb.id, rb.name),
                onPropertyDrop: stableHandleRequestBodyPropertyDrop,
                onPropertyDelete: stableHandleRequestBodyPropertyDelete,
              } as PathRequestBodyData,
            });
          });
        }

        // Create edges from request body nodes to operations
        for (const op of operations) {
          // Only check for request bodies on POST, PUT, PATCH operations
          if (!['POST', 'PUT', 'PATCH'].includes(op.operation)) continue;

          const linkedRbResponse = await getLinkedRequestBodyForOperation(op.id);
          const linkedRbData = JSON.parse(linkedRbResponse);

          if (linkedRbData.success && linkedRbData.requestBody) {
            const rbNodeId = `request-body-${linkedRbData.requestBody.id}`;

            const edgeType = edgeRouting === 'straight' ? 'straight'
              : edgeRouting === 'bezier' ? 'default'
              : edgeRouting === 'smart' ? 'smart'
              : 'smoothstep';

            allEdges.push({
              id: `edge-rb-op-${linkedRbData.requestBody.id}-${op.id}`,
              source: rbNodeId,
              sourceHandle: 'request-body-output',
              target: op.id,
              targetHandle: 'operation-input',
              type: edgeType,
              animated: edgeAnimation !== 'none',
              style: {
                stroke: '#8b5cf6',
                strokeWidth: 2,
                strokeDasharray: edgeAnimation === 'dash' ? '5,5' : undefined,
              },
              data: {
                sourceNodeId: rbNodeId,
                targetNodeId: op.id,
              },
            });
          }
        }

        // Response body nodes are created for responses that have content types with inline schemas
        // These allow users to add/edit properties in the inline schema

        setNodes([...operationNodes, ...allParameterNodes, ...allResponseNodes, ...allResponseBodyNodes, ...allClassNodes, ...allRequestBodyNodes]);
        setEdges(allEdges);
      } catch (error) {
        console.error('Error loading operations and parameters:', error);
      }
    };

    loadOperationsAndParameters();
  }, [selectedPathId, selectedVersionId, setNodes, setEdges, refreshKey, edgeRouting, edgeAnimation, handleDeleteOperation, handleDeleteParameter, handleDeleteResponse, handleDeleteSharedResponse, handleUnlinkResponse, handleClassDropOnResponse, handlePropertyDropOnResponse, handleClassUnlinkFromResponse, handleSchemaTypeChange, handleDeleteRequestBody, stableHandleRequestBodyPropertyDrop, stableHandleRequestBodyPropertyDelete, stableHandleResponseBodyPropertyDrop, stableHandleResponseBodyPropertyDelete, stableHandleCreateContentTypeWithProperty]);

  // Detect dark mode
  useEffect(() => {
    const checkDarkMode = () => {
      setIsDark(document.documentElement.classList.contains('dark'));
    };
    checkDarkMode();

    const observer = new MutationObserver(checkDarkMode);
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['class'],
    });

    return () => observer.disconnect();
  }, []);

  // Get background variant
  const backgroundVariant = useCallback((style: 'dots' | 'lines' | 'cross'): BackgroundVariant => {
    switch (style) {
      case 'dots': return BackgroundVariant.Dots;
      case 'lines': return BackgroundVariant.Lines;
      case 'cross': return BackgroundVariant.Cross;
      default: return BackgroundVariant.Dots;
    }
  }, []);

  // Handle drag over
  const onDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = 'copy';
    // Log occasionally to verify events are reaching canvas
    if (Math.random() < 0.02) {
      console.log('[onDragOver] Canvas receiving drag events');
    }
  }, []);

  // Handle node click to show properties in sidebar
  const onNodeClick = useCallback(
    (_event: React.MouseEvent, node: Node) => {
      if (node.type === 'operation') {
        onOperationSelect({
          id: node.data.dbOperationId as string,
          operation: node.data.operation as string,
        });
        if (onParameterSelect) {
          onParameterSelect(null);
        }
        if (onResponseSelect) {
          onResponseSelect(null);
        }
      } else if (node.type === 'parameter') {
        if (onParameterSelect) {
          onParameterSelect({
            id: node.data.dbParameterId as string,
            name: node.data.name as string,
            operationId: node.data.operationId as string,
          });
        }
        onOperationSelect(null);
        if (onResponseSelect) {
          onResponseSelect(null);
        }
      } else if (node.type === 'response') {
        if (onResponseSelect) {
          onResponseSelect({
            id: node.data.dbResponseId as string,
            statusCode: node.data.statusCode as string,
            description: node.data.description as string || '',
          });
        }
        onOperationSelect(null);
        if (onParameterSelect) {
          onParameterSelect(null);
        }
      }
    },
    [onOperationSelect, onParameterSelect, onResponseSelect]
  );

  // Handle connecting nodes
  const onConnect = useCallback(
    async (connection: Connection) => {
      if (connection.source && connection.target) {
        const sourceNode = nodes.find(n => n.id === connection.source);
        const targetNode = nodes.find(n => n.id === connection.target);

        // VALIDATION: Prevent invalid connections
        // Operations should NOT connect to response body nodes or request body nodes
        if (sourceNode?.type === 'operation' && (targetNode?.type === 'responseBody' || targetNode?.type === 'requestBody')) {
          await alertDialog({
            title: 'Invalid Connection',
            message: 'Operations can only connect to Response status codes (200, 404, etc.), not to schema nodes. The response node contains the schema reference.',
            variant: 'warning',
          });
          return;
        }
        
        // Also prevent reverse connection
        if (targetNode?.type === 'operation' && (sourceNode?.type === 'responseBody' || sourceNode?.type === 'requestBody')) {
          await alertDialog({
            title: 'Invalid Connection',
            message: 'Operations can only connect to Response status codes (200, 404, etc.), not to schema nodes. The response node contains the schema reference.',
            variant: 'warning',
          });
          return;
        }

        // Prevent connecting response body to anything except its parent response
        if (sourceNode?.type === 'responseBody' || targetNode?.type === 'responseBody') {
          await alertDialog({
            title: 'Invalid Connection',
            message: 'Response body nodes are automatically connected to their parent response. Manual connections are not allowed.',
            variant: 'warning',
          });
          return;
        }

        // Prevent connecting request body to anything except operations
        if (sourceNode?.type === 'requestBody' && targetNode?.type !== 'operation') {
          await alertDialog({
            title: 'Invalid Connection',
            message: 'Request body nodes can only connect to operations (POST, PUT, PATCH).',
            variant: 'warning',
          });
          return;
        }
        
        if (targetNode?.type === 'requestBody' && sourceNode?.type !== 'operation') {
          await alertDialog({
            title: 'Invalid Connection',
            message: 'Request body nodes can only connect to operations (POST, PUT, PATCH).',
            variant: 'warning',
          });
          return;
        }
      }

      // Get edge type based on settings
      const edgeType = edgeRouting === 'straight' ? 'straight'
        : edgeRouting === 'bezier' ? 'default'
        : edgeRouting === 'smart' ? 'smart'
        : 'smoothstep';

      // Add edge to UI first
      setEdges((eds) => addEdge({
        ...connection,
        type: edgeType,
        animated: edgeAnimation !== 'none',
        style: {
          stroke: '#9ca3af',
          strokeWidth: 2,
          strokeDasharray: edgeAnimation === 'dash' ? '5,5' : undefined,
        },
        data: {
          sourceNodeId: connection.source,
          targetNodeId: connection.target,
        },
      }, eds));

      // Save link to database if connecting operation to parameter or response (either direction)
      if (connection.source && connection.target) {
        const sourceNode = nodes.find(n => n.id === connection.source);
        const targetNode = nodes.find(n => n.id === connection.target);


        let operationId: string | undefined;
        let parameterId: string | undefined;
        let responseId: string | undefined;

        // Check if we're connecting operation to parameter (either direction)
        if (sourceNode?.type === 'operation' && targetNode?.type === 'parameter') {
          operationId = (sourceNode.data as any)?.dbOperationId;
          parameterId = (targetNode.data as any)?.dbParameterId;
        } else if (sourceNode?.type === 'parameter' && targetNode?.type === 'operation') {
          operationId = (targetNode.data as any)?.dbOperationId;
          parameterId = (sourceNode.data as any)?.dbParameterId;
        }
        // Check if we're connecting operation to response (either direction)
        else if (sourceNode?.type === 'operation' && targetNode?.type === 'response') {
          operationId = (sourceNode.data as any)?.dbOperationId;
          responseId = (targetNode.data as any)?.dbResponseId;
        } else if (sourceNode?.type === 'response' && targetNode?.type === 'operation') {
          operationId = (targetNode.data as any)?.dbOperationId;
          responseId = (sourceNode.data as any)?.dbResponseId;
        }

        // Handle response to class connection (both directions) - check this FIRST before other handlers
        if (
          (sourceNode?.type === 'response' && targetNode?.type === 'class') ||
          (sourceNode?.type === 'class' && targetNode?.type === 'response')
        ) {
          // Determine which is the response and which is the class
          const responseNode = sourceNode?.type === 'response' ? sourceNode : targetNode;
          const classNode = sourceNode?.type === 'class' ? sourceNode : targetNode;
          
          const responseId = (responseNode.data as any)?.dbResponseId;
          const classId = (classNode.data as any)?.dbClassId;
          const className = (classNode.data as any)?.className;
          
          if (responseId && classId) {
            try {
              // handleClassDropOnResponse expects { classId, className }
              await handleClassDropOnResponse(responseId, { 
                classId,
                className: className || 'Unknown',
                type: 'class'
              });
            } catch (error) {
              console.error('Error connecting response to class:', error);
              await alertDialog({
                title: 'Error',
                message: 'Failed to attach class to response. Please try again.',
                variant: 'error',
              });
              // Remove the edge from UI since DB save failed
              setEdges((eds) => eds.filter(e =>
                !(e.source === connection.source && e.target === connection.target)
              ));
            }
          }
        }
        // Handle parameter linking
        else if (operationId && parameterId) {
          try {
            const result = await linkParameterToOperation(operationId, parameterId, undefined);
            const parsed = JSON.parse(result);

            if (parsed.success) {
              // Update the operation node's parameters array to reflect the new link
              const paramNode = sourceNode?.type === 'parameter' ? sourceNode : targetNode;
              const opNode = sourceNode?.type === 'operation' ? sourceNode : targetNode;

              if (paramNode && opNode) {
                const paramData = paramNode.data as any;
                const newParam = {
                  id: paramData.dbParameterId,
                  name: paramData.name,
                  in: paramData.inLocation,
                  required: paramData.required,
                };

                // Update the operation node's parameters
                setNodes((nds) => nds.map((node) => {
                  if (node.id === opNode.id) {
                    const currentParams = (node.data as any).parameters || [];
                    // Check if parameter already exists to avoid duplicates
                    const paramExists = currentParams.some((p: any) => p.id === newParam.id);
                    if (!paramExists) {
                      return {
                        ...node,
                        data: {
                          ...node.data,
                          parameters: [...currentParams, newParam],
                        },
                      };
                    }
                  }
                  return node;
                }));
              }
            } else {
              console.error('Failed to link parameter to operation:', parsed.error);
              await alertDialog({
                title: 'Error',
                message: parsed.error || 'Failed to link parameter to operation',
                variant: 'error',
              });
              // Remove the edge from UI since DB save failed
              setEdges((eds) => eds.filter(e =>
                !(e.source === connection.source && e.target === connection.target)
              ));
            }
          } catch (error) {
            console.error('Error linking parameter to operation:', error);
            await alertDialog({
              title: 'Error',
              message: 'Failed to link parameter to operation',
              variant: 'error',
            });
            // Remove the edge from UI since DB save failed
            setEdges((eds) => eds.filter(e =>
              !(e.source === connection.source && e.target === connection.target)
            ));
          }
        }
        // Handle response linking
        else if (operationId && responseId) {
          try {
            const result = await linkResponseToOperation(operationId, responseId, undefined);
            const parsed = JSON.parse(result);

            if (!parsed.success) {
              console.error('Failed to link response to operation:', parsed.error);
              await alertDialog({
                title: 'Error',
                message: parsed.error || 'Failed to link response to operation',
                variant: 'error',
              });
              // Remove the edge from UI since DB save failed
              setEdges((eds) => eds.filter(e =>
                !(e.source === connection.source && e.target === connection.target)
              ));
            }
          } catch (error) {
            console.error('Error linking response to operation:', error);
            await alertDialog({
              title: 'Error',
              message: 'Failed to link response to operation',
              variant: 'error',
            });
            // Remove the edge from UI since DB save failed
            setEdges((eds) => eds.filter(e =>
              !(e.source === connection.source && e.target === connection.target)
            ));
          }
        }
      }
    },
    [setEdges, setNodes, nodes, alertDialog, edgeRouting, edgeAnimation, handleClassDropOnResponse, selectedPathId, selectedVersionId]
  );

  // Handle deleting edges (unlinking parameters and responses from operations)
  const onEdgesDelete = useCallback(
    async (edgesToDelete: Edge[]) => {
      for (const edge of edgesToDelete) {
        const sourceNode = nodes.find(n => n.id === edge.source);
        const targetNode = nodes.find(n => n.id === edge.target);

        let operationId: string | undefined;
        let parameterId: string | undefined;
        let responseId: string | undefined;

        // Check if we're unlinking operation from parameter (either direction)
        if (sourceNode?.type === 'operation' && targetNode?.type === 'parameter') {
          operationId = (sourceNode.data as any)?.dbOperationId;
          parameterId = (targetNode.data as any)?.dbParameterId;
        } else if (sourceNode?.type === 'parameter' && targetNode?.type === 'operation') {
          operationId = (targetNode.data as any)?.dbOperationId;
          parameterId = (sourceNode.data as any)?.dbParameterId;
        }
        // Check if we're unlinking operation from response (either direction)
        else if (sourceNode?.type === 'operation' && targetNode?.type === 'response') {
          operationId = (sourceNode.data as any)?.dbOperationId;
          responseId = (targetNode.data as any)?.dbResponseId;
        } else if (sourceNode?.type === 'response' && targetNode?.type === 'operation') {
          operationId = (targetNode.data as any)?.dbOperationId;
          responseId = (sourceNode.data as any)?.dbResponseId;
        }

        // Handle parameter unlinking
        if (operationId && parameterId) {
          try {
            const result = await unlinkParameterFromOperation(operationId, parameterId);
            const parsed = JSON.parse(result);

            if (parsed.success) {
              // Update the operation node's parameters array to remove the unlinked parameter
              const opNode = sourceNode?.type === 'operation' ? sourceNode : targetNode;

              if (opNode) {
                setNodes((nds) => nds.map((node) => {
                  if (node.id === opNode.id) {
                    const currentParams = (node.data as any).parameters || [];
                    return {
                      ...node,
                      data: {
                        ...node.data,
                        parameters: currentParams.filter((p: any) => p.id !== parameterId),
                      },
                    };
                  }
                  return node;
                }));
              }
            } else {
              console.error('Failed to unlink parameter from operation:', parsed.error);
              await alertDialog({
                title: 'Error',
                message: parsed.error || 'Failed to unlink parameter from operation',
                variant: 'error',
              });
            }
          } catch (error) {
            console.error('Error unlinking parameter from operation:', error);
          }
        }
        // Handle response unlinking
        else if (operationId && responseId) {
          try {
            const result = await unlinkResponseFromOperation(operationId, responseId);
            const parsed = JSON.parse(result);

            if (!parsed.success) {
              console.error('Failed to unlink response from operation:', parsed.error);
              await alertDialog({
                title: 'Error',
                message: parsed.error || 'Failed to unlink response from operation',
                variant: 'error',
              });
            }
          } catch (error) {
            console.error('Error unlinking response from operation:', error);
          }
        }
      }
    },
    [nodes, alertDialog, setNodes]
  );

  // Handle drop
  const onDrop = useCallback(
    async (event: React.DragEvent) => {
      console.log('=== [onDrop] Canvas drop event START ===');
      console.log('[onDrop] event.clientX:', event.clientX, 'event.clientY:', event.clientY);
      event.preventDefault();

      const data = event.dataTransfer.getData('application/json');
      console.log('[onDrop] Raw data from dataTransfer:', data);

      if (!data) {
        console.log('[onDrop] No data in dataTransfer, returning');
        return;
      }

      if (!selectedPathId) {
        console.log('[onDrop] No selectedPathId, showing alert');
        await alertDialog({
          title: 'No Path Selected',
          message: 'Please select a path from the sidebar before adding operations to the canvas.',
          variant: 'warning',
        });
        return;
      }

      const dropData = JSON.parse(data);
      console.log('[onDrop] Parsed dropData:', dropData);
      console.log('[onDrop] dropData.type:', dropData.type);

      // Handle property drops - check if dropping on a response body node
      if (dropData.type === 'property') {
        console.log('[onDrop] Property dropped at canvas level, checking for target node');

        const elementAtPoint = document.elementFromPoint(event.clientX, event.clientY);
        let targetNodeId: string | null = null;

        // Check if the drop target is within a drop zone that has its own handler
        // (like ContentTypePanel) - if so, let that handle it
        if (elementAtPoint) {
          // Check if we're dropping on a child element with its own drop handler
          const hasDropHandler = elementAtPoint.closest('[data-drop-handler]');
          if (hasDropHandler) {
            console.log('[onDrop] Drop target has its own handler, letting it handle the drop');
            return; // Let the child handler process it
          }

          // Also check for drop zone markers
          const isInDropZone = elementAtPoint.closest('[data-drop-zone]');
          if (isInDropZone) {
            console.log('[onDrop] Drop target is in a drop zone, letting it handle the drop');
            return; // Let the drop zone handle it
          }

          // Find the node wrapper
          const nodeWrapper = elementAtPoint.closest('[data-id]');
          if (nodeWrapper) {
            targetNodeId = nodeWrapper.getAttribute('data-id');
          }
        }

        console.log('[onDrop] Target node ID:', targetNodeId);

        // Only handle drops on response body nodes if they're on the node wrapper itself,
        // not on child elements (which should have their own handlers)
        if (targetNodeId && targetNodeId.startsWith('response-body-')) {
          // Check if the drop was on the node wrapper itself, not a child
          const elementAtPoint = document.elementFromPoint(event.clientX, event.clientY);
          const nodeWrapper = elementAtPoint?.closest('[data-id]');
          const isDirectNodeDrop = nodeWrapper && nodeWrapper.getAttribute('data-id') === targetNodeId;
          
          // If dropping directly on node wrapper (not a child), handle it as fallback
          // Otherwise, the child handlers (ContentTypePanel) should have handled it
          if (isDirectNodeDrop) {
            const responseBodyNode = nodes.find(n => n.id === targetNodeId);
            if (responseBodyNode) {
              const nodeData = responseBodyNode.data as PathResponseBodyData;
              console.log('[onDrop] Found response body node (fallback handler):', {
                id: targetNodeId,
                contentTypesCount: nodeData.contentTypes?.length,
                hasOnPropertyDrop: !!nodeData.onPropertyDrop,
                hasOnCreateContentTypeWithProperty: !!nodeData.onCreateContentTypeWithProperty,
              });

              if (nodeData.contentTypes && nodeData.contentTypes.length > 0) {
                // Has content types - add property to first content type (fallback)
                const contentId = nodeData.contentTypes[0].id;
                console.log('[onDrop] Adding property to existing content type (fallback):', contentId);
                if (nodeData.onPropertyDrop) {
                  nodeData.onPropertyDrop(contentId, dropData, undefined);
                }
              } else {
                // No content types - create one with the property
                console.log('[onDrop] Creating content type with property for response (fallback):', nodeData.id);
                if (nodeData.onCreateContentTypeWithProperty) {
                  nodeData.onCreateContentTypeWithProperty(nodeData.id, dropData);
                }
              }
              return; // Don't process further
            }
          } else {
            // Drop was on a child element - it should have been handled by the child handler
            // If we reach here, the child handler didn't process it, so return silently
            console.log('[onDrop] Drop was on child element, should have been handled by child handler');
            return;
          }
        }

        // Property dropped on empty canvas - show info message
        await alertDialog({
          title: 'Drop Property on Response',
          message: 'To add a property to a response schema, drag it onto a Response node on the canvas.',
          variant: 'info',
        });
        return;
      }

      if (dropData.type === 'operation') {
        const position = screenToFlowPosition({
          x: event.clientX,
          y: event.clientY,
        });

        try {
          // Get path pattern for generating operationId
          let pathPattern: string | undefined;
          try {
            const pathResponse = await getPathById(selectedPathId);
            const pathData = JSON.parse(pathResponse);
            pathPattern = pathData?.pathname;
          } catch (pathError) {
            console.log('[onDrop] Could not fetch path pattern:', pathError);
          }

          // Save to database (also creates path_operation_description with operationId)
          const result = await createOperation(
            selectedPathId,
            dropData.operation,
            { position },
            pathPattern
          );
          const savedOperation = JSON.parse(result);

          // Get the generated operationId from the description
          let operationId: string | undefined;
          try {
            const descResponse = await getOperationDescription(savedOperation.id);
            const descData = JSON.parse(descResponse);
            operationId = descData?.operation_id;
          } catch (descError) {
            console.log('[onDrop] Could not fetch operation description:', descError);
          }

          // Add to canvas
          const newNode: Node = {
            id: savedOperation.id,
            type: 'operation',
            position,
            data: {
              operation: savedOperation.operation,
              color: dropData.color,
              dbOperationId: savedOperation.id,
              operationId: operationId,
              parameters: [],
            },
          };

          setNodes((nds) => [...nds, newNode]);
        } catch (error) {
          console.error('Error creating operation:', error);
          await alertDialog({
            title: 'Error',
            message: 'Failed to add operation. Please try again.',
            variant: 'error',
          });
        }
      } else if (dropData.type === 'parameter') {
        await alertDialog({
          title: 'Add Parameter via Properties Panel',
          message: 'To add a parameter, click on an operation node and use the "Add Parameter" button in the Operation Details panel on the right.',
          variant: 'info',
        });
      } else if (dropData.type === 'class') {
        console.log('PathsCanvasView: Class dropped on canvas', {
          dropData,
          clientX: event.clientX,
          clientY: event.clientY,
          target: event.target,
          currentTarget: event.currentTarget,
        });
        
        // Check if we're dropping on a response node
        // React Flow nodes have data-id attribute on the wrapper
        // Use elementFromPoint to find the element under the cursor
        const elementAtPoint = document.elementFromPoint(event.clientX, event.clientY);
        console.log('PathsCanvasView: Element at drop point', {
          element: elementAtPoint,
          tagName: elementAtPoint?.tagName,
          className: elementAtPoint?.className,
          id: elementAtPoint?.id,
          dataset: elementAtPoint ? Object.keys((elementAtPoint as HTMLElement).dataset || {}) : [],
        });
        
        // Try multiple ways to find the response node
        let responseNodeId: string | null = null;
        
        if (elementAtPoint) {
          // Method 1: Check for data-id attribute (React Flow's node wrapper)
          const nodeWrapper = elementAtPoint.closest('[data-id]');
          if (nodeWrapper) {
            responseNodeId = nodeWrapper.getAttribute('data-id');
            console.log('PathsCanvasView: Found node via data-id', responseNodeId);
          }
          
          // Method 2: Check parent elements for data-id
          if (!responseNodeId) {
            let parent = elementAtPoint.parentElement;
            let depth = 0;
            while (parent && depth < 10) {
              const nodeId = parent.getAttribute('data-id');
              if (nodeId && nodeId.startsWith('response-')) {
                responseNodeId = nodeId;
                console.log('PathsCanvasView: Found node via parent traversal', responseNodeId);
                break;
              }
              parent = parent.parentElement;
              depth++;
            }
          }
          
          // Method 3: Use React Flow's getNodes to find node at position
          if (!responseNodeId) {
            try {
              const position = screenToFlowPosition({
                x: event.clientX,
                y: event.clientY,
              });
              
              // Get all nodes from React Flow
              const allNodes = getNodes();
              console.log('PathsCanvasView: All nodes from React Flow', allNodes.map(n => ({ id: n.id, type: n.type, position: n.position })));
              
              // Find response nodes and check if position is within bounds
              // React Flow nodes are approximately 280x150
              for (const node of allNodes) {
                if (node.type === 'response') {
                  const nodeX = node.position.x || 0;
                  const nodeY = node.position.y || 0;
                  const nodeWidth = 280; // Approximate width
                  const nodeHeight = 150; // Approximate height
                  
                  const isWithinBounds = (
                    position.x >= nodeX - 10 && // Add some padding
                    position.x <= nodeX + nodeWidth + 10 &&
                    position.y >= nodeY - 10 &&
                    position.y <= nodeY + nodeHeight + 10
                  );
                  
                  console.log('PathsCanvasView: Checking node', {
                    nodeId: node.id,
                    nodePosition: { x: nodeX, y: nodeY },
                    dropPosition: position,
                    isWithinBounds,
                  });
                  
                  if (isWithinBounds) {
                    responseNodeId = node.id;
                    console.log('PathsCanvasView: Found node via position calculation', responseNodeId);
                    break;
                  }
                }
              }
            } catch (error) {
              console.error('PathsCanvasView: Error in position calculation', error);
            }
          }
        }
        
        if (responseNodeId && responseNodeId.startsWith('response-')) {
          console.log('PathsCanvasView: Dropped on response node', { responseNodeId });
          
          // Find the response node and call its onClassDrop handler
          const responseNode = nodes.find(n => n.id === responseNodeId && n.type === 'response');
          const responseData = responseNode?.data as { onClassDrop?: (responseId: string, classData: unknown) => void; dbResponseId?: string } | undefined;
          if (responseNode && responseData?.onClassDrop && responseData?.dbResponseId) {
            try {
              await responseData.onClassDrop(responseData.dbResponseId, dropData);
            } catch (error) {
              console.error('Error in onClassDrop:', error);
            }
            return; // Don't create a new class node
          } else {
            console.warn('PathsCanvasView: Response node found but missing handler or dbResponseId', {
              responseNode: !!responseNode,
              hasOnClassDrop: !!responseData?.onClassDrop,
              hasDbResponseId: !!responseData?.dbResponseId,
            });
          }
        }
        
        // Class dropped on empty canvas - create a class node
        const position = screenToFlowPosition({
          x: event.clientX,
          y: event.clientY,
        });

        // Check if class node already exists
        const existingClassNode = nodes.find(
          (n) => n.type === 'class' && (n.data as any).dbClassId === dropData.classId
        );

        if (existingClassNode) {
          await alertDialog({
            title: 'Class Already on Canvas',
            message: `The class "${dropData.className}" is already on the canvas. You can connect it to responses by dragging it onto them.`,
            variant: 'info',
          });
          return;
        }

        // Create new class node
        const classNodeId = `class-${dropData.classId}`;
        const newNode: Node = {
          id: classNodeId,
          type: 'class',
          position,
          data: {
            className: dropData.className,
            classId: dropData.classId,
            dbClassId: dropData.classId,
            onDelete: () => handleDeleteClassFromCanvas(dropData.classId),
          },
        };

        setNodes((nds) => [...nds, newNode]);
      }
    },
    [screenToFlowPosition, setNodes, selectedPathId, alertDialog, nodes, handleClassDropOnResponse]
  );

  return (
    <div ref={reactFlowWrapper} className="flex-1 flex flex-col h-full">
        <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onEdgesDelete={onEdgesDelete}
        onDrop={onDrop}
        onDragOver={onDragOver}
        onNodeClick={onNodeClick}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        defaultEdgeOptions={{ zIndex: 0 }}
        snapToGrid={snapToGrid}
        snapGrid={[gridSize, gridSize]}
        fitView
        attributionPosition="bottom-left"
        className={isDark ? 'bg-gray-900' : ''}
        nodesDraggable={true}
        nodesConnectable={true}
        elementsSelectable={true}
        selectionOnDrag={true}
        nodesFocusable={true}
        edgesFocusable={true}
        style={{
          background: isDark
            ? 'radial-gradient(ellipse at top, #1e293b 0%, #0f172a 50%, #020617 100%)'
            : 'radial-gradient(ellipse at top, #ffffff 0%, #f8fafc 30%, #f1f5f9 100%)'
        }}
      >
        <Background
          variant={backgroundVariant(gridStyle)}
          gap={gridSize}
          size={1}
          color="currentColor"
          style={{
            color: isDark ? 'rgba(148, 163, 184, 0.15)' : 'rgba(99, 102, 241, 0.08)',
            opacity: 1
          }}
        />
        <Controls
          className="bg-white/95 dark:bg-gray-800/95 backdrop-blur-md border border-gray-200/50 dark:border-gray-700/50 rounded-xl shadow-xl overflow-hidden"
          style={{
            borderRadius: '12px',
            overflow: 'hidden',
            boxShadow: isDark 
              ? '0 4px 24px rgba(0, 0, 0, 0.4), 0 0 0 1px rgba(255, 255, 255, 0.05)'
              : '0 4px 24px rgba(0, 0, 0, 0.08), 0 0 0 1px rgba(0, 0, 0, 0.04)',
          }}
        />
      </ReactFlow>
    </div>
  );
}

export default function PathsCanvasView({
  selectedPathId,
  onOperationSelect,
  onParameterSelect,
  onResponseSelect,
  refreshKey,
  onRefresh,
}: {
  selectedPathId: string | null;
  onOperationSelect: (operation: { id: string; operation: string } | null) => void;
  onParameterSelect?: (parameter: { id: string; name: string; operationId: string } | null) => void;
  onResponseSelect?: (response: { id: string; statusCode: string; description: string } | null) => void;
  refreshKey?: number;
  onRefresh?: () => void;
}) {
  return (
    <ReactFlowProvider>
      <PathsCanvasInner
        selectedPathId={selectedPathId}
        onOperationSelect={onOperationSelect}
        onParameterSelect={onParameterSelect}
        onResponseSelect={onResponseSelect}
        refreshKey={refreshKey}
        onRefresh={onRefresh}
      />
    </ReactFlowProvider>
  );
}
