// Path Response Node Component for React Flow Canvas
'use client';

import React from 'react';
import { CheckCircle, ArrowRight, AlertCircle, XCircle, Trash2 } from 'lucide-react';
import { Handle, Position } from '@xyflow/react';

export interface PathResponseData {
  statusCode: string;
  description?: string;
  dbResponseId?: string;
  operationId?: string;
  onDelete?: () => void;
}

// Get color and icon based on status code
const getStatusConfig = (statusCode: string) => {
  const firstChar = statusCode.charAt(0);

  switch (firstChar) {
    case '2':
      return {
        color: '#10b981',
        bgClass: 'bg-emerald-500',
        borderClass: 'border-emerald-500',
        icon: CheckCircle,
        label: 'Success',
      };
    case '3':
      return {
        color: '#3b82f6',
        bgClass: 'bg-blue-500',
        borderClass: 'border-blue-500',
        icon: ArrowRight,
        label: 'Redirect',
      };
    case '4':
      return {
        color: '#f59e0b',
        bgClass: 'bg-amber-500',
        borderClass: 'border-amber-500',
        icon: AlertCircle,
        label: 'Client Error',
      };
    case '5':
      return {
        color: '#ef4444',
        bgClass: 'bg-red-500',
        borderClass: 'border-red-500',
        icon: XCircle,
        label: 'Server Error',
      };
    default:
      return {
        color: '#6b7280',
        bgClass: 'bg-gray-500',
        borderClass: 'border-gray-500',
        icon: AlertCircle,
        label: 'Response',
      };
  }
};

export default function PathResponseNode({ data }: { data: PathResponseData }) {
  const config = getStatusConfig(data.statusCode);
  const Icon = config.icon;

  return (
    <>
      {/* Connection handle - receives FROM operations */}
      <Handle
        type="target"
        position={Position.Left}
        id="response-input"
        className="w-3 h-3 bg-gray-400 dark:bg-gray-600"
      />

      <div className={`bg-white dark:bg-gray-800 rounded-lg border-2 ${config.borderClass} shadow-lg min-w-[180px] max-w-[280px] cursor-pointer relative group`}>
        {/* Delete button */}
        {data.onDelete && (
          <button
            onClick={(e) => {
              e.stopPropagation();
              data.onDelete?.();
            }}
            className="absolute -top-2 -right-2 bg-red-500 text-white rounded-full p-1 opacity-0 group-hover:opacity-100 transition-opacity shadow-lg hover:bg-red-600 z-10"
            title="Delete response"
          >
            <Trash2 size={12} />
          </button>
        )}

        {/* Header */}
        <div className={`${config.bgClass} text-white px-3 py-2 rounded-t-md flex items-center gap-2`}>
          <div className="w-6 h-6 rounded flex items-center justify-center bg-white/20">
            <Icon className="w-4 h-4" />
          </div>
          <div className="flex-1">
            <div className="text-xs font-medium opacity-90">{config.label}</div>
            <div className="font-bold text-sm">{data.statusCode}</div>
          </div>
        </div>

        {/* Content */}
        <div className="p-3">
          {data.description ? (
            <div className="text-xs text-gray-700 dark:text-gray-300 line-clamp-3">
              {data.description}
            </div>
          ) : (
            <div className="text-xs text-gray-400 dark:text-gray-500 italic">
              No description
            </div>
          )}
        </div>
      </div>
    </>
  );
}

