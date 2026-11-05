'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, Loader2, ShieldCheck } from 'lucide-react';

import { isTestDriveMessage, TEST_DRIVE_MESSAGE_PREFIX } from './openApiTestDrive';
import { asyncApiSummaryText, asyncApiViewerSrc, parseAsyncApiDocument } from './asyncApiTestDrive';

export interface AsyncApiTestDriveFrameProps {
  /** The emitted document's text (`asyncapi.json`, or YAML). */
  text: string;
}

/** What the frame shows while the renderer works. */
type FrameState = 'loading' | 'rendered' | 'error';

/**
 * AsyncApiTestDriveFrame — the AsyncAPI viewer test-drive tab body (MFX-44.4, #4370).
 *
 * Renders the emitted AsyncAPI 2.x / 3.x document with the AsyncAPI React component in a **sandboxed
 * iframe** (`sandbox="allow-scripts"`, opaque origin) whose page cannot reach the network
 * (`connect-src 'none'`). The document is parsed here and posted in; the renderer's sidebar navigates
 * its servers, operations (by channel), messages and schemas. A file that is not AsyncAPI 2.x / 3.x
 * shows a notice instead; one the renderer rejects shows its errors.
 *
 * @param props See {@link AsyncApiTestDriveFrameProps}.
 * @returns The renderer in its sandbox, or why the document cannot be shown.
 */
export function AsyncApiTestDriveFrame({ text }: AsyncApiTestDriveFrameProps) {
  const frameRef = useRef<HTMLIFrameElement | null>(null);
  const [ready, setReady] = useState(false);
  const [state, setState] = useState<FrameState>('loading');
  const [error, setError] = useState<string | null>(null);
  const parsed = useMemo(() => parseAsyncApiDocument(text), [text]);

  const post = useCallback((message: Record<string, unknown>) => {
    // The sandboxed page has an opaque origin, so it cannot be named as a target; the message goes to
    // this one window only.
    frameRef.current?.contentWindow?.postMessage(message, '*');
  }, []);

  // Send (or re-send, when the file changes) the document once the page listens.
  useEffect(() => {
    if (!ready || !parsed.ok) return;
    post({ type: `${TEST_DRIVE_MESSAGE_PREFIX}load`, spec: parsed.document.spec });
  }, [ready, parsed, post]);

  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      if (!frameRef.current || event.source !== frameRef.current.contentWindow) return;
      if (isTestDriveMessage(event.data, 'ready')) setReady(true);
      else if (isTestDriveMessage(event.data, 'rendered')) {
        setState('rendered');
        setError(null);
      } else if (isTestDriveMessage(event.data, 'error')) {
        setState('error');
        setError(String(event.data.message ?? 'The AsyncAPI renderer could not render this document.'));
      }
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, []);

  if (!parsed.ok) {
    return (
      <p className="xstd-notice" data-tone="warn" data-testid="asyncapi-test-drive-unreadable">
        <AlertTriangle aria-hidden />
        <span className="xstd-notice__grow">{parsed.error}</span>
      </p>
    );
  }

  return (
    <div className="xstd-testdrive__viewer" data-testid="asyncapi-test-drive" data-state={state}>
      <p className="xstd-testdrive__viewer-note">
        <ShieldCheck aria-hidden />
        <span>
          {asyncApiSummaryText(parsed.document)}. Drawn in a sandbox that makes no network requests; open the
          menu (☰) to jump to an operation, message or schema.
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
        title="AsyncAPI viewer of the generated AsyncAPI document"
        src={asyncApiViewerSrc()}
        sandbox="allow-scripts"
        referrerPolicy="no-referrer"
        className="xstd-testdrive__frame"
        data-testid="asyncapi-test-drive-frame"
      />
    </div>
  );
}
