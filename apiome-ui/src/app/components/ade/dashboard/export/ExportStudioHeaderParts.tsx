'use client';

import { PanelsTopLeft } from 'lucide-react';
import type { PageBreadcrumbItem } from '../../../shell/PageHeader';

/** Where the workspace crumb goes: the dashboard home. */
export const STUDIO_HOME_ROUTE = '/ade/dashboard';

/**
 * The Export studio's breadcrumb (HIVE-11.11b): `<workspace> › Ship › Export studio`.
 *
 * The way back to Versions or the Catalog is the header's ghost action, not a crumb — a crumb is
 * where the page sits, never a navigation verb (DESIGN.md page-header rules).
 *
 * @param workspaceName The workspace's name; `Home` until it is known.
 * @returns The trail.
 */
export function exportStudioBreadcrumb(workspaceName: string | null): PageBreadcrumbItem[] {
  return [
    { label: workspaceName || 'Home', href: STUDIO_HOME_ROUTE },
    { label: 'Ship' },
    { label: 'Export studio' },
  ];
}

/** The studio's title, with its icon in the title row rather than stacked above it. */
export function ExportStudioTitle() {
  return (
    <span className="xstd-page-title">
      <PanelsTopLeft aria-hidden />
      Export studio
    </span>
  );
}
