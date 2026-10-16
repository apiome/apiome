import * as React from 'react';

import { isFeatureReleased, type UnreleasedFeatureId } from '@lib/feature-release';
import { PLATFORM_NAV_GROUPS } from '@lib/platform-nav';
import { GatedState } from '@/app/components/ui/EmptyState';
import PageHeader from '@/app/components/shell/PageHeader';
import { Page, PageBody } from '@/app/components/shell/pageChrome';

/** Where the reader is sent instead: the two areas the MVP is built around. */
const PROJECTS_HREF = '/ade/dashboard/projects';

export interface UnreleasedFeatureGateProps {
  /** The rail item id of the route this gate wraps. */
  feature: UnreleasedFeatureId;
  /** The feature's pages, rendered only once the feature is released. */
  children: React.ReactNode;
}

/**
 * The route half of the release gate (`lib/feature-release.ts`).
 *
 * The rail, palette and jumps already show an unreleased destination as disabled, but a
 * bookmark, a typed URL or an in-page link can still arrive. Each gated route's `layout.tsx`
 * wraps its pages in this, so every page under it — list, detail, sub-tabs — answers with
 * the same locked state and a way back to Projects rather than the half-finished feature.
 *
 * @param props See {@link UnreleasedFeatureGateProps}.
 * @returns The feature's pages when released, otherwise the "not available yet" page.
 */
export default function UnreleasedFeatureGate({ feature, children }: UnreleasedFeatureGateProps) {
  if (isFeatureReleased(feature)) return <>{children}</>;

  const group = PLATFORM_NAV_GROUPS.find((candidate) =>
    candidate.items.some((navItem) => navItem.id === feature)
  );
  const label = group?.items.find((navItem) => navItem.id === feature)?.label ?? 'This page';

  return (
    <Page>
      <PageHeader
        breadcrumb={[
          { label: 'Home', href: '/ade/dashboard' },
          ...(group?.label ? [{ label: group.label }] : []),
          { label },
        ]}
        title={label}
      />
      <PageBody>
        <GatedState
          data-testid="unreleased-feature-gate"
          title="Not available yet"
          description={`${label} opens once Catalog and Projects are ready.`}
          href={PROJECTS_HREF}
          actionLabel="Go to Projects"
        />
      </PageBody>
    </Page>
  );
}
