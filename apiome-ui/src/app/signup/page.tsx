import { redirect } from 'next/navigation';

import { isEmailSignupAvailable } from '@lib/auth/email-signup';
import { resolvePostLoginRouteForUser } from '@lib/auth/post-login-routing';
import { providerSummaries } from '@lib/auth/provider-registry';
import { resolveProviderEnv } from '@lib/auth/provider-config-resolver';
import { getAuthSession } from '@lib/auth/server-session';
import { legalLinksFromEnv, signupPageState } from '@lib/auth/signup-page';
import { resolveSignupPolicy } from '@lib/auth/signup-policy-resolver';
import { turnstileSiteKey } from '@lib/auth/turnstile';

import SignupClient from './SignupClient';

/**
 * `/signup` — create an Apiome account (SGN-1.2, #5651).
 *
 * Everything that depends on configuration is decided here, server-side, and handed down as
 * plain data: the enabled sign-in providers (the same DB-over-env list the login page shows),
 * the installation's sign-up policy (SGN-1.4), whether email sign-up can run (SGN-1.1) and, when
 * Turnstile is configured, its public site key for the email form's CAPTCHA (SGN-1.5).
 * `signupPageState` turns the last two into what the page draws, so a closed or invite-only
 * installation never renders a control that could not work.
 *
 * A signed-in reader has nothing to sign up for and goes where the login page would send them.
 *
 * @returns The sign-up page.
 */
export default async function SignupPage() {
  const session = await getAuthSession();
  const userId = (session?.user as { user_id?: string; current_tenant_id?: string } | undefined)?.user_id;
  if (userId) {
    const route = await resolvePostLoginRouteForUser(userId, {
      lastActiveTenantId: (session?.user as { current_tenant_id?: string }).current_tenant_id,
    });
    redirect(route.destination);
  }

  const providers = providerSummaries(await resolveProviderEnv()).filter((provider) => provider.enabled);
  const state = signupPageState(await resolveSignupPolicy(), isEmailSignupAvailable());

  return (
    <SignupClient
      providers={providers}
      state={state}
      legalLinks={legalLinksFromEnv()}
      turnstileSiteKey={state.showEmailForm ? turnstileSiteKey() : null}
    />
  );
}
