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
    <section className="rounded-lg border border-ok/30 bg-ok-soft/40 shadow-xs">
      <header className="flex flex-wrap items-center gap-2 border-b border-ok/30 px-4 py-2.5">
        <h2 className="text-2xs font-semibold uppercase tracking-wider text-ok-fg">
          Mock server
        </h2>
        <span className="inline-flex items-center gap-1 rounded-full bg-ok-soft px-2 py-0.5 text-2xs font-medium text-ok-fg">
          <span className="h-1.5 w-1.5 rounded-full bg-ok"></span>
          Live
        </span>
      </header>
      <div className="space-y-3 p-4">
        <p className="text-sm leading-relaxed text-fg-muted">
          This version serves mock responses generated from its specification — no API key
          required.
        </p>

        <div>
          <div className="mb-1 text-2xs font-medium uppercase tracking-wider text-fg-muted">
            Base URL
          </div>
          <div className="flex items-stretch gap-2">
            <code className="min-w-0 flex-1 overflow-x-auto whitespace-pre rounded-lg bg-surface p-3 font-mono text-xs text-fg-muted ring-1 ring-inset ring-border">
              {mockBaseUrl}
            </code>
            <button
              type="button"
              onClick={() => copy(mockBaseUrl, setUrlCopied)}
              className="shrink-0 self-start rounded-lg bg-ink px-3 py-2 text-xs font-medium text-ink-fg transition-colors hover:bg-ink-hover"
            >
              {urlCopied ? 'Copied' : 'Copy'}
            </button>
          </div>
        </div>

        <div>
          <div className="mb-1 text-2xs font-medium uppercase tracking-wider text-fg-muted">
            Try it
          </div>
          <div className="flex items-stretch gap-2">
            <code className="min-w-0 flex-1 overflow-x-auto whitespace-pre rounded-lg bg-surface p-3 font-mono text-xs text-fg-muted ring-1 ring-inset ring-border">
              {curlCommand}
            </code>
            <button
              type="button"
              onClick={() => copy(curlCommand, setCurlCopied)}
              className="shrink-0 self-start rounded-lg bg-ink px-3 py-2 text-xs font-medium text-ink-fg transition-colors hover:bg-ink-hover"
            >
              {curlCopied ? 'Copied' : 'Copy'}
            </button>
          </div>
        </div>
      </div>
    </section>
  );
}
