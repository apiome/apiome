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

  return <McpEndpointDetailClient detail={detail} />;
}
