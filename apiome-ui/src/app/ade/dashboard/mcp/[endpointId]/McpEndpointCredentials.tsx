'use client';

/**
 * Endpoint-detail "Credentials" tab (V2-MCP-24.6 / MCAT-10.6, #3702).
 *
 * Configures the outbound credential apiome-rest sends to one MCP server, in three sections drawn
 * on the Settings tab's `.mcp-settings-grid`:
 *
 *  1. **Stored credential** — the redacted status: which scheme is stored, a **mask** in place of
 *     the secret (`••••••••`), the sealing key version and when it was written, and
 *     **Clear credential** behind a confirm. Reads `GET /api/mcp/endpoints/{id}/credentials`
 *     (MCAT-6.5), whose response has no field a secret could arrive in.
 *  2. **Set credential** — a form for a **Bearer token**, a **Custom header** or a pasted
 *     **OAuth 2.1 access token**; the secret field is a password input with a show/hide toggle,
 *     validated by {@link validateMcpCredentialForm} and sent with `PUT …/credentials`. The
 *     response is the redacted status, the field is emptied, and the secret is not kept anywhere.
 *     An encryption-at-rest note sits under the form.
 *  3. **OAuth connection** — {@link McpOAuthConnection} (MCAT-6.4), drawn only for a server whose
 *     authorization server a discovery run found; **Connect with OAuth** runs the browser
 *     handshake and comes back to this tab.
 *
 * The component owns its form state and network calls and tells the parent through `onChanged`
 * when the stored credential changed, so the header's auth badge can follow.
 */

import * as React from 'react';
import { Eye, EyeOff, KeyRound, Loader2, Lock, Save, Trash2, TriangleAlert } from 'lucide-react';

import { toast } from '@/app/components/ui/toast';
import { useDialog } from '@/app/components/providers/DialogProvider';
import { Alert, AlertDescription } from '@/app/components/ui/Alert';
import { Button } from '@/app/components/ui/Button';
import { Card, CardBody } from '@/app/components/ui/Card';
import { FormField } from '@/app/components/ui/FormField';
import { Input } from '@/app/components/ui/Input';
import { LiveRegion } from '@/app/components/ui/LiveRegion';
import { McpBadge } from '@/app/components/ui/mcp/McpBadge';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/app/components/ui/Select';
import { saveStateAnnouncement } from '@lib/a11y/announcements';
import { mcpAuthBadge } from '@/app/components/ade/dashboard/mcp/mcpUiPrimitives';
import {
  MCP_CREDENTIAL_AUTH_OPTIONS,
  MCP_CREDENTIAL_CLEAR_CONFIRM,
  MCP_CREDENTIAL_ENCRYPTION_NOTE,
  MCP_CREDENTIAL_MASK,
  MCP_CREDENTIAL_NONE,
  buildMcpCredentialBody,
  emptyMcpCredentialForm,
  mcpCredentialMetaLine,
  mcpCredentialSecretLabel,
  mcpCredentialStatusFromPayload,
  mcpCredentialSummary,
  validateMcpCredentialForm,
  type McpCredentialAuthType,
  type McpCredentialForm,
  type McpCredentialStatus,
} from '@/app/components/ade/dashboard/mcp/mcpCredentialsForm';
import McpOAuthConnection from './McpOAuthConnection';

export interface McpEndpointCredentialsProps {
  /** The endpoint whose credential is managed. */
  endpointId: string;
  /** Called after a credential is stored or cleared, with the new redacted status. */
  onChanged?: (status: McpCredentialStatus) => void;
}

/** Read an error message out of a `{ error }` JSON body, falling back to a status line. */
function errorFromResponse(data: unknown, statusText: string): string {
  if (data && typeof data === 'object' && 'error' in data) {
    const err = (data as { error: unknown }).error;
    if (typeof err === 'string' && err.trim()) return err;
  }
  return statusText || 'Request failed.';
}

/** Format an ISO timestamp in the reader's locale. */
function formatWhen(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString();
}

/**
 * The Credentials tab.
 *
 * @param props.endpointId The endpoint whose credential is managed.
 * @param props.onChanged  Told the new status after a store or a clear.
 * @returns The three sections.
 */
export default function McpEndpointCredentials({ endpointId, onChanged }: McpEndpointCredentialsProps) {
  const { confirm: confirmDialog } = useDialog();
  /** The redacted status; `null` until the first read answers. */
  const [status, setStatus] = React.useState<McpCredentialStatus | null>(null);
  /** Why the status could not be read, shown in place of the card. */
  const [loadError, setLoadError] = React.useState<string | null>(null);
  const [form, setForm] = React.useState<McpCredentialForm>(() => emptyMcpCredentialForm());
  /** Whether the secret field shows what was typed. Off again after every save. */
  const [revealed, setRevealed] = React.useState(false);
  /** Which mutation is in flight ("save" | "clear"), or null when idle. */
  const [busy, setBusy] = React.useState<string | null>(null);
  /** Inline validation or request error for the form. */
  const [formError, setFormError] = React.useState<string | null>(null);
  /**
   * Bumped after every store or clear so the OAuth section re-reads the status — clearing removes
   * the OAuth metadata with the credential, and a connect replaces a pasted token.
   */
  const [oauthEpoch, setOauthEpoch] = React.useState(0);
  const mountedRef = React.useRef(true);

  React.useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  /** Read the redacted status. */
  const load = React.useCallback(async () => {
    setLoadError(null);
    try {
      const res = await fetch(`/api/mcp/endpoints/${endpointId}/credentials`, {
        credentials: 'include',
        cache: 'no-store',
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(errorFromResponse(data, res.statusText));
      if (!mountedRef.current) return;
      setStatus(mcpCredentialStatusFromPayload(data) ?? MCP_CREDENTIAL_NONE);
    } catch (e) {
      if (!mountedRef.current) return;
      setStatus(null);
      setLoadError(e instanceof Error ? e.message : 'Could not load the credential status.');
    }
  }, [endpointId]);

  React.useEffect(() => {
    void load();
  }, [load]);

  const set = <K extends keyof McpCredentialForm>(key: K, value: McpCredentialForm[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }));
    setFormError(null);
  };

  /** Apply a new status everywhere it shows and tell the parent. */
  const applyStatus = (next: McpCredentialStatus) => {
    setStatus(next);
    setOauthEpoch((n) => n + 1);
    onChanged?.(next);
  };

  /** Validate and `PUT` the form; the secret leaves the component with the request. */
  async function handleSave() {
    const validation = validateMcpCredentialForm(form);
    if (validation) {
      setFormError(validation);
      return;
    }
    setFormError(null);
    setBusy('save');
    try {
      const res = await fetch(`/api/mcp/endpoints/${endpointId}/credentials`, {
        method: 'PUT',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(buildMcpCredentialBody(form)),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(errorFromResponse(data, res.statusText));
      if (!mountedRef.current) return;
      applyStatus(mcpCredentialStatusFromPayload(data) ?? { ...MCP_CREDENTIAL_NONE, authType: form.authType, configured: true });
      setForm(emptyMcpCredentialForm(form.authType));
      setRevealed(false);
      toast.success('Credential saved. It is encrypted and will not be shown again.');
    } catch (e) {
      if (!mountedRef.current) return;
      setFormError(e instanceof Error ? e.message : 'Could not save the credential.');
    } finally {
      if (mountedRef.current) setBusy(null);
    }
  }

  /** Confirm, then `DELETE` the stored credential. */
  async function handleClear() {
    const confirmed = await confirmDialog({
      title: MCP_CREDENTIAL_CLEAR_CONFIRM.title,
      message: MCP_CREDENTIAL_CLEAR_CONFIRM.message,
      variant: 'danger',
      confirmLabel: MCP_CREDENTIAL_CLEAR_CONFIRM.confirmLabel,
      cancelLabel: MCP_CREDENTIAL_CLEAR_CONFIRM.cancelLabel,
    });
    if (!confirmed) return;
    setBusy('clear');
    try {
      const res = await fetch(`/api/mcp/endpoints/${endpointId}/credentials`, {
        method: 'DELETE',
        credentials: 'include',
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(errorFromResponse(data, res.statusText));
      if (!mountedRef.current) return;
      applyStatus({ ...MCP_CREDENTIAL_NONE, endpointId });
      toast.success('Credential cleared. The server is reached anonymously.');
    } catch (e) {
      if (mountedRef.current) toast.error(e instanceof Error ? e.message : 'Could not clear the credential.');
    } finally {
      if (mountedRef.current) setBusy(null);
    }
  }

  const saving = busy === 'save';
  const clearing = busy === 'clear';
  const anyBusy = busy !== null;
  const dirty = form.secret.length > 0 || form.headerName.length > 0;
  const summary = status ? mcpCredentialSummary(status) : null;
  const badge = status ? mcpAuthBadge(status.configured ? status.authType : 'none') : null;
  const metaLine = status ? mcpCredentialMetaLine(status, formatWhen) : null;
  const secretLabel = mcpCredentialSecretLabel(form.authType);

  return (
    <div className="flex flex-col gap-6" data-testid="mcp-credentials">
      {/* Stored credential ------------------------------------------------------------------ */}
      <section className="mcp-settings-grid">
        <div>
          <h3 className="flex items-center gap-2 text-base font-semibold text-fg">
            <KeyRound aria-hidden className="size-[var(--fs-md)] shrink-0 text-fg-muted" />
            Stored credential
          </h3>
          <p className="mt-1 text-sm text-fg-muted">
            What Apiome sends to this server on discovery runs, the scheduled sweep and Test calls.
            The secret itself is never shown again once it is stored.
          </p>
        </div>
        <Card data-testid="mcp-credentials-status">
          <CardBody className="mcp-ep-row">
            {loadError ? (
              <p role="alert" className="flex items-center gap-1.5 text-sm text-fg" data-testid="mcp-credentials-load-error">
                <TriangleAlert aria-hidden className="size-4 shrink-0 text-danger" />
                {loadError}
              </p>
            ) : !status || !summary || !badge ? (
              <p role="status" className="text-sm text-fg-muted">
                Loading credential status…
              </p>
            ) : (
              <>
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2 text-sm font-medium text-fg">
                    <span data-testid="mcp-credentials-title">{summary.title}</span>
                    <McpBadge tone={badge.tone} data-testid="mcp-credentials-badge">
                      {badge.label}
                    </McpBadge>
                  </div>
                  <p className="text-xs text-fg-muted">{summary.detail}</p>
                  {status.configured ? (
                    <p className="mt-2 flex flex-wrap items-center gap-2 text-xs text-fg-muted">
                      <span
                        role="img"
                        className="mono text-sm tracking-widest text-fg"
                        aria-label="Stored secret, masked"
                        data-testid="mcp-credentials-mask"
                      >
                        {MCP_CREDENTIAL_MASK}
                      </span>
                      {metaLine ? <span data-testid="mcp-credentials-meta">{metaLine}</span> : null}
                    </p>
                  ) : null}
                </div>
                {status.configured ? (
                  <Button
                    type="button"
                    variant="danger-soft"
                    onClick={() => void handleClear()}
                    disabled={anyBusy}
                    data-testid="mcp-credentials-clear"
                  >
                    {clearing ? <Loader2 className="animate-spin" aria-hidden /> : <Trash2 aria-hidden />}
                    {clearing ? 'Clearing…' : 'Clear credential'}
                  </Button>
                ) : null}
              </>
            )}
          </CardBody>
        </Card>
      </section>

      {/* Set credential --------------------------------------------------------------------- */}
      <section className="mcp-settings-grid">
        <div>
          <h3 className="flex items-center gap-2 text-base font-semibold text-fg">
            <Lock aria-hidden className="size-[var(--fs-md)] shrink-0 text-fg-muted" />
            {status?.configured ? 'Replace credential' : 'Set credential'}
          </h3>
          <p className="mt-1 text-sm text-fg-muted">
            Paste a bearer token, name one custom header, or paste an OAuth 2.1 access token you
            already hold. Saving replaces whatever is stored and takes effect on the next request to
            the server.
          </p>
        </div>
        <Card>
          <CardBody>
            <form
              className="mcp-settings-fields"
              data-testid="mcp-credentials-form"
              onSubmit={(e) => {
                e.preventDefault();
                void handleSave();
              }}
            >
              <FormField label="Auth type" htmlFor="mcp-credentials-auth-type" className="mcp-settings-fields__wide">
                <Select
                  value={form.authType}
                  onValueChange={(v) => set('authType', v as McpCredentialAuthType)}
                  disabled={anyBusy}
                >
                  <SelectTrigger id="mcp-credentials-auth-type" data-testid="mcp-credentials-auth-type">
                    <SelectValue placeholder="Select auth type" />
                  </SelectTrigger>
                  <SelectContent>
                    {MCP_CREDENTIAL_AUTH_OPTIONS.map((opt) => (
                      <SelectItem key={opt.value} value={opt.value}>
                        {opt.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </FormField>

              {form.authType === 'header' ? (
                <FormField
                  label="Header name"
                  required
                  htmlFor="mcp-credentials-header-name"
                  helperText="The request header that carries the secret, such as X-Api-Key."
                  className="mcp-settings-fields__wide"
                >
                  <Input
                    id="mcp-credentials-header-name"
                    type="text"
                    autoComplete="off"
                    spellCheck={false}
                    placeholder="X-Api-Key"
                    value={form.headerName}
                    onChange={(e) => set('headerName', e.target.value)}
                    disabled={anyBusy}
                    data-testid="mcp-credentials-header-name"
                  />
                </FormField>
              ) : null}

              <FormField
                label={secretLabel}
                required
                htmlFor="mcp-credentials-secret"
                helperText={
                  form.authType === 'oauth2'
                    ? 'A token you obtained yourself. To let Apiome sign in and renew the token, use Connect with OAuth below instead.'
                    : 'Sent on every request Apiome makes to this server.'
                }
                className="mcp-settings-fields__wide"
              >
                <div className="flex items-center gap-2">
                  <Input
                    id="mcp-credentials-secret"
                    type={revealed ? 'text' : 'password'}
                    autoComplete="off"
                    spellCheck={false}
                    value={form.secret}
                    onChange={(e) => set('secret', e.target.value)}
                    disabled={anyBusy}
                    data-testid="mcp-credentials-secret"
                  />
                  <Button
                    type="button"
                    variant="outline"
                    size="icon"
                    onClick={() => setRevealed((v) => !v)}
                    aria-pressed={revealed}
                    aria-label={revealed ? `Hide ${secretLabel.toLowerCase()}` : `Show ${secretLabel.toLowerCase()}`}
                    title={revealed ? 'Hide' : 'Show'}
                    disabled={anyBusy}
                    data-testid="mcp-credentials-reveal"
                  >
                    {revealed ? <EyeOff aria-hidden /> : <Eye aria-hidden />}
                  </Button>
                </div>
              </FormField>

              {formError ? (
                // The words are the message and the glyph is emphasis, as the Settings tab does.
                <p
                  role="alert"
                  className="mcp-settings-fields__wide flex items-center gap-1.5 text-sm text-fg"
                  data-testid="mcp-credentials-error"
                >
                  <TriangleAlert aria-hidden className="size-4 shrink-0 text-danger" />
                  {formError}
                </p>
              ) : null}

              <Alert
                variant="info"
                icon={<Lock aria-hidden />}
                className="mcp-settings-fields__wide"
                data-testid="mcp-credentials-encryption-note"
              >
                <AlertDescription>{MCP_CREDENTIAL_ENCRYPTION_NOTE}</AlertDescription>
              </Alert>

              <LiveRegion
                message={saveStateAnnouncement({ saving, dirty, failed: Boolean(formError) })}
                data-testid="mcp-credentials-live"
              />
              <div className="mcp-settings-actions mcp-settings-fields__wide">
                <Button type="submit" disabled={anyBusy || !dirty} data-testid="mcp-credentials-save">
                  {saving ? <Loader2 className="animate-spin" aria-hidden /> : <Save aria-hidden />}
                  {saving ? 'Saving…' : status?.configured ? 'Replace credential' : 'Save credential'}
                </Button>
              </div>
            </form>
          </CardBody>
        </Card>
      </section>

      {/* OAuth connection — rendered only for an OAuth-protected server (MCAT-6.4). ---------- */}
      <McpOAuthConnection key={oauthEpoch} endpointId={endpointId} />
    </div>
  );
}
