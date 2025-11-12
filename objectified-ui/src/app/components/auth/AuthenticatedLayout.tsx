// AuthenticatedLayout.tsx
'use client';

import React, { useEffect } from 'react';
import { useSession } from 'next-auth/react';
import { useRouter } from 'next/navigation';

interface AuthenticatedLayoutProps {
  children: React.ReactNode;
  redirectTo?: string;
}

/**
 * Wrapper component that ensures user is authenticated before rendering children.
 * Automatically redirects to login if no session is found.
 * Provides session context to all children.
 */
export const AuthenticatedLayout: React.FC<AuthenticatedLayoutProps> = ({
  children,
  redirectTo = '/login'
}) => {
  const { data: session, status } = useSession();
  const router = useRouter();

  useEffect(() => {
    if (status === 'loading') return; // Wait for session to load

    if (session) {
      console.log('[AuthenticatedLayout] Session:', session, 'status:', status);
    }

    if (session === null) {
      router.push(redirectTo);
    }
  }, [session, status, router, redirectTo]);

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

