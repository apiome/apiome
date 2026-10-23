'use client';

/**
 * The §Coming next specimens of the gallery (HIVE-12.5, #5612).
 *
 * The production counterpart of callout 3 of `docs/mockups/proposals/launcher-focused.html`:
 * the launcher's line (host product, Community, Marketplace, and a What's new link that opens
 * a dialog), the same line linking to a page instead, and the bare line with no link. There is
 * no "disabled" specimen because the component has no disabled state.
 */

import * as React from 'react';

import { ComingNext, type ComingNextItem } from '@/app/components/ui';
import { SpecimenLabel } from './GallerySection';

/** The launcher's line on an install with the Developer Suite listed but unshipped. */
const LAUNCHER_ITEMS: readonly ComingNextItem[] = [
  { id: 'developer-suite', label: 'Developer Suite' },
  { id: 'community', label: 'Community' },
  { id: 'marketplace', label: 'Marketplace' },
];

/** What HIVE-11.9 puts on Members in place of the SSO / SCIM cards. */
const MEMBERS_ITEMS: readonly ComingNextItem[] = [
  { id: 'sso', label: 'Single sign-on' },
  { id: 'scim', label: 'SCIM provisioning' },
];

/**
 * The specimens.
 *
 * @returns Three labelled lines.
 */
export function ComingNextShowcase() {
  const [followed, setFollowed] = React.useState(0);

  return (
    <div className="space-y-6">
      <div>
        <SpecimenLabel>Launcher — follow opens What&apos;s new in place</SpecimenLabel>
        <ComingNext items={LAUNCHER_ITEMS} onFollow={() => setFollowed((n) => n + 1)} />
        <p className="mt-2 text-xs text-fg-muted" aria-live="polite">
          {followed === 0 ? 'Not followed yet.' : `Followed ${followed}×.`}
        </p>
      </div>
      <div>
        <SpecimenLabel>A page without the dialog — follow is a link</SpecimenLabel>
        <ComingNext items={MEMBERS_ITEMS} followHref="/ade/dashboard/help" />
      </div>
      <div>
        <SpecimenLabel>No follow action</SpecimenLabel>
        <ComingNext items={MEMBERS_ITEMS.slice(0, 1)} />
      </div>
    </div>
  );
}

export default ComingNextShowcase;
