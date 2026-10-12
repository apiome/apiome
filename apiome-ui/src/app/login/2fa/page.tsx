import { resolveCallbackUrl } from '@lib/auth/cookie-options';
import { normalizeTwoFactorMethods } from '@lib/auth/two-factor-callback';
import TwoFactorClient from '@/app/login/2fa/TwoFactorClient';

/**
 * Login second step — verify a code after the first factor (OLO-9.13 #5014). No full session
 * exists yet; only Better Auth's short-lived 2FA cookie.
 *
 * Reached two ways. A password sign-in answers `twoFactorRedirect` and the browser navigates here,
 * having stored the offered methods in `sessionStorage`. A provider sign-in (TFA-1.1 #5655) is
 * redirected here by the server (`two-factor-oauth-challenge.ts`), which cannot reach
 * `sessionStorage` and so names the methods in `?methods=totp,otp`. Both query values are
 * untrusted: the callback is checked against the allowlist and the methods reduced to the two the
 * screen knows. Naming a method here only decides which form is drawn — the server still decides
 * whether a code is accepted.
 */
export default async function TwoFactorLoginPage({
  searchParams,
}: {
  searchParams: Promise<{ callbackUrl?: string; error?: string; methods?: string }>;
}) {
  const params = await searchParams;
  const callbackUrl = resolveCallbackUrl(params.callbackUrl);
  const methods =
    typeof params.methods === 'string' && params.methods
      ? normalizeTwoFactorMethods(params.methods.split(','))
      : undefined;

  return <TwoFactorClient callbackUrl={callbackUrl} error={params.error} methods={methods} />;
}
