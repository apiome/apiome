import ProviderStatesClient from '@/app/components/ade/pactProviderStates/ProviderStatesClient';

/**
 * `/ade/dashboard/pacts/provider-states` — a provider's registered provider states and the
 * pre-run check of its pacts against them (PFX-3.3, #6933).
 *
 * @returns The page.
 */
export default function ProviderStatesPage() {
  return <ProviderStatesClient />;
}
