import { notFound } from 'next/navigation';
import { getPublicMcpEndpointDetail } from '../../../../../lib/db/helper';
import { McpEndpointDetailClient } from './McpEndpointDetailClient';

export const dynamic = 'force-dynamic';

export default async function McpEndpointDetailPage({
  params,
}: {
  params: Promise<{ tenantSlug: string; endpointSlug: string }>;
}) {
  const { tenantSlug, endpointSlug } = await params;
  const detail = await getPublicMcpEndpointDetail(tenantSlug, endpointSlug);

  if (!detail) {
    notFound();
  }

  // Browser-reachable REST base (ends in /v1); the badge helper reduces it to the origin the public
  // /mcp/badge/* route is served from.
  const restApiBaseUrl = process.env.NEXT_PUBLIC_REST_API_BASE_URL || 'http://localhost:8000/v1';

  return (
    <McpEndpointDetailClient
      detail={detail}
      tenantSlug={tenantSlug}
      endpointSlug={endpointSlug}
      restApiBaseUrl={restApiBaseUrl}
    />
  );
}
