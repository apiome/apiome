import { HealthClient } from '@/app/components/ade/pactHealth';
import { HEALTH_STATES, readWindow } from '@lib/pact-health';

/**
 * `/ade/dashboard/pacts/health` — every consumer ↔ provider pair's contract health, worst first, with
 * the window's pass rate, flakiness and duration (PFX-6.3, #6955). `?window=` (`7d`, `30d`, `90d`;
 * anything else reads as `30d`) and `?state=` (one state; anything else reads as every state) narrow
 * it. A thin server wrapper that unwraps the query.
 *
 * @param props - The query.
 * @returns The page.
 */
export default async function PactHealthPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const query = await searchParams;
  const window = readWindow(typeof query.window === 'string' ? query.window : null);
  const rawState = typeof query.state === 'string' ? query.state : '';
  const state = (HEALTH_STATES as readonly string[]).includes(rawState) ? rawState : null;
  return <HealthClient window={window} state={state} />;
}
