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
import { parseGeneratedPropertyExample } from '@lib/ai-property-description';

export interface PropertyExampleAiButtonProps {
  tenantId: string | null | undefined;
  projectId: string;
  versionId: string | null | undefined;
  propertyName: string;
  /** Compact JSON Schema snapshot for the property (`data`). */
  propertySchema: Record<string, unknown>;
  /** Documentation description field when present — improves example realism (#622). */
  propertyDescription?: string | null;
  /** Nested object member names (class canvas editor) for richer object examples. */
  nestedMembers?: Array<{ name: string; description?: string | null }>;
  contextClassName?: string | null;
  existingClasses: string[];
  existingProperties: PropertyItem[];
  studioContext: ChatStudioContext;
  /** Pretty-printed JSON string appended to the property examples list. */
  onGenerated: (exampleJson: string) => void;
  disabled?: boolean;
  className?: string;
}

export function PropertyExampleAiButton({
  tenantId,
  projectId,
  versionId,
  propertyName,
  propertySchema,
  propertyDescription,
  nestedMembers,
  contextClassName,
  existingClasses,
  existingProperties,
  studioContext,
  onGenerated,
  disabled,
  className,
}: PropertyExampleAiButtonProps) {
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

    try {
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

      const desc = typeof propertyDescription === 'string' ? propertyDescription.trim() : '';
      const nestedPayload =
        nestedMembers?.filter((m) => m?.name?.trim()).map((m) => ({
          name: m.name.trim(),
          ...(m.description != null && String(m.description).trim()
            ? { description: String(m.description).trim().slice(0, 500) }
            : {}),
        })) ?? [];

      const userLines = [
        `Generate one realistic example JSON value for this schema property (for OpenAPI / Studio documentation examples).`,
        `Property name: ${name}`,
        contextClassName?.trim() ? `Containing class: ${contextClassName.trim()}` : null,
        desc ? `Property documentation description: ${desc}` : null,
        nestedPayload.length > 0
          ? `Nested object members (when shaping objects): ${JSON.stringify(nestedPayload)}`
          : null,
        `JSON Schema for the property (library/canvas data): ${JSON.stringify(propertySchema)}`,
      ].filter(Boolean);

      const response = await fetch('/api/ollama/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        signal: ac.signal,
        body: JSON.stringify({
          model: selectedModel.trim(),
          task: 'property_example',
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

      const parsedExample = parseGeneratedPropertyExample(full);
      if (!parsedExample) {
        setError('The model did not return a valid {"example": ...} JSON block. Try again or pick another model.');
        return;
      }

      let jsonLine: string;
      try {
        jsonLine = JSON.stringify(parsedExample.value, null, 2);
      } catch {
        setError('The model returned a value that cannot be serialized as JSON.');
        return;
      }
      if (!jsonLine.trim()) {
        setError('The model returned an empty example. Try again or pick another model.');
        return;
      }
      onGenerated(jsonLine);
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
    propertyDescription,
    nestedMembers,
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
          data-testid="property-example-ai-generate"
          className="shrink-0 border-violet-300 text-violet-800 hover:bg-violet-50 dark:border-violet-700 dark:text-violet-200 dark:hover:bg-violet-950/40"
        >
          {busy ? (
            <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" aria-hidden />
          ) : (
            <Sparkles className="mr-1.5 h-3.5 w-3.5" aria-hidden />
          )}
          {busy ? 'Generating…' : 'Generate example with AI'}
        </Button>
        {busy && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={stop}
            data-testid="property-example-ai-stop"
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
