'use client';

import React, { useMemo } from 'react';
import {
  BaseEdge,
  EdgeProps,
  getBezierPath,
  getEdgeCenter,
  getSmoothStepPath,
  getStraightPath,
  useStore,
} from '@xyflow/react';

/** Invisible stroke width for easier edge hover (hit area) */
const HIT_AREA_STROKE = 20;

/**
 * Edge component that renders the same as React Flow's default/straight/smoothstep
 * but with a wider invisible path so the hover area is ~20px instead of 2–3px.
 */
const EdgeWithWideHit: React.FC<EdgeProps> = ({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  style = {},
  markerEnd,
  markerStart,
  label,
  labelStyle,
  labelBgStyle,
}) => {
  const edgeType = useStore((s) => s.edges.find((e) => e.id === id)?.type ?? 'default');

  const { path, labelX, labelY } = useMemo(() => {
    const params = {
      sourceX,
      sourceY,
      targetX,
      targetY,
      sourcePosition,
      targetPosition,
    };
    const [cx, cy] = getEdgeCenter({
      sourceX,
      sourceY,
      targetX,
      targetY,
    });
    if (edgeType === 'straight') {
      const [p] = getStraightPath(params);
      return { path: p, labelX: cx, labelY: cy };
    }
    if (edgeType === 'smoothstep') {
      const [p] = getSmoothStepPath({ ...params, borderRadius: 8 });
      return { path: p, labelX: cx, labelY: cy };
    }
    const [p, lx, ly] = getBezierPath(params);
    return { path: p, labelX: lx, labelY: ly };
  }, [edgeType, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition]);

  return (
    <>
      <BaseEdge
        id={id}
        path={path}
        markerEnd={markerEnd}
        markerStart={markerStart}
        style={style}
      />
      {/* Wider invisible path for easier hover */}
      <path
        d={path}
        fill="none"
        stroke="transparent"
        strokeWidth={HIT_AREA_STROKE}
        style={{ cursor: 'pointer' }}
      />
      {label != null && typeof label === 'string' && (() => {
        const width = Math.max(56, Math.min(180, label.length * 6.2 + 14));
        return (
          <g transform={`translate(${labelX}, ${labelY})`} style={{ pointerEvents: 'none' }}>
            <rect
              x={-width / 2}
              y={-9}
              width={width}
              height={18}
              rx={4}
              style={
                labelBgStyle ?? {
                  fill: 'var(--node-surface-muted)',
                  stroke: 'var(--node-border)',
                  strokeWidth: 1,
                }
              }
            />
            <text
              x={0}
              y={3}
              textAnchor="middle"
              style={
                labelStyle ?? {
                  fill: 'var(--node-text-muted)',
                  fontSize: 10,
                  fontWeight: 500,
                  letterSpacing: '-0.01em',
                  fontFamily: 'var(--app-font-mono, ui-monospace, SFMono-Regular, Menlo, monospace)',
                }
              }
              className="react-flow__edge-text"
            >
              {label}
            </text>
          </g>
        );
      })()}
    </>
  );
};

export default EdgeWithWideHit;
