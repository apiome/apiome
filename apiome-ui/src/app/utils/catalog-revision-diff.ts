/**
 * catalog-revision-diff (MFI-28.1, #4117) — the "compare read" behind the inline version diff in the
 * catalog detail Versions tab.
 *
 * The catalog reuses the **exact same** machinery the versions dashboard uses to diff two revisions:
 * it builds each revision's canonical OpenAPI spec JSON via the `buildOpenApiSpecJsonForVersion`
 * server action (see `apiome-ui/src/app/ade/dashboard/versions/page.tsx` `loadVersionSpec` →
 * `runCompareBetween`) and diffs the two pretty-printed strings. No new endpoints are introduced — the
 * two revisions are rendered side-by-side/unified in the shared Monaco diff viewer instead of routing
 * away to the dashboard.
 *
 * Isolating the server-action call here keeps `CatalogVersionsPanel` a thin view and gives its jest
 * tests a single module to mock (the action needs the server DB, so it never runs under jsdom).
 */

import { buildOpenApiSpecJsonForVersion } from '@lib/db/helper';
import { coerceProjectMetadataRecord } from '@lib/project-metadata';
import type { CatalogVersionRevision } from '@/app/utils/catalog-versions-timeline';

/**
 * Build one catalog revision's OpenAPI spec JSON exactly as the versions dashboard does. `itemId` is
 * the catalog item's (project's) id; `projectName` and `itemMetadata` feed the spec's `info` block so
 * both sides of the diff share identical, non-diverging metadata (and only real revision changes show).
 *
 * @returns The pretty-printed (2-space) OpenAPI spec JSON for the revision.
 */
export async function loadCatalogRevisionSpec(
  revision: CatalogVersionRevision,
  itemId: string,
  projectName: string | null,
  itemMetadata?: Record<string, unknown> | null,
): Promise<string> {
  return buildOpenApiSpecJsonForVersion(
    {
      id: revision.id,
      version_id: revision.version_id,
      description: revision.description ?? null,
      shortMessage: revision.shortMessage ?? null,
      project_id: itemId,
    },
    projectName,
    coerceProjectMetadataRecord(itemMetadata),
  );
}
