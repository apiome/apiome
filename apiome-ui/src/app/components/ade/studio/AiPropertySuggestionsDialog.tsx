'use client';

import React, { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '../../ui/Dialog';
import { Button } from '../../ui/Button';
import { Input } from '../../ui/Input';
import { Textarea } from '../../ui/Textarea';
import { Bot, Loader2, Square, ListChecks, Ban, Trash2 } from 'lucide-react';
import type { PropertyItem } from './StudioSideNav';
import {
  parseAiPropertySuggestionsResponse,
  suggestionPublicExplanation,
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
import { buildPropertyItemFromAiSeedForm, propertyItemToExistingApiShape } from '@lib/property-item-utils';

function aiSuggestionToDraftFields(s: AiPropertySuggestion): {
  name: string;
  description: string;
  schemaText: string;
} {
  return {
    name: s.name,
    description: s.description ?? '',
    schemaText: JSON.stringify(s.schema, null, 2),
  };
}

export interface AiPropertySuggestionsDialogProps {
  open: boolean;
  onClose: () => void;
  tenantId: string | null | undefined;
  projectId: string;
  versionId: string | null | undefined;
  existingClasses: string[];
  existingProperties: PropertyItem[];
  studioContext: ChatStudioContext;
  onCreatePropertyFromSuggestion: (seed: PropertyItem) => void;
  /** Opens Add Property for each remaining suggestion in order after each save (#271). */
  onAcceptAllPropertySuggestions: (seeds: PropertyItem[]) => void;
}

export function AiPropertySuggestionsDialog({
  open,
  onClose,
  tenantId,
  projectId,
  versionId,
  existingClasses,
  existingProperties,
  studioContext,
  onCreatePropertyFromSuggestion,
  onAcceptAllPropertySuggestions,
}: AiPropertySuggestionsDialogProps) {
  const [prompt, setPrompt] = useState('');
  const [modelNames, setModelNames] = useState<string[]>([]);
  const [selectedModel, setSelectedModel] = useState('');
  const [isGenerating, setIsGenerating] = useState(false);
  const [streamText, setStreamText] = useState('');
  const [parsed, setParsed] = useState<AiPropertySuggestionsPayload | null>(null);
  const [parseError, setParseError] = useState<string | null>(null);
  const [selectedIdx, setSelectedIdx] = useState<number | null>(null);
  const [rejectedIndices, setRejectedIndices] = useState<Set<number>>(() => new Set());
  const [draftsByIdx, setDraftsByIdx] = useState<
    Record<number, { name: string; description: string; schemaText: string }>
  >({});
  const [seedEditError, setSeedEditError] = useState<string | null>(null);
  const [acceptAllError, setAcceptAllError] = useState<string | null>(null);
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
      setRejectedIndices(new Set());
      setDraftsByIdx({});
      setSeedEditError(null);
      setAcceptAllError(null);
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
    const trimmed = prompt.trim();
    if (!trimmed || !selectedModel.trim()) return;

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
    setRejectedIndices(new Set());
    setDraftsByIdx({});
    setSeedEditError(null);
    setAcceptAllError(null);

    let schemaContextFingerprint: string | undefined;
    if (studioContext && !isChatStudioContextEmpty(studioContext)) {
      try {
        schemaContextFingerprint = await computeStudioSchemaFingerprint(studioContext);
      } catch {
        /* optional */
      }
    }

    const existingPropsPayload = existingProperties.map(propertyItemToExistingApiShape);

    try {
      const response = await fetch('/api/ollama/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        signal: ac.signal,
        body: JSON.stringify({
          model: selectedModel.trim(),
          task: 'property_suggestions',
          messages: [{ role: 'user', content: trimmed }],
          existingClassNames: existingClasses,
          existingProperties: existingPropsPayload,
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

      const structured = parseAiPropertySuggestionsResponse(full);
      if (structured) {
        setParsed(structured);
        setParseError(null);
        setSelectedIdx(0);
      } else {
        setParseError(
          'The model response could not be read as structured suggestions. Try again, or ask for fewer properties at once.',
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
    existingClasses,
    existingProperties,
    studioContext,
  ]);

  useEffect(() => {
    if (selectedIdx === null || !parsed) return;
    if (!rejectedIndices.has(selectedIdx)) return;
    const first = parsed.suggestions.findIndex((_, i) => !rejectedIndices.has(i));
    setSelectedIdx(first >= 0 ? first : null);
  }, [rejectedIndices, selectedIdx, parsed]);

  useLayoutEffect(() => {
    if (selectedIdx === null || !parsed?.suggestions[selectedIdx]) return;
    setDraftsByIdx((prev) => {
      if (prev[selectedIdx]) return prev;
      return { ...prev, [selectedIdx]: aiSuggestionToDraftFields(parsed.suggestions[selectedIdx]) };
    });
  }, [selectedIdx, parsed]);

  useEffect(() => {
    setSeedEditError(null);
  }, [selectedIdx]);

  const activeSuggestionRows = useMemo(() => {
    if (!parsed) return [];
    return parsed.suggestions
      .map((s, origIdx) => ({ suggestion: s, origIdx }))
      .filter(({ origIdx }) => !rejectedIndices.has(origIdx));
  }, [parsed, rejectedIndices]);

  const handleRejectOne = (origIdx: number) => {
    setRejectedIndices((prev) => {
      const next = new Set(prev);
      next.add(origIdx);
      return next;
    });
  };

  const handleRejectAll = () => {
    if (!parsed?.suggestions.length) return;
    setRejectedIndices(new Set(parsed.suggestions.map((_, i) => i)));
  };

  const handleAcceptAll = () => {
    if (!parsed) return;
    setAcceptAllError(null);
    const rows = parsed.suggestions
      .map((s, i) => ({ s, i }))
      .filter(({ i }) => !rejectedIndices.has(i));
    if (rows.length === 0) return;
    const seeds: PropertyItem[] = [];
    for (const { s, i } of rows) {
      const draft = draftsByIdx[i] ?? aiSuggestionToDraftFields(s);
      const built = buildPropertyItemFromAiSeedForm(draft);
      if (!built.ok) {
        setAcceptAllError(`Could not accept all: "${draft.name || s.name}" — ${built.error}`);
        return;
      }
      seeds.push(built.item);
    }
    onAcceptAllPropertySuggestions(seeds);
    onClose();
  };

  const selectedSuggestion: AiPropertySuggestion | null =
    parsed &&
    selectedIdx !== null &&
    !rejectedIndices.has(selectedIdx) &&
    parsed.suggestions[selectedIdx]
      ? parsed.suggestions[selectedIdx]
      : null;

  const selectedDraft = useMemo(() => {
    if (selectedIdx === null || !parsed?.suggestions[selectedIdx]) return null;
    return draftsByIdx[selectedIdx] ?? aiSuggestionToDraftFields(parsed.suggestions[selectedIdx]);
  }, [selectedIdx, parsed, draftsByIdx]);

  const updateDraftField = useCallback(
    (field: 'name' | 'description' | 'schemaText', value: string) => {
      if (selectedIdx === null || !parsed?.suggestions[selectedIdx]) return;
      setDraftsByIdx((prev) => {
        const base = prev[selectedIdx] ?? aiSuggestionToDraftFields(parsed.suggestions[selectedIdx]);
        return { ...prev, [selectedIdx]: { ...base, [field]: value } };
      });
      setSeedEditError(null);
      setAcceptAllError(null);
    },
    [selectedIdx, parsed],
  );

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
            Suggest properties with AI
          </DialogTitle>
        </DialogHeader>

        <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto px-1 py-2">
          <p className="text-sm text-slate-600 dark:text-slate-400">
            Describe the kinds of reusable properties you want for this project (for example accounting fields,
            user profile traits, or IoT telemetry). The model proposes JSON Schema snippets you can open in Add
            Property.
          </p>

          <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
            <label htmlFor="ai-prop-suggest-model" className="sr-only">
              Ollama model
            </label>
            <select
              id="ai-prop-suggest-model"
              data-testid="ai-property-suggestions-model"
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
            <label htmlFor="ai-prop-suggest-prompt" className="mb-1 block text-xs font-medium text-slate-700 dark:text-slate-300">
              What should we create?
            </label>
            <Textarea
              id="ai-prop-suggest-prompt"
              data-testid="ai-property-suggestions-prompt"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder="e.g. Standard fields for a subscription billing entity"
              disabled={isGenerating}
              rows={3}
              className="resize-y text-sm"
            />
          </div>

          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              data-testid="ai-property-suggestions-generate"
              onClick={() => void handleGenerate()}
              disabled={isGenerating || !prompt.trim() || !selectedModel.trim()}
              className="bg-gradient-to-r from-violet-600 to-indigo-600 text-white hover:from-violet-500 hover:to-indigo-500"
            >
              {isGenerating ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
                  Generating…
                </>
              ) : (
                'Generate suggestions'
              )}
            </Button>
            {isGenerating && (
              <Button type="button" variant="outline" onClick={handleStop} data-testid="ai-property-suggestions-stop">
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
                data-testid="ai-property-suggestions-thinking"
                className="max-h-36 overflow-y-auto rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-800 dark:border-slate-600 dark:bg-slate-900/60 dark:text-slate-200"
              >
                {thinkingBody}
              </div>
            </section>
          )}

          {parsed && parsed.suggestions.length > 0 && (
            <section aria-label="Suggested properties" className="space-y-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                  Suggested properties
                </h3>
                <div className="flex flex-wrap items-center gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    data-testid="ai-property-suggestions-add-all-suggested"
                    disabled={activeSuggestionRows.length === 0}
                    onClick={handleAcceptAll}
                    className="border-emerald-300 text-emerald-800 hover:bg-emerald-50 dark:border-emerald-700 dark:text-emerald-200 dark:hover:bg-emerald-950/40"
                  >
                    <ListChecks className="h-4 w-4" aria-hidden />
                    Add all suggested
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    data-testid="ai-property-suggestions-reject-all"
                    disabled={activeSuggestionRows.length === 0}
                    onClick={handleRejectAll}
                    className="border-rose-300 text-rose-800 hover:bg-rose-50 dark:border-rose-700 dark:text-rose-200 dark:hover:bg-rose-950/40"
                  >
                    <Ban className="h-4 w-4" aria-hidden />
                    Reject all
                  </Button>
                </div>
              </div>
              {acceptAllError && (
                <p
                  className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-900 dark:border-rose-900/50 dark:bg-rose-950/40 dark:text-rose-100"
                  data-testid="ai-property-suggestions-add-all-error"
                >
                  {acceptAllError}
                </p>
              )}
              {activeSuggestionRows.length === 0 ? (
                <p
                  data-testid="ai-property-suggestions-list-empty"
                  className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-600 dark:border-slate-600 dark:bg-slate-900/50 dark:text-slate-400"
                >
                  No suggestions left to review. Generate again or close.
                </p>
              ) : (
                <ul data-testid="ai-property-suggestions-list" className="max-h-48 space-y-1.5 overflow-y-auto sm:max-w-xl">
                  {activeSuggestionRows.map(({ suggestion: s, origIdx }) => {
                    const label = s.summary?.trim() ? s.summary : s.name;
                    const explanation = suggestionPublicExplanation(s);
                    const isSelected = selectedIdx === origIdx;
                    return (
                      <li
                        key={origIdx}
                        className={`flex items-stretch gap-1 rounded-lg border transition-colors ${
                          isSelected
                            ? 'border-violet-500 bg-violet-500/10 ring-2 ring-violet-500/30 dark:border-violet-500 dark:bg-violet-950/30'
                            : 'border-slate-200 bg-white dark:border-slate-600 dark:bg-slate-900'
                        }`}
                      >
                        <button
                          type="button"
                          data-testid={`ai-property-suggestions-item-${origIdx}`}
                          onClick={() => setSelectedIdx(origIdx)}
                          className="min-w-0 flex-1 px-3 py-2 text-left text-sm text-slate-900 hover:bg-slate-50 dark:text-slate-100 dark:hover:bg-slate-800/80"
                        >
                          <span className="font-medium">{label}</span>
                          {s.name && s.summary?.trim() ? (
                            <span className="mt-0.5 block font-mono text-xs text-slate-500 dark:text-slate-400">{s.name}</span>
                          ) : null}
                          {explanation ? (
                            <span
                              className="mt-1 block text-xs leading-snug text-slate-600 line-clamp-4 dark:text-slate-400"
                              data-testid={`ai-property-suggestions-item-explanation-${origIdx}`}
                            >
                              {explanation}
                            </span>
                          ) : null}
                        </button>
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          data-testid={`ai-property-suggestions-reject-${origIdx}`}
                          onClick={() => handleRejectOne(origIdx)}
                          className="shrink-0 rounded-none rounded-r-lg text-slate-500 hover:bg-rose-50 hover:text-rose-700 dark:hover:bg-rose-950/50 dark:hover:text-rose-300"
                          aria-label={`Reject suggestion ${s.name}`}
                          title="Reject this suggestion"
                        >
                          <Trash2 className="h-4 w-4" aria-hidden />
                        </Button>
                      </li>
                    );
                  })}
                </ul>
              )}
            </section>
          )}

          {selectedSuggestion && selectedDraft && (
            <section aria-label="Selected suggestion detail" className="space-y-2 rounded-lg border border-slate-200 p-3 dark:border-slate-600">
              <div>
                <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                  Why this property
                </h3>
                <p className="text-sm text-slate-700 dark:text-slate-300">
                  {suggestionPublicExplanation(selectedSuggestion) || '—'}
                </p>
              </div>
              <div>
                <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                  Customize before adding
                </h3>
                <p className="mb-2 text-xs text-slate-600 dark:text-slate-400">
                  Adjust the name, description, and JSON Schema, then open Add Property or use Add all suggested.
                </p>
                <label htmlFor="ai-prop-suggest-edit-name" className="mb-1 block text-xs font-medium text-slate-700 dark:text-slate-300">
                  Property name
                </label>
                <Input
                  id="ai-prop-suggest-edit-name"
                  data-testid="ai-property-suggestions-edit-name"
                  value={selectedDraft.name}
                  onChange={(e) => updateDraftField('name', e.target.value)}
                  className="font-mono text-sm"
                  autoComplete="off"
                  spellCheck={false}
                />
                <label htmlFor="ai-prop-suggest-edit-desc" className="mb-1 mt-2 block text-xs font-medium text-slate-700 dark:text-slate-300">
                  Description
                </label>
                <Textarea
                  id="ai-prop-suggest-edit-desc"
                  data-testid="ai-property-suggestions-edit-description"
                  value={selectedDraft.description}
                  onChange={(e) => updateDraftField('description', e.target.value)}
                  rows={2}
                  className="resize-y text-sm"
                />
                <label htmlFor="ai-prop-suggest-edit-schema" className="mb-1 mt-2 block text-xs font-medium text-slate-700 dark:text-slate-300">
                  Schema (JSON object)
                </label>
                <Textarea
                  id="ai-prop-suggest-edit-schema"
                  data-testid="ai-property-suggestions-edit-schema"
                  value={selectedDraft.schemaText}
                  onChange={(e) => updateDraftField('schemaText', e.target.value)}
                  rows={10}
                  className="max-h-56 resize-y font-mono text-xs leading-relaxed"
                  spellCheck={false}
                />
              </div>
              {seedEditError && (
                <p
                  className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-900 dark:border-rose-900/50 dark:bg-rose-950/40 dark:text-rose-100"
                  data-testid="ai-property-suggestions-seed-error"
                >
                  {seedEditError}
                </p>
              )}
              <Button
                type="button"
                data-testid="ai-property-suggestions-open-add"
                onClick={() => {
                  if (selectedIdx === null || !parsed) return;
                  const draft =
                    draftsByIdx[selectedIdx] ?? aiSuggestionToDraftFields(parsed.suggestions[selectedIdx]);
                  const built = buildPropertyItemFromAiSeedForm(draft);
                  if (!built.ok) {
                    setSeedEditError(built.error);
                    return;
                  }
                  setSeedEditError(null);
                  onCreatePropertyFromSuggestion(built.item);
                  onClose();
                }}
                className="w-full bg-gradient-to-r from-indigo-600 to-purple-600 text-white hover:from-indigo-500 hover:to-purple-500 sm:w-auto"
              >
                Open in Add Property
              </Button>
            </section>
          )}

          {summaryBelow && (
            <section aria-label="Summary">
              <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                Summary
              </h3>
              <div
                data-testid="ai-property-suggestions-summary"
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
