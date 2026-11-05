'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, Loader2, ShieldCheck } from 'lucide-react';

import { isTestDriveMessage, TEST_DRIVE_MESSAGE_PREFIX } from './openApiTestDrive';
import { appAppearance, graphiqlViewerSrc, readGraphQLSdl, schemaSummaryText } from './graphqlTestDrive';

export interface GraphQLTestDriveFrameProps {
  /** The SDL to explore (the emitted `schema.graphql`). */
  sdl: string;
}

/** What the frame shows while GraphiQL works. */
type FrameState = 'loading' | 'rendered' | 'error';

/**
 * GraphQLTestDriveFrame — the GraphiQL test-drive tab body (MFX-44.3, #4369).
 *
 * Renders GraphiQL over the SDL in a **sandboxed iframe** (`sandbox="allow-scripts"`, opaque origin)
 * whose page cannot reach the network (`connect-src 'none'`). Queries are answered by **mock
 * resolvers** built from the schema inside that page, and the tab says so. The docs explorer and
 * autocomplete come from the schema itself. An SDL that is not a valid schema shows a notice instead.
 *
 * Takes only SDL, so the same component can draw any schema (a catalog playground, private-suite#1096,
 * would pass a cataloged schema's SDL).
 *
 * @param props See {@link GraphQLTestDriveFrameProps}.
 * @returns GraphiQL in its sandbox, or why the schema cannot be explored.
 */
export function GraphQLTestDriveFrame({ sdl }: GraphQLTestDriveFrameProps) {
  const frameRef = useRef<HTMLIFrameElement | null>(null);
  const [ready, setReady] = useState(false);
  const [state, setState] = useState<FrameState>('loading');
  const [error, setError] = useState<string | null>(null);
  const read = useMemo(() => readGraphQLSdl(sdl), [sdl]);

  const post = useCallback((message: Record<string, unknown>) => {
    // The sandboxed page has an opaque origin, so it cannot be named as a target; the message goes to
    // this one window only.
    frameRef.current?.contentWindow?.postMessage(message, '*');
  }, []);

  // Send (or re-send, when the file changes) the SDL once the page listens.
  useEffect(() => {
    if (!ready || !read.ok) return;
    post({ type: `${TEST_DRIVE_MESSAGE_PREFIX}load`, sdl, theme: appAppearance(document.documentElement) });
  }, [ready, read, sdl, post]);

  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      if (!frameRef.current || event.source !== frameRef.current.contentWindow) return;
      if (isTestDriveMessage(event.data, 'ready')) setReady(true);
      else if (isTestDriveMessage(event.data, 'rendered')) {
        setState('rendered');
        setError(null);
      } else if (isTestDriveMessage(event.data, 'error')) {
        setState('error');
        setError(String(event.data.message ?? 'GraphiQL could not load this schema.'));
      }
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, []);

  if (!read.ok) {
    return (
      <p className="xstd-notice" data-tone="warn" data-testid="graphql-test-drive-unreadable">
        <AlertTriangle aria-hidden />
        <span className="xstd-notice__grow">{read.error}</span>
      </p>
    );
  }

  return (
    <div className="xstd-testdrive__viewer" data-testid="graphql-test-drive" data-state={state}>
      <p className="xstd-testdrive__viewer-note">
        <ShieldCheck aria-hidden />
        <span>
          <strong className="xstd-testdrive__mock-badge" data-testid="graphql-test-drive-mock-label">Mock data</strong>{' '}
          Queries are answered in your browser with generated values of the right type, not by a server, and
          nothing leaves the sandbox. {schemaSummaryText(read.summary)}.
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
        title="GraphiQL view of the generated GraphQL schema, answering with mock data"
        src={graphiqlViewerSrc()}
        sandbox="allow-scripts"
        referrerPolicy="no-referrer"
        className="xstd-testdrive__frame xstd-testdrive__frame--themed"
        data-testid="graphql-test-drive-frame"
      />
    </div>
  );
}
