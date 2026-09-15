import ReviewPageClient from '@/app/components/ade/reviews/ReviewPageClient';
import { reviewTabFromQuery } from '@lib/review-page';

/**
 * `/ade/reviews/{id}` — one review of a draft version (COL-2.2, #4518).
 *
 * @param props.params - The review id.
 * @param props.searchParams - `?tab=changes|spec|discussion` opens that tab.
 * @returns The review page.
 */
export default async function ReviewPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { id } = await params;
  const query = await searchParams;
  return <ReviewPageClient reviewId={id} initialTab={reviewTabFromQuery(query.tab)} />;
}
