/**
 * What the `/signup` page shows, decided from the installation's sign-up policy (SGN-1.2,
 * #5651). Pure, so every state is unit-tested without a server.
 *
 * The rule the page follows is the one HIVE-11.9 wrote down: **no control that cannot work is
 * shown.** So a closed installation shows a notice and the sign-in link — no provider buttons
 * that would only bounce back with "sign-ups are disabled", no form that would refuse. An
 * invite-only installation does the same with its own copy: invitations in Apiome go to people
 * who already have an account (SGN-1.4), so there is no invitation link to ask for, and a field
 * for one would be a control that could not work. An open installation shows every enabled
 * provider, then the email form when a mail sender is configured, and names the allowed email
 * domains when the policy restricts them.
 */

import type { SignupMode, SignupPolicy } from './signup-policy';

/** The page's state for one policy. */
export interface SignupPageState {
  /** The policy mode, which picks the page's copy. */
  mode: SignupMode;
  /** Whether provider sign-up buttons are shown. */
  showProviders: boolean;
  /** Whether the email + password form is shown (open policy and a mail sender configured). */
  showEmailForm: boolean;
  /** Open policy, but no mail sender: say email sign-up is unavailable instead of a form. */
  showEmailUnavailable: boolean;
  /** The allowed email domains to name, empty when any domain may sign up. */
  allowedDomains: readonly string[];
  /** The notice a closed or invite-only page shows in place of the controls; `null` when open. */
  notice: { title: string; text: string } | null;
}

/** The notice a closed installation shows. Wording follows the login page's `signup-disabled`. */
export const SIGNUP_CLOSED_NOTICE = {
  title: 'Sign-up is closed',
  text: 'New account sign-ups are currently disabled on this server. Contact your administrator to request an account.',
} as const;

/** The notice an invite-only installation shows. Wording follows `signup-invite-only`. */
export const SIGNUP_INVITE_ONLY_NOTICE = {
  title: 'Sign-up is by invitation',
  text: 'New accounts on this server are by invitation only. Ask a workspace administrator to set up your account and invite you.',
} as const;

/**
 * Decide what `/signup` shows.
 *
 * @param policy The effective installation sign-up policy (`resolveSignupPolicy`).
 * @param emailSignupAvailable Whether email sign-up can run (`isEmailSignupAvailable`).
 * @returns The page state.
 */
export function signupPageState(policy: SignupPolicy, emailSignupAvailable: boolean): SignupPageState {
  if (policy.mode !== 'open') {
    return {
      mode: policy.mode,
      showProviders: false,
      showEmailForm: false,
      showEmailUnavailable: false,
      allowedDomains: [],
      notice: policy.mode === 'closed' ? SIGNUP_CLOSED_NOTICE : SIGNUP_INVITE_ONLY_NOTICE,
    };
  }
  return {
    mode: 'open',
    showProviders: true,
    showEmailForm: emailSignupAvailable,
    showEmailUnavailable: !emailSignupAvailable,
    allowedDomains: [...policy.allowedEmailDomains],
    notice: null,
  };
}

/**
 * The allowed-domains hint, e.g. "Sign-up is open to addresses at northwind.io and
 * contoso.example."
 *
 * @param domains The allowed domains (already normalised by the policy).
 * @returns The sentence, or `null` when any domain may sign up.
 */
export function allowedDomainsHint(domains: readonly string[]): string | null {
  if (domains.length === 0) return null;
  const listed =
    domains.length === 1
      ? domains[0]
      : `${domains.slice(0, -1).join(', ')} and ${domains[domains.length - 1]}`;
  return `Sign-up is open to addresses at ${listed}.`;
}

/** Where the legal pages live, when the installation has them. */
export interface LegalLinks {
  termsUrl: string | null;
  privacyUrl: string | null;
}

/** Env var naming the Terms of Service URL. */
export const TERMS_URL_ENV = 'APIOME_TERMS_URL';

/** Env var naming the Privacy Policy URL. */
export const PRIVACY_URL_ENV = 'APIOME_PRIVACY_URL';

/**
 * Read the legal links from the environment. A link that is unset or not http(s) is `null`,
 * and the page leaves it out rather than drawing a link that goes nowhere.
 *
 * @param env Environment map; defaults to `process.env`.
 * @returns Both URLs, each or both possibly `null`.
 */
export function legalLinksFromEnv(env: NodeJS.Dict<string> = process.env): LegalLinks {
  const read = (name: string): string | null => {
    const raw = env[name]?.trim();
    if (!raw) return null;
    try {
      const url = new URL(raw);
      return url.protocol === 'https:' || url.protocol === 'http:' ? url.toString() : null;
    } catch {
      return null;
    }
  };
  return { termsUrl: read(TERMS_URL_ENV), privacyUrl: read(PRIVACY_URL_ENV) };
}
