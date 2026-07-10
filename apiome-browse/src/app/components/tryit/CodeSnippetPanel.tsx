'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  buildSnippetRequest,
  generateSnippet,
  type SnippetTarget,
} from '../../../../lib/tryit/snippet';
import {
  applyAuthToRequest,
  type AuthCredentialsMap,
  type SupportedAuthScheme,
} from '../../../../lib/tryit/auth';
import type { SecretPlaceholderMap } from '../../../../lib/tryit/secrets';
import type { ExtraHeader, ParamSpec } from '../../../../lib/tryit/operation';

const TARGET_ORDER: SnippetTarget[] = ['curl', 'fetch', 'httpx'];
const TARGET_LABELS: Record<SnippetTarget, string> = {
  curl: 'cURL',
  fetch: 'JavaScript',
  httpx: 'Python',
};

interface CodeSnippetPanelProps {
  /** Upper-case HTTP method. */
  method: string;
  /** Absolute server base URL from the picker (empty when unset). */
  serverUrl: string;
  /** Templated operation path. */
  path: string;
  /** Operation parameters for URL/header composition. */
  params: ParamSpec[];
  /** Raw parameter form values keyed by `paramKey`. */
  values: Record<string, string>;
  /** User-added header rows. */
  extraHeaders: ExtraHeader[];
  /** Raw body editor text. */
  bodyText: string;
  /** Selected body content type, or null when no body variant is active. */
  contentType: string | null;
  /** SIM-3.6 schemes applied to the composed request before snippet generation. */
  authSchemes?: SupportedAuthScheme[];
  /** SIM-3.6 credential values keyed by scheme name. */
  authCredentials?: AuthCredentialsMap;
  /** Optional SIM-3.6 auth-helper placeholders merged over inferred secret names. */
  secretPlaceholders?: SecretPlaceholderMap;
}

/**
 * Live code-snippet panel for the Try It request builder — SIM-3.5 (#4451).
 *
 * Renders curl / fetch / httpx samples that track the composed request as the form changes.
 * Credential values are replaced with placeholders (see `lib/tryit/secrets.ts`); actual secrets
 * never appear in generated snippets. SIM-3.6 auth helpers feed both the composed request and
 * explicit placeholders.
 */
export function CodeSnippetPanel({
  method,
  serverUrl,
  path,
  params,
  values,
  extraHeaders,
  bodyText,
  contentType,
  authSchemes,
  authCredentials,
  secretPlaceholders,
}: CodeSnippetPanelProps) {
  const [target, setTarget] = useState<SnippetTarget>('curl');
  const [copied, setCopied] = useState(false);
  const [toastVisible, setToastVisible] = useState(false);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      if (toastTimer.current) clearTimeout(toastTimer.current);
    },
    []
  );

  const composed = useMemo(() => {
    if (!serverUrl.trim()) return null;
    const base = buildSnippetRequest({
      method,
      serverUrl: serverUrl.trim(),
      path,
      params,
      values,
      extraHeaders,
      body: bodyText.trim() === '' ? null : bodyText,
      contentType,
    });
    if (!authSchemes?.length || !authCredentials) return base;
    const withAuth = applyAuthToRequest(base.url, base.headers, authSchemes, authCredentials);
    return { ...base, url: withAuth.url, headers: withAuth.headers };
  }, [
    method,
    serverUrl,
    path,
    params,
    values,
    extraHeaders,
    bodyText,
    contentType,
    authSchemes,
    authCredentials,
  ]);

  const snippet = useMemo(
    () => (composed ? generateSnippet(target, composed, secretPlaceholders) : null),
    [composed, target, secretPlaceholders]
  );

  const onCopy = useCallback(async () => {
    if (!snippet) return;
    try {
      await navigator.clipboard.writeText(snippet);
      setCopied(true);
      setToastVisible(true);
      if (toastTimer.current) clearTimeout(toastTimer.current);
      toastTimer.current = setTimeout(() => {
        setCopied(false);
        setToastVisible(false);
      }, 1800);
    } catch {
      setCopied(false);
      setToastVisible(false);
    }
  }, [snippet]);

  return (
    <div>
      <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
        <span className="text-[11px] font-medium uppercase tracking-wider text-zinc-500 dark:text-zinc-400">
          Copy as code
        </span>
        <div className="inline-flex gap-1" role="group" aria-label="Snippet format">
          {TARGET_ORDER.map((entry) => (
            <button
              key={entry}
              type="button"
              onClick={() => setTarget(entry)}
              aria-pressed={target === entry}
              className={`rounded-md px-2.5 py-1 text-[11px] font-medium transition-colors ${
                target === entry
                  ? 'bg-[var(--brand)] text-white'
                  : 'bg-zinc-100 text-zinc-600 hover:bg-zinc-200 dark:bg-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-700'
              }`}
            >
              {TARGET_LABELS[entry]}
            </button>
          ))}
        </div>
      </div>

      {!composed ? (
        <p className="text-[12px] text-zinc-500 dark:text-zinc-400">
          Pick a server to generate a code snippet for this request.
        </p>
      ) : (
        <div className="relative">
          <div className="flex items-stretch gap-2">
            <pre className="min-w-0 flex-1 overflow-x-auto whitespace-pre rounded-lg border border-zinc-200 bg-white p-3 font-mono text-[11px] leading-relaxed text-zinc-700 dark:border-zinc-800 dark:bg-zinc-950 dark:text-zinc-300">
              <code>{snippet}</code>
            </pre>
            <button
              type="button"
              onClick={onCopy}
              className="shrink-0 self-start rounded-lg bg-zinc-900 px-3 py-2 text-xs font-medium text-white transition-colors hover:bg-zinc-700 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-300"
            >
              {copied ? 'Copied' : 'Copy'}
            </button>
          </div>
          <p
            role="status"
            aria-live="polite"
            className={`pointer-events-none absolute bottom-3 right-16 rounded-md bg-zinc-900 px-2.5 py-1 text-[11px] font-medium text-white shadow-md transition-opacity dark:bg-zinc-100 dark:text-zinc-900 ${
              toastVisible ? 'opacity-100' : 'opacity-0'
            }`}
          >
            Snippet copied
          </p>
        </div>
      )}
    </div>
  );
}
