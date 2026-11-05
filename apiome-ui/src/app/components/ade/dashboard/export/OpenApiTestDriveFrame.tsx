'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, Loader2, ShieldCheck } from 'lucide-react';

import {
  isTestDriveMessage,
  mockRequestPath,
  openApiViewerSrc,
  parseOpenApiDocument,
  TEST_DRIVE_MESSAGE_PREFIX,
  withMockServer,
  type OpenApiViewerKind,
} from './openApiTestDrive';

/** The running mock a Swagger UI tab may send Try it out requests to. */
export interface OpenApiTestDriveMock {
  /** The mock instance id (its try proxy is `/api/export/mock/{id}/try`). */
  id: string;
  /** Its base URL; the document's servers are pointed here. */
  baseUrl: string;
}

export interface OpenApiTestDriveFrameProps {
  /** Swagger UI or ReDoc. */
  viewer: OpenApiViewerKind;
  /** The emitted document's text. */
  text: string;
  /** A running mock, when there is one — Swagger UI's Try it out reaches it; ReDoc is read-only. */
  mock?: OpenApiTestDriveMock | null;
}

/** What the frame shows while the viewer works. */
type FrameState = 'loading' | 'rendered' | 'error';

/**
 * OpenApiTestDriveFrame — the Swagger UI / ReDoc test-drive tab body (MFX-44.2, #4368).
 *
 * Renders the emitted OpenAPI document in a **sandboxed iframe** (`sandbox="allow-scripts"`, opaque
 * origin) whose page cannot reach the network (`connect-src 'none'`). The document is parsed here and
 * posted in. Swagger UI's Try it out is on only while a mock is running: the viewer posts each request
 * here, and a request under the mock's base URL is sent through the authenticated try proxy — anything
 * else is refused.
 *
 * @param props See {@link OpenApiTestDriveFrameProps}.
 * @returns The viewer, or why the document cannot be shown.
 */
export function OpenApiTestDriveFrame({ viewer, text, mock = null }: OpenApiTestDriveFrameProps) {
  const frameRef = useRef<HTMLIFrameElement | null>(null);
  const [ready, setReady] = useState(false);
  const [state, setState] = useState<FrameState>('loading');
  const [error, setError] = useState<string | null>(null);
  const parsed = useMemo(() => parseOpenApiDocument(text), [text]);
  const tryOut = viewer === 'swagger-ui' && mock !== null;
  // The mock by value: a new object for the same mock must not re-render the viewer.
  const mockBaseUrl = tryOut && mock ? mock.baseUrl : null;

  const post = useCallback((message: Record<string, unknown>) => {
    // The sandboxed page has an opaque origin, so it cannot be named as a target; the message goes to
    // this one window only.
    frameRef.current?.contentWindow?.postMessage(message, '*');
  }, []);

  // Send (or re-send, when the document or the mock changes) the document once the page listens.
  useEffect(() => {
    if (!ready || !parsed.ok) return;
    const spec = mockBaseUrl ? withMockServer(parsed.document.spec, mockBaseUrl) : parsed.document.spec;
    post({ type: `${TEST_DRIVE_MESSAGE_PREFIX}load`, spec, tryOut: mockBaseUrl !== null, large: parsed.document.large });
  }, [ready, parsed, mockBaseUrl, post]);

  const answer = useCallback(
    async (request: Record<string, unknown>) => {
      const id = request.id;
      const reply = (extra: Record<string, unknown>) => post({ type: `${TEST_DRIVE_MESSAGE_PREFIX}response`, id, ...extra });
      const path = mock ? mockRequestPath(String(request.url ?? ''), mock.baseUrl) : null;
      if (!tryOut || !mock || path === null) {
        reply({ error: 'Only requests to the running mock server are sent.' });
        return;
      }
      try {
        const res = await fetch(`/api/export/mock/${encodeURIComponent(mock.id)}/try`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ method: String(request.method ?? 'GET'), path }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || data?.success === false) {
          reply({ error: typeof data?.error === 'string' ? data.error : 'The mock did not answer.' });
          return;
        }
        reply({ status: data.status, headers: data.headers ?? {}, body: data.body ?? '' });
      } catch {
        reply({ error: 'The mock did not answer.' });
      }
    },
    [mock, tryOut, post],
  );

  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      if (!frameRef.current || event.source !== frameRef.current.contentWindow) return;
      if (isTestDriveMessage(event.data, 'ready')) setReady(true);
      else if (isTestDriveMessage(event.data, 'rendered')) setState('rendered');
      else if (isTestDriveMessage(event.data, 'error')) {
        setState('error');
        setError(String(event.data.message ?? 'The viewer could not render this document.'));
      } else if (isTestDriveMessage(event.data, 'request')) void answer(event.data);
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, [answer]);

  if (!parsed.ok) {
    return (
      <p className="xstd-notice" data-tone="warn" data-testid="openapi-test-drive-unreadable">
        <AlertTriangle aria-hidden />
        <span className="xstd-notice__grow">{parsed.error}</span>
      </p>
    );
  }

  const label = viewer === 'redoc' ? 'ReDoc' : 'Swagger UI';
  return (
    <div className="xstd-testdrive__viewer" data-testid={`openapi-test-drive-${viewer}`} data-state={state}>
      <p className="xstd-testdrive__viewer-note">
        <ShieldCheck aria-hidden />
        <span>
          {viewer === 'redoc'
            ? 'A read-only reference of the generated file, drawn in a sandbox that makes no network requests.'
            : tryOut
              ? 'Try it out sends requests to the running mock server, through Apiome. Nothing else leaves the sandbox.'
              : 'Drawn in a sandbox that makes no network requests. Start the mock server on the Mock server tab to try operations.'}
          {parsed.document.large ? ` This document has ${parsed.document.operations} operations, so it opens collapsed.` : ''}
        </span>
      </p>
      {/* MFX-46.5: the sandboxed viewer takes a moment to start — say so instead of a blank frame. */}
      {state === 'loading' ? (
        <p className="xstd-loading-row" role="status" data-testid="test-drive-frame-loading">
          <Loader2 className="motion-safe:animate-spin" aria-hidden />
          Drawing the viewer…
        </p>
      ) : null}
      {state === 'error' && error ? (
        <p className="xstd-notice" data-tone="warn" role="alert">
          <AlertTriangle aria-hidden />
          <span className="xstd-notice__grow">{error}</span>
        </p>
      ) : null}
      <iframe
        ref={frameRef}
        key={viewer}
        title={`${label} view of the generated OpenAPI document`}
        src={openApiViewerSrc(viewer)}
        sandbox="allow-scripts"
        referrerPolicy="no-referrer"
        className="xstd-testdrive__frame"
        data-testid={`openapi-test-drive-frame-${viewer}`}
      />
    </div>
  );
}
