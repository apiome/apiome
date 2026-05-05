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
import {
  parseClassDefinitionFromAssistantMarkdown,
  summarizeJsonSchemaProperties,
  type ParsedAiClassDefinition,
} from './assistant-action-detection';

export interface AiClassCreatePreviewDialogProps {
  open: boolean;
  assistantMarkdown: string | null;
  onOpenChange: (open: boolean) => void;
  onConfirmCreate: () => void;
}

export function AiClassCreatePreviewDialog({
  open,
  assistantMarkdown,
  onOpenChange,
  onConfirmCreate,
}: AiClassCreatePreviewDialogProps) {
  const parsed = React.useMemo<ParsedAiClassDefinition | null>(() => {
    if (!assistantMarkdown) return null;
    return parseClassDefinitionFromAssistantMarkdown(assistantMarkdown);
  }, [assistantMarkdown]);

  const schemaJson = React.useMemo(() => {
    if (!parsed) return '';
    try {
      return JSON.stringify(parsed.schema, null, 2);
    } catch {
      return '';
    }
  }, [parsed]);

  const propsList = React.useMemo(
    () => (parsed ? summarizeJsonSchemaProperties(parsed.schema) : []),
    [parsed],
  );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        data-testid="studio-ai-chat-class-create-preview-dialog"
        className="flex max-h-[90vh] max-w-3xl flex-col gap-0 overflow-hidden p-0 sm:max-w-3xl"
      >
        <div className="border-b border-gray-200 px-6 py-4 dark:border-gray-700">
          <DialogHeader className="space-y-2 text-left">
            <DialogTitle>Preview class schema</DialogTitle>
            <DialogDescription className="text-left">
              Review the class metadata, the suggested type for each property, and the formatted JSON Schema below before
              continuing. Cancel to return to the chat with no changes.
            </DialogDescription>
          </DialogHeader>
          {parsed ? (
            <dl className="mt-3 grid gap-1 text-xs text-gray-600 dark:text-gray-400 sm:grid-cols-2">
              <div className="flex flex-wrap gap-x-2">
                <dt className="font-medium text-gray-700 dark:text-gray-300">Class name</dt>
                <dd className="font-mono">{parsed.name}</dd>
              </div>
              <div className="flex flex-wrap gap-x-2 sm:col-span-2">
                <dt className="font-medium text-gray-700 dark:text-gray-300">Description</dt>
                <dd>{parsed.description?.trim() ? parsed.description : '—'}</dd>
              </div>
              <div className="sm:col-span-2">
                <dt className="font-medium text-gray-700 dark:text-gray-300">Properties (suggested types)</dt>
                <dd className="mt-1">
                  {propsList.length === 0 ? (
                    <span className="text-gray-500 dark:text-gray-500">No properties object</span>
                  ) : (
                    <ul className="m-0 max-h-40 list-inside list-disc overflow-y-auto pl-1">
                      {propsList.map((p) => (
                        <li key={p.name}>
                          <span className="font-mono">{p.name}</span>
                          <span className="text-gray-500 dark:text-gray-500"> — {p.suggestedType}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </dd>
              </div>
            </dl>
          ) : (
            <p className="mt-3 text-sm text-amber-800 dark:text-amber-200">
              Could not parse a class definition. Expected a ```json``` code block with{' '}
              <span className="font-mono">name</span> and <span className="font-mono">schema</span>.
            </p>
          )}
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-3">
          <div className="overflow-hidden rounded-lg border border-gray-200 dark:border-gray-600">
            <div className="border-b border-gray-200 bg-gray-100 px-3 py-1.5 dark:border-gray-700 dark:bg-gray-900">
              <span className="text-xs font-mono text-gray-700 dark:text-gray-300">
                {schemaJson ? 'JSON Schema' : 'Assistant response'}
              </span>
            </div>
            <pre
              className="max-h-[min(50vh,28rem)] overflow-auto bg-gray-50 p-3 text-xs leading-relaxed text-gray-900 dark:bg-gray-950 dark:text-gray-100"
              data-testid="studio-ai-chat-class-create-preview-json"
            >
              {schemaJson || assistantMarkdown || '—'}
            </pre>
          </div>
        </div>

        <DialogFooter className="border-t border-gray-200 bg-gray-50 px-6 py-4 dark:border-gray-700 dark:bg-gray-900/80 sm:justify-end">
          <button
            type="button"
            data-testid="studio-ai-chat-class-create-preview-cancel"
            className="inline-flex h-9 items-center justify-center rounded-md border border-gray-300 bg-white px-4 text-sm font-medium text-gray-700 shadow-sm transition-colors hover:bg-gray-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-300 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-gray-700"
            onClick={() => onOpenChange(false)}
          >
            Cancel
          </button>
          <button
            type="button"
            data-testid="studio-ai-chat-class-create-preview-confirm"
            disabled={!parsed}
            className="inline-flex h-9 items-center justify-center rounded-md border border-transparent bg-emerald-600 px-4 text-sm font-medium text-white shadow-sm transition-colors hover:bg-emerald-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400 disabled:pointer-events-none disabled:opacity-50 dark:focus-visible:ring-emerald-500"
            onClick={() => {
              if (!parsed) return;
              onConfirmCreate();
            }}
          >
            Continue to create
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
