import AgentDetailClient from './AgentDetailClient';

/**
 * Bring in → Catalog → one agent — `/ade/dashboard/catalog/agents/[slug]` (CDG-5.2, #5980).
 *
 * @param props - The route's params (a slug, or an id as a team page links it).
 * @returns The agent page.
 */
export default async function AgentPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  return <AgentDetailClient slug={slug} />;
}
