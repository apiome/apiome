'use client';

/**
 * The tabs of one pacticipant — **Overview**, **Versions** (PFX-8.11, #7308) and **Settings**
 * (PFX-8.10, #7307).
 *
 * Authority: `docs/mockups/contracts/pacticipant.html` (the tab row under the header). Each tab is
 * a route, so the strip is `<nav>` + `<Link>` wearing the shared tab classes with
 * `aria-current="page"` on the page's own tab, like `ContractsTabs`. **Overview** keeps its
 * read-only versions panel; **Versions** manages them (tag, delete, restore).
 */

import * as React from 'react';
import Link from 'next/link';
import { GitCommitHorizontal, LayoutDashboard, Settings2 } from 'lucide-react';
import { TAB_LIST_CLASS, tabTriggerClass } from '@/app/components/ui/tabStyles';
import { pacticipantRoute } from '@lib/pact-pacticipants';
import { SETTINGS_SEGMENT } from '@lib/pact-pacticipant-settings';
import { VERSIONS_SEGMENT } from '@lib/pact-pacticipant-versions';

/** One pacticipant tab. */
export type PacticipantTabId = 'overview' | 'versions' | 'settings';

/**
 * The tab row.
 *
 * @param props - The pacticipant's handle and the page's tab.
 * @returns A navigation landmark with the three links.
 */
export function PacticipantSubTabs({ slug, active }: { slug: string; active: PacticipantTabId }) {
  const tabs = [
    {
      id: 'overview' as const,
      label: 'Overview',
      href: pacticipantRoute(slug),
      Icon: LayoutDashboard,
    },
    {
      id: 'versions' as const,
      label: 'Versions',
      href: `${pacticipantRoute(slug)}/${VERSIONS_SEGMENT}`,
      Icon: GitCommitHorizontal,
    },
    {
      id: 'settings' as const,
      label: 'Settings',
      href: `${pacticipantRoute(slug)}/${SETTINGS_SEGMENT}`,
      Icon: Settings2,
    },
  ];
  return (
    <nav aria-label="Pacticipant" className={TAB_LIST_CLASS} data-testid="ppx-tabs">
      {tabs.map(({ id, label, href, Icon }) => (
        <Link
          key={id}
          href={href}
          aria-current={id === active ? 'page' : undefined}
          className={tabTriggerClass({ active: id === active })}
          data-testid={`ppx-tab-${id}`}
        >
          <Icon className="ctx-tab__glyph" aria-hidden />
          {label}
        </Link>
      ))}
    </nav>
  );
}
