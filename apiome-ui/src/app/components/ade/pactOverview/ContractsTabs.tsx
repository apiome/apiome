'use client';

/**
 * The **Contracts** tab row (PFX-8.1, #7298) — drawn in the header of every Contracts page.
 *
 * Authority: `docs/mockups/contracts/overview.html` (`nav.tabs` under the title). The area used to
 * be a set of pages reached from a row of buttons on the Pacticipants header; the tabs replace those
 * buttons, so a header keeps one primary and at most two secondary actions (DESIGN.md §5.3).
 *
 * Each tab is a route, so the strip is `<nav>` + `<Link>` wearing the shared tab classes
 * (`ui/tabStyles`), with `aria-current="page"` on the page's own tab — the same pattern as
 * `RepositoriesSubNav`. The page says which tab it belongs to (`active`), because several pages
 * nest under another tab's route (a pacticipant's pact is under **Pacticipants**, a re-publish
 * request under **Health**) and fixture renders have no router.
 */

import * as React from 'react';
import Link from 'next/link';
import {
  Activity,
  LayoutDashboard,
  Rocket,
  ServerCog,
  Settings2,
  Table2,
  Users,
  Webhook,
} from 'lucide-react';
import { TAB_LIST_CLASS, tabTriggerClass } from '@/app/components/ui/tabStyles';
import { CONTRACTS_TABS, type ContractsTabId } from '@lib/pact-overview';

/** The glyph each tab draws, matching the mockup's lucide names. */
const TAB_ICON: Readonly<
  Record<ContractsTabId, React.ComponentType<{ className?: string; 'aria-hidden'?: boolean }>>
> = {
  overview: LayoutDashboard,
  pacticipants: Users,
  matrix: Table2,
  'can-i-deploy': Rocket,
  environments: ServerCog,
  webhooks: Webhook,
  health: Activity,
  settings: Settings2,
};

/** Props for {@link ContractsTabs}. */
export interface ContractsTabsProps {
  /** The tab the page belongs to. */
  active: ContractsTabId;
}

/**
 * The tab row.
 *
 * @param props - The page's tab.
 * @returns A navigation landmark holding one link per Contracts page.
 */
export function ContractsTabs({ active }: ContractsTabsProps) {
  return (
    <nav aria-label="Contracts" className={TAB_LIST_CLASS} data-testid="contracts-tabs">
      {CONTRACTS_TABS.map((tab) => {
        const Icon = TAB_ICON[tab.id];
        const isActive = tab.id === active;
        return (
          <Link
            key={tab.id}
            href={tab.href}
            title={tab.description}
            aria-current={isActive ? 'page' : undefined}
            data-testid={`contracts-tab-${tab.id}`}
            className={tabTriggerClass({ active: isActive })}
          >
            <Icon className="ctx-tab__glyph" aria-hidden />
            {tab.label}
          </Link>
        );
      })}
    </nav>
  );
}

export default ContractsTabs;
