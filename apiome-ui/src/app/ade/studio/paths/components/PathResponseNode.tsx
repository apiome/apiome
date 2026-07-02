// Path Response Node Component for React Flow Canvas
// Design based on section 9.3.4 of PLANNED_FEATURE_ROADMAP_PATHS.md
'use client';

import React from 'react';
import { Check, AlertTriangle, X, Activity, Trash2, Unlink, CornerDownRight } from 'lucide-react';
import { Position } from '@xyflow/react';
import { getHttpStatusDescription } from '../../../../../../lib/utils/http-status-codes';
import { NodeCard } from '@/app/components/ade/canvas/NodeCard';
import { NodeHeader } from '@/app/components/ade/canvas/NodeHeader';
import { NodeHandleDot } from '@/app/components/ade/canvas/NodeHandleDot';
import { accentVar, type NodeAccentRole } from '@/app/components/ade/canvas/canvas-theme';
import { NODE_ATTACH_MIN_WIDTH_PX, NODE_ATTACH_MAX_WIDTH_PX } from './paths-theme';

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
  schemaMode?: 'class' | 'object' | 'primitive' | 'array';
  linkedOperations?: Array<{ id: string; operation: string }>;
  onDelete?: () => void;
  onUnlink?: (operationId: string) => void;
  onClassDrop?: (responseId: string, classData: any) => void;
  onPropertyDrop?: (responseId: string, propertyData: any) => void;
  onClassUnlink?: (responseId: string) => void;
  onSchemaTypeChange?: (
    responseId: string,
    schemaMode: 'object' | 'primitive' | 'array',
    schemaType?: string
  ) => void;
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
  headers?: Array<{
    name: string;
    description?: string;
    schema?: { type?: string; format?: string };
  }>;
  links?: Array<{
    name: string;
    operationId?: string;
    operationRef?: string;
    description?: string;
    parameters?: Record<string, string>;
  }>;
}

const getSchemaDisplayText = (
  schema: ContentTypeInfo['inline_schema'] | PathResponseData['inlineSchema']
): { text: string; isObject: boolean } => {
  if (!schema) return { text: '', isObject: false };
  const schemaType = schema.type?.toLowerCase();

  if (schema.$ref) {
    const className = schema.$ref.split('/').pop() || 'Reference';
    return { text: className, isObject: true };
  }

  if (schemaType === 'array' && schema.items) {
    if (schema.items.$ref) {
      const itemClass = schema.items.$ref.split('/').pop() || 'Object';
      return { text: `${itemClass}[]`, isObject: true };
    }
    const itemType = schema.items.type || 'any';
    return { text: `${itemType}[]`, isObject: false };
  }

  if (schemaType === 'object') {
    const propCount = Array.isArray(schema.properties) ? schema.properties.length : 0;
    return { text: propCount > 0 ? `Object (${propCount} props)` : 'Object', isObject: true };
  }

  if (schemaType && ['string', 'number', 'integer', 'boolean', 'null'].includes(schemaType)) {
    let text = schemaType;
    if (schema.format) text = `${schemaType} (${schema.format})`;
    return { text, isObject: false };
  }

  return { text: '', isObject: false };
};

// Map status code family to an accent role + icon.
const statusMeta = (statusCode: string): { role: NodeAccentRole; Icon: React.FC<{ size?: number; strokeWidth?: number }> } => {
  const code = statusCode.toLowerCase();
  if (code === 'default') return { role: 'revision', Icon: Activity };
  switch (code.charAt(0)) {
    case '2': return { role: 'status-2xx', Icon: Check };
    case '3': return { role: 'status-3xx', Icon: Activity };
    case '4': return { role: 'status-4xx', Icon: AlertTriangle };
    case '5': return { role: 'status-5xx', Icon: X };
    default:  return { role: 'revision', Icon: Activity };
  }
};

export default function PathResponseNode({ data }: { data: PathResponseData }) {
  const { role, Icon } = statusMeta(data.statusCode);
  const accent = accentVar(role);
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
      if (dropData.type === 'class' && data.onClassDrop) data.onClassDrop(data.dbResponseId, dropData);
      if (dropData.type === 'property' && data.onPropertyDrop) data.onPropertyDrop(data.dbResponseId, dropData);
    } catch (error) {
      console.error('PathResponseNode: Error parsing drop data:', error);
    }
  };

  const getDescription = () => data.description || getHttpStatusDescription(data.statusCode);

  const hasContentTypes = data.contentTypes && data.contentTypes.length > 0;
  const hasContentTypesWithSchema =
    hasContentTypes &&
    data.contentTypes!.some(
      (ct) =>
        ct.class_name ||
        ct.class_id ||
        (ct.inline_schema && (ct.inline_schema.type || ct.inline_schema.$ref))
    );
  const hasInlineSchema =
    data.inlineSchema &&
    ((data.inlineSchema.properties?.length ?? 0) > 0 ||
      data.inlineSchema.type ||
      data.inlineSchema.$ref);
  const hasAttachedClass = !!data.attachedClassName;
  const hasHeaders = data.headers && data.headers.length > 0;
  const hasLinks = data.links && data.links.length > 0;

  const showInlineSchemaFirst =
    hasInlineSchema &&
    !hasAttachedClass &&
    data.inlineSchema?.type &&
    ['string', 'number', 'integer', 'boolean', 'null', 'array'].includes(data.inlineSchema.type);

  const sectionLabelStyle: React.CSSProperties = {
    fontSize: '9px',
    fontWeight: 600,
    color: 'var(--node-text-muted)',
    textTransform: 'uppercase',
    letterSpacing: '0.06em',
    marginTop: '10px',
    marginBottom: '3px',
  };

  const treeLineStyle: React.CSSProperties = {
    fontSize: '10px',
    color: 'var(--node-text-muted)',
    display: 'flex',
    alignItems: 'center',
    gap: '5px',
  };

  return (
    <>
      <NodeHandleDot type="target" position={Position.Top} id="response-input" color={accent} />

      <NodeCard
        role={role}
        minWidth={NODE_ATTACH_MIN_WIDTH_PX}
        maxWidth={NODE_ATTACH_MAX_WIDTH_PX}
        onDragOver={(e) => {
          e.stopPropagation();
          handleDragOver(e);
        }}
        onDragLeave={(e) => {
          e.stopPropagation();
          handleDragLeave(e);
        }}
        onDrop={(e) => {
          e.stopPropagation();
          handleDrop(e);
        }}
        isValidDropTarget={dragOver}
      >
        <NodeHeader
          role={role}
          customBackground={accent}
          customTextColor="#ffffff"
          icon={<Icon size={14} strokeWidth={2.5} />}
          iconSize={26}
          title={
            <div style={{ display: 'flex', alignItems: 'baseline', gap: '8px', minWidth: 0 }}>
              <span style={{ fontWeight: 700, fontSize: '13px', letterSpacing: '-0.02em', flexShrink: 0, fontFamily: 'var(--app-font-mono, monospace)' }}>
                {data.statusCode}
              </span>
              <span
                style={{
                  fontSize: '11px',
                  opacity: 0.88,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                  fontWeight: 500,
                }}
              >
                {getDescription()}
              </span>
            </div>
          }
          badges={
            data.onDelete ? (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  data.onDelete?.();
                }}
                title="Delete response"
                aria-label="Delete response"
                style={{
                  background: 'rgba(255, 255, 255, 0.18)',
                  border: 'none',
                  cursor: 'pointer',
                  padding: '3px',
                  borderRadius: '4px',
                  color: 'white',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  transition: 'background 0.12s ease',
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.background = 'rgba(255, 255, 255, 0.32)';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = 'rgba(255, 255, 255, 0.18)';
                }}
              >
                <Trash2 size={11} />
              </button>
            ) : undefined
          }
        />

        <div style={{ padding: '10px 12px' }}>
          <div style={sectionLabelStyle}>Content type map</div>

          {showInlineSchemaFirst ? (
            (() => {
              const schemaDisplay = getSchemaDisplayText(data.inlineSchema);
              return (
                <div>
                  <div style={treeLineStyle}>
                    <span style={{ color: 'var(--node-text-subtle)' }}>○</span>
                    <span style={{ fontFamily: 'var(--app-font-mono, monospace)', fontSize: '10px' }}>
                      application/json
                    </span>
                  </div>
                  <div style={{ ...treeLineStyle, marginLeft: '10px', marginTop: '2px' }}>
                    <CornerDownRight size={10} style={{ color: 'var(--node-text-subtle)', marginRight: '2px', flexShrink: 0 }} />
                    <span style={{ fontFamily: 'var(--app-font-mono, monospace)', color: '#b45309', fontWeight: 600 }}>
                      {schemaDisplay.text || data.inlineSchema?.type}
                    </span>
                  </div>
                </div>
              );
            })()
          ) : hasContentTypesWithSchema ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
              {data.contentTypes!.map((ct) => {
                const schemaDisplay = getSchemaDisplayText(ct.inline_schema);
                const hasSchema = ct.class_name || schemaDisplay.text;
                return (
                  <div key={ct.id}>
                    <div style={treeLineStyle}>
                      <span style={{ color: 'var(--node-text-subtle)' }}>○</span>
                      <span style={{ fontFamily: 'var(--app-font-mono, monospace)', fontSize: '10px' }}>
                        {ct.media_type}
                      </span>
                    </div>
                    {hasSchema && (
                      <div style={{ ...treeLineStyle, marginLeft: '10px', marginTop: '2px' }}>
                        <CornerDownRight size={10} style={{ color: 'var(--node-text-subtle)', marginRight: '2px', flexShrink: 0 }} />
                        {ct.class_name ? (
                          <>
                            <span style={{ color: 'var(--node-text-subtle)' }}>{'{ }'}</span>
                            <span style={{ color: 'var(--node-accent)', fontWeight: 600 }}>
                              {ct.class_name}
                            </span>
                          </>
                        ) : schemaDisplay.isObject ? (
                          <>
                            <span style={{ color: 'var(--node-text-subtle)' }}>{'{ }'}</span>
                            <span style={{ color: 'var(--node-success)', fontWeight: 600 }}>
                              {schemaDisplay.text}
                            </span>
                          </>
                        ) : (
                          <span style={{ fontFamily: 'var(--app-font-mono, monospace)', color: '#b45309', fontWeight: 600 }}>
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
                <div>
                  <div style={treeLineStyle}>
                    <span style={{ color: 'var(--node-text-subtle)' }}>○</span>
                    <span style={{ fontFamily: 'var(--app-font-mono, monospace)', fontSize: '10px' }}>
                      application/json
                    </span>
                  </div>
                  <div style={{ ...treeLineStyle, marginLeft: '10px', marginTop: '2px' }}>
                    <CornerDownRight size={10} style={{ color: 'var(--node-text-subtle)', marginRight: '2px', flexShrink: 0 }} />
                    {schemaDisplay.isObject ? (
                      <>
                        <span style={{ color: 'var(--node-text-subtle)' }}>{'{ }'}</span>
                        <span style={{ color: 'var(--node-success)', fontWeight: 600 }}>
                          {schemaDisplay.text ||
                            `Object (${data.inlineSchema?.properties?.length || 0} props)`}
                        </span>
                      </>
                    ) : schemaDisplay.text ? (
                      <span style={{ fontFamily: 'var(--app-font-mono, monospace)', color: '#b45309', fontWeight: 600 }}>
                        {schemaDisplay.text}
                      </span>
                    ) : (
                      <>
                        <span style={{ color: 'var(--node-text-subtle)' }}>{'{ }'}</span>
                        <span style={{ color: 'var(--node-success)', fontWeight: 600 }}>
                          Object ({data.inlineSchema?.properties?.length || 0} props)
                        </span>
                      </>
                    )}
                  </div>
                </div>
              );
            })()
          ) : hasAttachedClass ? (
            <div>
              <div style={treeLineStyle}>
                <span style={{ color: 'var(--node-text-subtle)' }}>○</span>
                <span style={{ fontFamily: 'var(--app-font-mono, monospace)', fontSize: '10px' }}>
                  application/json
                </span>
              </div>
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  marginLeft: '10px',
                  marginTop: '2px',
                }}
              >
                <div style={treeLineStyle}>
                  <CornerDownRight size={10} style={{ color: 'var(--node-text-subtle)', marginRight: '2px', flexShrink: 0 }} />
                  <span style={{ color: 'var(--node-text-subtle)' }}>{'{ }'}</span>
                  <span style={{ color: 'var(--node-accent)', fontWeight: 600 }}>
                    {data.attachedClassName}
                  </span>
                </div>
                {data.onClassUnlink && data.dbResponseId && (
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      data.onClassUnlink?.(data.dbResponseId!);
                    }}
                    title={`Unlink ${data.attachedClassName} from response`}
                    style={{
                      background: 'transparent',
                      border: 'none',
                      cursor: 'pointer',
                      padding: '2px',
                      color: 'var(--node-text-subtle)',
                    }}
                  >
                    <Unlink size={10} />
                  </button>
                )}
              </div>
            </div>
          ) : (
            <div
              style={{
                fontSize: '10px',
                color: dragOver ? 'var(--node-accent)' : 'var(--node-text-subtle)',
                fontWeight: dragOver ? 500 : 400,
              }}
            >
              {dragOver ? 'Drop to set schema' : 'Drop class or property to set schema'}
            </div>
          )}

          {data.linkedOperations && data.linkedOperations.length > 0 && (
            <>
              <div style={sectionLabelStyle}>Linked to</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                {data.linkedOperations.map((op) => (
                  <div
                    key={op.id}
                    style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      fontSize: '10px',
                      background: 'var(--node-surface-muted)',
                      borderRadius: '4px',
                      padding: '3px 8px',
                    }}
                  >
                    <span style={{ fontWeight: 500, color: 'var(--node-text)' }}>{op.operation}</span>
                    {data.onUnlink && (
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          data.onUnlink?.(op.id);
                        }}
                        title={`Unlink from ${op.operation}`}
                        style={{
                          background: 'transparent',
                          border: 'none',
                          cursor: 'pointer',
                          padding: '1px',
                          color: 'var(--node-text-subtle)',
                        }}
                      >
                        <Unlink size={10} />
                      </button>
                    )}
                  </div>
                ))}
              </div>
            </>
          )}

          <div style={sectionLabelStyle}>Headers</div>
          {hasHeaders ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1px' }}>
              {data.headers!.map((header, idx) => (
                <div
                  key={idx}
                  style={{
                    fontSize: '10px',
                    color: 'var(--node-text-muted)',
                    display: 'flex',
                    gap: '5px',
                    alignItems: 'center',
                  }}
                >
                  <span style={{ fontFamily: 'var(--app-font-mono, monospace)' }}>{header.name}</span>
                  {header.schema?.type && (
                    <span style={{ color: 'var(--node-text-subtle)', fontFamily: 'var(--app-font-mono, monospace)' }}>
                      ({header.schema.type}
                      {header.schema.format ? `, ${header.schema.format}` : ''})
                    </span>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <div style={{ fontSize: '10px', color: 'var(--node-text-subtle)', fontStyle: 'italic' }}>
              (none)
            </div>
          )}

          <div style={sectionLabelStyle}>Links</div>
          {hasLinks ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1px' }}>
              {data.links!.map((link, idx) => (
                <div key={idx} style={{ fontSize: '10px', color: 'var(--node-text-muted)' }}>
                  <div style={{ display: 'flex', gap: '5px', alignItems: 'center', flexWrap: 'wrap' }}>
                    <span style={{ fontFamily: 'var(--app-font-mono, monospace)' }}>{link.name}</span>
                    {(link.operationId || link.operationRef) && (
                      <span
                        style={{
                          color: 'var(--node-text-subtle)',
                          fontFamily: 'var(--app-font-mono, monospace)',
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          maxWidth: '130px',
                        }}
                      >
                        → {link.operationId || link.operationRef}
                      </span>
                    )}
                  </div>
                  {link.parameters && Object.keys(link.parameters).length > 0 && (
                    <div
                      title={Object.entries(link.parameters)
                        .map(([k, v]) => `${k}: ${v}`)
                        .join(', ')}
                      style={{
                        marginLeft: '8px',
                        fontSize: '9px',
                        color: 'var(--node-text-subtle)',
                        fontFamily: 'var(--app-font-mono, monospace)',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                      }}
                    >
                      {Object.entries(link.parameters)
                        .slice(0, 2)
                        .map(([k, v]) => `${k}: ${v}`)
                        .join(', ')}
                      {Object.keys(link.parameters).length > 2 ? '…' : ''}
                    </div>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <div style={{ fontSize: '10px', color: 'var(--node-text-subtle)', fontStyle: 'italic' }}>
              (none)
            </div>
          )}
        </div>
      </NodeCard>

      <NodeHandleDot
        type="source"
        position={Position.Bottom}
        id="response-class-output"
        color={accent}
        style={{ opacity: data.attachedClassId ? 1 : 0.6 }}
      />
    </>
  );
}
