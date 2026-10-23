import * as React from 'react';

import UnreleasedFeatureGate from '@/app/components/shell/UnreleasedFeatureGate';

/**
 * The schema registry is not released while RC6 focuses on Catalog and Projects
 * (`lib/feature-release.ts`, `docs/RC6_OOE.md`): every page under this route answers with
 * the "not available yet" state until the feature id leaves the unreleased set.
 */
export default function Layout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <UnreleasedFeatureGate feature="schema-registry">{children}</UnreleasedFeatureGate>;
}
