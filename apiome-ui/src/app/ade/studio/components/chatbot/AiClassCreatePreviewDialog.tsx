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
  extractSuggestedRelationshipBulletsFromAssistantMarkdown,
  inferJsonSchemaRelationships,
  parseClassDefinitionFromAssistantMarkdown,
  summarizeJsonSchemaProperties,
  type ParsedAiClassDefinition,
} from './assistant-action-detection';

const REFINE_EXAMPLES = [
  'Add a phone number field',
  'Make email required',
  'Add validation for password length',
  'Include timestamps for audit',
] as const;

export interface AiClassCreatePreviewDialogProps {
  open: boolean;
  assistantMarkdown: string | null;
  onOpenChange: (open: boolean) => void;
  onConfirmCreate: () => void;
  /** While the assistant is refining the draft (#532). */
  refinementBusy?: boolean;
  /** Sends a refinement turn from the preview; transcript updates in the chat behind the modal. */
  onRequestRefinement?: (instruction: string) => void;
}

export function AiClassCreatePreviewDialog({
  open,
  assistantMarkdown,
  onOpenChange,
  onConfirmCreate,
  refinementBusy = false,
  onRequestRefinement,
}: AiClassCreatePreviewDialogProps) {
  const [refineText, setRefineText] = React.useState('');

  React.useEffect(() => {
    if (open) setRefineText('');
  }, [open, assistantMarkdown]);

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

  const hasPropertiesObject = React.useMemo(() => {
    if (!parsed) return false;
    const s = parsed.schema;
    return s !== null && typeof s === 'object' && !Array.isArray(s) && 'properties' in (s as object);
  }, [parsed]);

  const inferredRelationships = React.useMemo(
    () => (parsed ? inferJsonSchemaRelationships(parsed.schema) : []),
    [parsed],
  );

  const relationshipBullets = React.useMemo(
    () => (assistantMarkdown ? extractSuggestedRelationshipBulletsFromAssistantMarkdown(assistantMarkdown) : []),
    [assistantMarkdown],
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
              Review the class metadata, property types, relationship hints, and the formatted JSON Schema below before
              continuing. Use refine to iterate on the draft in chat; cancel leaves the workspace unchanged.
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
                    <span className="text-gray-500 dark:text-gray-500">
                      {hasPropertiesObject ? 'No properties defined' : 'No properties object'}
                    </span>
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
              <div className="sm:col-span-2">
                <dt className="font-medium text-gray-700 dark:text-gray-300">Relationships (from schema)</dt>
                <dd className="mt-1">
                  {inferredRelationships.length === 0 ? (
                    <span className="text-gray-500 dark:text-gray-500">
                      No $ref links on properties (direct or array items).
                    </span>
                  ) : (
                    <ul className="m-0 max-h-32 list-inside list-disc overflow-y-auto pl-1">
                      {inferredRelationships.map((r) => (
                        <li key={r.property}>
                          <span className="font-mono">{r.property}</span>
                          <span className="text-gray-500 dark:text-gray-500"> — {r.detail}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </dd>
              </div>
              {relationshipBullets.length > 0 ? (
                <div className="sm:col-span-2">
                  <dt className="font-medium text-gray-700 dark:text-gray-300">Suggested relationships</dt>
                  <dd className="mt-1">
                    <ul className="m-0 max-h-32 list-inside list-disc overflow-y-auto pl-1">
                      {relationshipBullets.map((line, i) => (
                        <li key={`${i}-${line.slice(0, 48)}`}>{line}</li>
                      ))}
                    </ul>
                  </dd>
                </div>
              ) : null}
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

        {onRequestRefinement && parsed ? (
          <div className="border-t border-gray-200 px-6 py-3 dark:border-gray-700">
            <p className="mb-2 text-xs font-medium text-gray-700 dark:text-gray-300">Refine with the assistant</p>
            <div className="mb-2 flex flex-wrap gap-1.5">
              {REFINE_EXAMPLES.map((ex) => (
                <button
                  key={ex}
                  type="button"
                  disabled={refinementBusy}
                  className="rounded-full border border-gray-200 bg-white px-2.5 py-0.5 text-xs text-gray-700 transition-colors hover:bg-gray-50 disabled:pointer-events-none disabled:opacity-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-gray-700"
                  onClick={() => setRefineText(ex)}
                >
                  {ex}
                </button>
              ))}
            </div>
            <textarea
              data-testid="studio-ai-chat-class-create-preview-refine-input"
              aria-label="Refinement instructions"
              value={refineText}
              disabled={refinementBusy}
              onChange={(e) => setRefineText(e.target.value)}
              placeholder="e.g. Add a phone number field, make email required…"
              rows={2}
              className="mb-2 w-full resize-y rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 shadow-sm placeholder:text-gray-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400 disabled:bg-gray-100 dark:border-gray-600 dark:bg-gray-950 dark:text-gray-100 dark:placeholder:text-gray-500 dark:disabled:bg-gray-900"
            />
            <button
              type="button"
              data-testid="studio-ai-chat-class-create-preview-refine-submit"
              disabled={refinementBusy || !refineText.trim()}
              className="inline-flex h-9 items-center justify-center rounded-md border border-transparent bg-indigo-600 px-4 text-sm font-medium text-white shadow-sm transition-colors hover:bg-indigo-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400 disabled:pointer-events-none disabled:opacity-50 dark:focus-visible:ring-indigo-500"
              onClick={() => {
                const t = refineText.trim();
                if (!t || refinementBusy) return;
                onRequestRefinement(t);
              }}
            >
              {refinementBusy ? 'Waiting for assistant…' : 'Ask assistant to refine'}
            </button>
          </div>
        ) : null}

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
