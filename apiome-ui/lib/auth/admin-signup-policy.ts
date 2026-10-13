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
