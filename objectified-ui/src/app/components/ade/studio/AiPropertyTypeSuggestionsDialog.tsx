'use client';

import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '../../ui/Dialog';
import { Button } from '../../ui/Button';
import { Textarea } from '../../ui/Textarea';
import { Bot, Loader2, Square } from 'lucide-react';
import type { PropertyItem } from './StudioSideNav';
import {
  parseAiPropertySuggestionsResponse,
  type AiPropertySuggestion,
  type AiPropertySuggestionsPayload,
} from '@lib/ai-property-suggestions';
import { computeStudioSchemaFingerprint } from '@lib/studio-schema-fingerprint';
import type { ChatStudioContext } from '@/app/ade/studio/components/chatbot/chat-context';
import { isChatStudioContextEmpty } from '@/app/ade/studio/components/chatbot/chat-context';
import {
  resolvePreferredOllamaModel,
  persistOllamaModelChoiceForScope,
} from '@/app/ade/studio/components/chatbot/ollama-model-defaults';
import { accumulateOllamaSse } from '@lib/ollama-chat-sse';
import { propertyItemToExistingApiShape } from './AiPropertySuggestionsDialog';

export interface AiPropertyTypeSuggestionsDialogProps {
  open: boolean;
  onClose: () => void;
  tenantId: string | null | undefined;
  projectId: string;
  versionId: string | null | undefined;
  targetPropertyName: string;
  targetPropertyDescription?: string;
  contextClassName?: string | null;
  existingClasses: string[];
  existingProperties: PropertyItem[];
  studioContext: ChatStudioContext;
  onApplyTypeSuggestion: (suggestion: AiPropertySuggestion) => void;
}

export function AiPropertyTypeSuggestionsDialog({
  open,
  onClose,
  tenantId,
  projectId,
  versionId,
  targetPropertyName,
  targetPropertyDescription,
  contextClassName,
  existingClasses,
  existingProperties,
  studioContext,
  onApplyTypeSuggestion,
}: AiPropertyTypeSuggestionsDialogProps) {
  const [prompt, setPrompt] = useState('');
  const [modelNames, setModelNames] = useState<string[]>([]);
  const [selectedModel, setSelectedModel] = useState('');
  const [isGenerating, setIsGenerating] = useState(false);
  const [streamText, setStreamText] = useState('');
  const [parsed, setParsed] = useState<AiPropertySuggestionsPayload | null>(null);
  const [parseError, setParseError] = useState<string | null>(null);
  const [selectedIdx, setSelectedIdx] = useState<number | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!open) return;

    let cancelled = false;
    (async () => {
      try {
        const res = await fetch('/api/ollama/models');
        const json = (await res.json()) as { success?: boolean; models?: { name?: string }[] };
        const list = res.ok && json.success && Array.isArray(json.models) ? json.models : undefined;
        const names = Array.isArray(list)
          ? list.map((m) => m?.name).filter((n): n is string => typeof n === 'string' && n.trim().length > 0)
          : [];
        if (cancelled) return;
        setModelNames(names);
        const preferred = resolvePreferredOllamaModel({
          tenantId,
          projectId,
          availableModelNames: names,
          storage: typeof window !== 'undefined' ? window.localStorage : null,
        });
        setSelectedModel(preferred);
      } catch {
        if (!cancelled) {
          setModelNames([]);
          setSelectedModel('');
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [open, tenantId, projectId]);

  useEffect(() => {
    if (!open) {
      setPrompt('');
      setStreamText('');
      setParsed(null);
      setParseError(null);
      setSelectedIdx(null);
      setIsGenerating(false);
      abortRef.current?.abort();
      abortRef.current = null;
    }
  }, [open]);

  const handleStop = () => {
    abortRef.current?.abort();
    abortRef.current = null;
    setIsGenerating(false);
  };

  const handleGenerate = useCallback(async () => {
    const propName = targetPropertyName.trim();
    if (!propName || !selectedModel.trim()) return;

    persistOllamaModelChoiceForScope({
      tenantId,
      projectId,
      modelName: selectedModel,
      storage: typeof window !== 'undefined' ? window.localStorage : null,
    });

    abortRef.current?.abort();
    const ac = new AbortController();
    abortRef.current = ac;

    setIsGenerating(true);
    setStreamText('');
    setParsed(null);
    setParseError(null);
    setSelectedIdx(null);

    let schemaContextFingerprint: string | undefined;
    if (studioContext && !isChatStudioContextEmpty(studioContext)) {
      try {
        schemaContextFingerprint = await computeStudioSchemaFingerprint(studioContext);
      } catch {
        /* optional */
      }
    }

    const existingPropsPayload = existingProperties.map(propertyItemToExistingApiShape);
    const trimmedPrompt = prompt.trim();
    const desc = (targetPropertyDescription || '').trim();

    const userContent = [
      `Target property: ${propName}`,
      contextClassName?.trim() ? `Class or domain context: ${contextClassName.trim()}` : null,
      desc ? `Current description in the form: ${desc}` : null,
      `User instructions:\n${trimmedPrompt || 'Infer strong type options from the property name and project context.'}`,
    ]
      .filter(Boolean)
      .join('\n\n');

    try {
      const response = await fetch('/api/ollama/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        signal: ac.signal,
        body: JSON.stringify({
          model: selectedModel.trim(),
          task: 'property_type_suggestions',
          messages: [{ role: 'user', content: userContent }],
          existingClassNames: existingClasses,
          existingProperties: existingPropsPayload,
          targetPropertyName: propName,
          ...(contextClassName?.trim() ? { targetClassName: contextClassName.trim() } : {}),
          ...(typeof versionId === 'string' && versionId ? { versionId } : {}),
          ...(schemaContextFingerprint ? { schemaContextFingerprint } : {}),
        }),
      });

      if (!response.ok) {
        const t = await response.text().catch(() => '');
        throw new Error(t || `Request failed (${response.status})`);
      }

      const full = await accumulateOllamaSse(response, ac.signal, (acc) => setStreamText(acc));
      setStreamText(full);

      if (ac.signal.aborted) return;

      const structured = parseAiPropertySuggestionsResponse(full, { canonicalPropertyName: propName });
      if (structured && structured.suggestions.length >= 2) {
        setParsed(structured);
        setParseError(null);
        setSelectedIdx(0);
      } else if (structured && structured.suggestions.length === 1) {
        setParseError('The model returned only one type option. Try again and ask for multiple alternatives.');
        setParsed(null);
      } else {
        setParseError(
          'The model response could not be read as structured type suggestions. Try again with a shorter hint.',
        );
      }
    } catch (e) {
      if (ac.signal.aborted) {
        setParseError(null);
      } else {
        setParseError(e instanceof Error ? e.message : 'Something went wrong.');
      }
    } finally {
      setIsGenerating(false);
      abortRef.current = null;
    }
  }, [
    prompt,
    selectedModel,
    tenantId,
    projectId,
    versionId,
    targetPropertyName,
    targetPropertyDescription,
    contextClassName,
    existingClasses,
    existingProperties,
    studioContext,
  ]);

  const selectedSuggestion: AiPropertySuggestion | null =
    parsed && selectedIdx !== null && parsed.suggestions[selectedIdx] ? parsed.suggestions[selectedIdx] : null;

  const thinkingBody = isGenerating
    ? streamText || '…'
    : parsed
      ? (parsed.thinking?.trim() ? parsed.thinking : '—')
      : streamText;

  const showThinkingSection = isGenerating || parsed !== null || (!!streamText && streamText.length > 0);

  const summaryBelow = parsed?.summary?.trim() ? parsed.summary : '';

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent
        className="max-h-[90vh] flex flex-col gap-0 overflow-hidden sm:max-w-2xl"
        aria-describedby={undefined}
      >
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-lg">
            <Bot className="h-5 w-5 text-violet-600 dark:text-violet-400" aria-hidden />
            Suggest property types with AI
          </DialogTitle>
        </DialogHeader>

        <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto px-1 py-2">
          <p className="text-sm text-slate-600 dark:text-slate-400">
            For property{' '}
            <span className="font-mono font-semibold text-slate-800 dark:text-slate-200">
              {targetPropertyName.trim() || '—'}
            </span>
            , the model proposes alternative JSON Schema shapes (primitives with formats, refs to existing classes,
            arrays, enums, or domain-oriented options). Pick one to fill the Add Property form.
          </p>

          <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
            <label htmlFor="ai-type-suggest-model" className="sr-only">
              Ollama model
            </label>
            <select
              id="ai-type-suggest-model"
              data-testid="ai-property-type-suggestions-model"
              value={selectedModel}
              onChange={(e) => setSelectedModel(e.target.value)}
              disabled={modelNames.length === 0 || isGenerating}
              className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-600 dark:bg-slate-900 sm:max-w-xs"
            >
              {modelNames.length === 0 ? (
                <option value="">No models — start Ollama</option>
              ) : (
                modelNames.map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))
              )}
            </select>
          </div>

          <div>
            <label
              htmlFor="ai-type-suggest-prompt"
              className="mb-1 block text-xs font-medium text-slate-700 dark:text-slate-300"
            >
              What should the types optimize for?
            </label>
            <Textarea
              id="ai-type-suggest-prompt"
              data-testid="ai-property-type-suggestions-prompt"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder="e.g. FHIR Patient identifiers, strict validation, or compatibility with existing emailAddress property"
              disabled={isGenerating}
              rows={3}
              className="resize-y text-sm"
            />
          </div>

          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              data-testid="ai-property-type-suggestions-generate"
              onClick={() => void handleGenerate()}
              disabled={isGenerating || !targetPropertyName.trim() || !selectedModel.trim()}
              className="bg-gradient-to-r from-violet-600 to-indigo-600 text-white hover:from-violet-500 hover:to-indigo-500"
            >
              {isGenerating ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
                  Generating…
                </>
              ) : (
                'Suggest types'
              )}
            </Button>
            {isGenerating && (
              <Button type="button" variant="outline" onClick={handleStop} data-testid="ai-property-type-suggestions-stop">
                <Square className="mr-2 h-3.5 w-3.5 fill-current" aria-hidden />
                Stop
              </Button>
            )}
          </div>

          {parseError && (
            <p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:border-amber-900/50 dark:bg-amber-950/40 dark:text-amber-100">
              {parseError}
            </p>
          )}

          {showThinkingSection && (
            <section aria-label="Thinking">
              <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                Thinking
              </h3>
              <div
                data-testid="ai-property-type-suggestions-thinking"
                className="max-h-36 overflow-y-auto rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-800 dark:border-slate-600 dark:bg-slate-900/60 dark:text-slate-200"
              >
                {thinkingBody}
              </div>
            </section>
          )}

          {parsed && parsed.suggestions.length > 0 && (
            <section aria-label="Suggested types">
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                Type alternatives
              </h3>
              <ul className="flex flex-wrap gap-2" data-testid="ai-property-type-suggestions-list">
                {parsed.suggestions.map((s, i) => (
                  <li key={`${s.summary || s.name}-${i}`}>
                    <button
                      type="button"
                      data-testid={`ai-property-type-suggestions-item-${i}`}
                      onClick={() => setSelectedIdx(i)}
                      className={`rounded-full border px-3 py-1.5 text-sm font-medium transition-colors ${
                        selectedIdx === i
                          ? 'border-violet-500 bg-violet-500/15 text-violet-800 dark:text-violet-200'
                          : 'border-slate-200 bg-white text-slate-700 hover:border-violet-300 hover:bg-violet-50 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-200 dark:hover:border-violet-500 dark:hover:bg-violet-950/40'
                      }`}
                    >
                      {s.summary?.trim() ? s.summary : `Alternative ${i + 1}`}
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {selectedSuggestion && (
            <section aria-label="Selected type detail" className="space-y-2 rounded-lg border border-slate-200 p-3 dark:border-slate-600">
              <div>
                <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                  Why this type
                </h3>
                <p className="text-sm text-slate-700 dark:text-slate-300">{selectedSuggestion.thinking || '—'}</p>
              </div>
              <div>
                <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                  Schema (JSON)
                </h3>
                <pre className="max-h-40 overflow-auto rounded-md bg-slate-950 px-3 py-2 text-xs text-slate-100">
                  {JSON.stringify(selectedSuggestion.schema, null, 2)}
                </pre>
              </div>
              <Button
                type="button"
                data-testid="ai-property-type-suggestions-apply"
                onClick={() => {
                  onApplyTypeSuggestion(selectedSuggestion);
                  onClose();
                }}
                className="w-full bg-gradient-to-r from-indigo-600 to-purple-600 text-white hover:from-indigo-500 hover:to-purple-500 sm:w-auto"
              >
                Apply to form
              </Button>
            </section>
          )}

          {summaryBelow && (
            <section aria-label="Summary">
              <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                Summary
              </h3>
              <div
                data-testid="ai-property-type-suggestions-summary"
                className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700 dark:border-slate-600 dark:bg-slate-900/40 dark:text-slate-200"
              >
                {summaryBelow}
              </div>
            </section>
          )}
        </div>

        <DialogFooter className="border-t border-slate-200 pt-3 dark:border-slate-700">
          <Button type="button" variant="outline" onClick={onClose}>
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
