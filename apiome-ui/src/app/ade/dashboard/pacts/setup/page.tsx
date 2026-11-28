import { SetupClient } from '@/app/components/ade/pactSetup';

/**
 * `/ade/dashboard/pacts/setup` — **Set up contracts** (PFX-8.20, #7317): six resumable sections from
 * an empty workspace to a yes-or-no before every deploy — pacticipants, environments, pipelines, the
 * first pact, the provider's side, gates. A thin server wrapper: the page reads its state through
 * `/api/pact/setup`.
 *
 * @returns The page.
 */
export default function PactSetupPage() {
  return <SetupClient />;
}
