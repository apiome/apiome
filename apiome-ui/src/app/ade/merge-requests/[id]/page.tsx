import MergeRequestPageClient from '@/app/components/ade/merge-requests/MergeRequestPageClient';
import { mergeRequestTabFromQuery } from '@lib/merge-requests';

/**
 * `/ade/merge-requests/{id}` — one merge request of a draft branch (COL-4.3, #4527).
 *
 * @param props.params - The merge request id.
 * @param props.searchParams - `?tab=changes|conflicts|review` opens that tab.
 * @returns The merge request page.
 */
export default async function MergeRequestPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { id } = await params;
  const query = await searchParams;
  return <MergeRequestPageClient mergeRequestId={id} initialTab={mergeRequestTabFromQuery(query.tab)} />;
}
