import ComponentDetailClient from './ComponentDetailClient';

/**
 * Bring in → Catalog → one component — `/ade/dashboard/catalog/components/[slug]` (CDG-5.5, #5983).
 *
 * @param props - The route's params (a slug, or an id as a team page links it).
 * @returns The page.
 */
export default async function ComponentPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  return <ComponentDetailClient slug={slug} />;
}
