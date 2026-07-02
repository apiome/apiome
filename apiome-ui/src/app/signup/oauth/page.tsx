import { redirect } from "next/navigation";
import { getOauthSignupPendingById } from "../../../../lib/db/oauth-signup";
import OauthSignupClient from "./OauthSignupClient";

function maskEmail(email: string): string {
  const [local, domain] = email.split("@");
  if (!domain) return "***";
  if (local.length <= 2) return `***@${domain}`;
  return `${local[0]}***${local[local.length - 1]}@${domain}`;
}

export default async function OauthSignupPage({
  searchParams,
}: {
  searchParams: Promise<{ token?: string }>;
}) {
  const { token } = await searchParams;
  if (!token) {
    redirect("/login?error=SignupSessionExpired");
  }

  const pending = await getOauthSignupPendingById(token);
  if (!pending) {
    redirect("/login?error=SignupSessionExpired");
  }

  return <OauthSignupClient token={token} emailHint={maskEmail(pending.email)} />;
}
