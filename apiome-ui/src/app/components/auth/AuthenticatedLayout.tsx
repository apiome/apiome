// AuthenticatedLayout.tsx
'use client';

import React, { useEffect } from 'react';
import { useSession } from 'next-auth/react';
import { usePathname, useRouter } from 'next/navigation';
import { buildLoginRedirect } from '@lib/auth/login-return-to';

interface AuthenticatedLayoutProps {
  children: React.ReactNode;
  redirectTo?: string;
}

/**
 * Wrapper component that ensures user is authenticated before rendering children.
 * Automatically redirects to login if no session is found.
 * Provides session context to all children.
 *
 * Session lifecycle hygiene (OLO-3.4, #4202): the redirect carries the current
 * location as `callbackUrl`, so a user whose session expired mid-task returns
 * to the same page after signing back in. When an explicit `redirectTo` is
 * given, it is used verbatim (no return-to attached).
 */
export const AuthenticatedLayout: React.FC<AuthenticatedLayoutProps> = ({
  children,
  redirectTo
}) => {
  const { data: session, status } = useSession();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (status === 'loading') return; // Wait for session to load

    if (session === null) {
      // window.location.search rather than useSearchParams(): reading params
      // here would force a Suspense boundary around every protected shell.
      const search = typeof window !== 'undefined' ? window.location.search : '';
      router.push(redirectTo ?? buildLoginRedirect(pathname, search));
    }
  }, [session, status, router, redirectTo, pathname]);

  // Show loading state while checking authentication
  if (status === 'loading') {
    return (
      <div className="flex items-center justify-center h-screen">
        <div className="text-gray-600 dark:text-gray-400">Loading...</div>
      </div>
    );
  }

  // Don't render children if not authenticated
  if (!session) {
    return null;
  }

  return <>{children}</>;
};

export default AuthenticatedLayout;
