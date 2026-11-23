'use client';

import { useEffect } from 'react';
import { ErrorPanel } from '../components/ErrorPanel';

/**
 * The search page's error page (DBP-1.16, #7199). A search that runs past the database statement
 * timeout is cancelled and lands here, so the visitor is told the search did not finish instead of
 * being shown "no results".
 */
export default function SearchError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    console.error('[browse] search error:', error.digest ?? error.message);
  }, [error]);

  return (
    <ErrorPanel
      title="This search did not finish."
      body="It took too long and was stopped. Try again, or narrow it: add a word, or a filter such as org:, project: or type:."
      onRetry={reset}
    />
  );
}
