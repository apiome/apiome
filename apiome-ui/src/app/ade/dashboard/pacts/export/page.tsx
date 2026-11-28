import { ExportPactClient } from '@/app/components/ade/pactExport';
import { readExportPrefill } from '@lib/pact-export';

/**
 * `/ade/dashboard/pacts/export` — **Export a contract** (PFX-8.18, #7315): a pact derived from a
 * project (`apiome pact export-consumer-contract`), a Postman collection (`apiome pact
 * export-postman`) or a published pact file. `?kind=`, `?provider=`, `?consumer=`, `?version=` and
 * `?project=` pre-fill the page; anything else is reported on it. A thin server wrapper that unwraps
 * the query.
 *
 * @param props - The query.
 * @returns The page.
 */
export default async function ExportPactPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  return <ExportPactClient prefill={readExportPrefill(await searchParams)} />;
}
