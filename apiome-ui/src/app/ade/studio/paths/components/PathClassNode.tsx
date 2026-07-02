// Path Class Node Component for React Flow Canvas
'use client';

import React from 'react';
import { Layers, Trash2 } from 'lucide-react';
import { Position } from '@xyflow/react';
import { NodeCard } from '@/app/components/ade/canvas/NodeCard';
import { NodeHeader } from '@/app/components/ade/canvas/NodeHeader';
import { NodeHandleDot } from '@/app/components/ade/canvas/NodeHandleDot';
import { NodeBadge } from '@/app/components/ade/canvas/NodeBadge';
import { NODE_ATTACH_MIN_WIDTH_PX, NODE_ATTACH_MAX_WIDTH_PX } from './paths-theme';

export interface PathClassNodeData {
  className: string;
  classId: string;
  description?: string;
  dbClassId: string;
  onDelete?: () => void;
}

export default function PathClassNode({ data }: { data: PathClassNodeData }) {
  return (
    <div className="relative group">
      {data.onDelete && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            data.onDelete?.();
          }}
          className="absolute -top-2 -right-2 z-20 rounded-full p-1.5 opacity-0 group-hover:opacity-100 transition-opacity shadow-md bg-rose-500 hover:bg-rose-600 text-white"
          title="Remove class from canvas"
          aria-label="Remove class from canvas"
        >
          <Trash2 size={12} />
        </button>
      )}

      <NodeCard role="default" minWidth={NODE_ATTACH_MIN_WIDTH_PX} maxWidth={NODE_ATTACH_MAX_WIDTH_PX}>
        <NodeHandleDot type="target" position={Position.Top} id="class-input" role="default" />

        <NodeHeader
          role="default"
          icon={<Layers size={14} strokeWidth={2.5} />}
          iconSize={26}
          title={
            <div
              style={{
                fontSize: '13px',
                fontWeight: 600,
                letterSpacing: '-0.01em',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
                lineHeight: 1.3,
              }}
            >
              {data.className}
            </div>
          }
          badges={<NodeBadge variant="info">Class</NodeBadge>}
        />

        <div
          style={{
            padding: '8px 12px',
            fontSize: '11px',
            lineHeight: 1.45,
            color: data.description ? 'var(--node-text-muted)' : 'var(--node-text-subtle)',
            fontStyle: data.description ? 'normal' : 'italic',
            background: 'var(--node-surface)',
            display: '-webkit-box',
            WebkitLineClamp: 2,
            WebkitBoxOrient: 'vertical',
            overflow: 'hidden',
          }}
        >
          {data.description || 'No description'}
        </div>

        <NodeHandleDot type="source" position={Position.Bottom} id="class-output" role="default" />
      </NodeCard>
    </div>
  );
}
