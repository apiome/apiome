/**
 * Wire types for the admin sign-up policy card (SGN-1.4, #5653).
 *
 * Mirrors the REST contract of `GET` / `PUT /v1/admin/signup-policy`
 * (`apiome-rest/src/app/signup_policy_routes.py`). Type-only apart from the mode labels, so it is
 * safe to import from the client card.
 */
import type { SignupMode, SignupPolicySource } from './signup-policy';

/** The policy as the REST surface returns it (GET and PUT share this shape). */
export interface AdminSignupPolicyView {
  /** Effective mode — the stored one, else the env fallback. */
  mode: SignupMode;
  /** Email domains allowed to sign up while the mode is `open`; empty means any domain. */
  allowed_email_domains: string[];
  /**
   * Extra domains refused for email sign-up, on top of the bundled disposable list (SGN-1.5).
   * Absent from a REST surface older than OpenAPI 1.311.0.
   */
  blocked_email_domains?: string[];
  /** `db` when a policy is stored; `env` when `AUTH_SIGNUP_DISABLED` governs. */
  source: SignupPolicySource;
  /** The mode the env fallback gives — what applies if the stored policy is cleared. */
  env_mode: SignupMode;
  /** When the stored policy was last changed; null when none is stored. */
  updated_at: string | null;
  /** Who last changed the stored policy; null when none is stored. */
  updated_by: string | null;
}

/** Body of `PUT /v1/admin/signup-policy`. `mode: null` clears the stored policy. */
export interface AdminSignupPolicyUpdatePayload {
  mode: SignupMode | null;
  allowed_email_domains: string[];
  /** Extra domains refused for email sign-up (SGN-1.5); omitted ⇒ none. */
  blocked_email_domains?: string[];
}

/** Which guard refused a sign-up (`auth_events.detail.guard`, SGN-1.5). */
export type BlockedSignupGuard = 'rate_limit' | 'disposable_domain' | 'captcha';

/** One refused attempt, as `GET /v1/admin/signup-policy/blocked-attempts` returns it. */
export interface BlockedSignupAttempt {
  id: string;
  /** ISO timestamp of the refusal. */
  created_at: string;
  /** Which guard refused it (an unknown value is shown as is). */
  guard: BlockedSignupGuard | string;
  /** For a rate limit: `ip` or `address`. */
  scope: 'ip' | 'address' | null;
  /** The code the person was shown. */
  error_code: string | null;
  /** `email` for the email form, else the sign-in provider slug; null when unknown. */
  provider: string | null;
  /** The address the attempt carried, when one was read. */
  email: string | null;
  /** A short prefix of the salted client-IP digest, to tell repeat clients apart. */
  client: string | null;
}

/** Payload of `GET /v1/admin/signup-policy/blocked-attempts`. */
export interface BlockedSignupAttemptList {
  attempts: BlockedSignupAttempt[];
}

/**
 * What the Recent blocked sign-ups list says refused an attempt.
 *
 * @param attempt The attempt.
 * @returns e.g. `Rate limit — too many attempts from one network`.
 */
export function blockedAttemptReason(attempt: Pick<BlockedSignupAttempt, 'guard' | 'scope'>): string {
  switch (attempt.guard) {
    case 'rate_limit':
      return attempt.scope === 'address'
        ? 'Rate limit — too many emails to one address'
        : 'Rate limit — too many attempts from one network';
    case 'disposable_domain':
      return 'Disposable email address';
    case 'captcha':
      return 'Security check failed';
    default:
      return attempt.guard;
  }
}

/**
 * How the list names the sign-up path an attempt used.
 *
 * @param provider The recorded provider.
 * @returns `Email`, `Provider sign-up` when unknown, else the provider slug.
 */
export function blockedAttemptPath(provider: string | null): string {
  if (provider === 'email') return 'Email';
  return provider ? provider : 'Provider sign-up';
}

/** Label and one-line meaning of each mode, as the card's options read. */
export const SIGNUP_MODE_OPTIONS: ReadonlyArray<{
  mode: SignupMode;
  label: string;
  description: string;
}> = [
  {
    mode: 'open',
    label: 'Open',
    description: 'Anyone can create an account, by email or any enabled sign-in provider.',
  },
  {
    mode: 'invite_only',
    label: 'Invite only',
    description:
      'No self-service accounts. Existing users, including invited members, still sign in.',
  },
  {
    mode: 'closed',
    label: 'Closed',
    description: 'No new accounts. Existing users still sign in.',
  },
];

/**
 * The label of a mode, for status chips and messages.
 *
 * @param mode The mode.
 * @returns Its label (`Open`, `Invite only` or `Closed`).
 */
export function signupModeLabel(mode: SignupMode): string {
  return SIGNUP_MODE_OPTIONS.find((option) => option.mode === mode)?.label ?? mode;
}
