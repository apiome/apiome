'use client';

import * as React from 'react';
import { useAuthSession } from '@lib/auth/session-client';
import { loadTenantMembershipContext } from '@lib/auth/tenant-membership-context';

/**
 * The current workspace's name, for the first step of a page's breadcrumb (`Acme Corp › …`).
 *
 * The name is context, not content: it is read once from the membership context the workspace
 * switcher uses, and a refused or pending read leaves `null`, so the caller keeps a fallback
 * label (`Home`) rather than failing the page.
 *
 * @param load The membership loader (a test seam); defaults to the server action.
 * @returns The workspace's name, or null until (or unless) it is known.
 */
export function useWorkspaceName(
  load: typeof loadTenantMembershipContext = loadTenantMembershipContext,
): string | null {
  const { data: session } = useAuthSession();
  const currentTenantId = (session?.user as { current_tenant_id?: string } | undefined)?.current_tenant_id;
  const [name, setName] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!currentTenantId) return;
    let cancelled = false;
    load()
      .then((context) => {
        if (cancelled) return;
        const match = context.tenants.find((tenant) => tenant.id === currentTenantId);
        setName(match?.name ?? null);
      })
      .catch(() => {
        /* The fallback label stays. */
      });
    return () => {
      cancelled = true;
    };
  }, [currentTenantId, load]);

  return name;
}
