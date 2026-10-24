'use client';

/**
 * **Recent blocked sign-ups** on the System settings Sign-up card (SGN-1.5, #5654).
 *
 * Lists the newest sign-up attempts an abuse guard refused — a rate limit, the disposable-email
 * blocklist or the CAPTCHA — read from `auth_events` through the super-admin proxy
 * (`/api/admin/signup-policy/blocked-attempts`). Sign-up happens before any workspace exists, so
 * this is where those refusals are visible; a workspace's access audit never shows them.
 *
 * The **Client** column is a short prefix of the salted IP digest the ledger keeps: equal values
 * mean the same network, but no address is ever shown.
 */
import { useCallback, useEffect, useId, useState } from 'react';
import { Loader2, RefreshCw } from 'lucide-react';
import { extractRestErrorMessage } from '@lib/auth/admin-provider-config';
import {
  blockedAttemptPath,
  blockedAttemptReason,
  type BlockedSignupAttempt,
  type BlockedSignupAttemptList,
} from '@lib/auth/admin-signup-policy';
import { SECONDARY_BUTTON_CLASSES } from './settingsStyles';

/** Proxy route the list reads from. */
const BLOCKED_ATTEMPTS_URL = '/api/admin/signup-policy/blocked-attempts?limit=20';

/** The list, with its own loading, error and empty states. */
export default function BlockedSignupAttempts() {
  const [attempts, setAttempts] = useState<BlockedSignupAttempt[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const headingId = useId();

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(BLOCKED_ATTEMPTS_URL, { cache: 'no-store' });
      const body: unknown = await response.json().catch(() => null);
      if (!response.ok) {
        setError(
          response.status === 401 || response.status === 403
            ? 'Your admin session has expired. Sign out and back in.'
            : extractRestErrorMessage(body, 'Could not load the blocked sign-ups.'),
        );
        return;
      }
      setAttempts((body as BlockedSignupAttemptList).attempts ?? []);
    } catch {
      setError('Could not load the blocked sign-ups: the server could not be reached.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-2" data-testid="blocked-signups">
      <div className="flex items-center gap-3">
        <h4 id={headingId} className="text-sm font-medium text-slate-700 dark:text-slate-200">
          Recent blocked sign-ups
        </h4>
        <button
          type="button"
          onClick={() => void load()}
          disabled={loading}
          className={`${SECONDARY_BUTTON_CLASSES} ml-auto`}
        >
          {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
          Refresh
        </button>
      </div>

      {error && (
        <p role="alert" className="text-sm text-rose-700 dark:text-rose-400">
          {error}
        </p>
      )}

      {!error && attempts && attempts.length === 0 && (
        <p className="text-sm text-slate-600 dark:text-slate-400" data-testid="blocked-signups-empty">
          No sign-ups have been blocked.
        </p>
      )}

      {!error && attempts && attempts.length > 0 && (
        <div className="overflow-x-auto rounded-md border border-slate-200 dark:border-slate-700">
          <table className="w-full text-left text-sm">
            <thead className="bg-slate-50 text-xs text-slate-600 dark:bg-slate-800 dark:text-slate-300">
              <tr>
                <th scope="col" className="px-3 py-2 font-medium">When</th>
                <th scope="col" className="px-3 py-2 font-medium">Reason</th>
                <th scope="col" className="px-3 py-2 font-medium">Path</th>
                <th scope="col" className="px-3 py-2 font-medium">Address</th>
                <th scope="col" className="px-3 py-2 font-medium">Client</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 text-slate-700 dark:divide-slate-800 dark:text-slate-200">
              {attempts.map((attempt) => (
                <tr key={attempt.id} data-testid="blocked-signup-row">
                  <td className="whitespace-nowrap px-3 py-2">
                    {new Date(attempt.created_at).toLocaleString()}
                  </td>
                  <td className="px-3 py-2">{blockedAttemptReason(attempt)}</td>
                  <td className="px-3 py-2">{blockedAttemptPath(attempt.provider)}</td>
                  <td className="px-3 py-2 font-mono">{attempt.email ?? '—'}</td>
                  <td className="px-3 py-2 font-mono">{attempt.client ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
