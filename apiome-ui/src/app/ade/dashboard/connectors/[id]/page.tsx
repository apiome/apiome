import ConnectorDetailClient from './ConnectorDetailClient';

/**
 * `/ade/dashboard/connectors/[id]` — one connector's Items, Runs and Settings (CDG-1.7, #5958).
 *
 * The `shadow` sibling is a static segment (the shadow-API report), which Next.js matches first.
 *
 * @param props.params - The route parameters.
 * @returns The connector page.
 */
export default async function ConnectorPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ConnectorDetailClient connectorId={id} />;
}
