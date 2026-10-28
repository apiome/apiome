/**
 * Export studio's source picker — the pure half (E1-2, #6218).
 *
 * Opened without a source (`/ade/dashboard/export/studio` from the rail or the command palette),
 * the studio's **Source** step lets the reader choose one: a **catalog item** (searched by name,
 * slug, format or protocol) or a **project version** (project, then version). Choosing writes the
 * resumable deep link (MFX-41.4) — the same URL every other entry point builds — and the studio
 * continues at **Target**.
 *
 * The Catalog/Projects boundary holds: catalog items (`publishable = false`) are listed only as
 * catalog items, and never among the projects (`isProjectPublishable`).
 */

import { isProjectPublishable } from '@/app/utils/catalog-publishable';
import { exportStudioHref } from '@/app/components/ade/dashboard/export/exportStudioLink';

/** A catalog item the picker lists. */
export interface PickerCatalogItem {
  id: string;
  name: string;
  slug?: string | null;
  sourceFormat?: string | null;
  protocol?: string | null;
  deleted_at?: string | null;
}

/** A project the picker lists. */
export interface PickerProject {
  id: string;
  name: string;
  slug?: string | null;
  description?: string | null;
  publishable?: boolean | null;
  deleted_at?: string | null;
}

/** A project version the picker lists. */
export interface PickerVersion {
  id: string;
  version_id: string;
  created_at?: string | null;
  published?: boolean | null;
  deleted_at?: string | null;
}

/** The picker's two kinds of source, in tab order. */
export const SOURCE_PICKER_KINDS = [
  { id: 'catalog', label: 'Catalog items' },
  { id: 'projects', label: 'Projects' },
] as const;

/** One of {@link SOURCE_PICKER_KINDS}. */
export type SourcePickerKind = (typeof SOURCE_PICKER_KINDS)[number]['id'];

/**
 * The live catalog items matching a search, by name.
 *
 * @param items The catalog list.
 * @param query What the reader typed; blank lists every live item.
 * @returns Live items whose name, slug, format or protocol contains every word of the query
 *     (case-insensitive), sorted by name.
 */
export function filterCatalogSources(items: readonly PickerCatalogItem[], query: string): PickerCatalogItem[] {
  const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  return items
    .filter((item) => !item.deleted_at)
    .filter((item) => {
      if (!words.length) return true;
      const haystack = [item.name, item.slug, item.sourceFormat, item.protocol].filter(Boolean).join(' ').toLowerCase();
      return words.every((word) => haystack.includes(word));
    })
    .sort((a, b) => a.name.localeCompare(b.name));
}

/**
 * The projects the picker offers: live, publishable (never a catalog item), by name.
 *
 * @param projects The projects list (the proxy already drops catalog items; this holds the line).
 * @returns The selectable projects.
 */
export function selectableProjects(projects: readonly PickerProject[]): PickerProject[] {
  return projects
    .filter((project) => !project.deleted_at && isProjectPublishable(project))
    .sort((a, b) => a.name.localeCompare(b.name));
}

/**
 * A project's live versions, newest first.
 *
 * @param versions The project's versions.
 * @returns The versions to offer.
 */
export function selectableVersions(versions: readonly PickerVersion[]): PickerVersion[] {
  return versions
    .filter((version) => !version.deleted_at)
    .sort((a, b) => String(b.created_at ?? '').localeCompare(String(a.created_at ?? '')));
}

/**
 * The deep link that opens the studio on a chosen catalog item, resuming at **Target**.
 *
 * @param item The chosen item.
 * @returns The studio URL (`origin=catalog`, so its back link returns to Catalog).
 */
export function catalogSourceHref(item: PickerCatalogItem): string {
  return exportStudioHref({
    artifact: item.id,
    label: item.name,
    origin: 'catalog',
    sourceFormat: item.sourceFormat ?? null,
    step: 'target',
  });
}

/**
 * The deep link that opens the studio on a chosen project version, resuming at **Target**.
 *
 * @param project The chosen project.
 * @param version The chosen version, or `null` for the project's latest.
 * @returns The studio URL (`origin=versions`).
 */
export function projectSourceHref(project: PickerProject, version: PickerVersion | null): string {
  return exportStudioHref({
    artifact: project.id,
    version: version?.id ?? null,
    label: version ? `${project.name} ${version.version_id}` : project.name,
    origin: 'versions',
    step: 'target',
  });
}
