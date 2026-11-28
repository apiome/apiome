'use client';

/**
 * **Contracts settings** — `/ade/dashboard/pacts/settings` (PFX-8.14, #7311), built to
 * `docs/mockups/contracts/settings.html`. The page opens on **Clean-up** (`CleanupTab`); the
 * **Verification** tab (`?tab=verification`) is PFX-6.2's verification settings. No primary action
 * in the header: each tab owns its one primary (mockup Notes, §1.2).
 */

import PageHeader from '@/app/components/shell/PageHeader';
import { Page, PageBody } from '@/app/components/shell/pageChrome';
import { CONTRACTS_ROUTE } from '@lib/pact-overview';
import { SETTINGS_DESCRIPTION, SETTINGS_TITLE } from '@lib/pact-retention';
import { ContractsTabs } from '../pactOverview/ContractsTabs';
import CleanupTab from './CleanupTab';
import { SettingsTabs } from './SettingsTabs';


/**
 * The page on its Clean-up tab.
 *
 * @returns The page.
 */
export default function ContractsSettingsClient() {
  return (
    <Page>
      <PageHeader
        tabs={<ContractsTabs active="settings" />}
        title={SETTINGS_TITLE}
        breadcrumb={[{ label: 'Home', href: '/ade/dashboard' }, { label: 'Contracts', href: CONTRACTS_ROUTE }, { label: 'Settings' }]}
        description={SETTINGS_DESCRIPTION}
      />
      <PageBody>
        <SettingsTabs active="cleanup" />
        <CleanupTab />
      </PageBody>
    </Page>
  );
}
