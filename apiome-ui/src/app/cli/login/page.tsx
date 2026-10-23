import { redirect } from 'next/navigation';

import { cliLoginPagePath, normalizeCliUserCode } from '@lib/auth/cli-login';
import { getAuthSession } from '@lib/auth/server-session';
import { getTenantById } from '@lib/db/helper';

import CliLoginClient from './CliLoginClient';

/**
 * `/cli/login?code=…` — where `apiome login` sends the person to approve a CLI sign-in (#5501).
 *
 * Signed out, it sends them to sign in and back here with the code kept. Signed in, the client
 * reads the pending login (`getCliLoginRequest`) and offers **Approve** for a workspace or
 * **Deny**. Opened without a code, it asks for the one shown in the terminal.
 *
 * @param props.searchParams The query string; only `code` is read.
 * @returns The approve screen.
 */
export default async function CliLoginPage({
  searchParams,
}: {
  searchParams: Promise<{ code?: string }>;
}) {
  const { code } = await searchParams;
  const canonical = normalizeCliUserCode(code);

  const session = await getAuthSession();
  const user = session?.user as { user_id?: string; current_tenant_id?: string } | undefined;
  if (!user?.user_id) {
    redirect(`/login?callbackUrl=${encodeURIComponent(cliLoginPagePath(canonical))}`);
  }

  // Start the workspace picker on the one the person last worked in, when they may approve there.
  const current = user.current_tenant_id ? await getTenantById(user.current_tenant_id).catch(() => null) : null;

  return <CliLoginClient initialCode={canonical} currentWorkspaceSlug={current?.slug ?? null} />;
}
