'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  SNIPPET_LANGS,
  SNIPPET_LANG_LABELS,
  operationIdForSnippet,
  publicSnippetUrl,
  snippetCacheKey,
  snippetErrorFromResponse,
  type PublicSnippetResponse,
} from '../../../../lib/sdk/snippets';
import type { PublicSdkCoordinates, SdkLang } from '../../../../lib/sdk/publicSdk';

interface OperationSnippetTabsProps {
  /** The tenant/project/version slugs of the viewed published version. */
  coords: PublicSdkCoordinates;
  /** The browser-reachable REST base URL, ending in `/v1`. */
  restApiBaseUrl: string;
  /** Upper-case HTTP method. */
  method: string;
  /** Templated operation path. */
  path: string;
  /** The spec-declared operationId, when it has one. */
  operationId?: string;
}

/** One tab's fetch state. */
type TabState =
  | { status: 'loading' }
  | { status: 'ready'; snippet: PublicSnippetResponse }
  | { status: 'error'; message: string };

/**
 * Per-operation snippet tabs on a published version page — SDK-3.3 (#4493).
 *
 * Renders the install line and the runnable call for one operation in TypeScript, Python and
 * cURL, fetched from the SDK-2.3 snippet service. The snippets come from the server rather than
 * being generated here on purpose: `lib/tryit/snippet` renders a request the *user* is composing,
 * while these show what the published contract says, rendered once so the browse tabs, the kit
 * download and Try It's copy-as-code can never disagree about the same operation.
 *
 * Each language is fetched on first view and cached for the life of the row, so switching tabs
 * back and forth costs nothing.
 */
export function OperationSnippetTabs({
  coords,
  restApiBaseUrl,
  method,
  path,
  operationId,
}: OperationSnippetTabsProps) {
  const [lang, setLang] = useState<SdkLang>('curl');
  const [state, setState] = useState<TabState>({ status: 'loading' });
  const [copied, setCopied] = useState(false);
  const cache = useRef(new Map<string, PublicSnippetResponse>());

  const identifier = operationIdForSnippet({ method, path, operationId });

  useEffect(() => {
    const key = snippetCacheKey(identifier, lang);
    const cached = cache.current.get(key);
    if (cached) {
      setState({ status: 'ready', snippet: cached });
      return;
    }

    let cancelled = false;
    setState({ status: 'loading' });
    (async () => {
      try {
        const response = await fetch(
          publicSnippetUrl(restApiBaseUrl, coords, identifier, lang)
        );
        if (!response.ok) {
          throw new Error(await snippetErrorFromResponse(response));
        }
        const snippet: PublicSnippetResponse = await response.json();
        cache.current.set(key, snippet);
        if (!cancelled) setState({ status: 'ready', snippet });
      } catch (err) {
        if (!cancelled) {
          setState({
            status: 'error',
            message: err instanceof Error ? err.message : 'Could not load the example.',
          });
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [restApiBaseUrl, coords, identifier, lang]);

  const copy = useCallback(async () => {
    if (state.status !== 'ready') return;
    try {
      await navigator.clipboard.writeText(state.snippet.code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard access refused — the code is on screen to select by hand.
    }
  }, [state]);

  return (
    <div className="overflow-hidden rounded-lg border border-zinc-200 dark:border-zinc-800">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-zinc-200 bg-zinc-50/60 px-2 dark:border-zinc-800 dark:bg-zinc-900/40">
        <div role="tablist" aria-label="Example language" className="flex flex-wrap">
          {SNIPPET_LANGS.map((value) => (
            <button
              key={value}
              type="button"
              role="tab"
              aria-selected={lang === value}
              onClick={() => setLang(value)}
              className={`-mb-px border-b-2 px-2.5 py-1.5 text-[11px] font-medium transition-colors ${
                lang === value
                  ? 'border-[var(--brand)] text-[var(--brand)]'
                  : 'border-transparent text-zinc-500 hover:text-zinc-800 dark:text-zinc-400 dark:hover:text-zinc-200'
              }`}
            >
              {SNIPPET_LANG_LABELS[value]}
            </button>
          ))}
        </div>
        {state.status === 'ready' && (
          <button
            type="button"
            onClick={copy}
            className="shrink-0 rounded px-2 py-1 text-[11px] font-medium text-zinc-500 transition-colors hover:bg-zinc-100 hover:text-zinc-800 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-200"
          >
            {copied ? 'Copied' : 'Copy'}
          </button>
        )}
      </div>

      <div className="p-3">
        {state.status === 'loading' && (
          <p className="text-[12px] text-zinc-500 dark:text-zinc-400">Loading example…</p>
        )}

        {state.status === 'error' && (
          <p className="text-[12px] text-zinc-500 dark:text-zinc-400">{state.message}</p>
        )}

        {state.status === 'ready' && (
          <div className="space-y-2">
            {state.snippet.install && (
              <pre className="overflow-x-auto rounded bg-zinc-50 px-3 py-2 font-mono text-[11.5px] text-zinc-700 dark:bg-zinc-900 dark:text-zinc-300">
                {state.snippet.install}
              </pre>
            )}
            <pre className="overflow-x-auto rounded bg-zinc-50 px-3 py-2 font-mono text-[11.5px] leading-relaxed text-zinc-800 dark:bg-zinc-900 dark:text-zinc-200">
              {state.snippet.code}
            </pre>
            {state.snippet.placeholders.length > 0 && (
              <ul className="flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-zinc-500 dark:text-zinc-400">
                {state.snippet.placeholders.map((placeholder) => (
                  <li key={placeholder.token}>
                    <code className="font-mono text-zinc-700 dark:text-zinc-300">
                      {placeholder.token}
                    </code>{' '}
                    — {placeholder.kind === 'secret' ? 'your ' : ''}
                    {placeholder.name}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
