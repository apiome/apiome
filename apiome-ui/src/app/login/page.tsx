import { getServerSession } from 'next-auth';
import { redirect } from 'next/navigation';
import { authOptions } from '@/app/api/auth/[...nextauth]/route';
import { resolveCallbackUrl } from '@lib/auth/cookie-options';
import { providerSummaries } from '@lib/auth/provider-registry';
import LoginClient from '@/app/login/LoginClient';

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string; callbackUrl?: string }>;
}) {
  const params = await searchParams;
  const callbackUrl = resolveCallbackUrl(params.callbackUrl);

  const session = await getServerSession(authOptions);
  if (session) {
    redirect(callbackUrl);
  }

  // Env is server-side only, so the enabled-provider list (provider registry, OLO-2.3)
  // is resolved here and passed down; the client resolves brand icons by id.
  const ssoProviders = providerSummaries().filter((provider) => provider.enabled);

  return <LoginClient error={params.error} callbackUrl={callbackUrl} ssoProviders={ssoProviders} />;
}
