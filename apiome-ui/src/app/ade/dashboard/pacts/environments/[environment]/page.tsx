import { EnvironmentDetailClient } from '@/app/components/ade/pactEnvironments';
import { environmentFromSegment } from '@lib/pact-environments';

/**
 * `/ade/dashboard/pacts/environments/{name}` — one environment: what runs there now, its
 * deployment history and a link to the deploy simulator (PFX-5.7, #6951). A thin server wrapper
 * that unwraps the name.
 *
 * @param props - The route params.
 * @returns The page.
 */
export default async function PactEnvironmentPage({ params }: { params: Promise<{ environment: string }> }) {
  const { environment } = await params;
  return <EnvironmentDetailClient name={environmentFromSegment(environment)} />;
}
