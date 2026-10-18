import TeamDetailClient from './TeamDetailClient';

/**
 * Workspace → Teams → one team — `/ade/dashboard/teams/[slug]` (CDG-2.4, #5963).
 *
 * @param props - The route's params.
 * @returns The team page.
 */
export default async function TeamPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  return <TeamDetailClient slug={slug} />;
}
