'use client';

import * as React from 'react';
import { Handle, Position, type NodeProps } from '@xyflow/react';
import { ArrowRight, ArrowLeft } from 'lucide-react';
import { NodeCard } from '../../../components/ade/canvas/NodeCard';
import { NodeHeader } from '../../../components/ade/canvas/NodeHeader';
import { accentVar, type NodeAccentRole } from '../../../components/ade/canvas/canvas-theme';

export interface MigrationClassNodeData {
  className: string;
  properties: Array<{ name: string; type?: string }>;
  side: 'from' | 'to';
}

function MigrationClassNode(props: NodeProps) {
  const data = props.data as unknown as MigrationClassNodeData;
  const { className, properties, side } = data;
  const isFrom = side === 'from';
  const role: NodeAccentRole = isFrom ? 'from' : 'to';
  const accent = accentVar(role);

  return (
    <NodeCard role={role} minWidth={210} maxWidth={290} selected={props.selected}>
      <NodeHeader
        role={role}
        icon={isFrom ? <ArrowRight size={14} strokeWidth={2.5} /> : <ArrowLeft size={14} strokeWidth={2.5} />}
        iconSize={26}
        compact
        title={
          <div style={{ display: 'flex', alignItems: 'baseline', gap: '6px', minWidth: 0 }}>
            <span
              style={{
                fontSize: '9px',
                fontWeight: 700,
                letterSpacing: '0.06em',
                textTransform: 'uppercase',
                color: 'var(--node-text-muted)',
                flexShrink: 0,
              }}
            >
              {isFrom ? 'From' : 'To'}
            </span>
            <span
              style={{
                fontSize: '13px',
                fontWeight: 600,
                color: 'var(--node-text)',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
              }}
              title={className}
            >
              {className}
            </span>
          </div>
        }
      />
      <div style={{ padding: '6px 10px 8px' }}>
        {properties.length === 0 ? (
          <p
            style={{
              fontSize: '11px',
              color: 'var(--node-text-subtle)',
              fontStyle: 'italic',
              margin: 0,
            }}
          >
            No properties
          </p>
        ) : (
          <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column' }}>
            {properties.map((p) => (
              <li
                key={p.name}
                style={{
                  position: 'relative',
                  display: 'flex',
                  alignItems: 'baseline',
                  justifyContent: 'space-between',
                  gap: '10px',
                  minHeight: '22px',
                  padding: '3px 2px',
                  borderBottom: '1px solid var(--node-border-muted)',
                }}
              >
                <span
                  style={{
                    fontSize: '12px',
                    fontWeight: 500,
                    color: 'var(--node-text)',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}
                  title={p.name}
                >
                  {p.name}
                </span>
                {p.type != null && p.type !== '' ? (
                  <span
                    style={{
                      fontSize: '10px',
                      color: 'var(--node-text-muted)',
                      fontFamily: 'var(--app-font-mono, monospace)',
                      flexShrink: 0,
                    }}
                  >
                    {p.type}
                  </span>
                ) : (
                  <span style={{ flexShrink: 0 }} />
                )}
                <Handle
                  type={isFrom ? 'source' : 'target'}
                  position={isFrom ? Position.Right : Position.Left}
                  id={`prop-${p.name}`}
                  style={{
                    background: accent,
                    width: 9,
                    height: 9,
                    minWidth: 0,
                    minHeight: 0,
                    border: '1.5px solid var(--node-surface)',
                    borderRadius: '50%',
                    top: '50%',
                    transform: 'translateY(-50%)',
                    [isFrom ? 'right' : 'left']: -16,
                  }}
                  isConnectable={false}
                />
              </li>
            ))}
          </ul>
        )}
      </div>
    </NodeCard>
  );
}

export default MigrationClassNode;
