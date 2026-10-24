/**
 * Write path for the `auth_events` ledger from apiome-ui (EID-1.1 #5011; shared by SGN-1.5 #5654).
 *
 * The hash-chained `auth_events` ledger (V193) is written only by apiome-rest. apiome-ui posts each
 * outcome to its service-token-gated `POST /v1/internal/auth-events`, which hashes the IP and
 * User-Agent before anything is stored. Enterprise SSO (`sso-resolution.ts`) and the sign-up abuse
 * guards (`signup-guard-events.ts`) both write through {@link postAuthEvent}.
 *
 * Best-effort: without `INTERNAL_SERVICE_TOKEN` nothing is sent, and a failed or slow write (2 s
 * timeout) is swallowed — an audit write never fails the request it records.
 *
 * Server-only.
 */
import { REST_API_BASE_URL } from '../rest-auth';

/** One `auth_events` row, as `/v1/internal/auth-events` accepts it. */
export interface AuthEventInput {
  event_type: 'sign_in' | 'sign_up' | 'link';
  outcome: 'success' | 'failure';
  /** `sso:<slug>`, an OAuth provider slug, `email`, or null when unknown. */
  provider?: string | null;
  user_id?: string | null;
  user_label?: string | null;
  error_code?: string | null;
  /** Raw client IP; REST hashes it and never stores it. */
  ip?: string | null;
  /** Raw User-Agent; REST hashes it and never stores it. */
  user_agent?: string | null;
  /** Small structured context (at most 2 KB serialized), never a secret. */
  detail?: Record<string, unknown>;
}

/**
 * Append one row to `auth_events` through apiome-rest.
 *
 * @param event The row.
 * @returns Resolves once the write was attempted; never rejects.
 */
export async function postAuthEvent(event: AuthEventInput): Promise<void> {
  const token = process.env.INTERNAL_SERVICE_TOKEN?.trim();
  if (!token) return;
  const base = process.env.REST_API_BASE_URL?.trim().replace(/\/+$/, '') || REST_API_BASE_URL;
  try {
    await fetch(`${base}/internal/auth-events`, {
      method: 'POST',
      cache: 'no-store',
      headers: { 'Content-Type': 'application/json', 'X-Internal-Service-Token': token },
      body: JSON.stringify(event),
      signal: AbortSignal.timeout(2_000),
    });
  } catch {
    // Best-effort: an audit write never fails the request it records.
  }
}
