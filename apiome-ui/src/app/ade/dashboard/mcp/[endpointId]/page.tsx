import McpEndpointDetailClient from "./McpEndpointDetailClient";

export const dynamic = "force-dynamic";

export default async function McpEndpointDetailPage({
  params,
}: {
  params: Promise<{ endpointId: string }>;
}) {
  const { endpointId } = await params;
  return <McpEndpointDetailClient endpointId={endpointId} />;
}
