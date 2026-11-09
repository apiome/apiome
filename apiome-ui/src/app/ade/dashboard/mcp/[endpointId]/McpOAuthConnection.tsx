'use client';

/**
 * The **OAuth connection** section of an MCP endpoint's Settings tab (V2-MCP-20.4 / MCAT-6.4, #3680).
 *
 * Shown only once a discovery run has found the server's authorization server (MCAT-6.3); for
 * every other endpoint it renders nothing. It says whether a token is stored, when it expires and
 * whether Apiome renews it by itself, and offers **Connect with OAuth** (or **Reconnect**).
 *
 * Connecting asks apiome-rest for an authorization URL and sends the browser there; the
 * authorization server returns the user to the callback page
 * (`/ade/dashboard/mcp/oauth/callback`), which finishes the connection and comes back here. When
 * the server has no registration endpoint, a **Client ID** registered with it out of band is
 * needed first. No token is ever shown: the status is the redacted credential status.
 *
 * The model lives in {@link ../../../../components/ade/dashboard/mcp/mcpOAuthConnect}.
 */

import * as React from 'react';
import { KeyRound, Link2, Loader2, TriangleAlert } from 'lucide-react';

import { Alert, AlertDescription, AlertTitle } from '@/app/components/ui/Alert';
import { Badge } from '@/app/components/ui/Badge';
import { Button } from '@/app/components/ui/Button';
import { Card, CardBody } from '@/app/components/ui/Card';
import { FormField } from '@/app/components/ui/FormField';
import { Input } from '@/app/components/ui/Input';
import {
  mcpOAuthAuthorizeBody,
  mcpOAuthExpiryLine,
  mcpOAuthRedirectUri,
  mcpOAuthStatusFromCredential,
  type McpOAuthStatus,
} from '@/app/components/ade/dashboard/mcp/mcpOAuthConnect';

export interface McpOAuthConnectionProps {
  /** The endpoint to connect. */
  endpointId: string;
  /**
   * Sends the browser to the authorization URL. Defaults to `window.location.assign`; tests pass
   * a spy.
   */
  navigate?: (url: string) => void;
}

/** Format an ISO timestamp in the reader's locale. */
function formatWhen(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString();
}

/**
 * The OAuth connection section.
 *
 * @param props.endpointId The endpoint whose connection is shown.
 * @param props.navigate   Where the browser is sent (tests).
 * @returns The section, or `null` when the server is not OAuth-protected.
 */
export default function McpOAuthConnection({ endpointId, navigate }: McpOAuthConnectionProps) {
  const [status, setStatus] = React.useState<McpOAuthStatus | null>(null);
  const [clientId, setClientId] = React.useState('');
  const [connecting, setConnecting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    let active = true;
    (async () => {
      try {
        const res = await fetch(`/api/mcp/endpoints/${endpointId}/credentials`, {
          credentials: 'include',
          cache: 'no-store',
        });
        const data = await res.json().catch(() => ({}));
        if (active && res.ok) setStatus(mcpOAuthStatusFromCredential(data?.credential));
      } catch {
        if (active) setStatus(null);
      }
    })();
    return () => {
      active = false;
    };
  }, [endpointId]);

  const needsClientId = Boolean(status && !status.dynamicRegistration);

  const connect = React.useCallback(async () => {
    if (needsClientId && !clientId.trim()) {
      setError('Enter the client ID registered with this authorization server.');
      return;
    }
    setConnecting(true);
    setError(null);
    try {
      const res = await fetch(`/api/mcp/endpoints/${endpointId}/oauth/authorize`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(mcpOAuthAuthorizeBody(mcpOAuthRedirectUri(window.location.origin), clientId)),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || typeof data?.authorization_url !== 'string') {
        throw new Error(typeof data?.error === 'string' ? data.error : res.statusText || 'Could not start the connection.');
      }
      (navigate ?? ((url: string) => window.location.assign(url)))(data.authorization_url);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not start the connection.');
      setConnecting(false);
    }
  }, [clientId, endpointId, navigate, needsClientId]);

  if (!status || !status.discovered) return null;

  const expiry = mcpOAuthExpiryLine(status, formatWhen);

  return (
    <section className="mcp-settings-grid" data-testid="mcp-oauth-connection">
      <div>
        <h3 className="flex items-center gap-2 text-base font-semibold text-fg">
          <KeyRound aria-hidden className="size-[var(--fs-md)] shrink-0 text-fg-muted" />
          OAuth connection
        </h3>
        <p className="mt-1 text-sm text-fg-muted">
          This server signs requests in with OAuth. Connect once and Apiome stores the token
          encrypted, sends it on discovery runs and test calls, and renews it before it expires.
        </p>
      </div>
      <Card>
        <CardBody className="flex flex-col gap-4">
          <div className="mcp-ep-row">
            <div>
              <div className="flex items-center gap-2 text-sm font-medium text-fg">
                {status.connected ? 'Connected' : 'Not connected'}
                <Badge variant={status.connected ? 'ok' : 'neutral'} data-testid="mcp-oauth-state">
                  {status.connected ? 'OAuth 2.1' : 'No token'}
                </Badge>
              </div>
              <p className="text-xs text-fg-muted" data-testid="mcp-oauth-detail">
                {expiry ?? `Authorization server: ${status.issuer ?? 'unknown'}`}
              </p>
              {status.connected && status.scope ? (
                <p className="text-xs text-fg-muted">Scope: {status.scope}</p>
              ) : null}
            </div>
            <Button
              type="button"
              variant={status.connected ? 'outline' : 'primary'}
              onClick={() => void connect()}
              disabled={connecting || !status.pkceSupported}
              data-testid="mcp-oauth-connect"
            >
              {connecting ? <Loader2 className="animate-spin" aria-hidden /> : <Link2 aria-hidden />}
              {status.connected ? 'Reconnect' : 'Connect with OAuth'}
            </Button>
          </div>

          {needsClientId ? (
            <FormField
              label="Client ID"
              htmlFor="mcp-oauth-client-id"
              helperText="This authorization server does not register clients automatically. Register Apiome with it and paste the client ID."
            >
              <Input
                id="mcp-oauth-client-id"
                value={clientId}
                onChange={(e) => setClientId(e.target.value)}
                autoComplete="off"
              />
            </FormField>
          ) : null}

          {!status.pkceSupported ? (
            <Alert variant="warn" icon={<TriangleAlert aria-hidden />} data-testid="mcp-oauth-no-pkce">
              <AlertTitle>PKCE not supported</AlertTitle>
              <AlertDescription>
                The authorization server does not advertise PKCE (S256), which the MCP specification
                requires, so Apiome will not connect to it.
              </AlertDescription>
            </Alert>
          ) : null}

          {status.lastRefreshError ? (
            <Alert variant="warn" icon={<TriangleAlert aria-hidden />} data-testid="mcp-oauth-refresh-error">
              <AlertTitle>Automatic renewal failed</AlertTitle>
              <AlertDescription>{status.lastRefreshError}. Reconnect to get a new token.</AlertDescription>
            </Alert>
          ) : null}

          {error ? (
            <p role="alert" className="flex items-center gap-1.5 text-sm text-fg" data-testid="mcp-oauth-error">
              <TriangleAlert aria-hidden className="size-4 shrink-0 text-danger" />
              {error}
            </p>
          ) : null}
        </CardBody>
      </Card>
    </section>
  );
}
