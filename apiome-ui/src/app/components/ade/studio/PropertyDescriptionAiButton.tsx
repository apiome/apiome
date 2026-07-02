'use client';

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Button } from '../../ui/Button';
import { Loader2, Sparkles, Square } from 'lucide-react';
import type { PropertyItem } from './StudioSideNav';
import type { ChatStudioContext } from '@/app/ade/studio/components/chatbot/chat-context';
import { isChatStudioContextEmpty } from '@/app/ade/studio/components/chatbot/chat-context';
import {
  persistOllamaModelChoiceForScope,
  resolvePreferredOllamaModel,
} from '@/app/ade/studio/components/chatbot/ollama-model-defaults';
import { accumulateOllamaSse } from '@lib/ollama-chat-sse';
import { computeStudioSchemaFingerprint } from '@lib/studio-schema-fingerprint';
import { propertyItemToExistingApiShape } from '@lib/property-item-utils';
import { normalizeGeneratedPropertyDescription } from '@lib/ai-property-description';

export interface PropertyDescriptionAiButtonProps {
  tenantId: string | null | undefined;
  projectId: string;
  versionId: string | null | undefined;
  propertyName: string;
  /** Compact JSON Schema snapshot for the property (`data`). */
  propertySchema: Record<string, unknown>;
  contextClassName?: string | null;
  existingClasses: string[];
  existingProperties: PropertyItem[];
  studioContext: ChatStudioContext;
  onGenerated: (description: string) => void;
  disabled?: boolean;
  /** Optional label for tests / layout */
  className?: string;
}

export function PropertyDescriptionAiButton({
  tenantId,
  projectId,
  versionId,
  propertyName,
  propertySchema,
  contextClassName,
  existingClasses,
  existingProperties,
  studioContext,
  onGenerated,
  disabled,
  className,
}: PropertyDescriptionAiButtonProps) {
  const [modelNames, setModelNames] = useState<string[]>([]);
  const [selectedModel, setSelectedModel] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const requestIdRef = useRef(0);

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
  }, [tenantId, projectId]);

  const stop = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
  }, []);

  const generate = useCallback(async () => {
    const name = propertyName.trim();
    if (!name || !selectedModel.trim()) return;

    persistOllamaModelChoiceForScope({
      tenantId,
      projectId,
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

    let schemaContextFingerprint: string | undefined;
    if (studioContext && !isChatStudioContextEmpty(studioContext)) {
      try {
        schemaContextFingerprint = await computeStudioSchemaFingerprint(studioContext);
      } catch {
        /* optional */
      }
    }
    if (ac.signal.aborted || requestId !== requestIdRef.current) return;

    const existingPropsPayload = existingProperties.map(propertyItemToExistingApiShape);

    const userLines = [
      `Write a documentation description for this schema property.`,
      `Property name: ${name}`,
      contextClassName?.trim() ? `Containing class: ${contextClassName.trim()}` : null,
      `JSON Schema for the property (library/canvas data): ${JSON.stringify(propertySchema)}`,
    ].filter(Boolean);

    try {
      const response = await fetch('/api/ollama/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        signal: ac.signal,
        body: JSON.stringify({
          model: selectedModel.trim(),
          task: 'property_description',
          messages: [{ role: 'user', content: userLines.join('\n') }],
          existingClassNames: existingClasses,
          existingProperties: existingPropsPayload,
          targetPropertyName: name,
          targetClassName: typeof contextClassName === 'string' ? contextClassName : undefined,
          ...(typeof versionId === 'string' && versionId ? { versionId } : {}),
          ...(schemaContextFingerprint ? { schemaContextFingerprint } : {}),
        }),
      });

      if (!response.ok) {
        const t = await response.text().catch(() => '');
        throw new Error(t || `Request failed (${response.status})`);
      }

      const full = await accumulateOllamaSse(response, ac.signal);
      if (ac.signal.aborted || requestId !== requestIdRef.current) return;

      const normalized = normalizeGeneratedPropertyDescription(full);
      if (!normalized) {
        setError('The model returned an empty description. Try again or pick another model.');
        return;
      }
      onGenerated(normalized);
    } catch (e) {
      if (ac.signal.aborted || requestId !== requestIdRef.current) return;
      setError(e instanceof Error ? e.message : 'Something went wrong.');
    } finally {
      if (requestId !== requestIdRef.current) return;
      setBusy(false);
      if (abortRef.current === ac) abortRef.current = null;
    }
  }, [
    propertyName,
    selectedModel,
    tenantId,
    projectId,
    versionId,
    propertySchema,
    contextClassName,
    existingClasses,
    existingProperties,
    studioContext,
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

  const canRun = Boolean(propertyName.trim() && selectedModel.trim() && !disabled);

  return (
    <div className={className}>
      <div className="flex flex-wrap items-center gap-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={!canRun || busy || modelNames.length === 0}
          onClick={() => void generate()}
          data-testid="property-description-ai-generate"
          className="shrink-0 border-violet-300 text-violet-800 hover:bg-violet-50 dark:border-violet-700 dark:text-violet-200 dark:hover:bg-violet-950/40"
        >
          {busy ? (
            <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" aria-hidden />
          ) : (
            <Sparkles className="mr-1.5 h-3.5 w-3.5" aria-hidden />
          )}
          {busy ? 'Generating…' : 'Generate with AI'}
        </Button>
        {busy && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={stop}
            data-testid="property-description-ai-stop"
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
