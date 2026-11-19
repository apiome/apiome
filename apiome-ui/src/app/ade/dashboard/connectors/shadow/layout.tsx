import * as React from 'react';

import UnreleasedFeatureGate from '@/app/components/shell/UnreleasedFeatureGate';

/**
 * The Shadow APIs report is held back while RC8 focuses on Catalog and Projects (`lib/feature-release.ts`):
 * every page under this route answers with the "not available yet" state until the feature id
 * leaves the unreleased set, which happens when its Enable project is complete.
 */
export default function Layout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <UnreleasedFeatureGate feature="shadow-apis">{children}</UnreleasedFeatureGate>;
}
