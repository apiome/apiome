import { redirect } from 'next/navigation';

/**
 * Interim target for REPO-10.1 row navigation. REPO-10.2 will replace this with
 * the real per-scan report view (same URL shape).
 */
export default async function RepositoryScanReportDrillInPage({
  params,
}: {
  params: Promise<{ id: string; scanId: string }>;
}) {
  const { id, scanId } = await params;
  redirect(
    `/ade/dashboard/repositories/${id}?tab=specs&scanReportId=${encodeURIComponent(scanId)}`,
  );
}
