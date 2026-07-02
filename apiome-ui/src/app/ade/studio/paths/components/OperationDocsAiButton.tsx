'use client';

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Button } from '../../../../components/ui/Button';
import { Loader2, Sparkles, Square } from 'lucide-react';
import {
  persistOllamaModelChoiceForScope,
  resolvePreferredOllamaModel,
} from '@/app/ade/studio/components/chatbot/ollama-model-defaults';
import { accumulateOllamaSse } from '@lib/ollama-chat-sse';
import { parseGeneratedOperationDocs } from '@lib/ai-property-description';

export interface OperationDocsAiButtonProps {
  tenantId: string | null | undefined;
  projectId: string | null | undefined;
  versionId: string | null | undefined;
  pathname: string;
  httpMethod: string;
  /** Optional operationId already chosen — helps the model stay aligned with codegen names. */
  operationIdHint?: string;
  /** Path template parameters extracted from the path (e.g. userId). */
  pathParameterNames?: string[];
  onGenerated: (docs: { summary: string; description: string }) => void;
  disabled?: boolean;
  wrapperClassName?: string;
}

export function OperationDocsAiButton({
  tenantId,
  projectId,
  versionId,
  pathname,
  httpMethod,
  operationIdHint,
  pathParameterNames,
  onGenerated,
  disabled,
  wrapperClassName,
}: OperationDocsAiButtonProps) {
  const [modelNames, setModelNames] = useState<string[]>([]);
  const [selectedModel, setSelectedModel] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const requestIdRef = useRef(0);

  const pid = typeof projectId === 'string' ? projectId.trim() : '';

  useEffect(() => {
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

  const stop = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
  }, []);

  const generate = useCallback(async () => {
    const path = pathname.trim();
    const method = httpMethod.trim().toUpperCase();
    if (!path || !method || !selectedModel.trim() || !pid) return;

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

    const paramLine =
      pathParameterNames && pathParameterNames.length > 0
        ? `Path parameters: ${pathParameterNames.join(', ')}`
        : '';
    const opIdLine =
      typeof operationIdHint === 'string' && operationIdHint.trim()
        ? `operationId (hint): ${operationIdHint.trim()}`
        : '';

    const userLines = [
      `Draft OpenAPI summary and description for this operation.`,
      `HTTP method: ${method}`,
      `Path template: ${path}`,
      paramLine,
      opIdLine,
    ].filter((line) => line.length > 0);

    try {
      const response = await fetch('/api/ollama/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        signal: ac.signal,
        body: JSON.stringify({
          model: selectedModel.trim(),
          task: 'operation_description',
          messages: [{ role: 'user', content: userLines.join('\n') }],
          ...(typeof versionId === 'string' && versionId ? { versionId } : {}),
        }),
      });

      if (!response.ok) {
        const t = await response.text().catch(() => '');
        throw new Error(t || `Request failed (${response.status})`);
      }

      const full = await accumulateOllamaSse(response, ac.signal);
      if (ac.signal.aborted || requestId !== requestIdRef.current) return;

      const parsed = parseGeneratedOperationDocs(full);
      if (!parsed) {
        setError('Could not parse the model response. Try again or pick another model.');
        return;
      }
      onGenerated(parsed);
    } catch (e) {
      if (ac.signal.aborted || requestId !== requestIdRef.current) return;
      setError(e instanceof Error ? e.message : 'Something went wrong.');
    } finally {
      if (requestId !== requestIdRef.current) return;
      setBusy(false);
      if (abortRef.current === ac) abortRef.current = null;
    }
  }, [
    pathname,
    httpMethod,
    operationIdHint,
    pathParameterNames,
    selectedModel,
    tenantId,
    pid,
    versionId,
    onGenerated,
  ]);

  useEffect(
    () => () => {
      requestIdRef.current += 1;
      abortRef.current?.abort();
      abortRef.current = null;
    },
    [],
  );

  const pathOk = Boolean(pathname.trim() && httpMethod.trim());
  const canRun = Boolean(pathOk && pid && selectedModel.trim() && !disabled);

  return (
    <div className={wrapperClassName}>
      <div className="flex flex-wrap items-center gap-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={!canRun || busy || modelNames.length === 0}
          onClick={() => void generate()}
          data-testid="operation-docs-ai-generate"
          className="shrink-0 border-violet-300 text-violet-800 hover:bg-violet-50 dark:border-violet-700 dark:text-violet-200 dark:hover:bg-violet-950/40"
        >
          {busy ? (
            <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" aria-hidden />
          ) : (
            <Sparkles className="mr-1.5 h-3.5 w-3.5" aria-hidden />
          )}
          {busy ? 'Generating…' : 'Generate summary & description'}
        </Button>
        {busy && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={stop}
            data-testid="operation-docs-ai-stop"
            className="text-slate-600 dark:text-slate-400"
          >
            <Square className="mr-1 h-3.5 w-3.5" aria-hidden />
            Stop
          </Button>
        )}
      </div>
      {modelNames.length === 0 && !busy && (
        <p className="mt-1 text-xs text-amber-700 dark:text-amber-300">
          No Ollama models available. Start Ollama or check OLLAMA_BASE_URL.
        </p>
      )}
      {error && (
        <p className="mt-1 text-xs text-red-600 dark:text-red-400" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
