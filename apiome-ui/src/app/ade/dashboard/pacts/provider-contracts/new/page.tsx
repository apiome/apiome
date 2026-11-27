import { ProviderContractClient } from '@/app/components/ade/pactProviderContract';

/**
 * `/ade/dashboard/pacts/provider-contracts/new` — **Publish a provider contract** (PFX-8.6, #7303):
 * the contract (a project version, an upload or a URL), whose version it is, and graded evidence that
 * the provider honours it; the verdict per consumer before anything is saved. A thin server wrapper.
 *
 * @returns The page.
 */
export default function PublishProviderContractPage() {
  return <ProviderContractClient />;
}
