'use client';

/**
 * Sign-up policy card on System settings (SGN-1.4, #5653).
 *
 * Lets a super-admin choose who may create an account on this installation:
 *
 *   - **Open** — anyone, optionally limited to a list of allowed email domains;
 *   - **Invite only** — no self-service accounts; people who already have an account (including
 *     invited members) still sign in;
 *   - **Closed** — no new accounts.
 *
 * The policy is stored in the database and wins over the `AUTH_SIGNUP_DISABLED` env flag; until
 * one is saved the card shows the env-derived mode, and **Use .env** removes the stored policy
 * again. The same policy is enforced for the email form and every OAuth provider, and a save
 * applies to the next sign-up without a restart.
 *
 * Abuse protection (SGN-1.5, #5654): **Blocked email domains** extends the disposable-email list
 * Apiome bundles (email sign-up only; a listed domain also blocks its subdomains), and
 * **Recent blocked sign-ups** lists what the guards refused. The extra domains are stored with the
 * policy, so **Use .env** removes them as well; the bundled list always applies.
 *
 * Reads and writes go through the super-admin proxy (`/api/admin/signup-policy`), gated by the
 * hardened admin session (OLO-8.1).
 */
import { useCallback, useEffect, useId, useState } from 'react';
import { AlertTriangle, CheckCircle2, Loader2, RefreshCw, UserPlus } from 'lucide-react';
import { extractRestErrorMessage } from '@lib/auth/admin-provider-config';
import {
  SIGNUP_MODE_OPTIONS,
  signupModeLabel,
  type AdminSignupPolicyUpdatePayload,
  type AdminSignupPolicyView,
} from '@lib/auth/admin-signup-policy';
import { BUNDLED_DISPOSABLE_EMAIL_DOMAINS } from '@lib/auth/disposable-email-domains';
import {
  MAX_ALLOWED_EMAIL_DOMAINS,
  MAX_BLOCKED_EMAIL_DOMAINS,
  parseAllowedEmailDomains,
  type SignupMode,
} from '@lib/auth/signup-policy';
import { ICON_SIZE } from '@/app/components/ui/iconSizes';
import BlockedSignupAttempts from './BlockedSignupAttempts';
import {
  INPUT_CLASSES,
  NEUTRAL_CHIP_CLASSES,
  PRIMARY_BUTTON_CLASSES,
  SECONDARY_BUTTON_CLASSES,
} from './settingsStyles';

/** Proxy route the card reads from and saves to. */
const SIGNUP_POLICY_URL = '/api/admin/signup-policy';

/** Colour classes of the header chip, per effective mode. */
const MODE_CHIP_CLASSES: Record<SignupMode, string> = {
  open: 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900/60 dark:bg-emerald-950/40 dark:text-emerald-400',
  invite_only:
    'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900/60 dark:bg-amber-950/40 dark:text-amber-400',
  closed:
    'border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-900/60 dark:bg-rose-950/40 dark:text-rose-400',
};

/**
 * Turn a failed proxy response into the message shown on the card.
 *
 * @param status The HTTP status of the response.
 * @param body The parsed response body.
 * @param fallback Message to use when the body carries none.
 * @returns The message to show.
 */
function failureMessage(status: number, body: unknown, fallback: string): string {
  if (status === 401 || status === 403) {
    return 'Your admin session has expired. Sign out and back in.';
  }
  return extractRestErrorMessage(body, fallback);
}

/**
 * Validate a typed domain list.
 *
 * @param invalid Entries that are not domains.
 * @param count How many valid domains were typed.
 * @param max The most the list may hold.
 * @returns The message to show, or null when the list is fine.
 */
function domainListError(invalid: string[], count: number, max: number): string | null {
  if (invalid.length > 0) {
    return `Not a valid email domain: ${invalid.join(', ')}. Enter domains such as example.com.`;
  }
  return count > max ? `Enter at most ${max} domains.` : null;
}

/** The Sign-up card: mode, allowed and blocked email domains, save, revert to .env, blocked sign-ups. */
export default function SignupPolicyCard() {
  const [view, setView] = useState<AdminSignupPolicyView | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  // Draft state — what the form shows, separate from what is stored.
  const [mode, setMode] = useState<SignupMode>('open');
  const [domainsText, setDomainsText] = useState('');
  const [blockedText, setBlockedText] = useState('');

  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [justSaved, setJustSaved] = useState(false);

  const groupName = useId();
  const domainsId = useId();
  const domainsHelpId = useId();
  const blockedId = useId();
  const blockedHelpId = useId();

  /** Adopt a view from the server as both the stored state and the draft. */
  const adopt = useCallback((next: AdminSignupPolicyView) => {
    setView(next);
    setMode(next.mode);
    setDomainsText(next.allowed_email_domains.join('\n'));
    setBlockedText((next.blocked_email_domains ?? []).join('\n'));
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const response = await fetch(SIGNUP_POLICY_URL, { cache: 'no-store' });
      const body: unknown = await response.json().catch(() => null);
      if (!response.ok) {
        setLoadError(
          failureMessage(
            response.status,
            body,
            'Could not load the sign-up policy. Check the configuration service and retry.',
          ),
        );
        return;
      }
      adopt(body as AdminSignupPolicyView);
    } catch {
      setLoadError('Could not load the sign-up policy: the server could not be reached.');
    } finally {
      setLoading(false);
    }
  }, [adopt]);

  useEffect(() => {
    void load();
  }, [load]);

  const parsed = parseAllowedEmailDomains(domainsText);
  // The domain list narrows Open only, so nothing typed there is sent for the other modes.
  const draftDomains = mode === 'open' ? parsed.domains : [];
  const domainsError =
    mode !== 'open'
      ? null
      : domainListError(parsed.invalid, parsed.domains.length, MAX_ALLOWED_EMAIL_DOMAINS);
  // The blocklist has the same shape as the allowed list, so it shares the parser.
  const blocked = parseAllowedEmailDomains(blockedText);
  const blockedError = domainListError(
    blocked.invalid,
    blocked.domains.length,
    MAX_BLOCKED_EMAIL_DOMAINS,
  );

  const stored = view?.source === 'db';
  const dirty =
    view !== null &&
    (!stored ||
      mode !== view.mode ||
      draftDomains.join('\n') !== view.allowed_email_domains.join('\n') ||
      blocked.domains.join('\n') !== (view.blocked_email_domains ?? []).join('\n'));

  /** Send a policy to the proxy and adopt the result. */
  const submit = async (payload: AdminSignupPolicyUpdatePayload, fallback: string) => {
    setSaving(true);
    setSaveError(null);
    setJustSaved(false);
    try {
      const response = await fetch(SIGNUP_POLICY_URL, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const body: unknown = await response.json().catch(() => null);
      if (!response.ok) {
        setSaveError(failureMessage(response.status, body, fallback));
        return;
      }
      adopt(body as AdminSignupPolicyView);
      setJustSaved(true);
    } catch {
      setSaveError(`${fallback} The server could not be reached.`);
    } finally {
      setSaving(false);
    }
  };

  const handleSave = () =>
    submit(
      { mode, allowed_email_domains: draftDomains, blocked_email_domains: blocked.domains },
      'Could not save the sign-up policy.',
    );

  const handleUseEnv = () =>
    submit(
      { mode: null, allowed_email_domains: [], blocked_email_domains: [] },
      'Could not remove the stored sign-up policy.',
    );

  /** Any edit clears the stale "Saved" / error notices. */
  const touch = () => {
    setJustSaved(false);
    setSaveError(null);
  };

  return (
    <section
      aria-label="Sign-up policy"
      className="rounded-lg border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900"
    >
      <div className="flex items-center gap-3 border-b border-slate-100 px-5 py-4 dark:border-slate-800">
        <span className="flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 bg-slate-50 dark:border-slate-700 dark:bg-slate-800">
          <UserPlus size={ICON_SIZE.dense} className="text-slate-600 dark:text-slate-300" />
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">Sign-up</h3>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            Who can create an account, by email or any sign-in provider.
          </p>
        </div>
        {view && (
          <>
            <span
              className={`inline-flex items-center rounded-full border px-2 py-0.5 text-2xs font-medium ${MODE_CHIP_CLASSES[view.mode]}`}
            >
              {signupModeLabel(view.mode)}
            </span>
            {!stored && <span className={NEUTRAL_CHIP_CLASSES}>Env-derived</span>}
          </>
        )}
      </div>

      <div className="flex flex-col gap-4 px-5 py-4">
        {loading && (
          <div className="flex items-center gap-2 text-sm text-slate-500 dark:text-slate-400">
            <Loader2 className="h-4 w-4 animate-spin" /> Loading the sign-up policy…
          </div>
        )}

        {!loading && loadError && (
          <div
            role="alert"
            className="flex items-start gap-3 rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800 dark:border-rose-900/60 dark:bg-rose-950/40 dark:text-rose-300"
          >
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <div className="flex-1">
              <p>{loadError}</p>
              <button
                type="button"
                onClick={() => void load()}
                className={`${SECONDARY_BUTTON_CLASSES} mt-3`}
              >
                <RefreshCw className="h-3.5 w-3.5" /> Retry
              </button>
            </div>
          </div>
        )}

        {!loading && !loadError && view && (
          <>
            <fieldset disabled={saving}>
              <legend className="mb-2 text-sm font-medium text-slate-700 dark:text-slate-200">
                Who can create an account
              </legend>
              <div className="grid gap-2 sm:grid-cols-3">
                {SIGNUP_MODE_OPTIONS.map((option) => (
                  <label
                    key={option.mode}
                    className="flex cursor-pointer items-start gap-3 rounded-md border border-slate-200 px-3 py-2 has-[:checked]:border-indigo-500 has-[:checked]:bg-indigo-50 dark:border-slate-700 dark:has-[:checked]:bg-indigo-950/40"
                  >
                    <input
                      type="radio"
                      name={groupName}
                      value={option.mode}
                      checked={mode === option.mode}
                      onChange={() => {
                        setMode(option.mode);
                        touch();
                      }}
                      className="mt-1 accent-indigo-600"
                    />
                    <span className="min-w-0">
                      <span className="block text-sm font-medium text-slate-900 dark:text-slate-100">
                        {option.label}
                      </span>
                      <span className="block text-sm text-slate-600 dark:text-slate-400">
                        {option.description}
                      </span>
                    </span>
                  </label>
                ))}
              </div>
            </fieldset>

            <div className="flex flex-col gap-1.5">
              <label
                htmlFor={domainsId}
                className="text-sm font-medium text-slate-700 dark:text-slate-200"
              >
                Allowed email domains
              </label>
              <textarea
                id={domainsId}
                rows={2}
                value={domainsText}
                onChange={(event) => {
                  setDomainsText(event.target.value);
                  touch();
                }}
                disabled={saving || mode !== 'open'}
                placeholder="example.com"
                spellCheck={false}
                aria-describedby={domainsHelpId}
                aria-invalid={domainsError ? true : undefined}
                className={`${INPUT_CLASSES} font-mono`}
              />
              <p id={domainsHelpId} className="text-xs text-slate-600 dark:text-slate-400">
                {mode === 'open'
                  ? 'Only addresses at these domains can sign up. Leave empty to allow any domain. Enter one domain per line; subdomains are listed separately.'
                  : 'Applies only while sign-up is Open.'}
              </p>
              {domainsError && (
                <p role="alert" className="text-xs text-rose-700 dark:text-rose-400">
                  {domainsError}
                </p>
              )}
            </div>

            <div className="flex flex-col gap-1.5">
              <label
                htmlFor={blockedId}
                className="text-sm font-medium text-slate-700 dark:text-slate-200"
              >
                Blocked email domains
              </label>
              <textarea
                id={blockedId}
                rows={2}
                value={blockedText}
                onChange={(event) => {
                  setBlockedText(event.target.value);
                  touch();
                }}
                disabled={saving}
                placeholder="throwaway.example"
                spellCheck={false}
                aria-describedby={blockedHelpId}
                aria-invalid={blockedError ? true : undefined}
                className={`${INPUT_CLASSES} font-mono`}
                data-testid="signup-blocked-domains"
              />
              <p id={blockedHelpId} className="text-xs text-slate-600 dark:text-slate-400">
                {`Email sign-up refuses these domains and their subdomains, on top of the ${BUNDLED_DISPOSABLE_EMAIL_DOMAINS.length} disposable-email domains Apiome always blocks. Sign-up with a provider is not affected. Enter one domain per line.`}
              </p>
              {blockedError && (
                <p role="alert" className="text-xs text-rose-700 dark:text-rose-400">
                  {blockedError}
                </p>
              )}
            </div>

            {saveError && (
              <div
                role="alert"
                className="flex items-start gap-2 rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800 dark:border-rose-900/60 dark:bg-rose-950/40 dark:text-rose-300"
              >
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                <p>{saveError}</p>
              </div>
            )}

            <div className="flex flex-wrap items-center gap-3 border-t border-slate-100 pt-3 dark:border-slate-800">
              <button
                type="button"
                onClick={() => void handleSave()}
                disabled={!dirty || saving || domainsError !== null || blockedError !== null}
                className={PRIMARY_BUTTON_CLASSES}
              >
                {saving && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                {saving ? 'Saving…' : 'Save'}
              </button>
              {stored && (
                <button
                  type="button"
                  onClick={() => void handleUseEnv()}
                  disabled={saving}
                  className={SECONDARY_BUTTON_CLASSES}
                >
                  Use .env
                </button>
              )}
              {justSaved && (
                <span
                  role="status"
                  className="inline-flex items-center gap-1 text-sm font-medium text-emerald-600 dark:text-emerald-400"
                >
                  <CheckCircle2 className="h-4 w-4" /> Saved
                </span>
              )}
              <span className="ml-auto text-xs text-slate-500 dark:text-slate-400">
                {stored
                  ? view.updated_at
                    ? `Last changed ${new Date(view.updated_at).toLocaleString()}${view.updated_by ? ` by ${view.updated_by}` : ''}`
                    : 'Stored in the database'
                  : `Not stored — .env gives ${signupModeLabel(view.env_mode)}`}
              </span>
            </div>

            <div className="border-t border-slate-100 pt-3 dark:border-slate-800">
              <BlockedSignupAttempts />
            </div>
          </>
        )}
      </div>
    </section>
  );
}
