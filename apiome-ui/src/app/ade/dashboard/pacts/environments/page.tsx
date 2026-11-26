import { EnvironmentsClient } from '@/app/components/ade/pactEnvironments';

/**
 * `/ade/dashboard/pacts/environments` — which version of each pacticipant runs in which
 * environment, and the environments themselves (PFX-5.7, #6951). A thin server wrapper.
 *
 * @returns The page.
 */
export default function PactEnvironmentsPage() {
  return <EnvironmentsClient />;
}
