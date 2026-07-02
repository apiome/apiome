// Path Parameter Node Component for React Flow Canvas
// Plan 2.4: Small chips/tags color-coded by parameter location.
'use client';

import React from 'react';
import { Trash2, Braces } from 'lucide-react';
import { Position } from '@xyflow/react';
import type { ParamSerializationStyle } from '../../../../../../lib/utils/openapi-parameter-style';
import { NodeHandleDot } from '@/app/components/ade/canvas/NodeHandleDot';

export type { ParamSerializationStyle } from '../../../../../../lib/utils/openapi-parameter-style';

export interface PathParameterData {
  name: string;
  inLocation: 'path' | 'query' | 'header' | 'cookie';
  summary?: string;
  description?: string;
  required?: boolean;
  type?: string;
  format?: string;
  defaultValue?: string | number | boolean;
  style?: ParamSerializationStyle;
  explode?: boolean;
  dbParameterId?: string;
  operationId?: string;
  onDelete?: () => void;
}

// Color-per-location — the chip uses a tinted surface + the role color for border/text.
const LOCATION_CONFIG = {
  path: {
    color: '#16a34a',
    bg: 'color-mix(in srgb, #16a34a 10%, var(--node-surface))',
    border: 'color-mix(in srgb, #16a34a 45%, transparent)',
    text: '#15803d',
    icon: 'braces' as const,
  },
  query: {
    color: '#2563eb',
    bg: 'color-mix(in srgb, #2563eb 10%, var(--node-surface))',
    border: 'color-mix(in srgb, #2563eb 45%, transparent)',
    text: '#1d4ed8',
    icon: 'query' as const,
  },
  header: {
    color: '#9333ea',
    bg: 'color-mix(in srgb, #9333ea 10%, var(--node-surface))',
    border: 'color-mix(in srgb, #9333ea 45%, transparent)',
    text: '#7e22ce',
    icon: 'header' as const,
  },
  cookie: {
    color: '#ea580c',
    bg: 'color-mix(in srgb, #ea580c 10%, var(--node-surface))',
    border: 'color-mix(in srgb, #ea580c 45%, transparent)',
    text: '#c2410c',
    icon: 'cookie' as const,
  },
};

function LocationIcon({
  location,
  color,
}: {
  location: keyof typeof LOCATION_CONFIG;
  color: string;
}) {
  const icon = LOCATION_CONFIG[location].icon;
  if (icon === 'braces') {
    return <Braces size={12} strokeWidth={2.5} style={{ color, flexShrink: 0 }} />;
  }
  if (icon === 'query') {
    return (
      <span
        style={{
          fontFamily: 'var(--app-font-mono, ui-monospace, SFMono-Regular, Menlo, monospace)',
          fontWeight: 700,
          fontSize: '12px',
          color,
          lineHeight: 1,
        }}
      >
        ?
      </span>
    );
  }
  if (icon === 'header') {
    return (
      <span style={{ fontWeight: 700, fontSize: '10px', letterSpacing: '0.04em', color }}>H</span>
    );
  }
  return (
    <span style={{ fontWeight: 700, fontSize: '10px', letterSpacing: '0.04em', color }}>C</span>
  );
}

export default function PathParameterNode({ data }: { data: PathParameterData }) {
  const config = LOCATION_CONFIG[data.inLocation] || LOCATION_CONFIG.query;

  const typeString = data.format
    ? `${data.type || 'string'} (${data.format})`
    : data.type || 'string';
  const requiredString = data.required ? 'required' : 'optional';
  const hasDefault =
    data.defaultValue !== undefined && data.defaultValue !== null && data.defaultValue !== '';

  const tooltipLines = [
    `${data.name} · ${typeString} · ${requiredString}`,
    data.inLocation !== 'path' && `in: ${data.inLocation}`,
    hasDefault && `default: ${String(data.defaultValue)}`,
    data.style && data.style !== 'form' && `style: ${data.style}`,
    data.explode && 'explode',
    data.description?.trim(),
  ].filter(Boolean);

  return (
    <>
      <NodeHandleDot
        type="target"
        position={Position.Top}
        id="parameter-input"
        color={config.color}
        size={7}
      />

      <div
        title={tooltipLines.join('\n')}
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: '6px',
          padding: '3px 8px',
          borderRadius: '6px',
          background: config.bg,
          border: `1px solid ${config.border}`,
          maxWidth: '200px',
          cursor: 'pointer',
          boxShadow: 'var(--node-shadow-sm)',
        }}
      >
        <LocationIcon location={data.inLocation} color={config.color} />
        <span
          style={{
            fontSize: '11px',
            fontWeight: 500,
            color: config.text,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
            letterSpacing: '-0.01em',
          }}
        >
          {data.name}
        </span>
        {data.required && (
          <span
            aria-label="required"
            title="required"
            style={{
              color: 'var(--node-danger)',
              fontSize: '11px',
              fontWeight: 700,
              lineHeight: 1,
              flexShrink: 0,
            }}
          >
            *
          </span>
        )}
        {data.onDelete && (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              data.onDelete?.();
            }}
            title="Delete parameter"
            aria-label="Delete parameter"
            style={{
              background: 'transparent',
              border: 'none',
              cursor: 'pointer',
              padding: '2px',
              borderRadius: '3px',
              color: 'var(--node-text-subtle)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              opacity: 0.7,
              transition: 'opacity 0.12s ease, color 0.12s ease',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.opacity = '1';
              e.currentTarget.style.color = 'var(--node-danger)';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.opacity = '0.7';
              e.currentTarget.style.color = 'var(--node-text-subtle)';
            }}
          >
            <Trash2 size={10} />
          </button>
        )}
      </div>

      <NodeHandleDot
        type="source"
        position={Position.Bottom}
        id="parameter-output"
        color={config.color}
        size={7}
      />
    </>
  );
}
