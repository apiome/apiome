import { VerificationSettingsClient } from '@/app/components/ade/pactRemediation';
import { ContractsSettingsClient } from '@/app/components/ade/pactSettings';
import type { ContractsSettingsTab } from '@/app/components/ade/pactSettings/ContractsSettingsClient';

/** The `?tab=` values the PFX-8.15 tabs answer to; anything else reads as Clean-up. */
const OWN_TABS: readonly ContractsSettingsTab[] = ['secrets', 'ci', 'agents'];

/**
 * `/ade/dashboard/pacts/settings` — **Contracts settings** (PFX-8.14, #7311). Opens on **Clean-up**:
 * keep-rules, the live "if it ran now" preview and Recently deleted. `?tab=verification` is the
 * **Verification** tab: cadence, stale threshold, concurrent scheduled runs, re-publish request
 * window, and provider / pair overrides (PFX-6.2, #6954). `?tab=secrets`, `?tab=ci` and `?tab=agents` are
 * Secrets, CI and commit statuses, and Agents (PFX-8.15, #7312). Any other tab reads as Clean-up. A
 * thin server wrapper.
 *
 * @param props - The route's search parameters.
 * @returns The page.
 */
export default async function PactSettingsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { tab } = await searchParams;
  if (tab === 'verification') return <VerificationSettingsClient />;
  const own = OWN_TABS.find((candidate) => candidate === tab);
  return <ContractsSettingsClient tab={own ?? 'cleanup'} />;
}
