import { PublishPactClient } from '@/app/components/ade/pactPublish';
import { readPublishPrefill } from '@lib/pact-publish-page';

/**
 * `/ade/dashboard/pacts/publish` — **Publish a consumer pact** (PFX-8.3, #7300): upload, paste or
 * derive pacts, say whose version they are, check them, publish. `?version=`, `?branch=`, `?tag=`
 * (repeatable), `?buildUrl=`, `?source=` and, for a derive, `?project=`, `?consumer=`, `?provider=`
 * pre-fill the form — the import dialog's shortcut uses them; anything else is reported on the page.
 * A thin server wrapper that unwraps the query.
 *
 * @param props - The query.
 * @returns The page.
 */
export default async function PublishPactPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  return <PublishPactClient prefill={readPublishPrefill(await searchParams)} />;
}
