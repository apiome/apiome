import PactComparisonsClient from '@/app/components/ade/pactComparisons/PactComparisonsClient';

/**
 * `/ade/dashboard/pacts/comparisons` — the workspace's bi-directional comparisons and their
 * fidelity reports (PFX-2.5, #6929).
 *
 * @returns The page.
 */
export default function PactComparisonsPage() {
  return <PactComparisonsClient />;
}
