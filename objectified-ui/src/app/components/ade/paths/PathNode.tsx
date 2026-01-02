'use client';

import React, { memo } from 'react';
import { Handle, Position, NodeProps } from '@xyflow/react';

export interface PathNodeData {
  label: string;
  nodeType: 'path' | 'method' | 'parameter' | 'response';
  color?: string;
  // Database IDs
  dbPathId?: string; // ID in odb.api_paths
  dbOperationId?: string; // ID in odb.path_operations
  connectedPathId?: string; // For method nodes: which path they're connected to
  pendingDbSave?: boolean; // Flag for nodes that need to be saved to DB
  // Path-specific data
  path?: string;
  summary?: string;
  description?: string;
  tags?: string[];
  deprecated?: boolean;
  pathVariables?: PathVariable[];
  externalDocs?: ExternalDocs;
  // Method-specific data
  method?: string;
  operationId?: string;
  parameters?: any[];
  responses?: any[];
  // Allow additional properties
  [key: string]: unknown;
}

export interface ExternalDocs {
  url: string;
  description?: string;
}

export interface PathVariable {
  name: string;
  description: string;
  type: string;
  required: boolean;
  example?: string;
}

// Helper function to extract path variables from a path pattern
export function extractPathVariables(path: string): string[] {
  const regex = /\{([^}]+)\}/g;
  const variables: string[] = [];
  let match;
  while ((match = regex.exec(path)) !== null) {
    variables.push(match[1]);
  }
  return variables;
}

// Method color mapping
const METHOD_COLORS: Record<string, string> = {
  GET: '#22c55e',
  POST: '#3b82f6',
  PUT: '#f97316',
  DELETE: '#ef4444',
  PATCH: '#a855f7',
  HEAD: '#6b7280',
  OPTIONS: '#6b7280',
};

const PathNode: React.FC<NodeProps> = ({ data, selected }) => {
  const nodeData = data as unknown as PathNodeData;
  const { nodeType, label, color, path, method } = nodeData;

  // Determine the background color based on node type
  const getBackgroundStyle = () => {
    if (nodeType === 'method' && method) {
      return { background: METHOD_COLORS[method] || '#6b7280' };
    }
    if (nodeType === 'path') {
      return { background: 'linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%)' };
    }
    if (color) {
      // Parse Tailwind color class to actual color
      const colorMap: Record<string, string> = {
        'bg-green-500': '#22c55e',
        'bg-blue-500': '#3b82f6',
        'bg-orange-500': '#f97316',
        'bg-red-500': '#ef4444',
        'bg-purple-500': '#a855f7',
        'bg-gray-500': '#6b7280',
        'bg-yellow-500': '#eab308',
      };
      return { background: colorMap[color] || '#6366f1' };
    }
    return { background: '#6366f1' };
  };

  // Extract path variables for display
  const pathVars = path ? extractPathVariables(path) : [];

  return (
    <div
      className={`rounded-lg shadow-lg transition-all ${
        selected ? 'ring-2 ring-indigo-400 ring-offset-2 dark:ring-offset-gray-900' : ''
      } ${nodeData.deprecated ? 'opacity-75' : ''}`}
      style={{
        ...getBackgroundStyle(),
        minWidth: 150,
        padding: '10px 14px',
      }}
    >
      {/* Input handle - top (for method, parameter, response nodes) */}
      {(nodeType === 'method' || nodeType === 'parameter' || nodeType === 'response') && (
        <Handle
          type="target"
          position={Position.Top}
          className="!bg-white !border-2 !border-gray-400 !w-3 !h-3"
        />
      )}

      {/* Node content */}
      <div className="text-white">
        {nodeType === 'path' && (
          <>
            <div className="text-xs font-medium opacity-80 mb-1 flex items-center gap-2">
              PATH
              {nodeData.deprecated && (
                <span className="px-1.5 py-0.5 bg-red-500/80 text-white text-[10px] font-bold rounded uppercase">
                  Deprecated
                </span>
              )}
            </div>
            <div className={`font-mono text-sm font-semibold truncate max-w-[200px] ${nodeData.deprecated ? 'line-through decoration-2' : ''}`}>
              {path || label}
            </div>
            {pathVars.length > 0 && (
              <div className="flex flex-wrap gap-1 mt-2">
                {pathVars.map((v) => (
                  <span
                    key={v}
                    className={`px-1.5 py-0.5 bg-white/20 rounded text-xs font-mono ${nodeData.deprecated ? 'line-through' : ''}`}
                  >
                    {v}
                  </span>
                ))}
              </div>
            )}
          </>
        )}

        {nodeType === 'method' && (
          <>
            <div className="font-bold text-sm">{method || label}</div>
          </>
        )}

        {nodeType === 'parameter' && (
          <>
            <div className="text-xs font-medium opacity-80 mb-1">PARAM</div>
            <div className="font-medium text-sm">{label}</div>
          </>
        )}

        {nodeType === 'response' && (
          <>
            <div className="text-xs font-medium opacity-80 mb-1">RESPONSE</div>
            <div className="font-bold text-sm">{label}</div>
          </>
        )}
      </div>

      {/* Output handle - bottom (for path, method, parameter nodes) */}
      {(nodeType === 'path' || nodeType === 'method' || nodeType === 'parameter') && (
        <Handle
          type="source"
          position={Position.Bottom}
          className="!bg-white !border-2 !border-gray-400 !w-3 !h-3"
        />
      )}
    </div>
  );
};

export default memo(PathNode);

