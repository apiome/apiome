import * as React from 'react';

import UnreleasedFeatureGate from '@/app/components/shell/UnreleasedFeatureGate';

/**
 * Access audit is not released while the MVP focuses on Catalog and Projects
 * (`lib/feature-release.ts`): every page under this route answers with the
 * "not available yet" state until the feature id leaves the unreleased set.
 */
export default function Layout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <UnreleasedFeatureGate feature="audit">{children}</UnreleasedFeatureGate>;
}
