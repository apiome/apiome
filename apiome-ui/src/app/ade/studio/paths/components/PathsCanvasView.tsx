'use client';

import React, { useCallback, useState, useEffect, useRef } from 'react';
import {
  ReactFlow,
  Background,
  BackgroundVariant,
  Controls,
  Panel,
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
import { getCanvasBackgroundStyle } from '../../../../utils/canvas-background-style';
import { computeAlignmentGuidesForNode, type AlignmentGuidesState } from '../../lib/smart-alignment-guides';
import SmartEdge from '../../../../components/ade/studio/SmartEdge';
import {
  getOperationsForPath,
  deleteOperation,
} from '../../../../../../lib/db/helper-path-operations';
import { createOperation as createOperationViaApi } from '../../../../../../lib/api/paths-client';
import {
  getPathById,
} from '../../../../../../lib/db/helper-paths';
import {
  getOperationDescription,
  upsertOperationDescription,
} from '../../../../../../lib/db/helper-path-operation-descriptions';
import { generateOperationId } from '../../../../../../lib/utils/path-utils';
import {
  getLinkedParametersForOperation,
  linkParameterToOperation,
  unlinkParameterFromOperation,
  getSharedPathParameters,
  createSharedPathParameter,
  updateSharedPathParameter,
  deleteSharedPathParameter,
} from '../../../../../../lib/db/helper-shared-path-parameters';
import { extractPathParameters, isValidPath, getPathWithSampleValues } from '../../../../../../lib/utils/path-params';
import { normalizeStyleForLocation } from '../../../../../../lib/utils/openapi-parameter-style';
import { propertyDataToParameterSchema } from '../../../../../../lib/utils/path-parameter-schema';
import {
  getLinkedResponsesForOperation,
  getSharedPathResponses,
  createSharedPathResponse,
  deleteSharedPathResponse,
  unlinkResponseFromOperation,
  linkResponseToOperation,
  updateSharedPathResponse,
  copyClassPropertiesToResponseInlineSchema,
} from '../../../../../../lib/db/helper-shared-path-responses';
import PathParameterNode from './PathParameterNode';
import PathResponseNode from './PathResponseNode';
import PathClassNode from './PathClassNode';
import PathRequestBodyNode, { PathRequestBodyData } from './PathRequestBodyNode';
import PathResponseBodyNode, { PathResponseBodyData } from './PathResponseBodyNode';
import ClassDropChoiceDialog, { ClassDropAction } from '../../../../components/dialogs/ClassDropChoiceDialog';
import PathTemplateNode from './PathTemplateNode';
import { OPERATION_COLORS } from './paths-operation-colors';
import { Trash2, Lock, Unlock, AlertTriangle, Eye, Copy, Check, LayoutGrid } from 'lucide-react';
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
  updateSharedPathRequestBody,
  addRequestBodyContentType,
  addPropertyToInlineSchema,
  deleteInlineSchemaProperty,
  convertClassToInlineSchema,
  updateRequestBodyContentType,
  copyClassPropertiesToRequestBodyContentType,
} from '../../../../../../lib/db/helper-shared-path-request-bodies';
import {
  addResponseContentType,
  addPropertyToResponseInlineSchema,
  deleteResponseInlineSchemaProperty,
  deleteResponseContentType,
  copyClassPropertiesToContentType,
  setResponseContentTypeClassReference,
} from '../../../../../../lib/db/helper-shared-path-responses-content';
import { getPathCanvas, putPathCanvas } from '../../../../../../lib/api/paths-client';
import {
  mergePathsCanvasLayout,
  serializePathsCanvas,
  type PathsCanvasBlob,
} from '../lib/paths-canvas-persist';
import { applyAutoLayout, type AutoLayoutOptions } from '../../../../utils/canvas-auto-layout';
import {
  labelPathToOperation,
  labelOperationToParameter,
  labelOperationToRequestBody,
  labelOperationToResponse,
  pathsCanvasEdgeLabelStyle,
  pathsCanvasEdgeLabelBgStyle,
  labelForManualConnection,
} from '../lib/paths-canvas-edge-labels';

const PATHS_CANVAS_AUTO_LAYOUT_OPTIONS: Partial<AutoLayoutOptions> = {
  nodeSpacingX: 64,
  nodeSpacingY: 168,
  padding: 56,
  direction: 'TB',
  centerNodes: true,
  minimizeCrossings: true,
};

// Enhanced Operation Node Component with Schema Drop Zones - Vertical Layout
function OperationNode({ data }: {
  data: { 
    operation: string; 
    color: string; 
    dbOperationId?: string;
    operationId?: string; // OpenAPI operationId (e.g., "createUser", "listOrders")
    parameters?: Array<{ id: string; name: string; in: string; required?: boolean }>;
    security?: Array<Record<string, string[]>>; // OpenAPI security requirements
    deprecated?: boolean; // Whether the operation is deprecated
    xPrivate?: boolean; // Hide from Swagger (x-private)
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

      <div 
        className={`bg-white dark:bg-gray-800 rounded-xl border-2 shadow-xl min-w-[220px] max-w-[280px] cursor-pointer relative ${
          data.deprecated ? 'border-dashed opacity-75' : ''
        } ${data.xPrivate ? 'ring-2 ring-indigo-400/50 ring-offset-2 ring-offset-white dark:ring-offset-gray-900' : ''}`}
        style={{ borderColor: data.deprecated ? '#f59e0b' : data.color }}
      >
        {/* Delete button */}
        {data.onDelete && (
          <button
            onClick={(e) => {
              e.stopPropagation();
              data.onDelete?.();
            }}
            className="absolute top-2 right-2 rounded p-1 text-white hover:opacity-80 z-20"
            title="Delete operation"
          >
            <Trash2 size={14} />
          </button>
        )}

        {/* Header - Only this part has color */}
        <div
          className={`text-white px-4 py-3 rounded-t-xl ${data.deprecated ? 'opacity-70' : ''}`}
          style={{ backgroundColor: data.color }}
        >
          <div className="flex items-center justify-between gap-1 flex-wrap">
            <div className="text-xs font-medium opacity-90">HTTP Method</div>
            <div className="flex items-center gap-1">
              {data.xPrivate && (
                <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[9px] font-semibold bg-indigo-400/90 text-indigo-900 dark:bg-indigo-300/90 dark:text-indigo-900" title="Hidden from Swagger (x-private)">
                  <Lock size={10} />
                  Private
                </span>
              )}
              {data.deprecated && (
                <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[9px] font-semibold bg-amber-400/90 text-amber-900">
                  <AlertTriangle size={10} />
                  Deprecated
                </span>
              )}
            </div>
          </div>
          <div className={`font-bold text-lg ${data.deprecated ? 'line-through opacity-80' : ''}`}>{data.operation}</div>
          {data.operationId && (
            <div className={`text-xs opacity-80 font-mono mt-1 ${data.deprecated ? 'line-through' : ''}`}>{data.operationId}</div>
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

          {/* Security badges: Public (unsecured), or OR = separate badges; within each, schemes are AND. */}
          {data.security && data.security.length === 0 && (
            <span
              className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400"
              title="Public endpoint — no authentication required"
            >
              <Unlock size={10} />
              Public
            </span>
          )}
          {data.security && data.security.length > 0 && (
            <div className="flex flex-wrap gap-1 items-center">
              {data.security.map((req, i) => {
                const entries = Object.entries(req).filter(([k]) => Boolean(k)) as [string, string[]][];
                if (entries.length === 0) return null;
                const labelParts = entries.map(([name, scopes]) =>
                  Array.isArray(scopes) && scopes.length > 0 ? `${name} (${scopes.join(', ')})` : name
                );
                const label = labelParts.join(' + ');
                const titleParts = entries.map(([name, scopes]) =>
                  Array.isArray(scopes) && scopes.length > 0 ? `${name}: [${scopes.join(', ')}]` : name
                );
                const title = entries.length > 1
                  ? `Security (AND): ${titleParts.join('; ')}`
                  : `Security: ${titleParts[0]}`;
                return (
                  <span
                    key={i}
                    className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400"
                    title={title}
                  >
                    <Lock size={10} />
                    {label}
                  </span>
                );
              })}
            </div>
          )}
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
  pathTemplate: PathTemplateNode,
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

/** Split pathname into segments: literal strings and variable names for clickable variables */
function parsePathSegments(pathname: string): Array<{ type: 'literal' | 'variable'; value: string }> {
  const segments: Array<{ type: 'literal' | 'variable'; value: string }> = [];
  const regex = /\{([^}]+)\}/g;
  let lastIndex = 0;
  let match;
  while ((match = regex.exec(pathname)) !== null) {
    if (match.index > lastIndex) {
      segments.push({ type: 'literal', value: pathname.slice(lastIndex, match.index) });
    }
    segments.push({ type: 'variable', value: match[1] });
    lastIndex = regex.lastIndex;
  }
  if (lastIndex < pathname.length) {
    segments.push({ type: 'literal', value: pathname.slice(lastIndex) });
  }
  return segments;
}

interface PathsCanvasInnerProps {
  selectedPathId: string | null;
  pathname?: string | null;
  onOperationSelect: (operation: { id: string; operation: string } | null) => void;
  onParameterSelect?: (parameter: { id: string; name: string; operationId: string } | null) => void;
  onResponseSelect?: (response: { id: string; statusCode: string; description: string } | null) => void;
  refreshKey?: number;
  onRefresh?: () => void;
  onPathnameUpdated?: (pathname: string) => void;
  /** When set (e.g. from sidebar), zoom to this node id after it exists on the canvas. */
  pendingFocusNodeId?: string | null;
  onPendingFocusComplete?: () => void;
}

function PathsCanvasInner({
  selectedPathId,
  pathname,
  onOperationSelect,
  onParameterSelect,
  onResponseSelect,
  refreshKey,
  onRefresh,
  onPathnameUpdated,
  pendingFocusNodeId,
  onPendingFocusComplete,
}: PathsCanvasInnerProps) {
  type ClassDropDialogOptions = { asArray: boolean };
  const {
    gridSize,
    gridStyle,
    showGrid,
    snapToGrid,
    smartGuidesEnabled,
    canvasBackground,
    edgeStyling,
    edgeRouting,
    edgeAnimation,
    selectedVersionId,
    registerPathsCanvasFlush,
    setFocusPathsCanvasNodeFn,
    setCanvasViewport,
  } = useStudio();

  const { alert: alertDialog, confirm: confirmDialog } = useDialog();
  const reactFlowWrapper = useRef<HTMLDivElement>(null);
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [isDark, setIsDark] = useState(false);
  const { screenToFlowPosition, getNodes, getNode, getViewport, setViewport, fitView } = useReactFlow();
  const [alignmentGuides, setAlignmentGuides] = useState<AlignmentGuidesState>({ horizontal: [], vertical: [] });

  // Remove legacy path->operation "has" labels that may still exist in in-memory edge state.
  useEffect(() => {
    setEdges((eds) => {
      let changed = false;
      const next = eds.map((edge) => {
        const semantic = (edge.data as { semantic?: unknown } | undefined)?.semantic;
        const isPathToOperation = edge.sourceHandle === 'path-output' && edge.targetHandle === 'operation-input';
        const isPathHasOperation = semantic === 'path-has-operation' || isPathToOperation;
        if (!isPathHasOperation) return edge;
        if (edge.label === undefined && edge.labelStyle === undefined && edge.labelBgStyle === undefined) {
          return edge;
        }
        changed = true;
        return {
          ...edge,
          label: undefined,
          labelStyle: undefined,
          labelBgStyle: undefined,
        };
      });
      return changed ? next : eds;
    });
  }, [setEdges]);

  useEffect(() => {
    const fn = (nodeId: string) => {
      const n = getNode(nodeId);
      if (n) {
        fitView({ nodes: [n], padding: 0.32, duration: 280 });
      }
    };
    setFocusPathsCanvasNodeFn(fn);
    return () => setFocusPathsCanvasNodeFn(null);
  }, [getNode, fitView, setFocusPathsCanvasNodeFn]);

  const appliedPendingFocusRef = useRef<string | null>(null);
  /** Sidebar: zoom to an operation after the graph loads or switches path. */
  useEffect(() => {
    if (!pendingFocusNodeId) {
      appliedPendingFocusRef.current = null;
      return;
    }
    const n = getNode(pendingFocusNodeId);
    if (n) {
      if (appliedPendingFocusRef.current !== pendingFocusNodeId) {
        appliedPendingFocusRef.current = pendingFocusNodeId;
        fitView({ nodes: [n], padding: 0.32, duration: 280 });
        onPendingFocusComplete?.();
      }
      return;
    }
    const t = window.setTimeout(() => {
      onPendingFocusComplete?.();
    }, 3500);
    return () => clearTimeout(t);
  }, [nodes, pendingFocusNodeId, getNode, fitView, onPendingFocusComplete]);
  const [canvasPersistReady, setCanvasPersistReady] = useState(false);
  const canvasSaveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const saveInFlightRef = useRef<Promise<unknown> | null>(null);
  const viewportToApplyRef = useRef<{ x: number; y: number; zoom: number } | null>(null);
  const shouldFitAfterLoadRef = useRef(false);
  const onPathnameUpdatedRef = useRef(onPathnameUpdated);
  useEffect(() => {
    onPathnameUpdatedRef.current = onPathnameUpdated;
  }, [onPathnameUpdated]);

  const canvasBackgroundStyle = React.useMemo(
    () => getCanvasBackgroundStyle(canvasBackground, isDark),
    [canvasBackground, isDark]
  );

  // State for class drop choice dialog
  const [classDropDialogOpen, setClassDropDialogOpen] = useState(false);
  const [classDropDialogClassName, setClassDropDialogClassName] = useState('');
  const [classDropDialogCallback, setClassDropDialogCallback] = useState<((action: 'copy' | 'reference', options: ClassDropDialogOptions) => void) | null>(null);
  const [classDropDialogShowArrayOption, setClassDropDialogShowArrayOption] = useState(false);
  const [classDropDialogAsArray, setClassDropDialogAsArray] = useState(false);

  // State for path variable drop target (property drag from sidebar for type binding)
  const [dragOverPathVariable, setDragOverPathVariable] = useState<string | null>(null);
  const pathVariableDragCounterRef = useRef(0);

  // Path parameters for sample-value preview (#360)
  const [pathParamsForPreview, setPathParamsForPreview] = useState<Array<{ name: string; in_location: string; data?: Record<string, unknown> }>>([]);
  const [samplePathCopied, setSamplePathCopied] = useState(false);
  useEffect(() => {
    if (!selectedPathId || !pathname || extractPathParameters(pathname).length === 0) {
      setPathParamsForPreview([]);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const res = await getSharedPathParameters(selectedPathId);
        const data = JSON.parse(res);
        if (cancelled || !data.success || !Array.isArray(data.parameters)) return;
        const pathParams = data.parameters.filter((p: { in_location: string }) => p.in_location === 'path');
        if (!cancelled) setPathParamsForPreview(pathParams);
      } catch {
        if (!cancelled) setPathParamsForPreview([]);
      }
    })();
    return () => { cancelled = true; };
  }, [selectedPathId, pathname, refreshKey]);

  // Refs to hold the latest handler functions
  // This prevents stale closures when nodes are moved or canvas is refreshed
  const handleResponseBodyPropertyDropRef = useRef<(contentId: string, propertyData: any, parentId?: string) => void>(() => {});
  const handleResponseBodyPropertyDeleteRef = useRef<(contentId: string, propertyId: string) => void>(() => {});
  const handleResponseBodyClassDropRef = useRef<(contentId: string, classData: any, action: 'copy' | 'reference') => void>(() => {});
  const handleCreateContentTypeWithPropertyRef = useRef<(responseId: string, propertyData: any) => void>(() => {});
  const handleCreateContentTypeWithClassRef = useRef<(responseId: string, classData: any, action: 'copy' | 'reference') => void>(() => {});
  const handleRequestBodyPropertyDropRef = useRef<(contentId: string, propertyData: any, parentId?: string) => void>(() => {});
  const handleRequestBodyPropertyDeleteRef = useRef<(contentId: string, propertyId: string) => void>(() => {});
  const handleRequestBodyClassDropRef = useRef<(contentId: string, classData: any, action: 'copy' | 'reference') => void>(() => {});

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

  // Handle class drop on response - now accepts an action for copy vs reference
  const handleClassDropOnResponse = useCallback(async (
    responseId: string,
    classData: any,
    action: 'copy' | 'reference'
  ) => {
    if (!selectedPathId || !classData.classId) return;

    try {
      if (action === 'copy') {
        // Copy class properties to the response's inline schema
        const result = await copyClassPropertiesToResponseInlineSchema(responseId, classData.classId);
        const parsed = JSON.parse(result);

        if (parsed.success) {
          await alertDialog({
            title: 'Properties Copied',
            message: `Copied ${parsed.copiedProperties} properties from class "${parsed.fromClass}" to the response schema.`,
            variant: 'success',
          });
        } else {
          await alertDialog({
            title: 'Error',
            message: parsed.error || 'Failed to copy class properties to response',
            variant: 'error',
          });
        }
      } else if (action === 'reference') {
        // Create class reference by updating response
        const result = await updateSharedPathResponse(responseId, {
          classId: classData.classId, // Set class reference
          schemaMode: 'class', // Set schema mode to class
          inlineSchema: null, // Clear any inline schema
          data: null, // Clear any legacy data
        });
        const parsed = JSON.parse(result);

        if (parsed.success) {
          await alertDialog({
            title: 'Class Referenced',
            message: `Response now references class "${classData.className}" ($ref).`,
            variant: 'success',
          });
        } else {
          await alertDialog({
            title: 'Error',
            message: parsed.error || 'Failed to reference class for response',
            variant: 'error',
          });
        }
      }
      // Refresh canvas to show updated schema
      if (onRefresh) {
        onRefresh();
      }
    } catch (error) {
      console.error('Error handling class drop on response:', error);
      await alertDialog({
        title: 'Error',
        message: 'Failed to handle class drop on response. Please try again.',
        variant: 'error',
      });
    }
  }, [selectedPathId, alertDialog, onRefresh]);

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
              } catch {
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

  // Handle click on path variable: create-or-get shared parameter and open schema editor
  const handlePathVariableClick = useCallback(
    async (variableName: string) => {
      if (!selectedPathId || !onParameterSelect) return;
      try {
        const result = await createSharedPathParameter(
          selectedPathId,
          variableName,
          'path',
          undefined,
          undefined,
          { type: 'string', required: true }
        );
        const parsed = JSON.parse(result);
        if (parsed.success && parsed.parameter) {
          onParameterSelect({
            id: parsed.parameter.id,
            name: variableName,
            operationId: '',
          });
          if (onRefresh) onRefresh();
        } else {
          await alertDialog({
            title: 'Error',
            message: parsed.error || 'Failed to open parameter schema',
            variant: 'error',
          });
        }
      } catch (error) {
        console.error('Error opening parameter for variable:', error);
        await alertDialog({
          title: 'Error',
          message: 'Failed to open parameter schema',
          variant: 'error',
        });
      }
    },
    [selectedPathId, onParameterSelect, onRefresh, alertDialog]
  );

  // Handle property drop on path variable: bind property type/schema to the parameter
  const handlePropertyDropOnPathVariable = useCallback(
    async (variableName: string, dropData: any) => {
      if (!selectedPathId) return;
      if (dropData?.type !== 'property') {
        await alertDialog({
          title: 'Invalid drop',
          message: 'Only properties are allowed to be bound to a path parameter.',
          variant: 'warning',
        });
        return;
      }
      const propertyData = dropData.data || { type: 'string' };
      const schema = propertyDataToParameterSchema(propertyData);
      try {
        const createResult = await createSharedPathParameter(
          selectedPathId,
          variableName,
          'path',
          undefined,
          undefined,
          schema
        );
        const createParsed = JSON.parse(createResult);
        if (!createParsed.success || !createParsed.parameter) {
          await alertDialog({
            title: 'Error',
            message: createParsed.error || 'Failed to bind property to parameter',
            variant: 'error',
          });
          return;
        }
        const param = createParsed.parameter;
        if (createParsed.existed) {
          const updateResult = await updateSharedPathParameter(param.id, { data: schema });
          const updateParsed = JSON.parse(updateResult);
          if (!updateParsed.success) {
            await alertDialog({
              title: 'Error',
              message: updateParsed.error || 'Failed to update parameter schema',
              variant: 'error',
            });
            return;
          }
        }
        if (onRefresh) onRefresh();
        if (onParameterSelect) {
          onParameterSelect({ id: param.id, name: variableName, operationId: '' });
        }
      } catch (error) {
        console.error('Error binding property to path variable:', error);
        await alertDialog({
          title: 'Error',
          message: 'Failed to bind property to parameter',
          variant: 'error',
        });
      }
    },
    [selectedPathId, onRefresh, onParameterSelect, alertDialog]
  );

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

  // Add a content type branch to a request body (application/json, multipart/form-data, etc.)
  const handleAddRequestBodyContentType = useCallback(async (requestBodyId: string, mediaType: string) => {
    try {
      const result = await addRequestBodyContentType(
        requestBodyId,
        mediaType,
        undefined,
        { type: 'object', properties: {} }
      );
      const parsed = JSON.parse(result);
      if (parsed.success) {
        if (onRefresh) onRefresh();
      } else {
        await alertDialog({
          title: 'Error',
          message: parsed.error || 'Failed to add content type',
          variant: 'error',
        });
      }
    } catch (error) {
      console.error('Error adding request body content type:', error);
      await alertDialog({
        title: 'Error',
        message: 'Failed to add content type',
        variant: 'error',
      });
    }
  }, [alertDialog, onRefresh]);

  // Update request body description (for request body node mapping #389)
  const handleUpdateRequestBodyDescription = useCallback(async (requestBodyId: string, description: string) => {
    try {
      const result = await updateSharedPathRequestBody(requestBodyId, { description: description || '' });
      const parsed = JSON.parse(result);
      if (parsed.success) {
        if (onRefresh) onRefresh();
      } else {
        await alertDialog({
          title: 'Error',
          message: parsed.error || 'Failed to update description',
          variant: 'error',
        });
      }
    } catch (error) {
      console.error('Error updating request body description:', error);
      await alertDialog({
        title: 'Error',
        message: 'Failed to update description',
        variant: 'error',
      });
    }
  }, [alertDialog, onRefresh]);

  // Update request body content type examples (#390)
  const handleUpdateRequestBodyExamples = useCallback(async (
    contentId: string,
    examples: Array<{ summary?: string; value: unknown }>
  ) => {
    try {
      const result = await updateRequestBodyContentType(contentId, { examples });
      const parsed = JSON.parse(result);
      if (parsed.success) {
        if (onRefresh) onRefresh();
      } else {
        await alertDialog({
          title: 'Error',
          message: parsed.error || 'Failed to update examples',
          variant: 'error',
        });
      }
    } catch (error) {
      console.error('Error updating request body examples:', error);
      await alertDialog({
        title: 'Error',
        message: 'Failed to update examples',
        variant: 'error',
      });
    }
  }, [alertDialog, onRefresh]);

  // Update request body content type encoding options (#391, multipart/form-data etc.)
  const handleUpdateRequestBodyEncoding = useCallback(async (
    contentId: string,
    encoding: Record<string, Record<string, unknown>> | null
  ) => {
    try {
      const result = await updateRequestBodyContentType(contentId, { encoding });
      const parsed = JSON.parse(result);
      if (parsed.success) {
        if (onRefresh) onRefresh();
      } else {
        await alertDialog({
          title: 'Error',
          message: parsed.error || 'Failed to update encoding',
          variant: 'error',
        });
      }
    } catch (error) {
      console.error('Error updating request body encoding:', error);
      await alertDialog({
        title: 'Error',
        message: 'Failed to update encoding',
        variant: 'error',
      });
    }
  }, [alertDialog, onRefresh]);

  // Handle request body property drop (add to inline schema; if content is $ref, convert first then add)
  const handleRequestBodyPropertyDrop = useCallback(async (
    contentId: string,
    propertyData: any,
    parentId?: string
  ) => {
    try {
      const actualProperty = propertyData.property || propertyData;
      const payload = {
        name: actualProperty.propertyName || actualProperty.name || 'newProperty',
        description: actualProperty.description,
        data: actualProperty.data || { type: 'string' },
      };

      let result = await addPropertyToInlineSchema(contentId, payload, parentId);
      let parsed = JSON.parse(result);

      if (!parsed.success && parsed.error?.includes('convert to inline schema first')) {
        await convertClassToInlineSchema(contentId);
        result = await addPropertyToInlineSchema(contentId, payload, parentId);
        parsed = JSON.parse(result);
      }

      if (parsed.success) {
        if (onRefresh) onRefresh();
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

  // Handle class drop on request body content type (replace $ref or add/copy into inline schema)
  const handleRequestBodyClassDrop = useCallback(async (
    contentId: string,
    classData: any,
    action: 'copy' | 'reference'
  ) => {
    const classId = classData.classId || classData.id;
    if (!classId) return;
    try {
      if (action === 'reference') {
        const result = await updateRequestBodyContentType(contentId, {
          classId,
          inlineSchema: null,
        });
        const parsed = JSON.parse(result);
        if (parsed.success) {
          if (onRefresh) onRefresh();
        } else {
          await alertDialog({ title: 'Error', message: parsed.error || 'Failed to set class reference', variant: 'error' });
        }
      } else {
        const result = await copyClassPropertiesToRequestBodyContentType(contentId, classId);
        const parsed = JSON.parse(result);
        if (parsed.success) {
          if (onRefresh) onRefresh();
        } else {
          await alertDialog({ title: 'Error', message: parsed.error || 'Failed to copy class properties', variant: 'error' });
        }
      }
    } catch (error) {
      console.error('Error handling class drop on request body:', error);
      await alertDialog({
        title: 'Error',
        message: error instanceof Error ? error.message : 'Failed to process class drop',
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

  // Detect synthetic content type IDs (e.g. response-<responseId>-application/json) and resolve to a real DB content id
  const resolveContentId = useCallback(async (contentId: string): Promise<string> => {
    const uuidOnly = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
    if (uuidOnly.test(contentId)) return contentId;
    const match = contentId.match(/^response-([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})-/i);
    if (!match) return contentId;
    const responseId = match[1];
    const createResult = await addResponseContentType(
      responseId,
      'application/json',
      undefined,
      { type: 'object', properties: [] },
      undefined
    );
    const parsed = JSON.parse(createResult);
    if (!parsed.success || !parsed.content?.id) throw new Error(parsed.error || 'Failed to create content type');
    return parsed.content.id;
  }, []);

  // Handle class drop on response body content type - supports copy or reference
  const handleResponseBodyClassDrop = useCallback(async (
    contentId: string,
    classData: any,
    action: 'copy' | 'reference'
  ) => {
    if (!classData.classId) return;

    try {
      const resolvedContentId = await resolveContentId(contentId);

      if (action === 'copy') {
        const result = await copyClassPropertiesToContentType(resolvedContentId, classData.classId);
        const parsed = JSON.parse(result);

        if (parsed.success) {
          await alertDialog({
            title: 'Properties Copied',
            message: `Copied ${parsed.copiedProperties} properties from class "${parsed.fromClass}" to the response schema.`,
            variant: 'success',
          });
          if (onRefresh) onRefresh();
        } else {
          await alertDialog({
            title: 'Error',
            message: parsed.error || 'Failed to copy class properties',
            variant: 'error',
          });
        }
      } else if (action === 'reference') {
        const result = await setResponseContentTypeClassReference(resolvedContentId, classData.classId);
        const parsed = JSON.parse(result);

        if (parsed.success) {
          await alertDialog({
            title: 'Class Reference Created',
            message: `Response now references class "${classData.className || 'class'}".`,
            variant: 'success',
          });
          if (onRefresh) onRefresh();
        } else {
          await alertDialog({
            title: 'Error',
            message: parsed.error || 'Failed to set class reference',
            variant: 'error',
          });
        }
      }
    } catch (error) {
      console.error('Error handling class drop on response content type:', error);
      await alertDialog({
        title: 'Error',
        message: error instanceof Error ? error.message : 'Failed to process class drop',
        variant: 'error',
      });
    }
  }, [alertDialog, onRefresh, resolveContentId]);

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

  // Handle creating content type with class - supports copy or reference
  const handleCreateContentTypeWithClass = useCallback(async (
    responseId: string,
    classData: any,
    action: 'copy' | 'reference'
  ) => {
    console.log('[PathsCanvasView] handleCreateContentTypeWithClass called');
    console.log('[PathsCanvasView] responseId:', responseId);
    console.log('[PathsCanvasView] classData:', classData);
    console.log('[PathsCanvasView] action:', action);

    if (!classData.classId) {
      console.error('[PathsCanvasView] No classId in classData');
      return;
    }

    try {
      if (action === 'reference') {
        // Create content type with class reference directly
        console.log('[PathsCanvasView] Creating content type with class reference:', responseId);
        const createResult = await addResponseContentType(
          responseId,
          'application/json',
          classData.classId, // set class_id for reference
          undefined, // no inline schema
          undefined // no examples
        );
        console.log('[PathsCanvasView] addResponseContentType result:', createResult);
        const createParsed = JSON.parse(createResult);

        if (createParsed.success) {
          await alertDialog({
            title: 'Class Reference Created',
            message: `Response now references class "${classData.className || 'class'}".`,
            variant: 'success',
          });

          if (onRefresh) {
            onRefresh();
          }
        } else {
          await alertDialog({
            title: 'Error',
            message: createParsed.error || 'Failed to create content type with class reference',
            variant: 'error',
          });
        }
      } else {
        // Copy class properties to inline schema
        console.log('[PathsCanvasView] Creating content type for response:', responseId);
        const createResult = await addResponseContentType(
          responseId,
          'application/json',
          undefined, // no class_id - we'll copy properties instead
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

        // Now copy class properties to the content type
        const copyResult = await copyClassPropertiesToContentType(contentId, classData.classId);
        console.log('[PathsCanvasView] copyClassPropertiesToContentType result:', copyResult);
        const copyParsed = JSON.parse(copyResult);

        if (copyParsed.success) {
          await alertDialog({
            title: 'Properties Copied',
            message: `Copied ${copyParsed.copiedProperties} properties from class "${copyParsed.fromClass}" to the response schema.`,
            variant: 'success',
          });

          if (onRefresh) {
            onRefresh();
          }
        } else {
          await alertDialog({
            title: 'Error',
            message: copyParsed.error || 'Failed to copy class properties',
            variant: 'error',
          });
        }
      }
    } catch (error) {
      console.error('Error creating content type with class:', error);
      await alertDialog({
        title: 'Error',
        message: 'Failed to create response schema from class',
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
  handleResponseBodyClassDropRef.current = handleResponseBodyClassDrop;
  handleCreateContentTypeWithPropertyRef.current = handleCreateContentTypeWithProperty;
  handleCreateContentTypeWithClassRef.current = handleCreateContentTypeWithClass;
  handleRequestBodyPropertyDropRef.current = handleRequestBodyPropertyDrop;
  handleRequestBodyPropertyDeleteRef.current = handleRequestBodyPropertyDelete;
  handleRequestBodyClassDropRef.current = handleRequestBodyClassDrop;

  // Stable wrapper functions that delegate to refs
  // These never change identity, so they won't cause node recreation
  const stableHandleResponseBodyPropertyDrop = useCallback((contentId: string, propertyData: any, parentId?: string) => {
    console.log('[stableHandleResponseBodyPropertyDrop] Called, delegating to ref');
    handleResponseBodyPropertyDropRef.current?.(contentId, propertyData, parentId);
  }, []);

  const stableHandleResponseBodyPropertyDelete = useCallback((contentId: string, propertyId: string) => {
    handleResponseBodyPropertyDeleteRef.current?.(contentId, propertyId);
  }, []);

  const stableHandleResponseBodyClassDrop = useCallback((contentId: string, classData: any, action: 'copy' | 'reference') => {
    console.log('[stableHandleResponseBodyClassDrop] Called, delegating to ref');
    handleResponseBodyClassDropRef.current?.(contentId, classData, action);
  }, []);

  const stableHandleCreateContentTypeWithProperty = useCallback((responseId: string, propertyData: any) => {
    console.log('[stableHandleCreateContentTypeWithProperty] Called, delegating to ref');
    handleCreateContentTypeWithPropertyRef.current?.(responseId, propertyData);
  }, []);

  const stableHandleCreateContentTypeWithClass = useCallback((responseId: string, classData: any, action: 'copy' | 'reference') => {
    console.log('[stableHandleCreateContentTypeWithClass] Called, delegating to ref');
    handleCreateContentTypeWithClassRef.current?.(responseId, classData, action);
  }, []);

  const stableHandleRequestBodyPropertyDrop = useCallback((contentId: string, propertyData: any, parentId?: string) => {
    handleRequestBodyPropertyDropRef.current?.(contentId, propertyData, parentId);
  }, []);

  const stableHandleRequestBodyPropertyDelete = useCallback((contentId: string, propertyId: string) => {
    handleRequestBodyPropertyDeleteRef.current?.(contentId, propertyId);
  }, []);

  const stableHandleRequestBodyClassDrop = useCallback((contentId: string, classData: any, action: 'copy' | 'reference') => {
    handleRequestBodyClassDropRef.current?.(contentId, classData, action);
  }, []);

  // Handler to show dialog asking user what action to take when dropping a class
  const handleShowClassDropDialog = useCallback((
    classData: any,
    onConfirm: (action: 'copy' | 'reference', options: ClassDropDialogOptions) => void,
    options?: { showArrayOption?: boolean }
  ) => {
    const className = classData.className || 'class';
    setClassDropDialogClassName(className);
    setClassDropDialogShowArrayOption(Boolean(options?.showArrayOption));
    setClassDropDialogAsArray(false);
    setClassDropDialogCallback(() => onConfirm);
    setClassDropDialogOpen(true);
  }, []);

  // Handle the choice from the class drop dialog
  const handleClassDropDialogChoice = useCallback((action: ClassDropAction) => {
    if (action !== 'cancel' && classDropDialogCallback) {
      classDropDialogCallback(action, { asArray: classDropDialogAsArray });
    }
    setClassDropDialogOpen(false);
    setClassDropDialogShowArrayOption(false);
    setClassDropDialogAsArray(false);
    setClassDropDialogCallback(null);
  }, [classDropDialogAsArray, classDropDialogCallback]);

  // Load operations and parameters when path is selected
  useEffect(() => {
    if (!selectedPathId) {
      setNodes([]);
      setEdges([]);
      setCanvasPersistReady(false);
      return;
    }

    setCanvasPersistReady(false);

    console.log('[PathsCanvasView] useEffect triggered - loading nodes. refreshKey:', refreshKey);

    const loadOperationsAndParameters = async () => {
      try {
        console.log('[PathsCanvasView] loadOperationsAndParameters starting...');
        const pathResponse = await getPathById(selectedPathId);
        const pathRow = JSON.parse(pathResponse);
        if (!pathRow?.id) {
          console.error('[PathsCanvasView] Path row missing for', selectedPathId);
          setCanvasPersistReady(false);
          return;
        }

        const pathNodeId = `path-node-${selectedPathId}`;
        const pathTemplateNode: Node = {
          id: pathNodeId,
          type: 'pathTemplate',
          position: { x: 120, y: 16 },
          deletable: false,
          data: {
            versionPathId: selectedPathId,
            versionId: selectedVersionId!,
            pathname: pathRow.pathname || '/',
            onPathnameSaved: (next: string) => {
              onPathnameUpdatedRef.current?.(next);
            },
          },
        };

        // Load operations
        const operationsResponse = await getOperationsForPath(selectedPathId);
        const operations = JSON.parse(operationsResponse);

        // First, load linked parameters and operationId for each operation to include in node data
        const operationParamsMap = new Map<string, Array<{ id: string; name: string; in: string; required?: boolean }>>();
        const operationIdMap = new Map<string, string>(); // Maps db operation id to OpenAPI operationId
        const operationSecurityMap = new Map<string, Array<Record<string, string[]>>>();
        const operationDeprecatedMap = new Map<string, boolean>();
        const operationPrivateMap = new Map<string, boolean>();

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

          // Load operation description to get operationId, security, deprecated, x-private
          try {
            const descResponse = await getOperationDescription(op.id);
            const descData = JSON.parse(descResponse);
            if (descData) {
              if (descData.operation_id) {
                operationIdMap.set(op.id, descData.operation_id);
              }
              const meta = descData.metadata;
              const sec = meta?.security;
              // Pass security when defined: [] = unsecured (public), non-empty = requirements
              if (Array.isArray(sec)) {
                operationSecurityMap.set(op.id, sec);
              }
              if (meta?.deprecated === true) {
                operationDeprecatedMap.set(op.id, true);
              }
              if (meta?.['x-private'] === true || meta?.x_private === true || descData.x_private === true) {
                operationPrivateMap.set(op.id, true);
              }
            }
          } catch {
            // No description found for this operation
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
              y: 220,
            },
          data: {
            operation: op.operation,
            color: OPERATION_COLORS[op.operation] || '#64748b',
            dbOperationId: op.id,
            versionPathId: selectedPathId,
            operationId: operationIdMap.get(op.id), // OpenAPI operationId from description
            parameters: operationParamsMap.get(op.id) || [],
            security: operationSecurityMap.get(op.id),
            deprecated: operationDeprecatedMap.get(op.id),
            xPrivate: operationPrivateMap.get(op.id),
            onDelete: () => handleDeleteOperation(op.id, op.operation),
            onSchemaDrop: async (operationId: string, schemaType: 'request' | 'response', schemaData: any) => {
              // Handle class drops with dialog for copy vs reference
              if (schemaData.type === 'class') {
                handleShowClassDropDialog(
                  { className: schemaData.name || schemaData.className || 'class', classId: schemaData.id || schemaData.classId },
                  async (action: 'copy' | 'reference', dialogOptions: ClassDropDialogOptions) => {
                    if (schemaType === 'request') {
                      // Handle request body creation with class
                      try {
                        // Create request body with a default name
                        const rbResult = await createSharedPathRequestBody(
                          selectedPathId!,
                          `${op.operation} Request Body`
                        );
                        const rbParsed = JSON.parse(rbResult);
                        if (rbParsed.success && rbParsed.requestBody) {
                          const rbId = rbParsed.requestBody.id;
                          
                          // Add content type with class reference or copy
                          const contentResult = await addRequestBodyContentType(
                            rbId,
                            'application/json',
                            action === 'reference' ? schemaData.id || schemaData.classId : undefined,
                            action === 'copy' ? { type: 'object', properties: [] } : undefined
                          );
                          const contentParsed = JSON.parse(contentResult);
                          
                          if (action === 'copy' && contentParsed.success && contentParsed.content) {
                            // For copy: first set class_id, then convert to inline schema
                            const classId = schemaData.id || schemaData.classId;
                            if (classId) {
                              // Update content to have class_id first
                              await updateRequestBodyContentType(contentParsed.content.id, { classId });
                              // Then convert to inline schema
                              await convertClassToInlineSchema(contentParsed.content.id);
                            }
                          }
                          
                          // Link request body to operation
                          await linkRequestBodyToOperation(operationId, rbId);
                          
                          if (onRefresh) onRefresh();
                        }
                      } catch (error) {
                        console.error('Error creating request body:', error);
                        await alertDialog({
                          title: 'Error',
                          message: 'Failed to create request body with schema',
                          variant: 'error',
                        });
                      }
                    } else {
                      // Handle response creation with class
                      try {
                        const classId = schemaData.id || schemaData.classId;
                        const linkAsArray = dialogOptions.asArray;
                        if (!classId) {
                          await alertDialog({
                            title: 'Error',
                            message: 'Missing class id for response schema drop.',
                            variant: 'error',
                          });
                          return;
                        }

                        // Find or create 200 response for this operation
                        const responsesResult = await getLinkedResponsesForOperation(operationId);
                        const responsesParsed = JSON.parse(responsesResult);

                        if (!responsesParsed.success) {
                          await alertDialog({
                            title: 'Error',
                            message: responsesParsed.error || 'Failed to load operation responses',
                            variant: 'error',
                          });
                          return;
                        }

                        let targetResponseId: string | null = responsesParsed.responses?.[0]?.id ?? null;
                        if (!targetResponseId) {
                          const createResult = await createSharedPathResponse(
                            selectedPathId!,
                            '200',
                            'Successful response',
                            { type: 'object', properties: [] }
                          );
                          const createParsed = JSON.parse(createResult);
                          if (!createParsed.success || !createParsed.response?.id) {
                            await alertDialog({
                              title: 'Error',
                              message: createParsed.error || 'Failed to create response',
                              variant: 'error',
                            });
                            return;
                          }
                          const createdResponseId = String(createParsed.response.id);
                          targetResponseId = createdResponseId;

                          const linkResult = await linkResponseToOperation(operationId, createdResponseId);
                          const linkParsed = JSON.parse(linkResult);
                          if (!linkParsed.success) {
                            await alertDialog({
                              title: 'Error',
                              message: linkParsed.error || 'Failed to link response to operation',
                              variant: 'error',
                            });
                            return;
                          }
                        }

                        if (!targetResponseId) {
                          await alertDialog({
                            title: 'Error',
                            message: 'Failed to resolve response id for operation.',
                            variant: 'error',
                          });
                          return;
                        }

                        if (linkAsArray && action === 'reference') {
                          const classNameForRef = schemaData.name || schemaData.className || 'Unknown';
                          const setArrayRefResult = await updateSharedPathResponse(targetResponseId, {
                            schemaMode: 'array',
                            classId: null,
                            inlineSchema: null,
                            data: { type: 'array', items: { $ref: `#/components/schemas/${classNameForRef}` } },
                          });
                          const setArrayRefParsed = JSON.parse(setArrayRefResult);
                          if (!setArrayRefParsed.success) {
                            await alertDialog({
                              title: 'Error',
                              message: setArrayRefParsed.error || 'Failed to set array response reference',
                              variant: 'error',
                            });
                            return;
                          }
                        } else {
                          const contentResult = await addResponseContentType(
                            targetResponseId,
                            'application/json',
                            action === 'reference' ? classId : undefined,
                            action === 'copy' ? { type: 'object', properties: [] } : undefined
                          );
                          const contentParsed = JSON.parse(contentResult);
                          if (!contentParsed.success || !contentParsed.content?.id) {
                            await alertDialog({
                              title: 'Error',
                              message: contentParsed.error || 'Failed to add response content type',
                              variant: 'error',
                            });
                            return;
                          }

                          if (action === 'copy') {
                            const copyResult = await copyClassPropertiesToContentType(contentParsed.content.id, classId);
                            const copyParsed = JSON.parse(copyResult);
                            if (!copyParsed.success) {
                              await alertDialog({
                                title: 'Error',
                                message: copyParsed.error || 'Failed to copy class properties',
                                variant: 'error',
                              });
                              return;
                            }
                          }
                        }

                        if (onRefresh) onRefresh();
                      } catch (error) {
                        console.error('Error adding class to response:', error);
                        await alertDialog({
                          title: 'Error',
                          message: 'Failed to add class to response',
                          variant: 'error',
                        });
                      }
                    }
                  },
                  schemaType === 'response' ? { showArrayOption: true } : undefined
                );
              } else if (schemaData.type === 'property') {
                // Handle property drop: create a request/response node that matches this property
                const prop = schemaData.property || schemaData;
                const name = prop.propertyName || prop.name || 'newProperty';
                const description = prop.description;
                const data = prop.data || { type: 'string' };

                if (schemaType === 'request') {
                  try {
                    const rbResult = await createSharedPathRequestBody(
                      selectedPathId!,
                      `${op.operation} Request Body`
                    );
                    const rbParsed = JSON.parse(rbResult);
                    if (!rbParsed.success || !rbParsed.requestBody) {
                      await alertDialog({
                        title: 'Error',
                        message: rbParsed.error || 'Failed to create request body',
                        variant: 'error',
                      });
                      return;
                    }
                    const rbId = rbParsed.requestBody.id;
                    const contentResult = await addRequestBodyContentType(
                      rbId,
                      'application/json',
                      undefined,
                      { type: 'object', properties: [] }
                    );
                    const contentParsed = JSON.parse(contentResult);
                    if (!contentParsed.success || !contentParsed.content) {
                      await alertDialog({
                        title: 'Error',
                        message: contentParsed.error || 'Failed to add content type',
                        variant: 'error',
                      });
                      return;
                    }
                    const addPropResult = await addPropertyToInlineSchema(
                      contentParsed.content.id,
                      { name, description, data },
                      undefined
                    );
                    const addPropParsed = JSON.parse(addPropResult);
                    if (!addPropParsed.success) {
                      await alertDialog({
                        title: 'Error',
                        message: addPropParsed.error || 'Failed to add property',
                        variant: 'error',
                      });
                      return;
                    }
                    await linkRequestBodyToOperation(operationId, rbId);
                    if (onRefresh) onRefresh();
                  } catch (error) {
                    console.error('Error creating request body from property:', error);
                    await alertDialog({
                      title: 'Error',
                      message: 'Failed to create request body with property',
                      variant: 'error',
                    });
                  }
                } else {
                  // Response: open panel and prompt to configure (existing behavior for response property drop)
                  onOperationSelect({ id: operationId, operation: op.operation });
                  await alertDialog({
                    title: 'Property on Response',
                    message: 'Please add or select a response and configure the property in the Response Properties panel.',
                    variant: 'info',
                  });
                }
              }
            },
          },
          };
        });

        // Load ALL shared parameters for this path (not just linked ones)
        const allParamsResponse = await getSharedPathParameters(selectedPathId);
        const allParamsData = JSON.parse(allParamsResponse);

        const allParameterNodes: Node[] = [];
        const pathToOpEdges: Edge[] = (operations as { id: string }[]).map((op) => {
          const edgeType = edgeRouting === 'straight' ? 'straight'
            : edgeRouting === 'bezier' ? 'default'
            : edgeRouting === 'smart' ? 'smart'
            : 'smoothstep';
          const pathToOperationLabel = labelPathToOperation();
          return {
            id: `edge-path-op-${selectedPathId}-${op.id}`,
            source: pathNodeId,
            sourceHandle: 'path-output',
            target: op.id,
            targetHandle: 'operation-input',
            type: edgeType,
            animated: edgeAnimation !== 'none',
            ...(pathToOperationLabel
              ? {
                  label: pathToOperationLabel,
                  labelStyle: pathsCanvasEdgeLabelStyle,
                  labelBgStyle: pathsCanvasEdgeLabelBgStyle,
                }
              : {}),
            style: {
              stroke: edgeStyling.directColor,
              strokeWidth: 2,
              strokeDasharray: edgeAnimation === 'dash' ? '5,5' : undefined,
            },
            data: {
              sourceNodeId: pathNodeId,
              targetNodeId: op.id,
              semantic: 'path-has-operation' as const,
            },
          };
        });
        const allEdges: Edge[] = [...pathToOpEdges];

        if (allParamsData.success && allParamsData.parameters) {
          // Create nodes for all parameters - positioned BELOW operations
          allParamsData.parameters.forEach((param: any, paramIndex: number) => {
            const paramNodeId = `param-${param.id}`;
            const paramData = typeof param.data === 'string' ? (JSON.parse(param.data) || {}) : (param.data || {});

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
                style: normalizeStyleForLocation(
                  param.in_location as 'path' | 'query' | 'header' | 'cookie',
                  paramData.style as string | undefined
                ),
                explode: paramData.explode === true,
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
                label: labelOperationToParameter(),
                labelStyle: pathsCanvasEdgeLabelStyle,
                labelBgStyle: pathsCanvasEdgeLabelBgStyle,
                style: {
                  stroke: edgeStyling.directColor,
                  strokeWidth: 2,
                  strokeDasharray: edgeAnimation === 'dash' ? '5,5' : undefined,
                },
                data: {
                  sourceNodeId: op.id,
                  targetNodeId: paramNodeId,
                  semantic: 'operation-has-parameter' as const,
                },
              });
            });
          }
        }

        // Load classes for this version (names for nodes + properties for $ref read-only display)
        let classesMap = new Map<string, { id: string; name: string; description?: string }>();
        const classesWithPropertiesMap = new Map<string, { name: string; properties: any[] }>();
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
              const rootProps = (cls.properties || []).filter((p: any) => !p.parent_id);
              classesWithPropertiesMap.set(cls.id, { name: cls.name, properties: rootProps });
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

            // Parse response headers and links from data (OpenAPI: headers/links are maps)
            let headers: Array<{ name: string; description?: string; schema?: { type?: string; format?: string } }> | undefined;
            let links: Array<{ name: string; operationId?: string; operationRef?: string; description?: string; parameters?: Record<string, string> }> | undefined;
            if (response.data) {
              try {
                const data = typeof response.data === 'string' ? JSON.parse(response.data) : response.data;
                if (data.headers && typeof data.headers === 'object' && !Array.isArray(data.headers)) {
                  headers = Object.entries(data.headers).map(([name, def]: [string, any]) => ({
                    name,
                    description: def?.description,
                    schema: def?.schema && typeof def.schema === 'object' ? { type: def.schema.type, format: def.schema.format } : undefined,
                  }));
                }
                if (data.links && typeof data.links === 'object' && !Array.isArray(data.links)) {
                  links = Object.entries(data.links).map(([name, link]: [string, any]) => ({
                    name,
                    operationId: link?.operationId,
                    operationRef: link?.operationRef,
                    description: link?.description,
                    parameters: link?.parameters && typeof link.parameters === 'object' ? link.parameters : undefined,
                  }));
                }
              } catch {
                // ignore
              }
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
                headers,
                links,
                linkedOperations: responseLinkedOpsMap.get(response.id) || [],
                onDelete: () => handleDeleteSharedResponse(response.id, response.status_code),
                onUnlink: (operationId: string) => {
                  const linkedOp = responseLinkedOpsMap.get(response.id)?.find(op => op.id === operationId);
                  handleUnlinkResponse(response.id, operationId, linkedOp?.operation);
                },
                onClassDrop: (responseId: string, classData: any) => {
                  handleShowClassDropDialog(classData, (action) => {
                    handleClassDropOnResponse(responseId, classData, action);
                  });
                },
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
                  deletable: false,
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
            // Get content types for this response (include class properties for $ref read-only display)
            const contentTypes = (response.content_types || []).map((ct: any) => {
              const classInfo = ct.class_id ? classesWithPropertiesMap.get(ct.class_id) : undefined;
              return {
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
                classProperties: classInfo?.properties,
              };
            });

            // Check if response itself has an object schema (from inline_schema column)
            // Response Properties panel saves object schema to response.inline_schema; ensure the node shows it
            let responseInlineSchema = null;
            if (response.inline_schema) {
              try {
                responseInlineSchema = typeof response.inline_schema === 'string'
                  ? JSON.parse(response.inline_schema)
                  : response.inline_schema;
              } catch {
                // Ignore parse errors
              }
            }

            const hasResponseLevelObjectSchema =
              responseInlineSchema?.type === 'object' &&
              Array.isArray(responseInlineSchema?.properties) &&
              responseInlineSchema.properties.length > 0;

            // Use response-level inline_schema so the node shows the same schema as Response Properties panel
            let contentTypesForNode = contentTypes;
            if (hasResponseLevelObjectSchema) {
              if (contentTypesForNode.length === 0) {
                contentTypesForNode = [{
                  id: `response-${response.id}-application/json`,
                  media_type: 'application/json',
                  class_id: null,
                  class_name: null,
                  inline_schema: responseInlineSchema,
                  examples: null,
                }];
              } else {
                const firstHasProps = Array.isArray(contentTypesForNode[0].inline_schema?.properties) &&
                  contentTypesForNode[0].inline_schema.properties.length > 0;
                if (!firstHasProps) {
                  contentTypesForNode = contentTypesForNode.map((ct: any, i: number) =>
                    i === 0 ? { ...ct, inline_schema: responseInlineSchema } : ct
                  );
                }
              }
            }
            // When response is $ref (schema_mode class) but has no content types, show one synthetic content type so the body node displays $ref + read-only properties
            if (contentTypesForNode.length === 0 && response.schema_mode === 'class' && response.class_id) {
              const classInfo = classesWithPropertiesMap.get(response.class_id);
              contentTypesForNode = [{
                id: `response-${response.id}-application/json-ref`,
                media_type: 'application/json',
                class_id: response.class_id,
                class_name: response.class_name,
                inline_schema: null,
                examples: null,
                classProperties: classInfo?.properties,
              }];
            }

            // Create response body node if:
            // 1. There are content types with object schemas or class references
            // 2. OR the response itself has an object type schema
            const hasContentTypeWithObjectSchema = contentTypesForNode.some((ct: any) =>
              ct.inline_schema?.type === 'object' || ct.class_id
            );
            const hasResponseObjectSchema = responseInlineSchema?.type === 'object';

            if (contentTypesForNode.length > 0 || hasContentTypeWithObjectSchema || hasResponseObjectSchema) {
              const responseBodyNodeId = `response-body-${response.id}`;
              allResponseBodyNodes.push({
                id: responseBodyNodeId,
                type: 'responseBody',
                deletable: false,
                position: {
                  x: 400 + (responseIndex * 300), // Offset to the right of response nodes
                  y: 550 + (responseIndex * 50), // Slightly below and staggered
                },
                data: {
                  id: response.id,
                  status_code: response.status_code,
                  description: response.description,
                  contentTypes: contentTypesForNode,
                  onDelete: () => handleDeleteSharedResponse(response.id, response.status_code),
                  onPropertyDrop: stableHandleResponseBodyPropertyDrop,
                  onClassDrop: stableHandleResponseBodyClassDrop,
                  onPropertyDelete: stableHandleResponseBodyPropertyDelete,
                  onCreateContentTypeWithProperty: stableHandleCreateContentTypeWithProperty,
                  onCreateContentTypeWithClass: stableHandleCreateContentTypeWithClass,
                  onShowClassDropDialog: handleShowClassDropDialog,
                } as PathResponseBodyData,
              });
            }
          });
        }

        // Helper: content types with schema binding -> short label for edge (e.g. "application/json" or "application/json, application/xml")
        const getContentTypeEdgeLabel = (contentTypes: Array<{ media_type?: string; class_id?: string | null; inline_schema?: any }> | undefined): string | undefined => {
          if (!contentTypes?.length) return undefined;
          const withSchema = contentTypes.filter((ct: any) =>
            ct.class_id || (ct.inline_schema && (ct.inline_schema.type || ct.inline_schema.$ref || (Array.isArray(ct.inline_schema?.properties) && ct.inline_schema.properties.length > 0)))
          );
          if (withSchema.length === 0) return undefined;
          const mediaTypes = withSchema.map((ct: any) => ct.media_type).filter(Boolean);
          if (mediaTypes.length === 0) return undefined;
          if (mediaTypes.length === 1) return mediaTypes[0];
          if (mediaTypes.length === 2) return `${mediaTypes[0]}, ${mediaTypes[1]}`;
          return `${mediaTypes[0]}, +${mediaTypes.length - 1}`;
        };

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

            const bodyContentTypes = (responseBodyNode.data as any).contentTypes;
            const contentTypeLabel = getContentTypeEdgeLabel(bodyContentTypes);

            allEdges.push({
              id: `edge-resp-body-${responseId}`,
              source: responseNodeId,
              sourceHandle: 'response-class-output', // Use existing output handle
              target: responseBodyNode.id,
              targetHandle: 'response-input', // PathResponseBodyNode uses this
              type: edgeType,
              animated: edgeAnimation !== 'none',
              label: contentTypeLabel || 'body',
              labelStyle: { fontSize: 10, fill: '#1e40af' },
              labelBgStyle: { fill: '#dbeafe', stroke: '#60a5fa' },
              style: {
                stroke: '#60a5fa', // Blue for response-to-body edges
                strokeWidth: 2,
                strokeDasharray: edgeAnimation === 'dash' ? '5,5' : undefined,
              },
              data: { semantic: 'response-has-body' as const },
            });
          }
        });

        // Create edges from operations to responses using the already-collected linked operations
        responseLinkedOpsMap.forEach((linkedOps, responseId) => {
          const responseNodeId = `response-${responseId}`;
          const responseNode = allResponseNodes.find((n) => n.id === responseNodeId);
          const responseContentTypes = (responseNode?.data as any)?.contentTypes;
          const contentTypeLabel = getContentTypeEdgeLabel(responseContentTypes);
          const statusCode = String((responseNode?.data as { statusCode?: string })?.statusCode ?? '').trim() || '?';

          linkedOps.forEach((op) => {
            console.log('[PathsCanvasView] Creating edge from', op.id, 'to', responseNodeId);

            // Create edge from operation to response (label = content types with schema bindings)
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
              label: labelOperationToResponse(statusCode, contentTypeLabel),
              labelStyle: pathsCanvasEdgeLabelStyle,
              labelBgStyle: pathsCanvasEdgeLabelBgStyle,
              style: {
                stroke: '#a78bfa',
                strokeWidth: 2,
                strokeDasharray: edgeAnimation === 'dash' ? '5,5' : undefined,
              },
              data: {
                sourceNodeId: op.id,
                targetNodeId: responseNodeId,
                semantic: 'operation-has-response' as const,
              },
            });
          });
        });

        // Create edges from response nodes to class nodes
        // Make sure we create edges for ALL responses that have the same class
        allResponseNodes.forEach((responseNode) => {
          const responseData = responseNode.data as any;
          if (responseData.attachedClassId) {
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
                    semantic: 'response-has-class' as const,
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

            // Parse content types (include classProperties for $ref read-only display)
            const contentTypes = (rb.content_types || []).map((ct: any) => {
              const classInfo = ct.class_id ? classesWithPropertiesMap.get(ct.class_id) : undefined;
              return {
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
                classProperties: classInfo?.properties,
              };
            });

            allRequestBodyNodes.push({
              id: requestBodyNodeId,
              type: 'requestBody',
              deletable: false,
              position: {
                x: -200,
                y: 50 + rbIndex * 280,
              },
              data: {
                id: rb.id,
                name: rb.name,
                description: rb.description,
                required: rb.required,
                contentTypes: contentTypes,
                onDelete: () => handleDeleteRequestBody(rb.id, rb.name),
                onAddContentType: (mediaType: string) => handleAddRequestBodyContentType(rb.id, mediaType),
                onDescriptionChange: (description: string) => handleUpdateRequestBodyDescription(rb.id, description),
                onExamplesChange: (contentId: string, examples: Array<{ summary?: string; value: unknown }>) =>
                  handleUpdateRequestBodyExamples(contentId, examples),
                onEncodingChange: (contentId: string, encoding: Record<string, Record<string, unknown>> | null) =>
                  handleUpdateRequestBodyEncoding(contentId, encoding),
                onPropertyDrop: stableHandleRequestBodyPropertyDrop,
                onClassDrop: stableHandleRequestBodyClassDrop,
                onPropertyDelete: stableHandleRequestBodyPropertyDelete,
                onShowClassDropDialog: handleShowClassDropDialog,
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
            const rbContentTypes = linkedRbData.requestBody.content_types || [];
            const contentTypeLabel = getContentTypeEdgeLabel(rbContentTypes);

            const edgeType = edgeRouting === 'straight' ? 'straight'
              : edgeRouting === 'bezier' ? 'default'
              : edgeRouting === 'smart' ? 'smart'
              : 'smoothstep';

            allEdges.push({
              id: `edge-rb-op-${linkedRbData.requestBody.id}-${op.id}`,
              source: op.id,
              sourceHandle: 'operation-output',
              target: rbNodeId,
              targetHandle: 'request-body-input',
              type: edgeType,
              animated: edgeAnimation !== 'none',
              label: labelOperationToRequestBody(contentTypeLabel),
              labelStyle: pathsCanvasEdgeLabelStyle,
              labelBgStyle: pathsCanvasEdgeLabelBgStyle,
              style: {
                stroke: '#8b5cf6',
                strokeWidth: 2,
                strokeDasharray: edgeAnimation === 'dash' ? '5,5' : undefined,
              },
              data: {
                sourceNodeId: op.id,
                targetNodeId: rbNodeId,
                semantic: 'operation-has-request-body' as const,
              },
            });
          }
        }

        // Response body nodes are created for responses that have content types with inline schemas
        // These allow users to add/edit properties in the inline schema

        const computedNodes = [
          pathTemplateNode,
          ...operationNodes,
          ...allParameterNodes,
          ...allResponseNodes,
          ...allResponseBodyNodes,
          ...allClassNodes,
          ...allRequestBodyNodes,
        ];

        let blob: PathsCanvasBlob | null = null;
        let canvasUpdatedAt: string | null | undefined;
        if (selectedVersionId && selectedPathId) {
          const canvasRes = await getPathCanvas(selectedVersionId, selectedPathId);
          if (canvasRes.success && canvasRes.data) {
            canvasUpdatedAt = canvasRes.data.updated_at;
            blob = {
              nodes: (canvasRes.data.nodes || []) as Record<string, unknown>[],
              edges: (canvasRes.data.edges || []) as Record<string, unknown>[],
              viewport: canvasRes.data.viewport || { x: 0, y: 0, zoom: 1 },
            };
          }
        }

        const noSavedNodeLayout = !blob?.nodes?.length || blob.nodes.length === 0;
        const noSavedCanvas =
          canvasUpdatedAt == null &&
          (!blob?.nodes?.length || blob.nodes.length === 0);

        // No persisted node positions: Sugiyama-style top-down layers (path → ops → params / responses /
        // request bodies → bodies / classes). Avoids legacy hard-coded coords (e.g. request bodies at x < 0).
        const nodesForPersistMerge =
          noSavedNodeLayout && computedNodes.length > 0
            ? applyAutoLayout(computedNodes, allEdges, PATHS_CANVAS_AUTO_LAYOUT_OPTIONS)
            : computedNodes;

        const merged = mergePathsCanvasLayout(nodesForPersistMerge, allEdges, blob);
        viewportToApplyRef.current = noSavedCanvas ? null : merged.viewport;
        shouldFitAfterLoadRef.current = noSavedCanvas;

        setNodes(merged.nodes);
        setEdges(merged.edges);
        setCanvasPersistReady(true);
      } catch (error) {
        console.error('Error loading operations and parameters:', error);
        setCanvasPersistReady(false);
      }
    };

    loadOperationsAndParameters();
  }, [selectedPathId, selectedVersionId, setNodes, setEdges, refreshKey, edgeRouting, edgeAnimation, edgeStyling, handleDeleteOperation, handleDeleteParameter, handleDeleteResponse, handleDeleteSharedResponse, handleUnlinkResponse, handleClassDropOnResponse, handlePropertyDropOnResponse, handleClassUnlinkFromResponse, handleSchemaTypeChange, handleDeleteRequestBody, handleAddRequestBodyContentType, handleUpdateRequestBodyDescription, handleUpdateRequestBodyExamples, handleUpdateRequestBodyEncoding, stableHandleRequestBodyPropertyDrop, stableHandleRequestBodyPropertyDelete, stableHandleRequestBodyClassDrop, stableHandleResponseBodyPropertyDrop, stableHandleResponseBodyPropertyDelete, stableHandleResponseBodyClassDrop, stableHandleCreateContentTypeWithProperty, stableHandleCreateContentTypeWithClass, handleShowClassDropDialog]);

  // Apply persisted viewport or initial fitView once after graph load (#2642).
  useEffect(() => {
    if (!canvasPersistReady || !selectedPathId) return;

    const t = window.setTimeout(() => {
      if (viewportToApplyRef.current) {
        setViewport(viewportToApplyRef.current, { duration: 0 });
        viewportToApplyRef.current = null;
      } else if (shouldFitAfterLoadRef.current) {
        shouldFitAfterLoadRef.current = false;
        fitView({ padding: 0.2 });
      }
    }, 0);

    return () => clearTimeout(t);
  }, [canvasPersistReady, selectedPathId, setViewport, fitView]);

  const schedulePersistPathsCanvas = useCallback(() => {
    if (!canvasPersistReady || !selectedVersionId || !selectedPathId) return;
    if (canvasSaveTimerRef.current) {
      clearTimeout(canvasSaveTimerRef.current);
    }
    canvasSaveTimerRef.current = setTimeout(() => {
      canvasSaveTimerRef.current = null;
      const vp = getViewport();
      const payload = serializePathsCanvas(nodes, edges, vp);
      const p = putPathCanvas(selectedVersionId, selectedPathId, payload);
      saveInFlightRef.current = p;
      p.finally(() => {
        if (saveInFlightRef.current === p) saveInFlightRef.current = null;
      });
    }, 650);
  }, [canvasPersistReady, selectedVersionId, selectedPathId, getViewport, nodes, edges]);

  const handlePathsCanvasAutoLayout = useCallback(() => {
    if (!canvasPersistReady || nodes.length === 0) return;
    const nextNodes = applyAutoLayout(nodes, edges, PATHS_CANVAS_AUTO_LAYOUT_OPTIONS);
    setNodes(nextNodes);
    window.requestAnimationFrame(() => {
      fitView({ padding: 0.2, duration: 240 });
    });
  }, [canvasPersistReady, nodes, edges, setNodes, fitView]);

  const flushPathsCanvasNow = useCallback(async () => {
    if (!canvasPersistReady || !selectedVersionId || !selectedPathId) return;
    if (canvasSaveTimerRef.current) {
      clearTimeout(canvasSaveTimerRef.current);
      canvasSaveTimerRef.current = null;
    }
    // Wait for any in-flight save to finish before sending the flush so an older
    // request cannot overwrite the newer layout after us (last-write-wins API).
    if (saveInFlightRef.current) {
      await saveInFlightRef.current.catch(() => {/* ignore prior-save errors */});
    }
    const vp = getViewport();
    const payload = serializePathsCanvas(nodes, edges, vp);
    const res = await putPathCanvas(selectedVersionId, selectedPathId, payload);
    if (!res.success) {
      throw new Error(res.error || 'Failed to save canvas layout');
    }
  }, [canvasPersistReady, selectedVersionId, selectedPathId, getViewport, nodes, edges]);

  useEffect(() => {
    registerPathsCanvasFlush(flushPathsCanvasNow);
    return () => {
      registerPathsCanvasFlush(null);
    };
  }, [registerPathsCanvasFlush, flushPathsCanvasNow]);

  useEffect(() => {
    schedulePersistPathsCanvas();
    return () => {
      if (canvasSaveTimerRef.current) {
        clearTimeout(canvasSaveTimerRef.current);
      }
    };
  }, [schedulePersistPathsCanvas]);

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

  /** Smart alignment guides — same behavior categories as Designer; math in smart-alignment-guides.ts (#2641). */
  const handlePathsNodeDrag = useCallback(
    (_event: React.MouseEvent, node: Node) => {
      if (!smartGuidesEnabled) {
        setAlignmentGuides({ horizontal: [], vertical: [] });
        return;
      }
      setAlignmentGuides(computeAlignmentGuidesForNode(node, nodes));
    },
    [smartGuidesEnabled, nodes]
  );

  const handlePathsNodeDragStop = useCallback(() => {
    setAlignmentGuides({ horizontal: [], vertical: [] });
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

        // VALIDATION: Prevent invalid connections to auxiliary schema nodes (not status / request body cards)
        if (sourceNode?.type === 'operation' && targetNode?.type === 'responseBody') {
          await alertDialog({
            title: 'Invalid Connection',
            message: 'Operations can only connect to Response status codes (200, 404, etc.), not to schema nodes. The response node contains the schema reference.',
            variant: 'warning',
          });
          return;
        }

        if (targetNode?.type === 'operation' && sourceNode?.type === 'responseBody') {
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

        // Prevent connecting request body to non-POST/PUT/PATCH operations
        if (sourceNode?.type === 'requestBody' || targetNode?.type === 'requestBody') {
          const operationNode = sourceNode?.type === 'operation' ? sourceNode
            : targetNode?.type === 'operation' ? targetNode
            : undefined;
          // operationNode is always defined here because the guards above ensured the other
          // node is an operation; this explicit check makes it unambiguous.
          if (!operationNode) return;
          const method = ((operationNode.data as any)?.operation as string | undefined)?.toUpperCase();
          if (!method || !['POST', 'PUT', 'PATCH'].includes(method)) {
            await alertDialog({
              title: 'Invalid Connection',
              message: 'Request bodies can only be linked to POST, PUT, or PATCH operations.',
              variant: 'warning',
            });
            return;
          }
        }

        // Class <-> Response: show copy vs $ref dialog only; do not add an edge (schema is bound to response)
        if (
          (sourceNode?.type === 'class' && targetNode?.type === 'response') ||
          (sourceNode?.type === 'response' && targetNode?.type === 'class')
        ) {
          const responseNode = sourceNode?.type === 'response' ? sourceNode : targetNode;
          const classNode = sourceNode?.type === 'class' ? sourceNode : targetNode;
          const respId = (responseNode?.data as any)?.dbResponseId;
          const classId = (classNode?.data as any)?.dbClassId;
          const className = (classNode?.data as any)?.className;
          if (respId && classId) {
            const classData = { classId, className: className || 'Unknown', type: 'class' };
            handleShowClassDropDialog(classData, (action) => {
              handleClassDropOnResponse(respId, classData, action);
            });
          }
          return;
        }
      }

      // Get edge type based on settings
      const edgeType = edgeRouting === 'straight' ? 'straight'
        : edgeRouting === 'bezier' ? 'default'
        : edgeRouting === 'smart' ? 'smart'
        : 'smoothstep';

      const sourceNodeForEdge = nodes.find((n) => n.id === connection.source);
      const targetNodeForEdge = nodes.find((n) => n.id === connection.target);
      const manualLabel = labelForManualConnection(sourceNodeForEdge, targetNodeForEdge);

      // Derive a stable edge id matching the computed topology so that saved-only duplicates
      // don't appear after a page reload (mergePathsCanvasLayout skips edges whose id already
      // exists in the computed set).
      let stableEdgeId: string | undefined;
      {
        const src = sourceNodeForEdge;
        const tgt = targetNodeForEdge;
        if (src?.type === 'operation' && tgt?.type === 'parameter') {
          stableEdgeId = `edge-${(src.data as any)?.dbOperationId}-${(tgt.data as any)?.dbParameterId}`;
        } else if (src?.type === 'parameter' && tgt?.type === 'operation') {
          stableEdgeId = `edge-${(tgt.data as any)?.dbOperationId}-${(src.data as any)?.dbParameterId}`;
        } else if (src?.type === 'operation' && tgt?.type === 'response') {
          stableEdgeId = `edge-op-resp-${(src.data as any)?.dbOperationId}-${(tgt.data as any)?.dbResponseId}`;
        } else if (src?.type === 'response' && tgt?.type === 'operation') {
          stableEdgeId = `edge-op-resp-${(tgt.data as any)?.dbOperationId}-${(src.data as any)?.dbResponseId}`;
        } else if (src?.type === 'operation' && tgt?.type === 'requestBody') {
          // Always requestBody id first, then operation id — matches computed topology
          stableEdgeId = `edge-rb-op-${(tgt.data as any)?.id}-${(src.data as any)?.dbOperationId}`;
        } else if (src?.type === 'requestBody' && tgt?.type === 'operation') {
          // Always requestBody id first, then operation id — matches computed topology
          stableEdgeId = `edge-rb-op-${(src.data as any)?.id}-${(tgt.data as any)?.dbOperationId}`;
        }
      }

      // Add edge to UI first
      setEdges((eds) => addEdge({
        ...connection,
        ...(stableEdgeId ? { id: stableEdgeId } : {}),
        type: edgeType,
        animated: edgeAnimation !== 'none',
        ...(manualLabel?.label
          ? {
              label: manualLabel.label,
              labelStyle: pathsCanvasEdgeLabelStyle,
              labelBgStyle: pathsCanvasEdgeLabelBgStyle,
            }
          : {}),
        style: {
          stroke: edgeStyling.directColor,
          strokeWidth: 2,
          strokeDasharray: edgeAnimation === 'dash' ? '5,5' : undefined,
        },
        data: {
          sourceNodeId: connection.source,
          targetNodeId: connection.target,
          ...(manualLabel ? { semantic: manualLabel.semantic } : {}),
        },
      }, eds));

      // Save link to database if connecting an operation to a parameter, response, or request body (either direction)
      if (connection.source && connection.target) {
        const sourceNode = sourceNodeForEdge;
        const targetNode = targetNodeForEdge;


        let operationId: string | undefined;
        let parameterId: string | undefined;
        let responseId: string | undefined;
        let requestBodyId: string | undefined;

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
        } else if (sourceNode?.type === 'operation' && targetNode?.type === 'requestBody') {
          operationId = (sourceNode.data as any)?.dbOperationId;
          requestBodyId = (targetNode.data as any)?.id;
        } else if (sourceNode?.type === 'requestBody' && targetNode?.type === 'operation') {
          operationId = (targetNode.data as any)?.dbOperationId;
          requestBodyId = (sourceNode.data as any)?.id;
        }

        // Handle parameter linking
        if (operationId && parameterId) {
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
        } else if (operationId && requestBodyId) {
          try {
            const result = await linkRequestBodyToOperation(operationId, requestBodyId);
            const parsed = JSON.parse(result);

            if (!parsed.success) {
              console.error('Failed to link request body to operation:', parsed.error);
              await alertDialog({
                title: 'Error',
                message: parsed.error || 'Failed to link request body to operation',
                variant: 'error',
              });
              setEdges((eds) => eds.filter((e) =>
                !(e.source === connection.source && e.target === connection.target)
              ));
            }
          } catch (error) {
            console.error('Error linking request body to operation:', error);
            await alertDialog({
              title: 'Error',
              message: 'Failed to link request body to operation',
              variant: 'error',
            });
            setEdges((eds) => eds.filter((e) =>
              !(e.source === connection.source && e.target === connection.target)
            ));
          }
        }
      }
    },
    [setEdges, setNodes, nodes, alertDialog, edgeRouting, edgeAnimation, edgeStyling, handleShowClassDropDialog, handleClassDropOnResponse, selectedPathId, selectedVersionId]
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
        let requestBodyUnlinkOperationId: string | undefined;

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
        } else if (sourceNode?.type === 'operation' && targetNode?.type === 'requestBody') {
          requestBodyUnlinkOperationId = (sourceNode.data as any)?.dbOperationId;
        } else if (sourceNode?.type === 'requestBody' && targetNode?.type === 'operation') {
          requestBodyUnlinkOperationId = (targetNode.data as any)?.dbOperationId;
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
        } else if (requestBodyUnlinkOperationId) {
          try {
            const result = await unlinkRequestBodyFromOperation(requestBodyUnlinkOperationId);
            const parsed = JSON.parse(result);

            if (!parsed.success) {
              console.error('Failed to unlink request body from operation:', parsed.error);
              await alertDialog({
                title: 'Error',
                message: parsed.error || 'Failed to unlink request body from operation',
                variant: 'error',
              });
            }
          } catch (error) {
            console.error('Error unlinking request body from operation:', error);
          }
        }
      }
    },
    [nodes, alertDialog, setNodes]
  );

  /** Keyboard delete (Delete/Backspace): sync removed nodes to the API. Auxiliary nodes stay non-deletable. */
  const onNodesDelete = useCallback(
    async (deleted: Node[]) => {
      /** Unlink `recordId` from every operation connected to `nodeId` via current edges. */
      const unlinkFromConnectedOperations = async (
        nodeId: string,
        recordId: string,
        unlinkFn: (operationId: string, recordId: string) => Promise<string>
      ) => {
        const connectedEdges = edges.filter((e) => e.source === nodeId || e.target === nodeId);
        for (const edge of connectedEdges) {
          const otherNodeId = edge.source === nodeId ? edge.target : edge.source;
          const otherNode = nodes.find((n) => n.id === otherNodeId);
          if (otherNode?.type === 'operation') {
            const operationId = (otherNode.data as any)?.dbOperationId;
            if (operationId) {
              await unlinkFn(operationId, recordId);
            }
          }
        }
      };

      for (const node of deleted) {
        try {
          if (node.type === 'operation') {
            await deleteOperation(node.id);
          } else if (node.type === 'parameter') {
            const pid = (node.data as { dbParameterId?: string })?.dbParameterId;
            if (pid) {
              await unlinkFromConnectedOperations(node.id, pid, unlinkParameterFromOperation);
              const result = await deleteSharedPathParameter(pid);
              const parsed = JSON.parse(result);
              if (!parsed.success) {
                await alertDialog({
                  title: 'Error',
                  message: parsed.error || 'Failed to delete parameter',
                  variant: 'error',
                });
              }
            }
          } else if (node.type === 'response') {
            const rid = (node.data as { dbResponseId?: string })?.dbResponseId;
            if (rid) {
              await unlinkFromConnectedOperations(node.id, rid, unlinkResponseFromOperation);
              const result = await deleteSharedPathResponse(rid);
              const parsed = JSON.parse(result);
              if (!parsed.success) {
                await alertDialog({
                  title: 'Error',
                  message: parsed.error || 'Failed to delete response',
                  variant: 'error',
                });
              }
            }
          }
        } catch (error) {
          console.error('onNodesDelete:', error);
          await alertDialog({
            title: 'Error',
            message: 'Failed to delete node on the server. Refresh the page to resync the canvas.',
            variant: 'error',
          });
        }
      }
      if (onRefresh) {
        onRefresh();
      }
    },
    [alertDialog, edges, nodes, onRefresh]
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

      // Dropping on a parameter node (header or canvas): only properties are allowed
      const elementAtDrop = document.elementFromPoint(event.clientX, event.clientY);
      const dropNodeWrapper = elementAtDrop?.closest('[data-id]');
      const dropTargetNodeId = dropNodeWrapper?.getAttribute('data-id');
      const dropTargetNode = dropTargetNodeId ? nodes.find((n) => n.id === dropTargetNodeId) : null;
      if (dropTargetNode?.type === 'parameter' && dropData?.type !== 'property') {
        await alertDialog({
          title: 'Invalid drop',
          message: 'Only designer properties can be dropped onto a parameter node to set its schema.',
          variant: 'warning',
        });
        return;
      }

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

        // Property dropped on a parameter node on the canvas - update parameter schema
        if (targetNodeId && targetNodeId.startsWith('param-')) {
          const paramNode = nodes.find((n) => n.id === targetNodeId && n.type === 'parameter');
          const paramData = paramNode?.data as { dbParameterId?: string; name?: string } | undefined;
          if (paramNode && paramData?.dbParameterId) {
            const propertyData = dropData.data || { type: 'string' };
            const schema = propertyDataToParameterSchema(propertyData);
            try {
              const updateResult = await updateSharedPathParameter(paramData.dbParameterId, { data: schema });
              const updateParsed = JSON.parse(updateResult);
              if (!updateParsed.success) {
                await alertDialog({
                  title: 'Error',
                  message: updateParsed.error || 'Failed to update parameter schema',
                  variant: 'error',
                });
                return;
              }
              if (onRefresh) onRefresh();
              if (onParameterSelect) {
                onParameterSelect({
                  id: paramData.dbParameterId,
                  name: paramData.name ?? '',
                  operationId: '',
                });
              }
            } catch (error) {
              console.error('Error updating parameter schema:', error);
              await alertDialog({
                title: 'Error',
                message: 'Failed to bind property to parameter',
                variant: 'error',
              });
            }
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
        const existingOp = nodes.some(
          (n) => n.type === 'operation' && (n.data as { operation?: string })?.operation === dropData.operation
        );
        if (existingOp) {
          await alertDialog({
            title: 'Operation Already Exists',
            message: `A ${dropData.operation} operation already exists on this path.`,
            variant: 'warning',
          });
          return;
        }

        const position = screenToFlowPosition({
          x: event.clientX,
          y: event.clientY,
        });

        try {
          if (!selectedVersionId) {
            await alertDialog({
              title: 'Error',
              message: 'No version selected.',
              variant: 'error',
            });
            return;
          }

          if (!selectedPathId) {
            await alertDialog({
              title: 'No Path Selected',
              message: 'Please select a path from the sidebar before adding an operation.',
              variant: 'warning',
            });
            return;
          }

          const result = await createOperationViaApi(
            selectedVersionId,
            selectedPathId,
            dropData.operation,
            { position }
          );

          if (!result.success || !result.data) {
            const errText = (result.error || '').toLowerCase();
            if (errText.includes('already exists') || errText.includes('409')) {
              await alertDialog({
                title: 'Operation already exists',
                message: `A ${dropData.operation} operation already exists for this path. Each method can only be used once per path template.`,
                variant: 'warning',
              });
            } else {
              await alertDialog({
                title: 'Error',
                message: result.error || 'Failed to add operation.',
                variant: 'error',
              });
            }
            return;
          }

          const savedOperation = result.data;
          const operationMethod = String(savedOperation.operation || dropData.operation || '').toUpperCase();
          const generatedOperationId = generateOperationId(pathname || '/', operationMethod);

          let operationId: string | undefined;
          try {
            const descResponse = await getOperationDescription(savedOperation.id);
            const descData = JSON.parse(descResponse);
            operationId = descData?.operation_id;
          } catch (descError) {
            console.log('[onDrop] Could not fetch operation description:', descError);
          }

          // Persist a default operationId immediately so the node and properties panel
          // both show a stable value on first add (before manual Save).
          if (!operationId) {
            try {
              await upsertOperationDescription(
                savedOperation.id,
                undefined,
                undefined,
                generatedOperationId,
                undefined
              );
              operationId = generatedOperationId;
            } catch (upsertError) {
              console.error('[onDrop] Could not persist generated operationId:', upsertError);
              // Keep UI usable even if the description upsert fails.
              operationId = generatedOperationId;
            }
          }

          const newNode: Node = {
            id: savedOperation.id,
            type: 'operation',
            deletable: true,
            position,
            data: {
              operation: operationMethod,
              color: OPERATION_COLORS[operationMethod] || dropData.color || '#64748b',
              dbOperationId: savedOperation.id,
              versionPathId: selectedPathId,
              operationId: operationId,
              parameters: [],
            },
          };

          const pathNodeId = `path-node-${selectedPathId}`;
          const dropEdgeType =
            edgeRouting === 'straight'
              ? 'straight'
              : edgeRouting === 'bezier'
                ? 'default'
                : edgeRouting === 'smart'
                  ? 'smart'
                  : 'smoothstep';

          setNodes((nds) => [...nds, newNode]);
          const pathToOperationLabel = labelPathToOperation();
          setEdges((eds) => [
            ...eds,
            {
              id: `edge-path-op-${selectedPathId}-${savedOperation.id}`,
              source: pathNodeId,
              sourceHandle: 'path-output',
              target: savedOperation.id,
              targetHandle: 'operation-input',
              type: dropEdgeType,
              animated: edgeAnimation !== 'none',
              ...(pathToOperationLabel
                ? {
                    label: pathToOperationLabel,
                    labelStyle: pathsCanvasEdgeLabelStyle,
                    labelBgStyle: pathsCanvasEdgeLabelBgStyle,
                  }
                : {}),
              style: {
                stroke: edgeStyling.directColor,
                strokeWidth: 2,
                strokeDasharray: edgeAnimation === 'dash' ? '5,5' : undefined,
              },
              data: {
                sourceNodeId: pathNodeId,
                targetNodeId: savedOperation.id,
                semantic: 'path-has-operation' as const,
              },
            },
          ]);

          // Rehydrate from server so the new operation has full node handlers/data
          // (schema drop, delete, security metadata) immediately after creation.
          if (onRefresh) {
            onRefresh();
          }
        } catch (error) {
          console.error('Error creating operation:', error);
          await alertDialog({
            title: 'Error',
            message: 'Failed to add operation. Please try again.',
            variant: 'error',
          });
        }
      } else if (dropData.type === 'parameter') {
        const rawLoc = dropData.inLocation;
        const VALID_LOCATIONS = ['query', 'path', 'header', 'cookie'] as const;
        type ParamLoc = typeof VALID_LOCATIONS[number];
        const inLoc: ParamLoc | undefined = VALID_LOCATIONS.includes(rawLoc as ParamLoc)
          ? (rawLoc as ParamLoc)
          : undefined;
        // OpenAPI 3.1 default name per location (matches the Parameters section
        // chips in the sidebar).
        const DEFAULT_NAME: Record<ParamLoc, string> = {
          query: 'q',
          path: 'id',
          header: 'Authorization',
          cookie: 'session',
        };
        const suggested =
          typeof dropData.suggestedName === 'string' && dropData.suggestedName.trim()
            ? dropData.suggestedName.trim()
            : inLoc
              ? DEFAULT_NAME[inLoc]
              : 'param';
        if (!inLoc) {
          await alertDialog({
            title: 'Add Parameter',
            message:
              'Drag a Query, Path, Header, or Cookie chip from the Operations sidebar onto an operation, or use Add Parameter in Operation Details.',
            variant: 'info',
          });
          return;
        }
        const elementAtPoint = document.elementFromPoint(event.clientX, event.clientY);
        const nodeWrapper = elementAtPoint?.closest('[data-id]');
        const nodeId = nodeWrapper?.getAttribute('data-id');
        if (!nodeId) {
          await alertDialog({
            title: 'Drop on Operation',
            message: 'Drag the parameter chip onto an operation node to attach it to that operation.',
            variant: 'info',
          });
          return;
        }
        const opNode = nodes.find((n) => n.id === nodeId && n.type === 'operation');
        if (!opNode || !selectedPathId) {
          await alertDialog({
            title: 'Drop on Operation',
            message: 'Drag the parameter chip onto an operation node to attach it to that operation.',
            variant: 'info',
          });
          return;
        }
        const dbOperationId = opNode.id;
        try {
          const allRes = await getSharedPathParameters(selectedPathId);
          const allParsed = JSON.parse(allRes) as {
            parameters?: Array<{ name: string; in_location: string }>;
          };
          const used = new Set(
            (allParsed.parameters || [])
              .filter((p) => p.in_location === inLoc)
              .map((p) => p.name)
          );
          let finalName = suggested;
          let suffix = 2;
          while (used.has(finalName)) {
            finalName = `${suggested}_${suffix}`;
            suffix += 1;
          }
          // OpenAPI 3.1 default style/explode per location. Path params are
          // always required; the others default to optional and let the user
          // flip that in the Parameter panel.
          const STYLE_DEFAULTS: Record<ParamLoc, { style: string; explode: boolean; required: boolean }> = {
            query:  { style: 'form',   explode: true,  required: false },
            path:   { style: 'simple', explode: false, required: true },
            header: { style: 'simple', explode: false, required: false },
            cookie: { style: 'form',   explode: false, required: false },
          };
          const schemaData: Record<string, unknown> = {
            type: 'string',
            ...STYLE_DEFAULTS[inLoc],
          };
          const paramResult = await createSharedPathParameter(
            selectedPathId,
            finalName,
            inLoc,
            undefined,
            undefined,
            schemaData
          );
          const paramParsed = JSON.parse(paramResult);
          if (!paramParsed.success || !paramParsed.parameter) {
            await alertDialog({
              title: 'Error',
              message: paramParsed.error || 'Failed to create parameter',
              variant: 'error',
            });
            return;
          }
          const linkResult = await linkParameterToOperation(dbOperationId, paramParsed.parameter.id);
          const linkParsed = JSON.parse(linkResult);
          if (!linkParsed.success) {
            await alertDialog({
              title: 'Error',
              message: linkParsed.error || 'Failed to link parameter to operation',
              variant: 'error',
            });
            return;
          }
          if (onParameterSelect) {
            onParameterSelect({
              id: paramParsed.parameter.id,
              name: finalName,
              operationId: dbOperationId,
            });
          }
          if (onRefresh) onRefresh();
        } catch (err) {
          console.error('Error adding parameter from palette:', err);
          await alertDialog({
            title: 'Error',
            message: 'Failed to add parameter.',
            variant: 'error',
          });
        }
      } else if (dropData.type === 'security-scheme') {
        const schemeName = dropData.schemeName;
        if (!schemeName) return;
        const elementAtPoint = document.elementFromPoint(event.clientX, event.clientY);
        const nodeWrapper = elementAtPoint?.closest('[data-id]');
        const nodeId = nodeWrapper?.getAttribute('data-id');
        if (!nodeId) {
          await alertDialog({
            title: 'Drop on Operation',
            message: 'Drag the security scheme onto an operation node to apply it.',
            variant: 'info',
          });
          return;
        }
        const opNode = nodes.find((n) => n.id === nodeId && n.type === 'operation');
        if (!opNode) {
          await alertDialog({
            title: 'Drop on Operation',
            message: 'Drag the security scheme onto an operation node to apply it.',
            variant: 'info',
          });
          return;
        }
        const dbOperationId = opNode.id;
        try {
          const descResponse = await getOperationDescription(dbOperationId);
          const desc = JSON.parse(descResponse);
          const meta = desc?.metadata
            ? typeof desc.metadata === 'string'
              ? JSON.parse(desc.metadata)
              : desc.metadata
            : {};
          const existingSec = Array.isArray(meta.security)
            ? meta.security
            : meta.security
              ? [meta.security]
              : [];
          const newReq: Record<string, string[]> = { [schemeName]: [] };
          const newSec = [...existingSec, newReq];
          await upsertOperationDescription(
            dbOperationId,
            desc?.summary,
            desc?.description,
            desc?.operation_id,
            { ...meta, security: newSec }
          );
          if (onRefresh) onRefresh();
        } catch (err) {
          console.error('Error applying security scheme to operation:', err);
          await alertDialog({
            title: 'Error',
            message: 'Failed to apply security scheme to the operation. Please try again.',
            variant: 'error',
          });
        }
      } else if (dropData.type === 'class') {
        const classDropData = {
          type: 'class' as const,
          classId: dropData.classId,
          className: dropData.className ?? 'Class',
        };
        if (!classDropData.classId) {
          return;
        }

        // Check if we're dropping on a response node
        const elementAtPoint = document.elementFromPoint(event.clientX, event.clientY);
        let responseNodeId: string | null = null;
        if (elementAtPoint) {
          const nodeWrapper = elementAtPoint.closest('[data-id]');
          if (nodeWrapper) {
            responseNodeId = nodeWrapper.getAttribute('data-id');
          }
          if (!responseNodeId) {
            let parent = elementAtPoint.parentElement;
            let depth = 0;
            while (parent && depth < 10) {
              const nodeId = parent.getAttribute('data-id');
              if (nodeId && nodeId.startsWith('response-')) {
                responseNodeId = nodeId;
                break;
              }
              parent = parent.parentElement;
              depth++;
            }
          }
          if (!responseNodeId) {
            try {
              const position = screenToFlowPosition({ x: event.clientX, y: event.clientY });
              const allNodes = getNodes();
              for (const node of allNodes) {
                if (node.type === 'response') {
                  const nodeX = node.position.x || 0;
                  const nodeY = node.position.y || 0;
                  const nodeWidth = 280;
                  const nodeHeight = 150;
                  if (
                    position.x >= nodeX - 10 && position.x <= nodeX + nodeWidth + 10 &&
                    position.y >= nodeY - 10 && position.y <= nodeY + nodeHeight + 10
                  ) {
                    responseNodeId = node.id;
                    break;
                  }
                }
              }
            } catch {}
          }
        }
        
        if (responseNodeId && responseNodeId.startsWith('response-')) {
          const responseNode = nodes.find(n => n.id === responseNodeId && n.type === 'response');
          const responseData = responseNode?.data as { onClassDrop?: (responseId: string, classData: unknown) => void; dbResponseId?: string } | undefined;
          if (responseNode && responseData?.onClassDrop && responseData?.dbResponseId) {
            try {
              await responseData.onClassDrop(responseData.dbResponseId, classDropData);
            } catch (error) {
              console.error('Error in onClassDrop:', error);
            }
          }
        }
        // Class dropped on empty canvas: no longer creates a node (undo #372)
      }
    },
    [
      screenToFlowPosition,
      getNodes,
      nodes,
      alertDialog,
      propertyDataToParameterSchema,
      updateSharedPathParameter,
      onRefresh,
      onParameterSelect,
      selectedVersionId,
      selectedPathId,
      setEdges,
      edgeRouting,
      edgeAnimation,
      edgeStyling,
      createSharedPathParameter,
      linkParameterToOperation,
      getSharedPathParameters,
    ]
  );

  return (
    <div ref={reactFlowWrapper} className="flex-1 flex flex-col h-full">
      {/* Path header with clickable variables - click to edit schema, or drag a property here for type binding */}
      {selectedPathId && pathname && (
        <>
          <div
            className={`relative flex-shrink-0 px-4 py-2 border-b bg-white/95 dark:bg-gray-800/95 flex items-center gap-1 flex-wrap font-mono text-sm ${
              !isValidPath(pathname)
                ? 'border-2 border-red-600 ring-2 ring-red-500/50 dark:border-red-500 dark:ring-red-400/50'
                : 'border-gray-200 dark:border-gray-700'
            }`}
            title={
              !isValidPath(pathname)
                ? 'Invalid path: must start with / and use valid {param} placeholders'
                : 'Click a variable to edit its schema, or drag a property from the sidebar for type binding'
            }
          >
            {!isValidPath(pathname) && (
              <div className="absolute top-1.5 right-2 flex items-center justify-center w-5 h-5 rounded-full bg-red-600 text-white shadow ring-2 ring-red-400/80" title="Path is misconfigured">
                <AlertTriangle className="w-3.5 h-3.5" strokeWidth={2.5} aria-hidden />
              </div>
            )}
            <span className="text-gray-500 dark:text-gray-400 mr-1">Path:</span>
            {parsePathSegments(pathname).map((seg, i) =>
              seg.type === 'literal' ? (
                <span key={i} className="text-gray-700 dark:text-gray-300">
                  {seg.value}
                </span>
              ) : (
                <button
                  key={i}
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    handlePathVariableClick(seg.value);
                  }}
                  onDragEnter={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    pathVariableDragCounterRef.current++;
                    setDragOverPathVariable(seg.value);
                  }}
                  onDragOver={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    e.dataTransfer.dropEffect = 'copy';
                  }}
                  onDragLeave={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    pathVariableDragCounterRef.current--;
                    if (pathVariableDragCounterRef.current === 0) {
                      setDragOverPathVariable(null);
                    }
                  }}
                  onDrop={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    pathVariableDragCounterRef.current = 0;
                    setDragOverPathVariable(null);
                    const dataStr = e.dataTransfer.getData('application/json');
                    if (dataStr) {
                      try {
                        const dropData = JSON.parse(dataStr);
                        handlePropertyDropOnPathVariable(seg.value, dropData);
                      } catch (err) {
                        console.error('Failed to parse drop data:', err);
                      }
                    }
                  }}
                  className={`px-1.5 py-0.5 rounded font-medium cursor-pointer transition-colors ${
                    dragOverPathVariable === seg.value
                      ? 'bg-indigo-300 dark:bg-indigo-600 text-indigo-900 dark:text-indigo-100 ring-2 ring-indigo-500 dark:ring-indigo-400'
                      : 'bg-indigo-100 dark:bg-indigo-900/50 text-indigo-700 dark:text-indigo-300 hover:bg-indigo-200 dark:hover:bg-indigo-800/50'
                  }`}
                  title={`Edit schema for ${seg.value}, or drop a property here for type binding`}
                >
                  {seg.value}
                </button>
              )
            )}
          </div>
          {/* #360: Path template preview with sample values */}
          {extractPathParameters(pathname).length > 0 && (() => {
            const paramSchemas: Record<string, { type?: string; format?: string; enum?: unknown[] } | null> = {};
            for (const p of pathParamsForPreview) {
              const data = typeof p.data === 'string' ? (() => { try { return JSON.parse(p.data as unknown as string); } catch { return {}; } })() : (p.data || {});
              paramSchemas[p.name] = { type: data.type, format: data.format, enum: data.enum };
            }
            const { samplePath } = getPathWithSampleValues(pathname, paramSchemas);
            return (
              <div
                className="flex-shrink-0 px-4 py-1.5 border-b bg-gray-50/95 dark:bg-gray-900/95 flex items-center gap-2 flex-wrap font-mono text-xs border-gray-200 dark:border-gray-700"
                title="Path with sample values substituted. Copy to use as example URL."
              >
                <Eye className="w-3.5 h-3.5 text-gray-400 dark:text-gray-500 flex-shrink-0" aria-hidden />
                <span className="text-gray-500 dark:text-gray-400">Sample:</span>
                <span className="text-gray-700 dark:text-gray-300 break-all">{samplePath}</span>
                <button
                  type="button"
                  onClick={() => {
                    navigator.clipboard.writeText(samplePath).then(() => {
                      setSamplePathCopied(true);
                      setTimeout(() => setSamplePathCopied(false), 2000);
                    });
                  }}
                  className={`ml-auto flex items-center gap-1 px-2 py-1 rounded text-xs font-medium transition-colors ${
                    samplePathCopied
                      ? 'bg-green-100 dark:bg-green-900/40 text-green-800 dark:text-green-200'
                      : 'bg-gray-200/80 dark:bg-gray-700/80 text-gray-700 dark:text-gray-300 hover:bg-gray-300 dark:hover:bg-gray-600'
                  }`}
                  title="Copy sample URL"
                >
                  {samplePathCopied ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
                  {samplePathCopied ? 'Copied' : 'Copy'}
                </button>
              </div>
            );
          })()}
        </>
      )}
        <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onEdgesDelete={onEdgesDelete}
        onNodesDelete={onNodesDelete}
        deleteKeyCode={['Delete', 'Backspace']}
        onDrop={onDrop}
        onDragOver={onDragOver}
        onNodeClick={onNodeClick}
        onNodeDrag={handlePathsNodeDrag}
        onNodeDragStop={handlePathsNodeDragStop}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        defaultEdgeOptions={{
          zIndex: 0,
          style: { stroke: edgeStyling.directColor, strokeWidth: 2 },
        }}
        connectionLineStyle={{ stroke: edgeStyling.directColor, strokeWidth: 2 }}
        snapToGrid={snapToGrid}
        snapGrid={[gridSize, gridSize]}
        fitView={false}
        onMoveEnd={(_, viewport) => {
          schedulePersistPathsCanvas();
          setCanvasViewport(viewport);
        }}
        attributionPosition="bottom-left"
        className={isDark ? 'bg-gray-900' : ''}
        nodesDraggable={true}
        nodesConnectable={true}
        elementsSelectable={true}
        selectionOnDrag={true}
        nodesFocusable={true}
        edgesFocusable={true}
        style={canvasBackgroundStyle}
      >
        {canvasBackground.type === 'grid' && showGrid && (
          <Background
            variant={backgroundVariant(gridStyle)}
            gap={gridSize}
            size={1.5}
            color="currentColor"
            style={{
              color: canvasBackground.gridColor || (isDark ? 'rgb(148, 163, 184)' : 'rgb(99, 102, 241)'),
              opacity: canvasBackground.gridOpacity ?? (isDark ? 0.25 : 0.15),
            }}
          />
        )}
        <Controls
          className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-md overflow-hidden"
          style={{ borderRadius: '6px', overflow: 'hidden', boxShadow: 'none' }}
        />
        {selectedPathId && (
          <Panel position="top-right" className="m-2">
            <button
              type="button"
              onClick={handlePathsCanvasAutoLayout}
              disabled={!canvasPersistReady || nodes.length === 0}
              className="flex items-center gap-1.5 rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-xs font-medium text-slate-700 shadow-sm transition-colors hover:bg-slate-50 disabled:pointer-events-none disabled:opacity-40 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800"
              title="Arrange nodes in a top-down layered layout and fit the view. Saves with your path canvas."
              aria-label="Auto-arrange path canvas layout"
            >
              <LayoutGrid className="h-3.5 w-3.5 shrink-0" aria-hidden />
              Auto layout
            </button>
          </Panel>
        )}
        {(alignmentGuides.horizontal.length > 0 || alignmentGuides.vertical.length > 0) && (() => {
          const viewport = getViewport();
          return (
            <div
              className="pointer-events-none absolute inset-0 z-[1000] overflow-hidden"
            >
              <svg className="pointer-events-none absolute inset-0 overflow-visible" aria-hidden>
                <g transform={`translate(${viewport.x}, ${viewport.y}) scale(${viewport.zoom})`}>
                  {alignmentGuides.horizontal.map((guide, index) => (
                    <line
                      key={`h-${index}`}
                      x1={guide.x1}
                      y1={guide.y}
                      x2={guide.x2}
                      y2={guide.y}
                      stroke={isDark ? '#818cf8' : '#4f46e5'}
                      strokeWidth={1 / viewport.zoom}
                      strokeDasharray={`${4 / viewport.zoom} ${3 / viewport.zoom}`}
                    />
                  ))}
                  {alignmentGuides.vertical.map((guide, index) => (
                    <line
                      key={`v-${index}`}
                      x1={guide.x}
                      y1={guide.y1}
                      x2={guide.x}
                      y2={guide.y2}
                      stroke={isDark ? '#818cf8' : '#4f46e5'}
                      strokeWidth={1 / viewport.zoom}
                      strokeDasharray={`${4 / viewport.zoom} ${3 / viewport.zoom}`}
                    />
                  ))}
                </g>
              </svg>
            </div>
          );
        })()}
      </ReactFlow>

      {/* Class Drop Choice Dialog */}
      <ClassDropChoiceDialog
        open={classDropDialogOpen}
        onOpenChange={setClassDropDialogOpen}
        className={classDropDialogClassName}
        showArrayOption={classDropDialogShowArrayOption}
        arrayOptionChecked={classDropDialogAsArray}
        onArrayOptionCheckedChange={setClassDropDialogAsArray}
        onChoice={handleClassDropDialogChoice}
      />
    </div>
  );
}

export default function PathsCanvasView({
  selectedPathId,
  pathname,
  onOperationSelect,
  onParameterSelect,
  onResponseSelect,
  refreshKey,
  onRefresh,
  onPathnameUpdated,
  pendingFocusNodeId,
  onPendingFocusComplete,
}: {
  selectedPathId: string | null;
  pathname?: string | null;
  onOperationSelect: (operation: { id: string; operation: string } | null) => void;
  onParameterSelect?: (parameter: { id: string; name: string; operationId: string } | null) => void;
  onResponseSelect?: (response: { id: string; statusCode: string; description: string } | null) => void;
  refreshKey?: number;
  onRefresh?: () => void;
  onPathnameUpdated?: (pathname: string) => void;
  pendingFocusNodeId?: string | null;
  onPendingFocusComplete?: () => void;
}) {
  return (
    <ReactFlowProvider>
      <PathsCanvasInner
        selectedPathId={selectedPathId}
        pathname={pathname}
        onOperationSelect={onOperationSelect}
        onParameterSelect={onParameterSelect}
        onResponseSelect={onResponseSelect}
        refreshKey={refreshKey}
        onRefresh={onRefresh}
        onPathnameUpdated={onPathnameUpdated}
        pendingFocusNodeId={pendingFocusNodeId}
        onPendingFocusComplete={onPendingFocusComplete}
      />
    </ReactFlowProvider>
  );
}
