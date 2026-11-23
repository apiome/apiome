'use client';

import { useEffect } from 'react';
import { ErrorPanel } from './components/ErrorPanel';

/**
 * The error page for any route without its own (DBP-1.16, #7199). A page whose data could not be
 * read — a statement cancelled by the database statement timeout, for example — renders this
 * instead of leaving the request hanging or showing an empty page as if nothing were published.
 */
export default function RouteError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    console.error('[browse] route error:', error.digest ?? error.message);
  }, [error]);

  return (
    <ErrorPanel
      title="This page could not be loaded."
      body="The catalog took too long to answer or is temporarily unavailable. Try again in a moment."
      onRetry={reset}
    />
  );
}
