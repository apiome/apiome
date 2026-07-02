import React from 'react';
import { Handle, Position, type HandleType } from '@xyflow/react';
import { accentVar, CANVAS_TOKENS, type NodeAccentRole } from './canvas-theme';

/**
 * NodeHandleDot — canonical react-flow handle used across all canvas nodes.
 *
 * Standardizes size, border, shadow, and role-based color. Pass the `role` to
 * pick an accent (e.g. 'ref' for property $ref handles, 'comp-all' for allOf
 * composition, 'from'/'to' for migration). Override via inline style when
 * the node has a custom user-chosen color.
 */
export interface NodeHandleDotProps {
  type: HandleType;
  position: Position;
  id?: string;
  role?: NodeAccentRole;
  /** Explicit color (overrides role). Accepts any CSS color. */
  color?: string;
  size?: number;
  isConnectable?: boolean;
  /** Extra CSS to merge (e.g. positional overrides). */
  style?: React.CSSProperties;
  className?: string;
}

export const NodeHandleDot: React.FC<NodeHandleDotProps> = ({
  type,
  position,
  id,
  role = 'default',
  color,
  size = CANVAS_TOKENS.handleSize,
  isConnectable,
  style,
  className,
}) => {
  const bg = color ?? accentVar(role);
  return (
    <Handle
      type={type}
      position={position}
      id={id}
      isConnectable={isConnectable}
      className={className}
      style={{
        width: `${size}px`,
        height: `${size}px`,
        background: bg,
        border: '1.5px solid var(--node-surface)',
        borderRadius: '50%',
        boxShadow: '0 1px 2px rgba(15, 23, 42, 0.25)',
        ...style,
      }}
    />
  );
};

export default NodeHandleDot;
