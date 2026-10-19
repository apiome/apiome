import GatewayConfigClient from './GatewayConfigClient';

/**
 * Bring in → Connectors → one environment — `/ade/dashboard/connectors/environments/[slug]`
 * (CDG-5.3, #5981).
 *
 * @param props - The route's params (a slug, or an id as a team page links it).
 * @returns The gateway config page.
 */
export default async function GatewayConfigPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  return <GatewayConfigClient slug={slug} />;
}
