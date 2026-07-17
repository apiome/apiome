'use client';

import { useRouter } from 'next/navigation';
import { signOut } from 'next-auth/react';
import { Building2, LogOut, RefreshCw } from 'lucide-react';
import { Button } from '../ui/Button';

/**
 * Blocking prompt shown by {@link FirstTenantOnboardingGuard} to authenticated
 * users with zero tenant memberships (OLO-3.3, #4201).
 *
 * This is the mount point for the first-tenant onboarding wizard (OLO-4.1,
 * #4205): the wizard steps replace the body of this panel. Until then it
 * explains the state and offers the only two useful actions — re-check
 * memberships (for users who have just been invited to a tenant) and sign out.
 * There is deliberately no dismiss control: a tenant-less user cannot use any
 * dashboard surface, so the prompt is not skippable.
 */
export function FirstTenantOnboardingPrompt() {
  const router = useRouter();

  return (
    <main
      className="flex h-full items-center justify-center overflow-y-auto bg-gray-50 p-6 dark:bg-gray-900"
      data-testid="first-tenant-onboarding-prompt"
    >
      <section
        aria-labelledby="first-tenant-onboarding-title"
        className="w-full max-w-md rounded-2xl border border-gray-200 bg-white p-8 text-center shadow-sm dark:border-gray-700 dark:bg-gray-800"
      >
        <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-indigo-100 to-purple-100 dark:from-indigo-900/30 dark:to-purple-900/30">
          <Building2 aria-hidden="true" className="h-7 w-7 text-indigo-600 dark:text-indigo-400" />
        </div>
        <h1
          id="first-tenant-onboarding-title"
          className="text-xl font-bold text-gray-900 dark:text-white"
        >
          Let&apos;s set up your first tenant
        </h1>
        <p className="mt-2 text-sm text-gray-600 dark:text-gray-400">
          Your account isn&apos;t a member of any tenant yet. The setup assistant will walk you
          through creating one so you can start building.
        </p>
        <p className="mt-2 text-sm text-gray-500 dark:text-gray-500">
          Expecting an invitation? Once a tenant administrator adds you, refresh to continue.
        </p>
        <div className="mt-6 flex flex-col justify-center gap-3 sm:flex-row">
          <Button onClick={() => router.refresh()}>
            <RefreshCw aria-hidden="true" className="h-4 w-4" />
            Check again
          </Button>
          <Button variant="outline" onClick={() => signOut({ callbackUrl: '/login' })}>
            <LogOut aria-hidden="true" className="h-4 w-4" />
            Sign out
          </Button>
        </div>
      </section>
    </main>
  );
}

export default FirstTenantOnboardingPrompt;
