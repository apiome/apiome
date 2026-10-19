import { Suspense } from 'react';
import GraphClient from './GraphClient';

/**
 * `/ade/dashboard/graph` — the tenant-wide dependency graph (CDG-3.4, #5969).
 *
 * A thin route shell: the page needs the session and reads `?entity=`, so the whole of it is a
 * client component.
 *
 * @returns The dependency graph page.
 */
export default function DependencyGraphPage() {
  return (
    <Suspense fallback={null}>
      <GraphClient />
    </Suspense>
  );
}
