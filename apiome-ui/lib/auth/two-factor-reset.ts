/**
 * Shared pieces of the admin two-factor reset (TFA-1.2, #5656).
 *
 * apiome-rest performs a reset and audits it; the web app collects the reason and the typed
 * confirmation, forwards them, and — once the reset has succeeded — emails the user. Two screens
 * start a reset (the admin console and the member drawer) through two routes, so what they have
 * in common lives here: the limits the dialogs check before sending, the shape of the answer, and
 * the step that turns apiome-rest's reply into the response a dialog shows.
 *
 * The limits mirror `apiome-rest/src/app/two_factor_reset_routes.py`, which enforces them; the
 * copies here only let a dialog disable its button instead of collecting a 422.
 */

/** Shortest reason apiome-rest accepts, after trimming. */
export const RESET_REASON_MIN_LENGTH = 10;

/** Longest reason apiome-rest accepts, after trimming. */
export const RESET_REASON_MAX_LENGTH = 500;

/** What a dialog sends. */
export interface TwoFactorResetRequest {
  /** Why the two-factor is being reset. Stored in the audit trail. */
  reason: string;
  /** The target user's email address, typed out to confirm. */
  confirm: string;
}

/** What a successful reset answers with. */
export interface TwoFactorResetOutcome {
  /** The user whose two-factor was reset. */
  userId: string;
  /** Whether the user had two-factor on before the reset. */
  hadTwoFactor: boolean;
  /** How many of the user's sessions were ended. */
  sessionsRevoked: number;
  /** How many trusted-device records were removed. */
  trustedDevicesRevoked: number;
  /** Whether the user was emailed. `false` when no sender is configured or delivery failed. */
  emailSent: boolean;
}

/** What a refused reset answers with. */
export interface TwoFactorResetRefusal {
  /** Stable code from apiome-rest, e.g. `multi_tenant_member`, when it sent one. */
  code: string | null;
  /** The sentence to show. */
  message: string;
}

/**
 * Whether a reason is within the limits apiome-rest enforces.
 *
 * @param reason What the administrator typed.
 * @returns `true` when the trimmed reason is long enough and not too long.
 */
export function isValidResetReason(reason: string): boolean {
  const length = reason.trim().length;
  return length >= RESET_REASON_MIN_LENGTH && length <= RESET_REASON_MAX_LENGTH;
}

/**
 * Whether the typed confirmation names the target.
 *
 * @param typed What the administrator typed.
 * @param email The target user's email address.
 * @returns `true` when they match, ignoring case and surrounding space — the comparison
 *   apiome-rest makes.
 */
export function matchesResetConfirmation(typed: string, email: string | null | undefined): boolean {
  const expected = email?.trim().toLowerCase();
  return Boolean(expected) && typed.trim().toLowerCase() === expected;
}

/**
 * Read the body of a reset request.
 *
 * @param body The parsed JSON a dialog posted.
 * @returns The reason and confirmation, or `null` when the body is not an object carrying both
 *   as strings (apiome-rest validates their content).
 */
export function parseResetRequest(body: unknown): TwoFactorResetRequest | null {
  if (!body || typeof body !== 'object' || Array.isArray(body)) return null;
  const { reason, confirm } = body as Record<string, unknown>;
  return typeof reason === 'string' && typeof confirm === 'string' ? { reason, confirm } : null;
}

/**
 * Word apiome-rest's refusal of a reset.
 *
 * Its refusals carry `detail: { error, message }`; anything else (a plain-string detail, a proxy
 * failure) falls back to a general sentence.
 *
 * @param body The parsed JSON apiome-rest answered with.
 * @returns The stable code, when there is one, and the sentence to show.
 */
export function describeResetRefusal(body: unknown): TwoFactorResetRefusal {
  const record = (body && typeof body === 'object' ? body : {}) as Record<string, unknown>;
  const detail = record.detail;
  if (detail && typeof detail === 'object') {
    const { error, message } = detail as Record<string, unknown>;
    if (typeof message === 'string' && message) {
      return { code: typeof error === 'string' ? error : null, message };
    }
  }
  if (typeof detail === 'string' && detail) return { code: null, message: detail };
  if (typeof record.message === 'string' && record.message) {
    return { code: typeof record.error === 'string' ? record.error : null, message: record.message };
  }
  return { code: null, message: 'The two-factor reset could not be completed. Try again.' };
}

/**
 * Turn apiome-rest's reply to a reset into the response a dialog receives.
 *
 * On success the user is emailed — after the fact, because the reset is already committed and an
 * email problem must not undo or mask it — and the answer says whether that email went out.
 *
 * @param status The HTTP status apiome-rest answered with.
 * @param body The parsed JSON it answered with.
 * @param sendEmail Sends the notice; resolves `false` when it could not be sent.
 * @returns The status and JSON body to answer the browser with: `{ success: true, data }` or
 *   `{ success: false, error, code? }`.
 */
export async function finishTwoFactorReset(
  status: number,
  body: unknown,
  sendEmail: (recipient: { email?: string | null; name?: string | null }) => Promise<boolean>
): Promise<{ status: number; body: Record<string, unknown> }> {
  if (status < 200 || status >= 300) {
    const refusal = describeResetRefusal(body);
    return {
      status,
      body: { success: false, error: refusal.message, ...(refusal.code ? { code: refusal.code } : {}) },
    };
  }
  const result = (body ?? {}) as Record<string, unknown>;
  const emailSent = await sendEmail({
    email: typeof result.email === 'string' ? result.email : null,
    name: typeof result.name === 'string' ? result.name : null,
  });
  const data: TwoFactorResetOutcome = {
    userId: String(result.user_id ?? ''),
    hadTwoFactor: Boolean(result.had_two_factor),
    sessionsRevoked: Number(result.sessions_revoked ?? 0),
    trustedDevicesRevoked: Number(result.trusted_devices_revoked ?? 0),
    emailSent,
  };
  return { status: 200, body: { success: true, data } };
}
