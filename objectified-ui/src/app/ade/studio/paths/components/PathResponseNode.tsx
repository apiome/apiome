// Path Response Node Component for React Flow Canvas
// Design based on section 9.3.4 of FUTURE_FEATURE_ROADMAP_PATHS.md
'use client';

import React from 'react';
import { Check, AlertTriangle, X, Activity, Trash2, Unlink } from 'lucide-react';
import { Handle, Position } from '@xyflow/react';

export interface ContentTypeInfo {
  id: string;
  media_type: string;
  class_id?: string | null;
  class_name?: string | null;
  inline_schema?: {
    type?: string;
    items?: { type?: string; $ref?: string };
    properties?: any[];
    $ref?: string;
    format?: string;
    enum?: (string | number | boolean | null)[];
    default?: unknown;
  } | null;
  examples?: any[] | null;
}

export interface PathResponseData {
  statusCode: string;
  description?: string;
  dbResponseId?: string;
  operationId?: string;
  schemaMode?: 'class' | 'object' | 'primitive' | 'array'; // Explicit schema mode
  linkedOperations?: Array<{ id: string; operation: string }>; // Operations this response is linked to
  onDelete?: () => void;
  onUnlink?: (operationId: string) => void; // Unlink from a specific operation
  onClassDrop?: (responseId: string, classData: any) => void;
  onPropertyDrop?: (responseId: string, propertyData: any) => void; // NEW: Handle property drops
  onClassUnlink?: (responseId: string) => void; // Unlink attached class from response
  onSchemaTypeChange?: (responseId: string, schemaMode: 'object' | 'primitive' | 'array', schemaType?: string) => void;
  attachedClassId?: string;
  attachedClassName?: string;
  contentTypes?: ContentTypeInfo[];
  inlineSchema?: {
    type?: string;
    items?: { type?: string; $ref?: string };
    properties?: any[];
    $ref?: string;
    format?: string;
    enum?: (string | number | boolean | null)[];
    default?: unknown;
  } | null;
  headers?: Array<{ name: string; description?: string }>;
}

// Helper to get schema display text for primitives and arrays
const getSchemaDisplayText = (schema: ContentTypeInfo['inline_schema'] | PathResponseData['inlineSchema']): { text: string; isObject: boolean } => {
  if (!schema) {
    console.log('[PathResponseNode] getSchemaDisplayText: schema is null/undefined');
    return { text: '', isObject: false };
  }

  console.log('[PathResponseNode] getSchemaDisplayText input:', JSON.stringify(schema));

  const schemaType = schema.type?.toLowerCase();

  // Check for $ref (class reference)
  if (schema.$ref) {
    const className = schema.$ref.split('/').pop() || 'Reference';
    return { text: className, isObject: true };
  }

  // Handle array types
  if (schemaType === 'array' && schema.items) {
    if (schema.items.$ref) {
      const itemClass = schema.items.$ref.split('/').pop() || 'Object';
      return { text: `${itemClass}[]`, isObject: true };
    }
    const itemType = schema.items.type || 'any';
    return { text: `${itemType}[]`, isObject: false };
  }

  // Handle object type
  if (schemaType === 'object') {
    const propCount = Array.isArray(schema.properties) ? schema.properties.length : 0;
    return { text: propCount > 0 ? `Object (${propCount} props)` : 'Object', isObject: true };
  }

  // Handle primitive types with optional format
  if (schemaType && ['string', 'number', 'integer', 'boolean', 'null'].includes(schemaType)) {
    let text = schemaType;
    if (schema.format) {
      text = `${schemaType} (${schema.format})`;
    }
    return { text, isObject: false };
  }

  return { text: '', isObject: false };
};

// Get color scheme and icon based on status code (per 9.3.4 spec)
const getStatusConfig = (statusCode: string) => {
  const code = statusCode.toLowerCase();
  const firstChar = code.charAt(0);

  if (code === 'default') {
    return {
      headerBg: 'bg-gray-500',
      borderColor: 'border-gray-500',
      color: '#6b7280',
      icon: '∿',
      iconComponent: Activity,
    };
  }

  switch (firstChar) {
    case '2':
      return {
        headerBg: 'bg-emerald-500',
        borderColor: 'border-emerald-500',
        color: '#10b981',
        icon: '✓',
        iconComponent: Check,
      };
    case '3':
      return {
        headerBg: 'bg-blue-500',
        borderColor: 'border-blue-500',
        color: '#3b82f6',
        icon: '→',
        iconComponent: Activity,
      };
    case '4':
      return {
        headerBg: 'bg-amber-500',
        borderColor: 'border-amber-500',
        color: '#f59e0b',
        icon: '⚠️',
        iconComponent: AlertTriangle,
      };
    case '5':
      return {
        headerBg: 'bg-red-500',
        borderColor: 'border-red-500',
        color: '#ef4444',
        icon: '✕',
        iconComponent: X,
      };
    default:
      return {
        headerBg: 'bg-gray-500',
        borderColor: 'border-gray-500',
        color: '#6b7280',
        icon: '○',
        iconComponent: Activity,
      };
  }
};

export default function PathResponseNode({ data }: { data: PathResponseData }) {
  const config = getStatusConfig(data.statusCode);
  const [dragOver, setDragOver] = React.useState(false);

  const handleDragOver = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setDragOver(true);
    e.dataTransfer.dropEffect = 'copy';
  };

  const handleDragLeave = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setDragOver(false);
  };

  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setDragOver(false);

    const dataStr = e.dataTransfer.getData('application/json');
    if (!dataStr || !data.dbResponseId) return;

    try {
      const dropData = JSON.parse(dataStr);
      
      // Handle class drops
      if (dropData.type === 'class' && data.onClassDrop) {
        data.onClassDrop(data.dbResponseId, dropData);
      }
      
      // Handle property drops - NEW FUNCTIONALITY
      if (dropData.type === 'property' && data.onPropertyDrop) {
        data.onPropertyDrop(data.dbResponseId, dropData);
      }
    } catch (error) {
      console.error('PathResponseNode: Error parsing drop data:', error);
    }
  };

  // Get description text - use provided description or generate from status code
  const getDescription = () => {
    if (data.description) return data.description;
    const code = data.statusCode;
    if (code === '200') return 'OK';
    if (code === '201') return 'Created';
    if (code === '204') return 'No Content';
    if (code === '400') return 'Bad Request';
    if (code === '401') return 'Unauthorized';
    if (code === '403') return 'Forbidden';
    if (code === '404') return 'Not Found';
    if (code === '500') return 'Internal Error';
    if (code === 'default') return 'Default Response';
    return '';
  };

  // Determine what content to show
  const hasContentTypes = data.contentTypes && data.contentTypes.length > 0;
  // Check if content types have actual schema data
  const hasContentTypesWithSchema = hasContentTypes && data.contentTypes!.some(ct =>
    ct.class_name || ct.class_id || (ct.inline_schema && (ct.inline_schema.type || ct.inline_schema.$ref))
  );
  const hasInlineSchema = data.inlineSchema && (
    (data.inlineSchema.properties?.length ?? 0) > 0 ||
    data.inlineSchema.type ||
    data.inlineSchema.$ref
  );
  const hasAttachedClass = !!data.attachedClassName;
  const hasHeaders = data.headers && data.headers.length > 0;

  // For primitive/array types, prioritize inlineSchema display
  const showInlineSchemaFirst = hasInlineSchema && !hasAttachedClass &&
    data.inlineSchema?.type &&
    ['string', 'number', 'integer', 'boolean', 'null', 'array'].includes(data.inlineSchema.type);

  // Debug logging
  console.log('[PathResponseNode]', data.statusCode, {
    hasContentTypes,
    hasContentTypesWithSchema,
    hasInlineSchema,
    hasAttachedClass,
    showInlineSchemaFirst,
    inlineSchema: data.inlineSchema,
    schemaMode: data.schemaMode,
  });

  return (
    <>
      {/* Connection handle at TOP */}
      <Handle
        type="target"
        position={Position.Top}
        id="response-input"
        className="!w-3 !h-2 !rounded-t-md !rounded-b-none"
        style={{ backgroundColor: config.color }}
      />

      <div 
        className={`bg-white dark:bg-gray-800 rounded-lg border-2 ${config.borderColor} shadow-lg min-w-[200px] max-w-[280px] cursor-pointer relative group ${
          dragOver ? 'ring-2 ring-indigo-500 ring-offset-2' : ''
        }`}
        onDragOver={(e) => { e.stopPropagation(); handleDragOver(e); }}
        onDragLeave={(e) => { e.stopPropagation(); handleDragLeave(e); }}
        onDrop={(e) => { e.stopPropagation(); handleDrop(e); }}
      >
        {/* Delete button */}
        {data.onDelete && (
          <button
            onClick={(e) => { e.stopPropagation(); data.onDelete?.(); }}
            className="absolute -top-2 -right-2 bg-red-500 text-white rounded-full p-1 opacity-0 group-hover:opacity-100 transition-opacity shadow-lg hover:bg-red-600 z-10"
            title="Delete response"
          >
            <Trash2 size={12} />
          </button>
        )}

        {/* Header - Status code + description + icon */}
        <div className={`${config.headerBg} text-white px-3 py-2 rounded-t-md flex items-center justify-between`}>
          <div className="flex items-center gap-2">
            <span className="font-bold text-sm">{data.statusCode}</span>
            <span className="text-xs opacity-90">{getDescription()}</span>
          </div>
          <span className="text-lg">{config.icon}</span>
        </div>

        {/* Content Section */}
        <div className="p-3">
          <div className="text-[10px] font-medium text-gray-600 dark:text-gray-400 mb-1.5">Content:</div>

          {/* Priority 1: Primitive/Array types from inlineSchema */}
          {showInlineSchemaFirst ? (
            (() => {
              const schemaDisplay = getSchemaDisplayText(data.inlineSchema);
              return (
                <div className="text-[10px]">
                  <div className="flex items-center gap-1.5 text-gray-700 dark:text-gray-300">
                    <span className="text-gray-400">○</span>
                    <span className="font-mono">application/json</span>
                  </div>
                  <div className="flex items-center gap-1.5 ml-3 mt-0.5 text-gray-600 dark:text-gray-400">
                    <span className="text-gray-400">└─</span>
                    <span className="font-medium text-amber-600 dark:text-amber-400 font-mono">
                      {schemaDisplay.text || data.inlineSchema?.type}
                    </span>
                  </div>
                </div>
              );
            })()
          ) : hasContentTypesWithSchema ? (
            <div className="space-y-1.5">
              {data.contentTypes!.map((ct) => {
                const schemaDisplay = getSchemaDisplayText(ct.inline_schema);
                const hasSchema = ct.class_name || schemaDisplay.text;

                return (
                  <div key={ct.id} className="text-[10px]">
                    <div className="flex items-center gap-1.5 text-gray-700 dark:text-gray-300">
                      <span className="text-gray-400">○</span>
                      <span className="font-mono">{ct.media_type}</span>
                    </div>
                    {hasSchema && (
                      <div className="flex items-center gap-1.5 ml-3 mt-0.5 text-gray-600 dark:text-gray-400">
                        <span className="text-gray-400">└─</span>
                        {ct.class_name ? (
                          <>
                            <span className="text-gray-400">{'{ }'}</span>
                            <span className="font-medium text-indigo-600 dark:text-indigo-400">
                              {ct.class_name}
                            </span>
                          </>
                        ) : schemaDisplay.isObject ? (
                          <>
                            <span className="text-gray-400">{'{ }'}</span>
                            <span className="font-medium text-green-600 dark:text-green-400">
                              {schemaDisplay.text}
                            </span>
                          </>
                        ) : (
                          <span className="font-medium text-amber-600 dark:text-amber-400 font-mono">
                            {schemaDisplay.text}
                          </span>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          ) : data.inlineSchema ? (
            (() => {
              const schemaDisplay = getSchemaDisplayText(data.inlineSchema);
              return (
                <div className="text-[10px]">
                  <div className="flex items-center gap-1.5 text-gray-700 dark:text-gray-300">
                    <span className="text-gray-400">○</span>
                    <span className="font-mono">application/json</span>
                  </div>
                  <div className="flex items-center gap-1.5 ml-3 mt-0.5 text-gray-600 dark:text-gray-400">
                    <span className="text-gray-400">└─</span>
                    {schemaDisplay.isObject ? (
                      <>
                        <span className="text-gray-400">{'{ }'}</span>
                        <span className="font-medium text-green-600 dark:text-green-400">
                          {schemaDisplay.text || `Object (${data.inlineSchema?.properties?.length || 0} props)`}
                        </span>
                      </>
                    ) : schemaDisplay.text ? (
                      <span className="font-medium text-amber-600 dark:text-amber-400 font-mono">
                        {schemaDisplay.text}
                      </span>
                    ) : (
                      <>
                        <span className="text-gray-400">{'{ }'}</span>
                        <span className="font-medium text-green-600 dark:text-green-400">
                          Object ({data.inlineSchema?.properties?.length || 0} props)
                        </span>
                      </>
                    )}
                  </div>
                </div>
              );
            })()
          ) : hasAttachedClass ? (
            <div className="text-[10px]">
              <div className="flex items-center gap-1.5 text-gray-700 dark:text-gray-300">
                <span className="text-gray-400">○</span>
                <span className="font-mono">application/json</span>
              </div>
              <div className="flex items-center justify-between ml-3 mt-0.5">
                <div className="flex items-center gap-1.5 text-gray-600 dark:text-gray-400">
                  <span className="text-gray-400">└─</span>
                  <span className="text-gray-400">{'{ }'}</span>
                  <span className="font-medium text-indigo-600 dark:text-indigo-400">
                    {data.attachedClassName}
                  </span>
                </div>
                {data.onClassUnlink && data.dbResponseId && (
                  <button
                    onClick={(e) => { e.stopPropagation(); data.onClassUnlink?.(data.dbResponseId!); }}
                    className="text-gray-400 hover:text-red-500 transition-colors p-0.5"
                    title={`Unlink ${data.attachedClassName} from response`}
                  >
                    <Unlink size={10} />
                  </button>
                )}
              </div>
            </div>
          ) : (
            <div className={`text-[10px] ${dragOver ? 'text-indigo-600 dark:text-indigo-400' : 'text-gray-400 dark:text-gray-500 italic'}`}>
              {dragOver ? 'Drop class or property here' : '(none)'}
            </div>
          )}

          {/* Linked Operations Section */}
          {data.linkedOperations && data.linkedOperations.length > 0 && (
            <>
              <div className="text-[10px] font-medium text-gray-600 dark:text-gray-400 mt-3 mb-1">Linked to:</div>
              <div className="space-y-1">
                {data.linkedOperations.map((op) => (
                  <div key={op.id} className="flex items-center justify-between text-[10px] bg-gray-50 dark:bg-gray-700/50 rounded px-2 py-1">
                    <span className="font-medium text-gray-700 dark:text-gray-300">{op.operation}</span>
                    {data.onUnlink && (
                      <button
                        onClick={(e) => { e.stopPropagation(); data.onUnlink?.(op.id); }}
                        className="text-gray-400 hover:text-red-500 transition-colors"
                        title={`Unlink from ${op.operation}`}
                      >
                        <Unlink size={10} />
                      </button>
                    )}
                  </div>
                ))}
              </div>
            </>
          )}

          {/* Headers Section */}
          {hasHeaders && (
            <>
              <div className="text-[10px] font-medium text-gray-600 dark:text-gray-400 mt-3 mb-1">Headers:</div>
              <div className="space-y-0.5">
                {data.headers!.map((header, idx) => (
                  <div key={idx} className="text-[10px] text-gray-600 dark:text-gray-400 font-mono">
                    {header.name}
                  </div>
                ))}
              </div>
            </>
          )}

          {!hasHeaders && (
            <>
              <div className="text-[10px] font-medium text-gray-600 dark:text-gray-400 mt-3 mb-1">Headers:</div>
              <div className="text-[10px] text-gray-400 dark:text-gray-500 italic">(none)</div>
            </>
          )}
        </div>
      </div>

      {/* Output handle at BOTTOM */}
      <Handle
        type="source"
        position={Position.Bottom}
        id="response-class-output"
        className="!w-3 !h-2 !rounded-b-md !rounded-t-none"
        style={{
          backgroundColor: config.color,
          opacity: data.attachedClassId ? 1 : 0.6,
        }}
      />
    </>
  );
}

