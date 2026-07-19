/**
 * Authoring route group layout (UXE-1.2).
 *
 * Resolves the session's license flags on the server — so no unentitled
 * product data reaches the client — then hands them to the client shell that
 * owns scope, navigation and the command palette.
 *
 * This layout nests inside `/ade/layout.tsx`, which already provides the
 * authenticated shell, theme and top header, so it only adds Authoring chrome.
 */

import * as React from 'react';
import { Suspense } from 'react';
import { getCommercialAccessForSession } from '@lib/db/commercial-access';
import { AuthoringProvider } from './AuthoringContext';
import AuthoringShell from './components/AuthoringShell';

export const metadata = {
  title: 'Apiome: Authoring',
  description: 'Authoring workspace — content, portals, releases and insights.',
};

/**
 * Wrap every Authoring surface in the shared shell.
 *
 * @param props - The routed surface.
 */
export default async function AuthoringLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const { entitledFlags } = await getCommercialAccessForSession();

  return (
    // The shell reads scope from `useSearchParams`, which requires a Suspense
    // boundary so the rest of the page can still be statically rendered.
    <Suspense fallback={null}>
      <AuthoringProvider entitledFlags={entitledFlags}>
        <AuthoringShell>{children}</AuthoringShell>
      </AuthoringProvider>
    </Suspense>
  );
}
