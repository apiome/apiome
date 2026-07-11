import { getServerSession } from 'next-auth';
import { redirect } from 'next/navigation';
import { authOptions } from '@/app/api/auth/[...nextauth]/route';
import { resolveCallbackUrl } from '@lib/auth/cookie-options';
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

  return <LoginClient error={params.error} callbackUrl={callbackUrl} />;
}
