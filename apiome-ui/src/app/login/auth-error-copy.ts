/**
 * User-facing copy for the structured auth error contract (OLO-1.5, #4190).
 *
 * Every code the login page can receive on its `?error=` query param maps here to distinct
 * guidance. The stable codes are emitted by the account-resolution engine
 * (`lib/auth/account-resolution.ts`, mirrored in `apiome-rest/src/app/account_resolution.py`);
 * the remaining keys are NextAuth built-ins and pre-contract copy keys the page must keep
 * understanding. The full contract is documented in `apiome-ui/docs/AUTH_ERROR_CODES.md` —
 * keep the doc, this map, and the enum in sync when adding a code.
 */

/** Severity of the message box the login page renders. */
export interface AuthErrorCopy {
  type: 'error' | 'info';
  text: string;
  /**
   * Renders a "Try again" affordance in the banner (OLO-3.2): a link back to a clean login
   * page (error cleared, callbackUrl preserved). Set on codes the user can resolve outside
   * Apiome and then retry — e.g. verifying their email with the provider. Terminal states
   * (disabled account, suspended membership, disabled signup) must not offer it.
   */
  retry?: boolean;
}

/** Copy per known error code; codes not listed here fall back to a generic message. */
export const AUTH_ERROR_COPY: Readonly<Record<string, AuthErrorCopy>> = {
  // --- Stable contract codes (OLO-1.5) ---
  'unverified-email': {
    type: 'error',
    text: 'Your sign-in provider could not confirm that your email address is verified. Verify your email with the provider (e.g. GitHub or GitLab), then try again.',
    retry: true,
  },
  'account-disabled': {
    type: 'error',
    text: 'Your account is currently disabled. Please contact support if you believe this is a mistake.',
  },
  'account-not-verified': {
    type: 'error',
    text: 'You have not yet verified your account e-mail address. Check your inbox for the verification email, then sign in again.',
    retry: true,
  },
  'provider-already-linked': {
    type: 'error',
    text: 'Your account already has a different identity linked for this provider. Sign in with the originally linked provider account, or manage linked accounts from your dashboard.',
  },
  'identity-linked-elsewhere': {
    type: 'error',
    text: 'This provider account is already linked to another user. Sign in with that account, or use a different provider account.',
  },
  'last-sign-in-method': {
    type: 'error',
    text: 'That account is your only way to sign in. Set a password or link another provider before unlinking it, so you keep access to your account.',
  },
  'membership-suspended': {
    type: 'error',
    text: 'Your membership in this workspace has been suspended. Contact your workspace administrator to restore access.',
  },
  'provider-not-configured': {
    type: 'error',
    text: 'Sign-in with that provider is not available on this server. Choose one of the sign-in options shown, or contact your administrator.',
  },
  'signup-disabled': {
    type: 'info',
    text: 'New account sign-ups are currently disabled on this server. Contact your administrator to request an account or an invitation.',
  },
  'signup-invite-only': {
    type: 'info',
    text: 'New accounts on this server are by invitation only. Ask a workspace administrator to set up your account and invite you.',
  },
  'signup-domain-not-allowed': {
    type: 'info',
    text: 'New accounts on this server are limited to approved email domains, and yours is not one of them. Sign up with your work email address, or contact your administrator.',
  },
  'sign-in-failed': {
    type: 'error',
    text: 'Something went wrong while signing you in. Please try again, or contact support if the issue persists.',
    retry: true,
  },

  // --- Pre-contract stable copy keys still emitted by the engine ---
  OAuthEmailRequired: {
    type: 'error',
    text: 'Your Git provider did not share an email address. Set your email to public or add a verified email on GitHub/GitLab, then try again.',
    retry: true,
  },
  OAuthProfileIncomplete: {
    type: 'error',
    text: 'We could not read your OAuth profile. Please try again or contact support.',
    retry: true,
  },

  // --- NextAuth built-ins and flow-specific keys ---
  AccessDenied: {
    type: 'error',
    text: 'An issue occurred with the OAuth provider. Your account may not have been set up properly. Please contact support or try a different sign-in method.',
  },
  OAuthAccountExists: {
    type: 'info',
    text: 'An account with this email already exists. Sign in with your password or use "Continue with GitHub/GitLab" without create-account mode.',
  },
  // --- Enterprise SSO (EID-1.1, #5011; `lib/auth/sso-resolution.ts` SSO_ERROR_CODES) ---
  'sso-token-invalid': {
    type: 'error',
    text: 'Apiome could not verify the sign-in token from your single sign-on provider. Try again; if it keeps happening, ask your administrator to check the OIDC connection.',
    retry: true,
  },
  'sso-assertion-invalid': {
    type: 'error',
    text: 'Apiome could not verify the SAML response from your single sign-on provider. Try again; if it keeps happening, ask your administrator to check the SAML connection.',
    retry: true,
  },
  'sso-assertion-replayed': {
    type: 'error',
    text: 'That sign-in response was already used. Start single sign-on again from this page.',
    retry: true,
  },
  'sso-binding-unsupported': {
    type: 'error',
    text: 'Your single sign-on provider answered in a way Apiome does not accept. Ask your administrator to send sign-in responses over HTTP-POST.',
  },
  'sso-discovery-failed': {
    type: 'error',
    text: 'Apiome could not reach your single sign-on provider. Try again in a moment, or ask your administrator.',
    retry: true,
  },
  'sso-state-invalid': {
    type: 'error',
    text: 'Your single sign-on attempt expired. Start it again from this page.',
    retry: true,
  },
  'sso-provider-not-found': {
    type: 'error',
    text: 'Single sign-on is not set up for that email domain. Sign in another way, or ask your administrator.',
    retry: true,
  },
  'sso-email-domain-mismatch': {
    type: 'error',
    text: 'Your single sign-on provider returned an email address outside the domains it is set up for. Ask your administrator to check the connection.',
  },
  'sso-account-not-linked': {
    type: 'error',
    text: 'An account with your email already exists but could not be linked to single sign-on. Sign in another way, or ask your administrator.',
  },
  SignupSessionExpired: {
    type: 'error',
    text: 'Your signup session expired. Please start again from Create account.',
    retry: true,
  },
  CredentialsSignin: {
    type: 'error',
    text: 'Your account could not be found or the credentials provided were incorrect. Please check your email and password, or sign up for a new account.',
  },
  TwoFactorInvalid: {
    type: 'error',
    text: 'That authentication code was not accepted. Check your authenticator app and try again.',
  },
};

/**
 * Safe generic banner for unknown codes (OLO-3.2). The `?error=` value is attacker-influenced
 * (anyone can craft the URL), so unknown codes are never echoed back into the page — the user
 * sees only this fixed copy.
 */
export const GENERIC_AUTH_ERROR: Readonly<AuthErrorCopy> = {
  type: 'error',
  text: 'Something went wrong while signing you in. Please try again, or contact support if the issue persists.',
  retry: true,
};

/**
 * Resolve the message to render for a login error code.
 *
 * @param errorCode The `?error=` query-param value from the NextAuth error redirect.
 * @returns The mapped copy, the safe generic fallback for unknown values, or null when no code
 *   is present.
 */
export function getAuthErrorCopy(errorCode?: string): AuthErrorCopy | null {
  if (!errorCode) return null;

  return AUTH_ERROR_COPY[errorCode] ?? GENERIC_AUTH_ERROR;
}
