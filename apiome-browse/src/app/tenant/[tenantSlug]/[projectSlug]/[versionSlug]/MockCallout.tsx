'use client';

import { useState } from 'react';

interface MockCalloutProps {
  /** The version's public mock base URL: `{mockHost}/{tenant}/{project}/{version}`. */
  mockBaseUrl: string;
  /** Ready-to-copy curl one-liner hitting a sample operation on the mock. */
  curlCommand: string;
}

/**
 * "Mock server" panel on the public version page — SIM-2.3 (#4444).
 *
 * Rendered only when the version's mock is enabled: shows the copyable mock base URL and a curl
 * one-liner so an API consumer reading the docs can hit the mock in seconds. The parent computes
 * both strings (via `lib/mock/mockUrl`), keeping this component purely presentational.
 */
export function MockCallout({ mockBaseUrl, curlCommand }: MockCalloutProps) {
  const [urlCopied, setUrlCopied] = useState(false);
  const [curlCopied, setCurlCopied] = useState(false);

  const copy = async (text: string, setFlag: (copied: boolean) => void) => {
    await navigator.clipboard.writeText(text);
    setFlag(true);
    setTimeout(() => setFlag(false), 1800);
  };

  return (
    <section className="rounded-xl border border-emerald-200 bg-emerald-50/40 shadow-xs dark:border-emerald-900/50 dark:bg-emerald-950/20">
      <header className="flex flex-wrap items-center gap-2 border-b border-emerald-100 px-4 py-2.5 dark:border-emerald-900/40">
        <h2 className="text-[11px] font-semibold uppercase tracking-wider text-emerald-800 dark:text-emerald-300">
          Mock server
        </h2>
        <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-0.5 text-[11px] font-medium text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300">
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-500"></span>
          Live
        </span>
      </header>
      <div className="space-y-3 p-4">
        <p className="text-[13px] leading-relaxed text-zinc-600 dark:text-zinc-400">
          This version serves mock responses generated from its specification — no API key
          required.
        </p>

        <div>
          <div className="mb-1 text-[11px] font-medium uppercase tracking-wider text-zinc-500 dark:text-zinc-400">
            Base URL
          </div>
          <div className="flex items-stretch gap-2">
            <code className="min-w-0 flex-1 overflow-x-auto whitespace-pre rounded-lg bg-white p-3 font-mono text-xs text-zinc-700 ring-1 ring-inset ring-zinc-200 dark:bg-zinc-950 dark:text-zinc-300 dark:ring-zinc-800">
              {mockBaseUrl}
            </code>
            <button
              type="button"
              onClick={() => copy(mockBaseUrl, setUrlCopied)}
              className="shrink-0 self-start rounded-lg bg-zinc-900 px-3 py-2 text-xs font-medium text-white transition-colors hover:bg-zinc-700 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-300"
            >
              {urlCopied ? 'Copied' : 'Copy'}
            </button>
          </div>
        </div>

        <div>
          <div className="mb-1 text-[11px] font-medium uppercase tracking-wider text-zinc-500 dark:text-zinc-400">
            Try it
          </div>
          <div className="flex items-stretch gap-2">
            <code className="min-w-0 flex-1 overflow-x-auto whitespace-pre rounded-lg bg-white p-3 font-mono text-xs text-zinc-700 ring-1 ring-inset ring-zinc-200 dark:bg-zinc-950 dark:text-zinc-300 dark:ring-zinc-800">
              {curlCommand}
            </code>
            <button
              type="button"
              onClick={() => copy(curlCommand, setCurlCopied)}
              className="shrink-0 self-start rounded-lg bg-zinc-900 px-3 py-2 text-xs font-medium text-white transition-colors hover:bg-zinc-700 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-300"
            >
              {curlCopied ? 'Copied' : 'Copy'}
            </button>
          </div>
        </div>
      </div>
    </section>
  );
}
