import { notFound } from 'next/navigation';
import {
  getPublicVersionChangelog,
  getPublicVersionDetails,
  getPublicVersionsForProject,
} from '../../../../../../lib/db/helper';
import { buildMockBaseUrl } from '../../../../../../lib/mock/mockUrl';
import { VersionClient } from './VersionClient';
import { getReaderSession } from '../../../../portal/readerSession';
import { sanitizeSearchInput } from '../../../../utils/searchValidation';

export default async function VersionPage({
  params,
  searchParams,
}: {
  params: Promise<{ tenantSlug: string; projectSlug: string; versionSlug: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { tenantSlug, projectSlug, versionSlug } = await params;
  const { tab, find } = await searchParams;
  // BDX-1.3: `?find=` pre-fills the "find in this version" box (a search result deep link).
  const initialFind = sanitizeSearchInput(Array.isArray(find) ? (find[0] ?? '') : (find ?? ''));
  const [version, versions, changelog, readerSession] = await Promise.all([
    getPublicVersionDetails(tenantSlug, projectSlug, versionSlug),
    getPublicVersionsForProject(tenantSlug, projectSlug),
    getPublicVersionChangelog(tenantSlug, projectSlug, versionSlug),
    // COL-4.4: the Feedback tab needs to know whether a reader of this portal is signed in.
    getReaderSession(tenantSlug),
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
      readerEmail={readerSession?.reader.email ?? null}
      initialFind={initialFind}
      initialTab={tab === 'feedback' ? 'feedback' : tab === 'changes' ? 'changes' : 'specification'}
    />
  );
}
