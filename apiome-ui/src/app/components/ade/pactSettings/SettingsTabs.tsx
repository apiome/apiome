/**
 * The tabs of `/ade/dashboard/pacts/settings`, in the mockup's order: **Clean-up** (the default,
 * PFX-8.14), **Secrets**, **CI and commit statuses** (PFX-8.15), **Verification schedule** (PFX-6.2's
 * verification settings and what Apiome verifies on its own) and **Agents** (PFX-8.15). Each tab is a
 * link, so a tab can be bookmarked and the browser's back button moves between them.
 */

import Link from 'next/link';
import { Bot, CalendarClock, Eraser, GitPullRequest, LockKeyhole } from 'lucide-react';
import { AGENTS_TAB_ROUTE, CI_TAB_ROUTE, SECRETS_TAB_ROUTE } from '@lib/pact-contract-settings';
import { SETTINGS_ROUTE, VERIFICATION_TAB_ROUTE } from '@lib/pact-retention';

/** A tab of the settings page. */
export type SettingsTab = 'cleanup' | 'secrets' | 'ci' | 'verification' | 'agents';

/** Every tab id, for the page to read `?tab=` with. */
export const SETTINGS_TABS: readonly SettingsTab[] = ['cleanup', 'secrets', 'ci', 'verification', 'agents'];

const TABS: ReadonlyArray<{ id: SettingsTab; label: string; href: string; Icon: typeof Eraser }> = [
  { id: 'cleanup', label: 'Clean-up', href: SETTINGS_ROUTE, Icon: Eraser },
  { id: 'secrets', label: 'Secrets', href: SECRETS_TAB_ROUTE, Icon: LockKeyhole },
  { id: 'ci', label: 'CI and commit statuses', href: CI_TAB_ROUTE, Icon: GitPullRequest },
  { id: 'verification', label: 'Verification schedule', href: VERIFICATION_TAB_ROUTE, Icon: CalendarClock },
  { id: 'agents', label: 'Agents', href: AGENTS_TAB_ROUTE, Icon: Bot },
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
