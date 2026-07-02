import { getServerSession } from 'next-auth';
import { redirect } from 'next/navigation';
import { authOptions } from '@/app/api/auth/[...nextauth]/route';
import LoginClient from '@/app/login/LoginClient';

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string }>;
}) {
  const session = await getServerSession(authOptions);
  if (session) {
    redirect('/ade');
  }

  const params = await searchParams;
  return <LoginClient error={params.error} />;
}
