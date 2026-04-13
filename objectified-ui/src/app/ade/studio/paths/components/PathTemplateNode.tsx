'use client';

import React, { memo, useState, useEffect, useCallback } from 'react';
import { Handle, Position, type NodeProps } from '@xyflow/react';
import { updatePath } from '../../../../../../lib/api/paths-client';
import { getSharedPathParameters } from '../../../../../../lib/db/helper-shared-path-parameters';
import { getPathParameterCoverageError, getPathTemplateValidationError } from '../../../../../../lib/utils/path-params';

export interface PathTemplateNodeData {
  versionPathId: string;
  versionId: string;
  pathname: string;
  onPathnameSaved?: (pathname: string) => void;
}

function PathTemplateNode({ data, selected }: NodeProps) {
  const d = data as unknown as PathTemplateNodeData;
  const [value, setValue] = useState(d.pathname);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setValue(d.pathname);
    setError(null);
  }, [d.pathname]);

  const commit = useCallback(async () => {
    const trimmed = value.trim();
    const validationError = getPathTemplateValidationError(trimmed);
    if (validationError) {
      setError(validationError);
      return;
    }

    try {
      const paramsRaw = await getSharedPathParameters(d.versionPathId);
      const paramsParsed = JSON.parse(paramsRaw) as {
        success?: boolean;
        parameters?: { name: string; in_location: string }[];
      };
      if (paramsParsed.success && paramsParsed.parameters) {
        const coverageError = getPathParameterCoverageError(trimmed, paramsParsed.parameters);
        if (coverageError) {
          setError(coverageError);
          return;
        }
      }
    } catch {
      setError('Could not validate path parameters against the template. Try again.');
      return;
    }

    if (trimmed === d.pathname.trim()) {
      setError(null);
      return;
    }
    setSaving(true);
    try {
      const result = await updatePath(d.versionId, d.versionPathId, { pathname: trimmed });
      if (!result.success || !result.data) {
        setError(result.error || 'Failed to save path');
        return;
      }
      setError(null);
      d.onPathnameSaved?.(result.data.pathname);
    } finally {
      setSaving(false);
    }
  }, [value, d]);

  return (
    <div
      className={`rounded-xl border-2 shadow-xl min-w-[280px] max-w-[360px] bg-white dark:bg-gray-800 ${
        selected ? 'ring-2 ring-indigo-400 ring-offset-2 dark:ring-offset-gray-900' : ''
      } border-indigo-500`}
    >
      <div className="bg-gradient-to-r from-indigo-600 to-violet-600 text-white px-3 py-2 rounded-t-lg">
        <div className="text-xs font-medium opacity-90">Path template</div>
      </div>
      <div className="p-3 space-y-2">
        <label
          htmlFor={`path-template-input-${d.versionPathId}`}
          className="block text-xs font-medium text-gray-600 dark:text-gray-400"
        >
          OpenAPI path
        </label>
        <input
          id={`path-template-input-${d.versionPathId}`}
          value={value}
          onChange={(e) => {
            setValue(e.target.value);
            setError(null);
          }}
          onBlur={() => {
            void commit();
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.currentTarget.blur();
            }
          }}
          disabled={saving}
          className="w-full font-mono text-sm px-2 py-1.5 rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100"
          spellCheck={false}
          autoComplete="off"
        />
        {error && <p className="text-xs text-red-600 dark:text-red-400">{error}</p>}
        {saving && <p className="text-xs text-gray-500 dark:text-gray-400">Saving…</p>}
        <p className="text-[10px] text-gray-500 dark:text-gray-400">
          Start with /; use {'{name}'} for parameters. Names must be unique.
        </p>
      </div>
      <Handle
        type="source"
        position={Position.Bottom}
        id="path-output"
        className="!bg-indigo-500 !border-2 !border-white dark:!border-gray-800 !w-3 !h-3"
      />
    </div>
  );
}

export default memo(PathTemplateNode);
