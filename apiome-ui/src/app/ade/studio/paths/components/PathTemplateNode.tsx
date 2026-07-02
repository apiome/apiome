'use client';

import React, { memo, useState, useEffect, useCallback } from 'react';
import { Position, type NodeProps } from '@xyflow/react';
import { updatePath } from '../../../../../../lib/api/paths-client';
import { getSharedPathParameters } from '../../../../../../lib/db/helper-shared-path-parameters';
import {
  getPathParameterCoverageError,
  getPathTemplateValidationError,
} from '../../../../../../lib/utils/path-params';
import { Route } from 'lucide-react';
import { NodeCard } from '@/app/components/ade/canvas/NodeCard';
import { NodeHeader } from '@/app/components/ade/canvas/NodeHeader';
import { NodeHandleDot } from '@/app/components/ade/canvas/NodeHandleDot';

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
    <NodeCard role="path" selected={selected} minWidth={280} maxWidth={360}>
      <NodeHeader
        role="path"
        icon={<Route size={14} strokeWidth={2.5} />}
        title={
          <div
            style={{
              fontSize: '10px',
              fontWeight: 600,
              letterSpacing: '0.06em',
              textTransform: 'uppercase',
              color: 'var(--node-text-muted)',
            }}
          >
            Path template
          </div>
        }
      />
      <div style={{ padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: '6px' }}>
        <label
          htmlFor={`path-template-input-${d.versionPathId}`}
          style={{ fontSize: '10px', fontWeight: 600, color: 'var(--node-text-muted)', letterSpacing: '0.02em' }}
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
          spellCheck={false}
          autoComplete="off"
          style={{
            width: '100%',
            fontFamily: 'var(--app-font-mono, ui-monospace, SFMono-Regular, Menlo, monospace)',
            fontSize: '12px',
            padding: '6px 8px',
            borderRadius: '6px',
            border: `1px solid ${error ? 'var(--node-danger)' : 'var(--node-border)'}`,
            background: 'var(--node-surface)',
            color: 'var(--node-text)',
            outline: 'none',
          }}
        />
        {error && (
          <p style={{ fontSize: '10px', color: 'var(--node-danger)', margin: 0 }}>{error}</p>
        )}
        {saving && (
          <p style={{ fontSize: '10px', color: 'var(--node-text-muted)', margin: 0 }}>Saving...</p>
        )}
        <p style={{ fontSize: '10px', color: 'var(--node-text-subtle)', margin: 0, lineHeight: 1.4 }}>
          Start with /; use {'{name}'} for parameters. Names must be unique.
        </p>
      </div>
      <NodeHandleDot
        type="source"
        position={Position.Bottom}
        id="path-output"
        role="path"
      />
    </NodeCard>
  );
}

export default memo(PathTemplateNode);
