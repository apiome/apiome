import { notFound } from 'next/navigation';
import {
  getPublicVersionChangelog,
  getPublicVersionDetails,
  getPublicVersionsForProject,
} from '../../../../../../lib/db/helper';
import { buildMockBaseUrl } from '../../../../../../lib/mock/mockUrl';
import { VersionClient } from './VersionClient';

export default async function VersionPage({
  params,
}: {
  params: Promise<{ tenantSlug: string; projectSlug: string; versionSlug: string }>;
}) {
  const { tenantSlug, projectSlug, versionSlug } = await params;
  const [version, versions, changelog] = await Promise.all([
    getPublicVersionDetails(tenantSlug, projectSlug, versionSlug),
    getPublicVersionsForProject(tenantSlug, projectSlug),
    getPublicVersionChangelog(tenantSlug, projectSlug, versionSlug),
  ]);

  if (!version) {
    notFound();
  }

  const restApiBaseUrl =
    process.env.NEXT_PUBLIC_REST_API_BASE_URL || 'http://localhost:8000/v1';

  // Public mock base URL for this version — only when its mock is enabled (SIM-2.3, #4444).
  // Rendered server-side into props, mirroring the Control Panel's use of the same variable.
  const mockPublicBaseUrl =
    process.env.APIOME_MOCK_PUBLIC_BASE_URL || 'http://localhost:8775';
  const mockBaseUrl = version.mock_enabled
    ? buildMockBaseUrl(mockPublicBaseUrl, tenantSlug, projectSlug, version.version_id)
    : null;

  return (
    <VersionClient
      version={version}
      versions={versions}
      changelog={changelog}
      tenantSlug={tenantSlug}
      projectSlug={projectSlug}
      versionSlug={versionSlug}
      restApiBaseUrl={restApiBaseUrl}
      mockBaseUrl={mockBaseUrl}
    />
  );
}
