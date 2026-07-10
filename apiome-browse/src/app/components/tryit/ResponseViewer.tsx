'use client';

import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import dynamic from 'next/dynamic';
import { decodeBodyBytes } from '../../../../lib/tryit/body';
import {
  bodyDataUrl,
  classifyBody,
  describeGatewayFailure,
  formatBytes,
  formatDuration,
  headersClipboardText,
  prettyPrintBody,
  suggestDownloadFilename,
} from '../../../../lib/tryit/response';
import type { TryItResult } from '../../../../lib/tryit/send';

const Editor = dynamic(() => import('@monaco-editor/react'), {
  ssr: false,
  loading: () => (
    <div className="flex h-[120px] items-center justify-center bg-zinc-50 text-[12px] text-zinc-500 dark:bg-zinc-900 dark:text-zinc-400">
      Loading viewer...
    </div>
  ),
});

/** Line height (px) matching the Monaco options below, for sizing the read-only viewer. */
const EDITOR_LINE_HEIGHT = 18;
/** Vertical padding (px) around the Monaco content when sizing the viewer. */
const EDITOR_PADDING = 14;
/** Tallest the body viewer grows before it scrolls internally. */
const EDITOR_MAX_HEIGHT = 360;

interface ResponseViewerProps {
  /** The completed Try It result to display. */
  result: TryItResult;
  /** The templated operation path (drives the download filename). */
  operationPath: string;
}

/**
 * Try It response viewer — SIM-3.3 (#4449).
 *
 * Renders a completed `TryItResult`: a status line (color-coded status, timing, size), a
 * Headers tab with copy support, and a Body tab with pretty/raw syntax-highlighted text views,
 * inline images, a download-only card for other binary content, and a clearly surfaced notice
 * when the relay truncated the body. Relay-synthesized gateway failures (timeout, unreachable
 * target) render as distinct, actionable error cards instead of masquerading as upstream
 * responses.
 */
export function ResponseViewer({ result, operationPath }: ResponseViewerProps) {
  const idBase = useId();
  const [tab, setTab] = useState<'body' | 'headers'>('body');

  const gatewayFailure = describeGatewayFailure(result);
  const presentation = useMemo(() => classifyBody(result), [result]);
  const prettyText = useMemo(
    () =>
      presentation.view === 'text' ? prettyPrintBody(result.bodyText, presentation.pretty) : null,
    [presentation, result.bodyText]
  );

  const filename = suggestDownloadFilename(result, operationPath);
  const download = useCallback(() => {
    // Copy into a fresh array so TypeScript sees a plain ArrayBuffer-backed BlobPart.
    const bytes = new Uint8Array(decodeBodyBytes(result.bodyText, result.bodyEncoding));
    const blob = new Blob([bytes], {
      type: presentation.mime || 'application/octet-stream',
    });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = filename;
    anchor.click();
    URL.revokeObjectURL(url);
  }, [result.bodyText, result.bodyEncoding, presentation.mime, filename]);

  const headerEntries = Object.entries(result.headers);

  // Relay-synthesized failures (timeout / unreachable) get a distinct actionable card: there is
  // no upstream response to inspect, so tabs and body views would only mislead.
  if (gatewayFailure) {
    return (
      <div className="rounded-lg border border-rose-200 bg-rose-50/60 p-3 dark:border-rose-900/50 dark:bg-rose-950/20">
        <div className="flex flex-wrap items-center gap-3">
          <span className="rounded bg-rose-100 px-1.5 py-0.5 font-mono text-[11px] font-semibold text-rose-700 dark:bg-rose-500/10 dark:text-rose-300">
            {result.status} {result.statusText}
          </span>
          <span className="text-[12px] font-semibold text-rose-800 dark:text-rose-300">
            {gatewayFailure.title}
          </span>
          <span className="text-[11px] tabular-nums text-rose-700/70 dark:text-rose-300/70">
            after {formatDuration(result.durationMs)}
          </span>
        </div>
        {result.bodyText && (
          <p className="mt-2 font-mono text-[11px] text-rose-800/90 dark:text-rose-300/90">
            {result.bodyText}
          </p>
        )}
        <p className="mt-2 text-[12px] text-rose-800 dark:text-rose-300">{gatewayFailure.hint}</p>
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-lg border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-950">
      {/* Status line */}
      <div className="flex flex-wrap items-center gap-3 border-b border-zinc-100 px-3 py-2 dark:border-zinc-800/80">
        <span
          className={`rounded px-1.5 py-0.5 font-mono text-[11px] font-semibold ${
            result.status < 300
              ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300'
              : result.status < 400
              ? 'bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300'
              : 'bg-rose-50 text-rose-700 dark:bg-rose-500/10 dark:text-rose-300'
          }`}
        >
          {result.status} {result.statusText}
        </span>
        <span className="text-[11px] tabular-nums text-zinc-500 dark:text-zinc-400">
          {formatDuration(result.durationMs)} · {formatBytes(result.sizeBytes)} · via{' '}
          {result.via === 'proxy' ? 'relay' : 'direct fetch'}
        </span>
        {result.truncated && (
          <span className="rounded-full bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium text-amber-700 dark:bg-amber-500/10 dark:text-amber-300">
            truncated at 1 MB
          </span>
        )}
        <span className="grow" />
        {presentation.view !== 'empty' && (
          <button
            type="button"
            onClick={download}
            className="rounded-md border border-zinc-200 bg-white px-2 py-1 text-[11px] font-medium text-zinc-700 shadow-xs transition-colors hover:bg-zinc-50 dark:border-zinc-800 dark:bg-zinc-950 dark:text-zinc-300 dark:hover:bg-zinc-800"
          >
            Download {filename}
          </button>
        )}
      </div>

      {/* Tabs */}
      <div
        role="tablist"
        aria-label="Response sections"
        className="flex items-center gap-1 border-b border-zinc-100 px-3 pt-2 dark:border-zinc-800/80"
      >
        {(['body', 'headers'] as const).map((key) => (
          <button
            key={key}
            type="button"
            role="tab"
            id={`${idBase}-tab-${key}`}
            aria-selected={tab === key}
            aria-controls={`${idBase}-panel-${key}`}
            onClick={() => setTab(key)}
            className={`rounded-t-md border-b-2 px-2.5 py-1.5 text-[11px] font-medium uppercase tracking-wider transition-colors ${
              tab === key
                ? 'border-[var(--brand)] text-zinc-800 dark:text-zinc-200'
                : 'border-transparent text-zinc-500 hover:text-zinc-700 dark:text-zinc-400 dark:hover:text-zinc-300'
            }`}
          >
            {key === 'body' ? 'Body' : `Headers (${headerEntries.length})`}
          </button>
        ))}
      </div>

      <div
        role="tabpanel"
        id={`${idBase}-panel-${tab}`}
        aria-labelledby={`${idBase}-tab-${tab}`}
      >
        {tab === 'headers' ? (
          <HeadersView headers={result.headers} />
        ) : (
          <BodyView result={result} presentation={presentation} prettyText={prettyText} download={download} />
        )}
      </div>
    </div>
  );
}

/** The Headers tab: copyable name/value rows plus a copy-all action. */
function HeadersView({ headers }: { headers: Record<string, string> }) {
  const entries = Object.entries(headers);
  const { copied, copy } = useCopyFeedback();

  if (entries.length === 0) {
    return (
      <p className="p-3 text-[12px] text-zinc-500 dark:text-zinc-400">
        The response carried no headers.
      </p>
    );
  }
  return (
    <div className="p-3">
      <div className="mb-2 flex justify-end">
        <button
          type="button"
          onClick={() => copy('__all__', headersClipboardText(headers))}
          className="rounded-md border border-zinc-200 bg-white px-2 py-1 text-[11px] font-medium text-zinc-700 shadow-xs transition-colors hover:bg-zinc-50 dark:border-zinc-800 dark:bg-zinc-950 dark:text-zinc-300 dark:hover:bg-zinc-800"
        >
          {copied === '__all__' ? 'Copied' : 'Copy all'}
        </button>
      </div>
      <dl className="space-y-1">
        {entries.map(([name, value]) => (
          <div key={name} className="group flex items-start gap-2 font-mono text-[11px]">
            <dt className="shrink-0 text-zinc-500 dark:text-zinc-400">{name}:</dt>
            <dd className="min-w-0 break-all text-zinc-800 dark:text-zinc-200">{value}</dd>
            <button
              type="button"
              onClick={() => copy(name, `${name}: ${value}`)}
              aria-label={`Copy header ${name}`}
              className="ml-auto shrink-0 rounded border border-transparent px-1 font-sans text-[10px] text-zinc-400 opacity-0 transition-opacity hover:text-zinc-700 focus:opacity-100 group-hover:opacity-100 dark:hover:text-zinc-300"
            >
              {copied === name ? 'Copied' : 'Copy'}
            </button>
          </div>
        ))}
      </dl>
    </div>
  );
}

/** The Body tab: truncation notice plus the text / image / binary / empty presentation. */
function BodyView({
  result,
  presentation,
  prettyText,
  download,
}: {
  result: TryItResult;
  presentation: ReturnType<typeof classifyBody>;
  prettyText: string | null;
  download: () => void;
}) {
  const [mode, setMode] = useState<'pretty' | 'raw'>(prettyText !== null ? 'pretty' : 'raw');
  // A fresh response (new pretty form) re-picks the default view for that body — the
  // adjust-state-during-render pattern, so no extra effect pass is needed.
  const [seenPretty, setSeenPretty] = useState(prettyText);
  if (seenPretty !== prettyText) {
    setSeenPretty(prettyText);
    setMode(prettyText !== null ? 'pretty' : 'raw');
  }
  const shown = mode === 'pretty' && prettyText !== null ? prettyText : result.bodyText;
  const editorHeight = useMemo(() => {
    const lines = shown.split('\n').length;
    return Math.min(EDITOR_MAX_HEIGHT, lines * EDITOR_LINE_HEIGHT + EDITOR_PADDING);
  }, [shown]);

  return (
    <div>
      {result.truncated && (
        <p className="border-b border-amber-100 bg-amber-50/60 px-3 py-2 text-[11px] text-amber-800 dark:border-amber-900/40 dark:bg-amber-950/20 dark:text-amber-300">
          The relay truncated this body at its 1 MB cap — the view and download contain only the
          first {formatBytes(result.sizeBytes)} of the response.
        </p>
      )}

      {presentation.view === 'empty' && (
        <p className="p-3 text-[12px] text-zinc-500 dark:text-zinc-400">
          The response body is empty.
        </p>
      )}

      {presentation.view === 'image' && (
        <figure className="space-y-2 p-3">
          {/* A data: URL is required here — the bytes only exist in the relay envelope. */}
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={bodyDataUrl(result, presentation.mime)}
            alt={`Response image (${presentation.mime})`}
            className="max-h-80 max-w-full rounded-md border border-zinc-200 dark:border-zinc-800"
          />
          <figcaption className="text-[11px] text-zinc-500 dark:text-zinc-400">
            {presentation.mime} · {formatBytes(result.sizeBytes)}
            {result.truncated ? ' — truncated, the image may not render completely' : ''}
          </figcaption>
        </figure>
      )}

      {presentation.view === 'binary' && (
        <div className="flex flex-wrap items-center gap-3 p-3">
          <p className="text-[12px] text-zinc-600 dark:text-zinc-400">
            Binary response ({presentation.mime || 'unknown type'} ·{' '}
            {formatBytes(result.sizeBytes)}) — download it to view the content.
          </p>
          <button
            type="button"
            onClick={download}
            className="rounded-md border border-zinc-200 bg-white px-2 py-1 text-[11px] font-medium text-zinc-700 shadow-xs transition-colors hover:bg-zinc-50 dark:border-zinc-800 dark:bg-zinc-950 dark:text-zinc-300 dark:hover:bg-zinc-800"
          >
            Download
          </button>
        </div>
      )}

      {presentation.view === 'text' && (
        <div>
          {prettyText !== null && (
            <div className="flex items-center gap-1 px-3 pt-2">
              {(['pretty', 'raw'] as const).map((key) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => setMode(key)}
                  aria-pressed={mode === key}
                  className={`rounded-md px-2 py-1 text-[11px] font-medium transition-colors ${
                    mode === key
                      ? 'bg-zinc-100 text-zinc-800 dark:bg-zinc-800 dark:text-zinc-200'
                      : 'text-zinc-500 hover:text-zinc-700 dark:text-zinc-400 dark:hover:text-zinc-300'
                  }`}
                >
                  {key === 'pretty' ? 'Pretty' : 'Raw'}
                </button>
              ))}
            </div>
          )}
          <ReadOnlyBody
            text={shown}
            language={presentation.monacoLanguage}
            height={editorHeight}
          />
        </div>
      )}
    </div>
  );
}

/**
 * The syntax-highlighted read-only body view. Monaco virtualizes rendering, so even bodies at
 * the relay's 1 MB cap stay responsive.
 */
function ReadOnlyBody({
  text,
  language,
  height,
}: {
  text: string;
  language: string;
  height: number;
}) {
  const idBase = useId();
  return (
    <div className="border-t border-zinc-100 dark:border-zinc-800/80">
      <Editor
        height={`${height}px`}
        language={language}
        path={`tryit-response://${idBase.replace(/[^a-zA-Z0-9]/g, '')}/body`}
        value={text}
        options={{
          readOnly: true,
          domReadOnly: true,
          minimap: { enabled: false },
          lineNumbers: 'off',
          scrollBeyondLastLine: false,
          fontSize: 12,
          lineHeight: EDITOR_LINE_HEIGHT,
          fontFamily:
            'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace',
          automaticLayout: true,
          folding: false,
          renderLineHighlight: 'none',
          wordWrap: 'on',
          contextmenu: false,
        }}
      />
    </div>
  );
}

/** Clipboard helper: `copy(key, text)` writes text and marks `key` copied for a moment. */
function useCopyFeedback() {
  const [copied, setCopied] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    []
  );
  const copy = useCallback((key: string, text: string) => {
    void navigator.clipboard.writeText(text).then(() => {
      setCopied(key);
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => setCopied(null), 1500);
    });
  }, []);
  return { copied, copy };
}
