import { RepublishRequestsClient } from '@/app/components/ade/pactRemediation';
import { REQUEST_STATES } from '@lib/pact-remediation';

/**
 * `/ade/dashboard/pacts/republish-requests` — the workspace's re-publish requests, newest first
 * (PFX-6.2, #6954). `?state=` narrows them: `open` (the default), `all`, or one state; anything
 * else reads as `open`. A thin server wrapper that unwraps the query.
 *
 * @param props - The query.
 * @returns The page.
 */
export default async function RepublishRequestsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const query = await searchParams;
  const raw = typeof query.state === 'string' ? query.state : 'open';
  const state = raw === 'all' || (REQUEST_STATES as readonly string[]).includes(raw) ? raw : 'open';
  return <RepublishRequestsClient state={state} />;
}
