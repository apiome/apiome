// Path Parameter Node Component for React Flow Canvas
// Design based on section 9.3.3 of PLANNED_FEATURE_ROADMAP_PATHS.md
'use client';

import React from 'react';
import { Trash2 } from 'lucide-react';
import { Handle, Position } from '@xyflow/react';

/** Serialization style for the parameter (OpenAPI 3.0; default "form") */
export type ParamSerializationStyle = 'form' | 'spaceDelimited' | 'pipeDelimited' | 'deepObject';

export interface PathParameterData {
  name: string;
  inLocation: 'path' | 'query' | 'header' | 'cookie';
  summary?: string;
  description?: string;
  required?: boolean;
  type?: string;
  format?: string;
  defaultValue?: string | number | boolean;
  /** Serialization style (default form) */
  style?: ParamSerializationStyle;
  /** Explode arrays/objects (OpenAPI 3.0) */
  explode?: boolean;
  dbParameterId?: string;
  operationId?: string;
  onDelete?: () => void;
}

// Configuration for each parameter location type per 9.3.3 spec
const LOCATION_CONFIG = {
  path: {
    color: '#22c55e', // Green for path params
    icon: ':',
    borderClass: 'border-green-500',
    textClass: 'text-green-600 dark:text-green-400',
  },
  query: {
    color: '#3b82f6', // Blue for query params
    icon: '?',
    borderClass: 'border-blue-500',
    textClass: 'text-blue-600 dark:text-blue-400',
  },
  header: {
    color: '#a855f7', // Purple for header params
    icon: 'H',
    borderClass: 'border-purple-500',
    textClass: 'text-purple-600 dark:text-purple-400',
  },
  cookie: {
    color: '#f97316', // Orange for cookie params
    icon: '🍪',
    borderClass: 'border-orange-500',
    textClass: 'text-orange-600 dark:text-orange-400',
  },
};

export default function PathParameterNode({ data }: { data: PathParameterData }) {
  const config = LOCATION_CONFIG[data.inLocation] || LOCATION_CONFIG.query;

  // Build the type string (e.g., "string (uuid)" or "integer")
  const typeString = data.format
    ? `${data.type || 'string'} (${data.format})`
    : (data.type || 'string');

  // Build the required/optional string
  const requiredString = data.required ? 'required' : 'optional';

  // Check if we have a default value
  const hasDefault = data.defaultValue !== undefined && data.defaultValue !== null && data.defaultValue !== '';

  return (
    <>
      {/* Connection handle at TOP */}
      <Handle
        type="target"
        position={Position.Top}
        id="parameter-input"
        className="!w-3 !h-2 !rounded-t-md !rounded-b-none"
        style={{ backgroundColor: config.color }}
      />

      <div className={`bg-white dark:bg-gray-800 rounded-lg border-2 ${config.borderClass} shadow-md min-w-[180px] max-w-[240px] cursor-pointer relative`}>
        {/* Delete button */}
        {data.onDelete && (
          <button
            onClick={(e) => {
              e.stopPropagation();
              data.onDelete?.();
            }}
            className="absolute top-2 right-2 rounded p-1 text-gray-600 dark:text-white hover:opacity-80 z-10"
            title="Delete parameter"
          >
            <Trash2 size={12} />
          </button>
        )}

        {/* Content - compact chip design per 9.3.3 */}
        <div className="px-3 py-2">
          {/* First line: Icon + Parameter name */}
          <div className="flex items-center gap-2">
            <span className={`font-mono font-bold text-sm ${config.textClass}`}>
              {config.icon}
            </span>
            <span className="font-semibold text-sm text-gray-900 dark:text-gray-100 truncate">
              {data.name}
            </span>
          </div>

          {/* Second line: type · required/optional */}
          <div className="mt-1 text-xs text-gray-500 dark:text-gray-400">
            <span className="font-mono">{typeString}</span>
            <span className="mx-1">·</span>
            <span className={data.required ? 'text-red-500 dark:text-red-400 font-medium' : ''}>
              {requiredString}
            </span>
          </div>

          {/* Third line: default value (if present) */}
          {hasDefault && (
            <div className="mt-1 text-xs text-gray-500 dark:text-gray-400">
              <span>default: </span>
              <span className="font-mono text-gray-700 dark:text-gray-300">
                {String(data.defaultValue)}
              </span>
            </div>
          )}

          {/* Fourth line: in: location (for non-path params) */}
          {data.inLocation !== 'path' && (
            <div className="mt-1 text-xs text-gray-400 dark:text-gray-500">
              <span>in: {data.inLocation}</span>
            </div>
          )}

          {/* Style line: serialization style (show when set; default is form) */}
          <div className="mt-1 text-xs text-gray-400 dark:text-gray-500">
            <span>style: {data.style ?? 'form'}</span>
            {data.explode && <span className="ml-1.5">· explode</span>}
          </div>

          {/* Description (if present) */}
          {data.description && data.description.trim() !== '' && (
            <div className="mt-1 text-xs text-gray-500 dark:text-gray-400 line-clamp-2" title={data.description}>
              {data.description}
            </div>
          )}
        </div>
      </div>

      {/* Output handle at BOTTOM */}
      <Handle
        type="source"
        position={Position.Bottom}
        id="parameter-output"
        className="!w-3 !h-2 !rounded-b-md !rounded-t-none"
        style={{ backgroundColor: config.color }}
      />
    </>
  );
}

