'use client';

/**
 * The `apiome login` approve screen (#5501).
 *
 * States, in order:
 *
 * - **enter** — opened without a code (or with a bad one): a field for the code in the terminal.
 * - **loading** — reading the login.
 * - **review** — the code (to compare with the terminal), what asked (`client_name`), a workspace
 *   picker limited to workspaces where the person may create API keys, **Approve** and **Deny**.
 *   With no such workspace, the screen says so and only **Deny** is offered.
 * - **approved** / **denied** — tells the person to return to the terminal.
 * - **missing** — the code is not waiting (expired, used or mistyped).
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { CircleAlert, CircleCheck, KeyRound, Terminal } from 'lucide-react';

import {
  approveCliLogin,
  denyCliLogin,
  getCliLoginRequest,
  type CliLoginActionResult,
} from '@lib/auth/cli-login-actions';
import {
  CLI_LOGIN_KEY_DAYS,
  defaultCliLoginWorkspace,
  normalizeCliUserCode,
  type CliLoginRequest,
} from '@lib/auth/cli-login';
import { AuthShell } from '@/app/components/auth/AuthShell';
import { AuthField } from '@/app/components/auth/AuthField';
import { BetaBadge } from '@/app/components/auth/BetaBadge';
import { BrandMark } from '@/app/components/brand';
import { Alert } from '@/app/components/ui/Alert';
import { Button } from '@/app/components/ui/Button';
import { Card } from '@/app/components/ui/Card';
import { Label } from '@/app/components/ui/Label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/app/components/ui/Select';
import { Spinner } from '@/app/components/ui/Spinner';
import { ICON_SIZE } from '@/app/components/ui/iconSizes';

/** Props for {@link CliLoginClient}. */
export interface CliLoginClientProps {
  /** The canonical code from the URL, or `null`. */
  initialCode: string | null;
  /** The workspace the person last worked in, to preselect when allowed. */
  currentWorkspaceSlug: string | null;
  /**
   * Skip the read and show this login (docs fixtures and tests only). Never set by the page.
   * @internal
   */
  initialRequest?: CliLoginRequest;
}

type View =
  | { kind: 'enter'; error?: string }
  | { kind: 'loading' }
  | { kind: 'review'; request: CliLoginRequest }
  | { kind: 'approved'; workspace: string }
  | { kind: 'denied' }
  | { kind: 'missing'; message: string };

/**
 * Read a login and say which view shows it.
 *
 * @param code The canonical code.
 * @returns The review or missing view; `null` when the session ended (the page reloads, which
 *   sends the person to sign in and back).
 */
async function readLogin(code: string): Promise<View | null> {
  const result = await getCliLoginRequest(code).catch(
    (): CliLoginActionResult<CliLoginRequest> => ({ ok: false, reason: 'failed', message: 'Try again.' })
  );
  if (result.ok) return { kind: 'review', request: result.data };
  if (result.reason === 'signed-out') {
    window.location.reload();
    return null;
  }
  return { kind: 'missing', message: result.message };
}

/**
 * The approve screen.
 *
 * @param props See {@link CliLoginClientProps}.
 * @returns The page body inside the auth shell.
 */
export default function CliLoginClient({ initialCode, currentWorkspaceSlug, initialRequest }: CliLoginClientProps) {
  const [view, setView] = useState<View>(
    initialRequest ? { kind: 'review', request: initialRequest } : initialCode ? { kind: 'loading' } : { kind: 'enter' }
  );
  const started = useRef(Boolean(initialRequest));

  const load = useCallback(async (code: string) => {
    setView({ kind: 'loading' });
    const next = await readLogin(code);
    if (next) setView(next);
  }, []);

  // The initial state is already `loading` when the URL carries a code; read it once.
  useEffect(() => {
    if (started.current || !initialCode) return;
    started.current = true;
    void (async () => {
      const next = await readLogin(initialCode);
      if (next) setView(next);
    })();
  }, [initialCode]);

  return (
    <AuthShell>
      <div className="auth-brandbar">
        <BrandMark variant="lockup" size={36} className="auth-brand__lockup" priority />
        <BetaBadge />
      </div>
      <Card className="auth-card" data-testid="cli-login-card">
        {view.kind === 'enter' && <EnterCode error={view.error} onSubmit={load} />}
        {view.kind === 'loading' && (
          <div className="auth-wait" role="status" aria-live="polite" data-testid="cli-login-loading">
            <Spinner size="md" aria-hidden="true" />
            <div className="text-sm font-semibold text-fg">Looking up the login…</div>
          </div>
        )}
        {view.kind === 'review' && (
          <Review
            request={view.request}
            currentWorkspaceSlug={currentWorkspaceSlug}
            onApproved={(workspace) => setView({ kind: 'approved', workspace })}
            onDenied={() => setView({ kind: 'denied' })}
            onMissing={(message) => setView({ kind: 'missing', message })}
          />
        )}
        {view.kind === 'approved' && (
          <Outcome
            testId="cli-login-approved"
            icon={<CircleCheck />}
            title="CLI signed in"
            text={
              <>
                Return to your terminal — apiome is now signed in to {view.workspace}. The key lasts{' '}
                {CLI_LOGIN_KEY_DAYS} days; run <code className="mono">apiome logout</code> to end it sooner.
              </>
            }
          />
        )}
        {view.kind === 'denied' && (
          <Outcome
            testId="cli-login-denied"
            icon={<CircleAlert />}
            title="Login denied"
            text="Nothing was signed in. The terminal reports that the login was denied."
          />
        )}
        {view.kind === 'missing' && (
          <div data-testid="cli-login-missing">
            <span className="auth-icon" aria-hidden="true">
              <CircleAlert />
            </span>
            <h1 className="auth-title mt-4">This code does not work</h1>
            <div className="auth-sub mt-1">{view.message}</div>
            <Button variant="secondary" size="lg" className="mt-5 w-full" onClick={() => setView({ kind: 'enter' })}>
              Enter another code
            </Button>
          </div>
        )}
      </Card>
    </AuthShell>
  );
}

/**
 * The code field, for a page opened without one.
 *
 * @param props.error A message for the last attempt.
 * @param props.onSubmit Called with the canonical code.
 * @returns The form.
 */
function EnterCode({ error, onSubmit }: { error?: string; onSubmit: (code: string) => void }) {
  const [value, setValue] = useState('');
  const [invalid, setInvalid] = useState<string | undefined>(error);

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    const code = normalizeCliUserCode(value);
    if (!code) {
      setInvalid('Enter the 8-character code shown in your terminal, for example KTXR-MWDB.');
      return;
    }
    onSubmit(code);
  };

  return (
    <div data-testid="cli-login-enter">
      <span className="auth-icon" aria-hidden="true">
        <Terminal />
      </span>
      <h1 className="auth-title mt-4">Sign in the Apiome CLI</h1>
      <div className="auth-sub mt-1">
        Enter the code that <code className="mono">apiome login</code> shows in your terminal.
      </div>
      <form className="mt-5 space-y-4" onSubmit={handleSubmit}>
        <AuthField
          className="auth-code"
          id="cli-login-code"
          label="Code"
          icon={<KeyRound size={ICON_SIZE.dense} aria-hidden="true" />}
          name="code"
          type="text"
          autoComplete="off"
          autoCapitalize="characters"
          spellCheck={false}
          placeholder="XXXX-XXXX"
          value={value}
          onChange={(event) => {
            setValue(event.target.value);
            setInvalid(undefined);
          }}
          error={invalid}
          invalid={Boolean(invalid)}
        />
        <Button type="submit" size="lg" className="w-full">
          Continue
        </Button>
      </form>
    </div>
  );
}

/**
 * The login to approve: code, requester, workspace and the two decisions.
 *
 * @param props.request The pending login.
 * @param props.currentWorkspaceSlug The workspace to preselect when allowed.
 * @param props.onApproved Called with the workspace name once approved.
 * @param props.onDenied Called once denied.
 * @param props.onMissing Called when the login stopped waiting meanwhile.
 * @returns The review panel.
 */
function Review({
  request,
  currentWorkspaceSlug,
  onApproved,
  onDenied,
  onMissing,
}: {
  request: CliLoginRequest;
  currentWorkspaceSlug: string | null;
  onApproved: (workspace: string) => void;
  onDenied: () => void;
  onMissing: (message: string) => void;
}) {
  const approvable = request.workspaces.filter((workspace) => workspace.can_approve);
  const [workspace, setWorkspace] = useState<string | null>(
    defaultCliLoginWorkspace(request.workspaces, currentWorkspaceSlug)
  );
  const [busy, setBusy] = useState<'approve' | 'deny' | null>(null);
  const [error, setError] = useState<string | null>(null);

  const decide = async (decision: 'approve' | 'deny') => {
    setBusy(decision);
    setError(null);
    const result =
      decision === 'approve'
        ? await approveCliLogin(request.user_code, workspace)
        : await denyCliLogin(request.user_code);
    setBusy(null);
    if (result.ok) {
      if (decision === 'deny') onDenied();
      else onApproved(approvable.find((entry) => entry.slug === workspace)?.name ?? workspace ?? '');
      return;
    }
    if (result.reason === 'not-found') onMissing(result.message);
    else if (result.reason === 'signed-out') window.location.reload();
    else setError(result.message);
  };

  return (
    <div data-testid="cli-login-review">
      <span className="auth-icon" aria-hidden="true">
        <Terminal />
      </span>
      <h1 className="auth-title mt-4">Sign in the Apiome CLI?</h1>
      <div className="auth-sub mt-1">
        {request.client_name ? `${request.client_name} is` : 'The Apiome CLI is'} asking to act as you. Approve only
        if you just ran <code className="mono">apiome login</code> and this code matches your terminal.
      </div>

      <div className="cli-login-code mt-5" data-testid="cli-login-code" aria-label="Code from the terminal">
        {request.user_code}
      </div>

      {approvable.length > 0 ? (
        <div className="mt-5 space-y-2">
          <Label htmlFor="cli-login-workspace">Workspace</Label>
          <Select value={workspace ?? undefined} onValueChange={setWorkspace} disabled={busy !== null}>
            <SelectTrigger id="cli-login-workspace" data-testid="cli-login-workspace">
              <SelectValue placeholder="Choose a workspace" />
            </SelectTrigger>
            <SelectContent>
              {approvable.map((entry) => (
                <SelectItem key={entry.slug} value={entry.slug}>
                  {entry.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <p className="auth-sub">
            The CLI gets an API key for this workspace that lasts {CLI_LOGIN_KEY_DAYS} days. It appears on the
            workspace&apos;s API Keys page, where you can revoke it.
          </p>
        </div>
      ) : (
        <Alert variant="info" role="status" className="mt-5" data-testid="cli-login-no-workspace">
          {request.workspaces.length === 0
            ? 'You are not a member of any workspace yet, so there is nothing to sign the CLI in to.'
            : 'You cannot create API keys in any of your workspaces, so you cannot approve a CLI login. Ask a workspace administrator.'}
        </Alert>
      )}

      {error && (
        <Alert variant="danger" role="alert" className="mt-4" data-testid="cli-login-error">
          {error}
        </Alert>
      )}

      <div className="mt-5 flex flex-col gap-3">
        {approvable.length > 0 && (
          <Button
            size="lg"
            className="w-full"
            disabled={!workspace || busy !== null}
            onClick={() => void decide('approve')}
            data-testid="cli-login-approve"
          >
            {busy === 'approve' ? 'Approving…' : 'Approve'}
          </Button>
        )}
        <Button
          variant="secondary"
          size="lg"
          className="w-full"
          disabled={busy !== null}
          onClick={() => void decide('deny')}
          data-testid="cli-login-deny"
        >
          {busy === 'deny' ? 'Denying…' : 'Deny'}
        </Button>
      </div>
    </div>
  );
}

/**
 * A final state.
 *
 * @param props.testId The panel's test id.
 * @param props.icon The status icon.
 * @param props.title The heading.
 * @param props.text What happens next.
 * @returns The panel.
 */
function Outcome({
  testId,
  icon,
  title,
  text,
}: {
  testId: string;
  icon: React.ReactNode;
  title: string;
  text: React.ReactNode;
}) {
  return (
    <div data-testid={testId} role="status">
      <span className="auth-icon" aria-hidden="true">
        {icon}
      </span>
      <h1 className="auth-title mt-4">{title}</h1>
      <div className="auth-sub mt-1">{text}</div>
    </div>
  );
}
