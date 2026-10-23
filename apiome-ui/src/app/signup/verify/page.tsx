import VerifyEmailClient from './VerifyEmailClient';

/**
 * `/signup/verify?token=…` — where the sign-up confirmation link lands (SGN-1.1, #5650).
 *
 * A thin server wrapper: the token is redeemed from the client (`verifyEmailSignup`), because a
 * successful redemption ends in a sign-in that sets cookies, which a server component's render
 * cannot do. The page is public; without a valid token it only offers a resend.
 *
 * @param props.searchParams The query string; only `token` is read.
 * @returns The verification screen.
 */
export default async function VerifyEmailPage({
  searchParams,
}: {
  searchParams: Promise<{ token?: string }>;
}) {
  const { token } = await searchParams;
  return <VerifyEmailClient token={typeof token === 'string' ? token : ''} />;
}
