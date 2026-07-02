'use client';

import { useMemo } from 'react';
import { Alert } from '@/app/components/ui/Alert';
import {
  extractRepositorySpecOriginalMetadata,
} from '@lib/project-draft-from-repository-spec';
import {
  formatMetadataCell,
  type ParsedRepositorySpecMetadata,
} from '@lib/repository-file-spec-metadata';
import { cn } from '@lib/utils';

function formatMetadataJson(value: unknown): string {
  if (value == null) return '—';
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

export default function RepositoryImportSpecMetadataPanel({
  content,
  path,
  specMetadata,
  truncated = false,
  className,
}: {
  content: string;
  path: string;
  specMetadata: ParsedRepositorySpecMetadata;
  truncated?: boolean;
  className?: string;
}) {
  const original = useMemo(
    () => extractRepositorySpecOriginalMetadata(content, path),
    [content, path]
  );

  const hasSpecContext = Object.keys(original.specContext).length > 0;
  const hasPayload = original.payload != null && Object.keys(original.payload).length > 0;

  return (
    <div className={cn('space-y-5', className)}>
      <Alert variant="info">
        This is a read-only view used only for reference. Values shown here come directly from the
        imported file and are not editable.
      </Alert>

      {truncated ? (
        <p className="text-xs text-amber-700 dark:text-amber-300">
          File body is truncated; metadata below reflects only the loaded portion.
        </p>
      ) : null}

      {original.parseError ? (
        <p className="text-sm text-amber-700 dark:text-amber-300">
          Could not parse as YAML/JSON: {original.parseError}
        </p>
      ) : null}

      <div className="rounded-xl border border-gray-200 bg-white p-5 dark:border-gray-700 dark:bg-gray-900/40">
        <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">Detected summary</h3>
        <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
          Client-side parse of <span className="font-mono">{path}</span>
        </p>
        {specMetadata.format === 'unknown' && !specMetadata.parseError ? (
          <p className="mt-3 text-sm text-gray-500 dark:text-gray-400">
            No recognised OpenAPI, Swagger, AsyncAPI, Arazzo, JSON Schema, or GraphQL SDL structure
            in this file.
          </p>
        ) : (
          <dl className="mt-4 space-y-2 text-sm">
            <div className="flex justify-between gap-2">
              <dt className="text-gray-500">Spec</dt>
              <dd className="max-w-[60%] text-right font-medium text-gray-900 dark:text-gray-100">
                {specMetadata.spec ?? '—'}
              </dd>
            </div>
            <div className="flex justify-between gap-2">
              <dt className="text-gray-500">Title</dt>
              <dd className="max-w-[60%] text-right font-medium text-gray-900 dark:text-gray-100">
                {specMetadata.title ?? '—'}
              </dd>
            </div>
            <div className="flex justify-between gap-2">
              <dt className="text-gray-500">Version</dt>
              <dd className="text-right font-mono text-xs text-gray-800 dark:text-gray-200">
                {specMetadata.version ?? '—'}
              </dd>
            </div>
            <div className="flex justify-between gap-2">
              <dt className="text-gray-500">Endpoints</dt>
              <dd className="text-right font-mono text-xs text-gray-800 dark:text-gray-200">
                {formatMetadataCell(specMetadata.endpoints)}
              </dd>
            </div>
            <div className="flex justify-between gap-2">
              <dt className="text-gray-500">Components</dt>
              <dd className="text-right font-mono text-xs text-gray-800 dark:text-gray-200">
                {formatMetadataCell(specMetadata.components)}
              </dd>
            </div>
            <div className="flex justify-between gap-2">
              <dt className="text-gray-500">Servers</dt>
              <dd className="text-right font-mono text-xs text-gray-800 dark:text-gray-200">
                {formatMetadataCell(specMetadata.servers)}
              </dd>
            </div>
          </dl>
        )}
      </div>

      {hasSpecContext ? (
        <div className="rounded-xl border border-gray-200 bg-white p-5 dark:border-gray-700 dark:bg-gray-900/40">
          <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">Spec context</h3>
          <pre className="mt-3 max-h-48 overflow-auto rounded-lg bg-gray-950 p-4 text-xs leading-relaxed text-gray-100">
            {formatMetadataJson(original.specContext)}
          </pre>
        </div>
      ) : null}

      <div className="rounded-xl border border-gray-200 bg-white p-5 dark:border-gray-700 dark:bg-gray-900/40">
        <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
          Original metadata
          {original.sectionLabel !== '—' ? (
            <span className="ml-2 font-mono text-xs font-normal text-gray-500 dark:text-gray-400">
              ({original.sectionLabel})
            </span>
          ) : null}
        </h3>
        {original.format === 'graphql' ? (
          <p className="mt-3 text-sm text-gray-500 dark:text-gray-400">
            GraphQL SDL files do not expose a structured metadata block like OpenAPI{' '}
            <span className="font-mono">info</span>. Use the detected summary above or switch to
            Form to enter project details manually.
          </p>
        ) : hasPayload ? (
          <pre
            className="mt-3 max-h-[min(40vh,420px)] overflow-auto rounded-lg bg-gray-950 p-4 text-xs leading-relaxed text-gray-100"
            data-testid="repository-import-spec-original-metadata"
          >
            {formatMetadataJson(original.payload)}
          </pre>
        ) : (
          <p className="mt-3 text-sm text-gray-500 dark:text-gray-400">
            No metadata block was found in this file for reference.
          </p>
        )}
      </div>

      {original.externalDocs && original.sectionLabel === 'info' ? (
        <div className="rounded-xl border border-gray-200 bg-white p-5 dark:border-gray-700 dark:bg-gray-900/40">
          <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
            Original externalDocs
          </h3>
          <pre className="mt-3 max-h-48 overflow-auto rounded-lg bg-gray-950 p-4 text-xs leading-relaxed text-gray-100">
            {formatMetadataJson(original.externalDocs)}
          </pre>
        </div>
      ) : null}
    </div>
  );
}
