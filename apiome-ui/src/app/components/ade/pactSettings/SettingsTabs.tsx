/**
 * The tabs of `/ade/dashboard/pacts/settings` (PFX-8.14, #7311): **Clean-up** (the default) and
 * **Verification** (PFX-6.2's verification settings). Each tab is a link, so a tab can be bookmarked
 * and the browser's back button moves between them.
 */

import Link from 'next/link';
import { Eraser, CalendarClock } from 'lucide-react';
import { SETTINGS_ROUTE, VERIFICATION_TAB_ROUTE } from '@lib/pact-retention';

/** A tab of the settings page. */
export type SettingsTab = 'cleanup' | 'verification';

const TABS: ReadonlyArray<{ id: SettingsTab; label: string; href: string; Icon: typeof Eraser }> = [
  { id: 'cleanup', label: 'Clean-up', href: SETTINGS_ROUTE, Icon: Eraser },
  { id: 'verification', label: 'Verification', href: VERIFICATION_TAB_ROUTE, Icon: CalendarClock },
];

/**
 * The tab strip.
 *
 * @param props - The tab being shown.
 * @returns The strip.
 */
export function SettingsTabs({ active }: { active: SettingsTab }) {
  return (
    <nav className="pcx-tabs" aria-label="Settings" data-testid="pcx-tabs">
      {TABS.map(({ id, label, href, Icon }) => (
        <Link
          key={id}
          href={href}
          className="pcx-tabs__tab"
          aria-current={id === active ? 'page' : undefined}
          data-testid={`pcx-tab-${id}`}
        >
          <Icon aria-hidden className="pcx-tabs__icon" />
          {label}
        </Link>
      ))}
    </nav>
  );
}

export default SettingsTabs;
