'use client';

/**
 * Finishes an MCP OAuth connection (V2-MCP-20.4 / MCAT-6.4, #3680).
 *
 * The authorization server redirects here with `state` and `code` (or `error`). The page posts
 * them once to `/api/mcp/oauth/callback`; apiome-rest checks the sealed state, exchanges the code
 * with the PKCE verifier and stores the tokens sealed. On success the user is sent to the
 * endpoint's Settings tab; on failure the reason is shown with a way back to the catalog.
 */

import * as React from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { KeyRound, Loader2, TriangleAlert } from 'lucide-react';

import { Alert, AlertDescription, AlertTitle } from '@/app/components/ui/Alert';
import { Button } from '@/app/components/ui/Button';
import {
  mcpOAuthCallbackParams,
  mcpOAuthReturnPath,
} from '@/app/components/ade/dashboard/mcp/mcpOAuthConnect';

/**
 * The callback screen: a progress line, then a redirect or the failure.
 *
 * @returns The callback screen.
 */
export default function McpOAuthCallbackClient() {
  const router = useRouter();
  const [error, setError] = React.useState<string | null>(null);
  const sent = React.useRef(false);

  React.useEffect(() => {
    if (sent.current) return;
    sent.current = true;
    const params = mcpOAuthCallbackParams(window.location.search);
    if (!params) {
      setError('This page is opened by the authorization server after you connect an MCP server.');
      return;
    }
    (async () => {
      try {
        const res = await fetch('/api/mcp/oauth/callback', {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(params),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || typeof data?.endpoint_id !== 'string') {
          throw new Error(typeof data?.error === 'string' ? data.error : res.statusText || 'The connection failed.');
        }
        router.replace(mcpOAuthReturnPath(data.endpoint_id));
      } catch (e) {
        setError(e instanceof Error ? e.message : 'The connection failed.');
      }
    })();
  }, [router]);

  return (
    <div className="mx-auto flex max-w-xl flex-col gap-4 p-6" data-testid="mcp-oauth-callback">
      <h1 className="flex items-center gap-2 text-lg font-semibold text-fg">
        <KeyRound aria-hidden className="size-[var(--fs-md)] shrink-0 text-fg-muted" />
        Connecting MCP server
      </h1>
      {error ? (
        <>
          <Alert variant="danger" icon={<TriangleAlert aria-hidden />} data-testid="mcp-oauth-callback-error">
            <AlertTitle>The connection was not completed</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
          <div>
            <Button asChild variant="outline">
              <Link href="/ade/dashboard/mcp">Back to MCP servers</Link>
            </Button>
          </div>
        </>
      ) : (
        <p role="status" className="flex items-center gap-2 text-sm text-fg-muted" data-testid="mcp-oauth-callback-busy">
          <Loader2 aria-hidden className="size-4 animate-spin" />
          Storing the token…
        </p>
      )}
    </div>
  );
}
