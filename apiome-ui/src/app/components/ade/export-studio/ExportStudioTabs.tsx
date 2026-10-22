'use client';

/**
 * Export studio's tab strip (HIVE-12.2, #5609): **Export** · **SDK & branding**.
 *
 * A route strip on the shared tab classes, like `RepositoriesSubNav`: each tab is a link with
 * `aria-current="page"`, because each is an address (`?tab=sdk`) a reader can bookmark or
 * share. The rules — which tab a URL selects and how a link keeps the rest of the query — are
 * `exportStudioTabs.ts`.
 *
 * A tab whose feature is unreleased (`lib/feature-release.ts`) is left out, and a strip with
 * only one tab left is not drawn at all.
 */

import * as React from 'react';
import Link from 'next/link';
import { usePathname, useSearchParams } from 'next/navigation';
import { Package, PanelsTopLeft, type LucideIcon } from 'lucide-react';

import { isFeatureReleased } from '@lib/feature-release';
import { TAB_LIST_CLASS, tabTriggerClass } from '@/app/components/ui/tabStyles';

import {
  EXPORT_STUDIO_TABS,
  exportStudioTabFromParams,
  exportStudioTabHref,
  type ExportStudioTabId,
} from './exportStudioTabs';

/** The route the strip links within, when `usePathname()` has not resolved. */
const EXPORT_STUDIO_PATH = '/ade/dashboard/export/studio';

/** The glyph each tab leads with. */
const TAB_ICON: Readonly<Record<ExportStudioTabId, LucideIcon>> = {
  export: PanelsTopLeft,
  sdk: Package,
};

/** Props for {@link ExportStudioTabs}. */
export interface ExportStudioTabsProps {
  /** Force the active tab instead of reading `?tab=` (for the gallery and tests). */
  active?: ExportStudioTabId;
}

/**
 * Render the strip. See {@link ExportStudioTabsProps}.
 *
 * @returns A navigation landmark with one link per released tab, or nothing when fewer than
 *   two tabs are released.
 */
export function ExportStudioTabs({ active }: ExportStudioTabsProps) {
  const pathname = usePathname() || EXPORT_STUDIO_PATH;
  const searchParams = useSearchParams();
  const current = active ?? exportStudioTabFromParams(searchParams);
  const tabs = EXPORT_STUDIO_TABS.filter((tab) => isFeatureReleased(tab.feature));
  if (tabs.length < 2) return null;

  // `URLSearchParams` from Next is read-only; copy it so the href helper can build on it.
  const params = new URLSearchParams(searchParams?.toString() ?? '');

  return (
    <nav aria-label="Export studio sections" className={TAB_LIST_CLASS} data-testid="export-studio-tabs">
      {tabs.map((tab) => {
        const Icon = TAB_ICON[tab.id];
        const isActive = tab.id === current;
        return (
          <Link
            key={tab.id}
            href={exportStudioTabHref(pathname, params, tab.id)}
            aria-current={isActive ? 'page' : undefined}
            data-testid={`export-studio-tab-${tab.id}`}
            className={tabTriggerClass({ active: isActive })}
          >
            <Icon className="xstd-tab__glyph" aria-hidden />
            {tab.label}
          </Link>
        );
      })}
    </nav>
  );
}

export default ExportStudioTabs;
