import { VerificationSettingsClient } from '@/app/components/ade/pactRemediation';
import { ContractsSettingsClient } from '@/app/components/ade/pactSettings';

/**
 * `/ade/dashboard/pacts/settings` — **Contracts settings** (PFX-8.14, #7311). Opens on **Clean-up**:
 * keep-rules, the live "if it ran now" preview and Recently deleted. `?tab=verification` is the
 * **Verification** tab: cadence, stale threshold, concurrent scheduled runs, re-publish request
 * window, and provider / pair overrides (PFX-6.2, #6954). Any other tab reads as Clean-up. A thin
 * server wrapper.
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
  return tab === 'verification' ? <VerificationSettingsClient /> : <ContractsSettingsClient />;
}
