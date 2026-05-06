'use client';

import React, { useCallback, useEffect, useState } from 'react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '../../ui/Dialog';
import { Button } from '../../ui/Button';
import { Textarea } from '../../ui/Textarea';
import { Bot, Copy, Loader2, Square, Sparkles } from 'lucide-react';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '../../ui/Tooltip';
import {
  parseAiSchemaImprovementSuggestionsResponse,
  type AiSchemaImprovementEffort,
  type AiSchemaImprovementSuggestionsPayload,
} from '@lib/ai-schema-improvement-suggestions';
import {
  resolvePreferredOllamaModel,
  persistOllamaModelChoiceForScope,
} from '@/app/ade/studio/components/chatbot/ollama-model-defaults';
import { accumulateOllamaSse } from '@lib/ollama-chat-sse';

export interface AiSchemaImprovementSuggestionsDialogProps {
  open: boolean;
  onClose: () => void;
  tenantId: string | null | undefined;
  projectId: string;
  versionId: string | null | undefined;
  /** Pre-built digest from Schema Metrics (required when generating). */
  studioMetricsDigest: string;
  existingClassNames: string[];
}

const CATEGORY_LABEL: Record<string, string> = {
  documentation: 'Docs',
  naming: 'Naming',
  structure: 'Structure',
  api: 'API',
  performance: 'Performance',
  other: 'Other',
};

const EFFORT_LABEL: Record<AiSchemaImprovementEffort, string> = {
  quick_win: 'Quick win',
  moderate: 'Standard',
  substantial: 'Larger effort',
};

const EFFORT_BADGE_CLASS: Record<AiSchemaImprovementEffort, string> = {
  quick_win:
    'bg-emerald-100 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-200',
  moderate: 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300',
  substantial: 'bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200',
};

function formatEstimatedScoreImpact(delta: number): string {
  const sign = delta > 0 ? '+' : '';
  return `${sign}${delta} pts`;
}

export function AiSchemaImprovementSuggestionsDialog({
  open,
  onClose,
  tenantId,
  projectId,
  versionId,
  studioMetricsDigest,
  existingClassNames,
}: AiSchemaImprovementSuggestionsDialogProps) {
  const [hint, setHint] = useState('');
  const [modelNames, setModelNames] = useState<string[]>([]);
  const [selectedModel, setSelectedModel] = useState('');
  const [isGenerating, setIsGenerating] = useState(false);
  const [streamText, setStreamText] = useState('');
  const [parsed, setParsed] = useState<AiSchemaImprovementSuggestionsPayload | null>(null);
  const [parseError, setParseError] = useState<string | null>(null);
  const [copyIdx, setCopyIdx] = useState<number | null>(null);
  const abortRef = React.useRef<AbortController | null>(null);

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
      setHint('');
      setStreamText('');
      setParsed(null);
      setParseError(null);
      setCopyIdx(null);
      setIsGenerating(false);
      abortRef.current?.abort();
      abortRef.current = null;
    }
  }, [open]);

  const handleStop = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setIsGenerating(false);
  }, []);

  const handleGenerate = useCallback(async () => {
    const trimmedHint = hint.trim();
    if (!selectedModel.trim()) {
      setParseError('Pick an Ollama model first.');
      return;
    }
    if (!studioMetricsDigest.trim()) {
      setParseError('Schema metrics are not available.');
      return;
    }

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

    const userLines = [
      'Based on the Studio metrics digest in your system context, propose improvement suggestions as specified.',
      trimmedHint ? `Additional focus from the user: ${trimmedHint}` : '',
    ].filter(Boolean);

    try {
      const response = await fetch('/api/ollama/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        signal: ac.signal,
        body: JSON.stringify({
          model: selectedModel.trim(),
          task: 'schema_improvement_suggestions',
          messages: [{ role: 'user', content: userLines.join('\n\n') }],
          existingClassNames,
          studioMetricsDigest: studioMetricsDigest.trim(),
          ...(typeof versionId === 'string' && versionId ? { versionId } : {}),
        }),
      });

      if (!response.ok) {
        const t = await response.text().catch(() => '');
        throw new Error(t || `Request failed (${response.status})`);
      }

      const full = await accumulateOllamaSse(response, ac.signal, (acc) => setStreamText(acc));
      setStreamText(full);

      if (ac.signal.aborted) return;

      const structured = parseAiSchemaImprovementSuggestionsResponse(full);
      if (structured) {
        setParsed(structured);
        setParseError(null);
      } else {
        setParseError(
          'The model response could not be read as structured suggestions. Try again, or shorten the optional focus note.',
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
      if (abortRef.current === ac) abortRef.current = null;
    }
  }, [hint, selectedModel, tenantId, projectId, versionId, studioMetricsDigest, existingClassNames]);

  const handleCopyRow = async (
    idx: number,
    title: string,
    detail: string,
    effort: AiSchemaImprovementEffort,
    estimatedDelta?: number
  ) => {
    const scoreLine =
      typeof estimatedDelta === 'number'
        ? `\nEst. overall score impact: ${formatEstimatedScoreImpact(estimatedDelta)} (0–100 composite; model estimate)`
        : '';
    const text = `${title}\nEffort: ${EFFORT_LABEL[effort]}${scoreLine}\n\n${detail}`;
    try {
      await navigator.clipboard.writeText(text);
      setCopyIdx(idx);
      window.setTimeout(() => setCopyIdx((c) => (c === idx ? null : c)), 2000);
    } catch {
      setParseError('Could not copy to clipboard.');
    }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-lg max-h-[90vh] flex flex-col gap-0 p-0 overflow-hidden sm:max-w-lg">
        <DialogHeader className="px-4 pt-4 pb-2 border-b border-gray-200 dark:border-gray-700 shrink-0">
          <DialogTitle className="flex items-center gap-2 text-base">
            <Sparkles className="h-4 w-4 text-amber-500 shrink-0" aria-hidden />
            AI improvement suggestions
          </DialogTitle>
          <p className="text-xs text-gray-500 dark:text-gray-400 font-normal pt-1">
            Uses live Schema Metrics and class names from the canvas. Quick wins are listed first; each row shows effort, optional estimated impact on the 0–100 overall schema quality score, and category.
            Suggestions are advisory—review before changing your model.
          </p>
        </DialogHeader>

        <div className="flex-1 min-h-0 overflow-y-auto px-4 py-3 space-y-3">
          <div className="flex flex-wrap items-end gap-2">
            <label className="flex flex-col gap-1 text-xs font-medium text-gray-700 dark:text-gray-300 min-w-[12rem] flex-1">
              Model
              <select
                data-testid="ai-schema-improvement-model"
                className="h-9 w-full rounded-md border border-gray-200 bg-white px-2 text-sm dark:border-gray-600 dark:bg-gray-900"
                value={selectedModel}
                onChange={(e) => setSelectedModel(e.target.value)}
                disabled={isGenerating || modelNames.length === 0}
              >
                {modelNames.length === 0 ? (
                  <option value="">No models</option>
                ) : (
                  modelNames.map((name) => (
                    <option key={name} value={name}>
                      {name}
                    </option>
                  ))
                )}
              </select>
            </label>
            <Button
              type="button"
              variant="default"
              className="shrink-0"
              data-testid="ai-schema-improvement-generate"
              disabled={isGenerating || !selectedModel.trim() || modelNames.length === 0}
              onClick={() => void handleGenerate()}
            >
              {isGenerating ? (
                <>
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  Generating…
                </>
              ) : (
                <>
                  <Bot className="h-4 w-4 mr-2" />
                  Generate
                </>
              )}
            </Button>
            {isGenerating && (
              <Button type="button" variant="outline" data-testid="ai-schema-improvement-stop" onClick={handleStop}>
                <Square className="h-4 w-4 mr-2" />
                Stop
              </Button>
            )}
          </div>

          <label className="flex flex-col gap-1 text-xs font-medium text-gray-700 dark:text-gray-300">
            Optional focus (paths, product area, constraints)
            <Textarea
              data-testid="ai-schema-improvement-hint"
              value={hint}
              onChange={(e) => setHint(e.target.value)}
              rows={3}
              disabled={isGenerating}
              placeholder="e.g. We expose GET /orders and GET /users list endpoints—comment on pagination."
              className="text-sm resize-y min-h-[4rem]"
            />
          </label>

          {parseError && (
            <p className="text-sm text-red-600 dark:text-red-400" data-testid="ai-schema-improvement-error">
              {parseError}
            </p>
          )}

          {parsed && (
            <div className="space-y-2">
              {parsed.summary ? (
                <p className="text-sm text-gray-700 dark:text-gray-300 border border-gray-200 dark:border-gray-600 rounded-md p-2 bg-gray-50 dark:bg-gray-900/40">
                  {parsed.summary}
                </p>
              ) : null}
              <ul className="space-y-2" data-testid="ai-schema-improvement-list">
                {parsed.suggestions.map((s, i) => (
                  <li
                    key={`${i}-${s.title}`}
                    className="rounded-lg border border-gray-200 dark:border-gray-600 p-3 bg-white dark:bg-gray-900/30"
                    data-testid={`ai-schema-improvement-item-${i}`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2 mb-1">
                          <span className="text-sm font-semibold text-gray-900 dark:text-gray-100">{s.title}</span>
                          <span className="text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded bg-indigo-100 text-indigo-800 dark:bg-indigo-950 dark:text-indigo-200">
                            {CATEGORY_LABEL[s.category] ?? s.category}
                          </span>
                          <span
                            className={`text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded ${EFFORT_BADGE_CLASS[s.effort]}`}
                            data-testid={`ai-schema-improvement-effort-${i}`}
                          >
                            {EFFORT_LABEL[s.effort]}
                          </span>
                          {typeof s.estimatedOverallScoreDelta === 'number' ? (
                            <TooltipProvider>
                              <Tooltip>
                                <TooltipTrigger asChild>
                                  <span
                                    className="text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded bg-sky-100 text-sky-900 dark:bg-sky-950 dark:text-sky-200 tabular-nums cursor-default"
                                    data-testid={`ai-schema-improvement-score-${i}`}
                                  >
                                    {formatEstimatedScoreImpact(s.estimatedOverallScoreDelta)}
                                  </span>
                                </TooltipTrigger>
                                <TooltipContent>
                                  Estimated change to the Studio overall schema quality score (0–100) if this fix were fully applied
                                </TooltipContent>
                              </Tooltip>
                            </TooltipProvider>
                          ) : null}
                        </div>
                        <p className="text-xs text-gray-600 dark:text-gray-400 whitespace-pre-wrap">{s.detail}</p>
                      </div>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        className="shrink-0"
                        data-testid={`ai-schema-improvement-copy-${i}`}
                        onClick={() => void handleCopyRow(i, s.title, s.detail, s.effort, s.estimatedOverallScoreDelta)}
                      >
                        <Copy className="h-3.5 w-3.5 mr-1" />
                        {copyIdx === i ? 'Copied' : 'Copy'}
                      </Button>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {isGenerating && streamText && !parsed && (
            <pre
              className="text-xs text-gray-500 dark:text-gray-400 whitespace-pre-wrap max-h-40 overflow-y-auto rounded border border-gray-100 dark:border-gray-700 p-2 bg-gray-50 dark:bg-gray-900/20"
              data-testid="ai-schema-improvement-stream"
            >
              {streamText}
            </pre>
          )}
        </div>

        <DialogFooter className="px-4 py-3 border-t border-gray-200 dark:border-gray-700 shrink-0">
          <Button type="button" variant="outline" onClick={onClose}>
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
