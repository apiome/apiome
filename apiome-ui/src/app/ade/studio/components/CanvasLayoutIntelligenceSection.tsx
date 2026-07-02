'use client';

import * as React from 'react';
import ReactMarkdown from 'react-markdown';
import { Sparkles, Square, LayoutGrid } from 'lucide-react';
import {
  persistOllamaModelChoiceForScope,
  resolvePreferredOllamaModel,
} from '@/app/ade/studio/components/chatbot/ollama-model-defaults';
import { accumulateOllamaSse } from '@lib/ollama-chat-sse';
import {
  canvasLayoutAnalysisDigest,
  type CanvasLayoutGraphAnalysis,
} from '@/app/utils/canvas-layout-graph-analysis';
import { cn } from '../../../../../lib/utils';

export interface CanvasLayoutIntelligenceSectionProps {
  analysis: CanvasLayoutGraphAnalysis;
  tenantId: string | null | undefined;
  projectId: string | null | undefined;
  versionId: string | null | undefined;
  onPreviewLayoutDirection: (direction: 'TB' | 'LR') => void;
}

export function CanvasLayoutIntelligenceSection({
  analysis,
  tenantId,
  projectId,
  versionId,
  onPreviewLayoutDirection,
}: CanvasLayoutIntelligenceSectionProps) {
  const pid = typeof projectId === 'string' ? projectId.trim() : '';
  const [modelNames, setModelNames] = React.useState<string[]>([]);
  const [selectedModel, setSelectedModel] = React.useState('');
  const [busy, setBusy] = React.useState(false);
  const [aiText, setAiText] = React.useState('');
  const [error, setError] = React.useState<string | null>(null);
  const abortRef = React.useRef<AbortController | null>(null);
  const requestIdRef = React.useRef(0);

  React.useEffect(() => {
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
          projectId: pid || undefined,
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
  }, [tenantId, pid]);

  const stop = React.useCallback(() => {
    requestIdRef.current += 1;
    abortRef.current?.abort();
    abortRef.current = null;
    setBusy(false);
  }, []);

  const runAi = React.useCallback(async () => {
    if (!selectedModel.trim() || !pid) {
      setError('Pick a project and Ollama model first.');
      return;
    }
    const digest = canvasLayoutAnalysisDigest(analysis);
    if (!digest.trim()) {
      setError('Layout analysis is empty.');
      return;
    }

    persistOllamaModelChoiceForScope({
      tenantId,
      projectId: pid,
      modelName: selectedModel,
      storage: typeof window !== 'undefined' ? window.localStorage : null,
    });

    requestIdRef.current += 1;
    const requestId = requestIdRef.current;

    abortRef.current?.abort();
    const ac = new AbortController();
    abortRef.current = ac;

    setBusy(true);
    setError(null);
    setAiText('');

    try {
      const response = await fetch('/api/ollama/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        signal: ac.signal,
        body: JSON.stringify({
          model: selectedModel.trim(),
          task: 'canvas_layout_recommendations',
          canvasLayoutDigest: digest,
          messages: [
            {
              role: 'user',
              content:
                'Summarize the canvas layout analysis JSON from your system context and give concrete ReactFlow arrangement advice.',
            },
          ],
          ...(typeof versionId === 'string' && versionId ? { versionId } : {}),
        }),
      });

      if (!response.ok) {
        const t = await response.text().catch(() => '');
        throw new Error(t || `Request failed (${response.status})`);
      }

      const full = await accumulateOllamaSse(response, ac.signal, (acc) => {
        if (ac.signal.aborted || requestId !== requestIdRef.current) return;
        setAiText(acc);
      });
      if (ac.signal.aborted || requestId !== requestIdRef.current) return;
      setAiText(full);
    } catch (e) {
      if (ac.signal.aborted || requestId !== requestIdRef.current) return;
      setError(e instanceof Error ? e.message : 'AI request failed.');
    } finally {
      if (requestId === requestIdRef.current && !ac.signal.aborted) setBusy(false);
      if (abortRef.current === ac) abortRef.current = null;
    }
  }, [analysis, pid, selectedModel, tenantId, versionId]);

  React.useEffect(
    () => () => {
      requestIdRef.current += 1;
      abortRef.current?.abort();
      abortRef.current = null;
    },
    [],
  );

  const dirLabel = analysis.recommendedDirection === 'TB' ? 'Top → Bottom' : 'Left → Right';
  const topScc = analysis.stronglyConnectedComponents.find((s) => s.memberIds.length > 1);
  const hubPreview = analysis.hubClasses.slice(0, 3).map((h) => h.name);

  return (
    <div className="pt-2 border-t border-gray-200 dark:border-gray-700 space-y-2">
      <div className="flex items-center gap-1.5 text-[10px] text-gray-500 dark:text-gray-400 uppercase tracking-wider">
        <LayoutGrid className="w-3 h-3" aria-hidden />
        Canvas layout intelligence (#623)
      </div>

      <div className="rounded-lg border border-indigo-200/80 dark:border-indigo-800/60 bg-indigo-50/50 dark:bg-indigo-950/20 px-2.5 py-2 space-y-1.5">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-semibold text-indigo-900 dark:text-indigo-200">Suggested direction</span>
          <span className="text-xs font-bold tabular-nums text-indigo-800 dark:text-indigo-100">{dirLabel}</span>
          <button
            type="button"
            onClick={() => onPreviewLayoutDirection(analysis.recommendedDirection)}
            className="ml-auto text-[11px] font-medium text-indigo-700 dark:text-indigo-300 hover:underline flex items-center gap-1"
          >
            <LayoutGrid className="w-3.5 h-3.5" aria-hidden />
            Preview auto-layout
          </button>
        </div>
        <p className="text-[11px] text-indigo-900/85 dark:text-indigo-200/85 leading-snug">{analysis.recommendationReason}</p>
        <dl className="grid grid-cols-2 gap-x-2 gap-y-1 text-[10px] text-indigo-800/90 dark:text-indigo-200/80">
          <div>
            <dt className="text-gray-500 dark:text-gray-400">Vertices (layout graph)</dt>
            <dd className="font-medium tabular-nums">{analysis.vertexCount}</dd>
          </div>
          <div>
            <dt className="text-gray-500 dark:text-gray-400">Directed cycles (SCCs)</dt>
            <dd className="font-medium tabular-nums">{analysis.nonTrivialSccCount}</dd>
          </div>
          <div>
            <dt className="text-gray-500 dark:text-gray-400">Weak components</dt>
            <dd className="font-medium tabular-nums">{analysis.weaklyConnectedComponentCount}</dd>
          </div>
          <div>
            <dt className="text-gray-500 dark:text-gray-400">Pseudo depth × width</dt>
            <dd className="font-medium tabular-nums">
              {analysis.pseudoLayerDepth} × {analysis.pseudoLayerMaxWidth}
            </dd>
          </div>
        </dl>
        {topScc && (
          <p className="text-[10px] text-indigo-800/80 dark:text-indigo-300/80 leading-snug">
            <span className="font-medium">Largest cycle:</span> {topScc.memberNames.slice(0, 8).join(', ')}
            {topScc.memberNames.length > 8 ? '…' : ''}
          </p>
        )}
        {hubPreview.length > 0 && (
          <p className="text-[10px] text-indigo-800/80 dark:text-indigo-300/80 leading-snug">
            <span className="font-medium">Hubs:</span> {hubPreview.join(', ')}
            {analysis.hubClasses.length > 3 ? '…' : ''}
          </p>
        )}
        {analysis.hierarchyRoots.length > 0 && (
          <p className="text-[10px] text-indigo-800/80 dark:text-indigo-300/80 leading-snug">
            <span className="font-medium">Roots:</span>{' '}
            {analysis.hierarchyRoots
              .slice(0, 6)
              .map((r) => r.name)
              .join(', ')}
            {analysis.hierarchyRoots.length > 6 ? '…' : ''}
          </p>
        )}
      </div>

      <div className="space-y-1.5">
        <div className="flex flex-wrap items-center gap-2">
          <select
            value={selectedModel}
            onChange={(e) => setSelectedModel(e.target.value)}
            disabled={busy || modelNames.length === 0}
            className="flex-1 min-w-0 text-[11px] rounded-md border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-900 px-2 py-1 text-gray-800 dark:text-gray-200"
            aria-label="Ollama model for layout advice"
          >
            {modelNames.length === 0 ? (
              <option value="">No models — start Ollama</option>
            ) : (
              modelNames.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))
            )}
          </select>
          {busy ? (
            <button
              type="button"
              onClick={stop}
              className="inline-flex items-center gap-1 rounded-md border border-gray-300 dark:border-gray-600 px-2 py-1 text-[11px] font-medium text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-800"
            >
              <Square className="w-3 h-3" aria-hidden />
              Stop
            </button>
          ) : (
            <button
              type="button"
              onClick={() => void runAi()}
              disabled={!selectedModel.trim() || !pid}
              className={cn(
                'inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] font-medium',
                selectedModel.trim() && pid
                  ? 'bg-amber-600 text-white hover:bg-amber-700 dark:bg-amber-700 dark:hover:bg-amber-600'
                  : 'bg-gray-200 text-gray-500 cursor-not-allowed dark:bg-gray-700 dark:text-gray-400',
              )}
            >
              <Sparkles className="w-3 h-3" aria-hidden />
              AI narrative
            </button>
          )}
        </div>
        {error && <p className="text-[11px] text-rose-600 dark:text-rose-400">{error}</p>}
        {aiText.trim().length > 0 && (
          <div className="max-h-40 overflow-y-auto rounded-md border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-900/80 px-2 py-1.5 text-[11px] prose prose-sm dark:prose-invert max-w-none">
            <ReactMarkdown>{aiText}</ReactMarkdown>
          </div>
        )}
      </div>
    </div>
  );
}
