'use client';

/**
 * **Contracts settings** — `/ade/dashboard/pacts/settings` (PFX-8.14, #7311; PFX-8.15, #7312), built to
 * `docs/mockups/contracts/settings.html`. The page opens on **Clean-up** (`CleanupTab`); `?tab=secrets`,
 * `?tab=ci` and `?tab=agents` are the PFX-8.15 tabs; the **Verification schedule** tab
 * (`?tab=verification`) is PFX-6.2's `VerificationSettingsClient`. No primary action in the header:
 * each tab owns its one primary (mockup Notes, §1.2).
 */

import PageHeader from '@/app/components/shell/PageHeader';
import { Page, PageBody } from '@/app/components/shell/pageChrome';
import { CONTRACTS_ROUTE } from '@lib/pact-overview';
import { SETTINGS_DESCRIPTION, SETTINGS_TITLE } from '@lib/pact-retention';
import { ContractsTabs } from '../pactOverview/ContractsTabs';
import AgentsTab from './AgentsTab';
import CiTab from './CiTab';
import CleanupTab from './CleanupTab';
import SecretsTab from './SecretsTab';
import { SettingsTabs, type SettingsTab } from './SettingsTabs';

/** The tabs this component draws (Verification schedule is its own client). */
export type ContractsSettingsTab = Exclude<SettingsTab, 'verification'>;


/**
 * The page on one of its tabs.
 *
 * @param props - The tab to show (Clean-up when omitted).
 * @returns The page.
 */
export default function ContractsSettingsClient({ tab = 'cleanup' }: { tab?: ContractsSettingsTab }) {
  return (
    <Page>
      <PageHeader
        tabs={<ContractsTabs active="settings" />}
        title={SETTINGS_TITLE}
        breadcrumb={[{ label: 'Home', href: '/ade/dashboard' }, { label: 'Contracts', href: CONTRACTS_ROUTE }, { label: 'Settings' }]}
        description={SETTINGS_DESCRIPTION}
      />
      <PageBody>
        <SettingsTabs active={tab} />
        {tab === 'secrets' ? <SecretsTab /> : tab === 'ci' ? <CiTab /> : tab === 'agents' ? <AgentsTab /> : <CleanupTab />}
      </PageBody>
    </Page>
  );
}
