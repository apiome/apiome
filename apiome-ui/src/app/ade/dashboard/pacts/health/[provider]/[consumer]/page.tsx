import { PairHealthClient } from '@/app/components/ade/pactHealth';
import { readWindow } from '@lib/pact-health';

/**
 * `/ade/dashboard/pacts/health/{provider}/{consumer}` — one pair's contract health: every fused
 * signal with why, and its pass-rate, flakiness and duration trends over the window (PFX-6.3,
 * #6955). `?window=` (`7d`, `30d`, `90d`; anything else reads as `30d`). A thin server wrapper that
 * unwraps the handles and the query.
 *
 * @param props - The route params and the query.
 * @returns The page.
 */
export default async function PactPairHealthPage({
  params,
  searchParams,
}: {
  params: Promise<{ provider: string; consumer: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { provider, consumer } = await params;
  const query = await searchParams;
  const window = readWindow(typeof query.window === 'string' ? query.window : null);
  return <PairHealthClient provider={provider} consumer={consumer} window={window} />;
}
