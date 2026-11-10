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
    <div className="flex h-[120px] items-center justify-center bg-subtle text-xs text-fg-muted">
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
      <div className="rounded-lg border border-danger/30 bg-danger-soft/60 p-3">
        <div className="flex flex-wrap items-center gap-3">
          <span className="rounded-xs bg-danger-soft px-1.5 py-0.5 font-mono text-2xs font-semibold text-danger-fg">
            {result.status} {result.statusText}
          </span>
          <span className="text-xs font-semibold text-danger-fg">
            {gatewayFailure.title}
          </span>
          <span className="text-2xs tabular-nums text-danger-fg/70">
            after {formatDuration(result.durationMs)}
          </span>
        </div>
        {result.bodyText && (
          <p className="mt-2 font-mono text-2xs text-danger-fg/90">
            {result.bodyText}
          </p>
        )}
        <p className="mt-2 text-xs text-danger-fg">{gatewayFailure.hint}</p>
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-lg border border-border bg-surface">
      {/* Status line */}
      <div className="flex flex-wrap items-center gap-3 border-b border-border px-3 py-2">
        <span
          className={`rounded-xs px-1.5 py-0.5 font-mono text-2xs font-semibold ${
            result.status < 300
              ? 'bg-ok-soft text-ok-fg'
              : result.status < 400
              ? 'bg-honey-soft text-honey-fg'
              : 'bg-danger-soft text-danger-fg'
          }`}
        >
          {result.status} {result.statusText}
        </span>
        <span className="text-2xs tabular-nums text-fg-muted">
          {formatDuration(result.durationMs)} · {formatBytes(result.sizeBytes)} · via{' '}
          {result.via === 'proxy' ? 'relay' : 'direct fetch'}
        </span>
        {result.truncated && (
          <span className="rounded-full bg-honey-soft px-1.5 py-0.5 text-2xs font-medium text-honey-fg">
            truncated at 1 MB
          </span>
        )}
        <span className="grow" />
        {presentation.view !== 'empty' && (
          <button
            type="button"
            onClick={download}
            className="rounded-md border border-border bg-surface px-2 py-1 text-2xs font-medium text-fg-muted shadow-xs transition-colors hover:bg-subtle"
          >
            Download {filename}
          </button>
        )}
      </div>

      {/* Tabs */}
      <div
        role="tablist"
        aria-label="Response sections"
        className="flex items-center gap-1 border-b border-border px-3 pt-2"
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
            className={`rounded-t-md border-b-2 px-2.5 py-1.5 text-2xs font-medium uppercase tracking-wider transition-colors ${
              tab === key
                ? 'border-accent text-fg'
                : 'border-transparent text-fg-muted hover:text-fg-muted'
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
      <p className="p-3 text-xs text-fg-muted">
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
          className="rounded-md border border-border bg-surface px-2 py-1 text-2xs font-medium text-fg-muted shadow-xs transition-colors hover:bg-subtle"
        >
          {copied === '__all__' ? 'Copied' : 'Copy all'}
        </button>
      </div>
      <dl className="space-y-1">
        {entries.map(([name, value]) => (
          <div key={name} className="group flex items-start gap-2 font-mono text-2xs">
            <dt className="shrink-0 text-fg-muted">{name}:</dt>
            <dd className="min-w-0 break-all text-fg">{value}</dd>
            <button
              type="button"
              onClick={() => copy(name, `${name}: ${value}`)}
              aria-label={`Copy header ${name}`}
              className="ml-auto shrink-0 rounded-xs border border-transparent px-1 font-sans text-2xs text-fg-subtle opacity-0 transition-opacity hover:text-fg-muted focus:opacity-100 group-hover:opacity-100"
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
        <p className="border-b border-honey/30 bg-honey-soft/60 px-3 py-2 text-2xs text-honey-fg">
          The relay truncated this body at its 1 MB cap — the view and download contain only the
          first {formatBytes(result.sizeBytes)} of the response.
        </p>
      )}

      {presentation.view === 'empty' && (
        <p className="p-3 text-xs text-fg-muted">
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
            className="max-h-80 max-w-full rounded-md border border-border"
          />
          <figcaption className="text-2xs text-fg-muted">
            {presentation.mime} · {formatBytes(result.sizeBytes)}
            {result.truncated ? ' — truncated, the image may not render completely' : ''}
          </figcaption>
        </figure>
      )}

      {presentation.view === 'binary' && (
        <div className="flex flex-wrap items-center gap-3 p-3">
          <p className="text-xs text-fg-muted">
            Binary response ({presentation.mime || 'unknown type'} ·{' '}
            {formatBytes(result.sizeBytes)}) — download it to view the content.
          </p>
          <button
            type="button"
            onClick={download}
            className="rounded-md border border-border bg-surface px-2 py-1 text-2xs font-medium text-fg-muted shadow-xs transition-colors hover:bg-subtle"
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
                  className={`rounded-md px-2 py-1 text-2xs font-medium transition-colors ${
                    mode === key
                      ? 'bg-subtle text-fg'
                      : 'text-fg-muted hover:text-fg-muted'
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
    <div className="border-t border-border">
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
