import ModelDetailClient from './ModelDetailClient';

/**
 * Bring in → Catalog → one model — `/ade/dashboard/catalog/models/[slug]` (CDG-5.2, #5980).
 *
 * @param props - The route's params (a slug, or an id as a team page links it).
 * @returns The model page.
 */
export default async function ModelPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  return <ModelDetailClient slug={slug} />;
}
