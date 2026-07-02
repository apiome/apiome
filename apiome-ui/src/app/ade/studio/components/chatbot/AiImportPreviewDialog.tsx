'use client';

import * as React from 'react';

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/app/components/ui/Dialog';
import type { DetectedOpenApiSpec } from './openapi-detection';

export interface AiImportPreviewDialogProps {
  open: boolean;
  spec: DetectedOpenApiSpec | null;
  onOpenChange: (open: boolean) => void;
  onConfirmApply: () => void;
}

function summarizeOpenApi(spec: Record<string, unknown>) {
  const info =
    spec.info && typeof spec.info === 'object' && !Array.isArray(spec.info)
      ? (spec.info as Record<string, unknown>)
      : null;
  const title = typeof info?.title === 'string' ? info.title : 'Untitled';
  const infoVersion = typeof info?.version === 'string' ? info.version : null;
  const openapi =
    typeof spec.openapi === 'string'
      ? spec.openapi
      : typeof spec.swagger === 'string'
        ? `Swagger ${spec.swagger}`
        : null;
  let pathCount = 0;
  if (spec.paths && typeof spec.paths === 'object' && !Array.isArray(spec.paths)) {
    pathCount = Object.keys(spec.paths as Record<string, unknown>).length;
  }
  let schemaCount = 0;
  const components = spec.components;
  if (components && typeof components === 'object' && !Array.isArray(components)) {
    const schemas = (components as Record<string, unknown>).schemas;
    if (schemas && typeof schemas === 'object' && !Array.isArray(schemas)) {
      schemaCount = Object.keys(schemas as Record<string, unknown>).length;
    }
  }
  return { title, infoVersion, openapi, pathCount, schemaCount };
}

export function AiImportPreviewDialog({
  open,
  spec,
  onOpenChange,
  onConfirmApply,
}: AiImportPreviewDialogProps) {
  const pretty = React.useMemo(() => {
    if (!spec) return '';
    try {
      return JSON.stringify(spec.spec, null, 2);
    } catch {
      return spec.raw;
    }
  }, [spec]);

  const summary = React.useMemo(() => (spec ? summarizeOpenApi(spec.spec) : null), [spec]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        data-testid="studio-ai-chat-import-preview-dialog"
        className="flex max-h-[90vh] max-w-3xl flex-col gap-0 overflow-hidden p-0 sm:max-w-3xl"
      >
        <div className="border-b border-gray-200 px-6 py-4 dark:border-gray-700">
          <DialogHeader className="space-y-2 text-left">
            <DialogTitle>Preview import</DialogTitle>
            <DialogDescription className="text-left">
              Review this OpenAPI document before it is applied. Cancel to return to the chat with no
              changes.
            </DialogDescription>
          </DialogHeader>
          {summary && (
            <dl className="mt-3 grid gap-1 text-xs text-gray-600 dark:text-gray-400 sm:grid-cols-2">
              <div className="flex flex-wrap gap-x-2">
                <dt className="font-medium text-gray-700 dark:text-gray-300">API title</dt>
                <dd>{summary.title}</dd>
              </div>
              {summary.openapi && (
                <div className="flex flex-wrap gap-x-2">
                  <dt className="font-medium text-gray-700 dark:text-gray-300">Document</dt>
                  <dd>{summary.openapi}</dd>
                </div>
              )}
              {summary.infoVersion && (
                <div className="flex flex-wrap gap-x-2">
                  <dt className="font-medium text-gray-700 dark:text-gray-300">Version</dt>
                  <dd>{summary.infoVersion}</dd>
                </div>
              )}
              <div className="flex flex-wrap gap-x-2">
                <dt className="font-medium text-gray-700 dark:text-gray-300">Paths</dt>
                <dd>{summary.pathCount}</dd>
              </div>
              <div className="flex flex-wrap gap-x-2">
                <dt className="font-medium text-gray-700 dark:text-gray-300">Component schemas</dt>
                <dd>{summary.schemaCount}</dd>
              </div>
            </dl>
          )}
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-3">
          <pre
            className="max-h-[min(50vh,28rem)] overflow-auto rounded-lg border border-gray-200 bg-gray-50 p-3 text-xs leading-relaxed text-gray-900 dark:border-gray-600 dark:bg-gray-950 dark:text-gray-100"
            data-testid="studio-ai-chat-import-preview-json"
          >
            {pretty}
          </pre>
        </div>

        <DialogFooter className="border-t border-gray-200 bg-gray-50 px-6 py-4 dark:border-gray-700 dark:bg-gray-900/80 sm:justify-end">
          <button
            type="button"
            data-testid="studio-ai-chat-import-preview-cancel"
            className="inline-flex h-9 items-center justify-center rounded-md border border-gray-300 bg-white px-4 text-sm font-medium text-gray-700 shadow-sm transition-colors hover:bg-gray-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-300 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-gray-700"
            onClick={() => onOpenChange(false)}
          >
            Cancel
          </button>
          <button
            type="button"
            data-testid="studio-ai-chat-import-preview-apply"
            className="inline-flex h-9 items-center justify-center rounded-md border border-transparent bg-indigo-600 px-4 text-sm font-medium text-white shadow-sm transition-colors hover:bg-indigo-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-300 dark:focus-visible:ring-indigo-500"
            onClick={() => {
              onConfirmApply();
            }}
          >
            Apply import
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
