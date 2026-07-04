/**
 * Client-side sort for the tenant Projects dashboard table (#2982).
 */

export type ProjectsDashboardSortColumn =
  | 'name'
  | 'description'
  | 'quality'
  | 'versions'
  | 'status'
  | 'creator'
  | 'created'
  | 'updated';

export type ProjectsDashboardSortDirection = 'asc' | 'desc';

/** Minimal project row shape used by the sorter. */
export type ProjectSortRow = {
  id: string;
  name: string;
  description: string;
  enabled: boolean;
  deleted_at: string | null;
  created_at: string;
  updated_at: string;
  creator_name: string;
  creator_email: string;
  metadata?: { summary?: string };
  slug?: string;
  versionsCount?: number;
};

function statusTier(p: ProjectSortRow): number {
  if (p.deleted_at) return 2;
  if (!p.enabled) return 1;
  return 0;
}

function compareStringsCaseInsensitive(a: string, b: string, dir: 1 | -1): number {
  const ac = a.trim().toLowerCase();
  const bc = b.trim().toLowerCase();
  if (ac === bc) return 0;
  return ac < bc ? -dir : dir;
}

/**
 * @param latestQualityByProjectId Latest overall import quality score per project, or null when unknown.
 */
export function compareProjectsDashboardRows(
  a: ProjectSortRow,
  b: ProjectSortRow,
  column: ProjectsDashboardSortColumn,
  direction: ProjectsDashboardSortDirection,
  latestQualityA: number | null,
  latestQualityB: number | null
): number {
  const dir: 1 | -1 = direction === 'asc' ? 1 : -1;

  switch (column) {
    case 'name': {
      const c = compareStringsCaseInsensitive(a.name, b.name, dir);
      if (c !== 0) return c;
      return compareStringsCaseInsensitive(a.slug ?? '', b.slug ?? '', dir);
    }
    case 'description': {
      const at = `${a.description ?? ''} ${a.metadata?.summary ?? ''}`.trim();
      const bt = `${b.description ?? ''} ${b.metadata?.summary ?? ''}`.trim();
      return compareStringsCaseInsensitive(at, bt, dir);
    }
    case 'quality': {
      const aNull = latestQualityA == null || Number.isNaN(latestQualityA);
      const bNull = latestQualityB == null || Number.isNaN(latestQualityB);
      if (aNull && bNull) return 0;
      if (aNull) return 1;
      if (bNull) return -1;
      if (latestQualityA === latestQualityB) return 0;
      return latestQualityA < latestQualityB ? -dir : dir;
    }
    case 'versions': {
      const va = a.versionsCount ?? 0;
      const vb = b.versionsCount ?? 0;
      if (va === vb) return 0;
      return va < vb ? -dir : dir;
    }
    case 'status': {
      const ta = statusTier(a);
      const tb = statusTier(b);
      if (ta !== tb) return ta < tb ? -dir : dir;
      return compareStringsCaseInsensitive(a.name, b.name, dir);
    }
    case 'creator': {
      const c = compareStringsCaseInsensitive(a.creator_name, b.creator_name, dir);
      if (c !== 0) return c;
      return compareStringsCaseInsensitive(a.creator_email, b.creator_email, dir);
    }
    case 'created': {
      const ta = Date.parse(a.created_at);
      const tb = Date.parse(b.created_at);
      const aOk = Number.isFinite(ta);
      const bOk = Number.isFinite(tb);
      if (!aOk && !bOk) return 0;
      if (!aOk) return 1;
      if (!bOk) return -1;
      if (ta === tb) return 0;
      return ta < tb ? -dir : dir;
    }
    case 'updated': {
      const ta = Date.parse(a.updated_at);
      const tb = Date.parse(b.updated_at);
      const aOk = Number.isFinite(ta);
      const bOk = Number.isFinite(tb);
      if (!aOk && !bOk) return 0;
      if (!aOk) return 1;
      if (!bOk) return -1;
      if (ta === tb) return 0;
      return ta < tb ? -dir : dir;
    }
    default:
      return 0;
  }
}

export function sortProjectsDashboardRows<T extends ProjectSortRow>(
  projects: readonly T[],
  column: ProjectsDashboardSortColumn | null,
  direction: ProjectsDashboardSortDirection,
  latestQualityByProjectId: Readonly<Record<string, number | null>>
): T[] {
  if (!column) return [...projects];
  return [...projects].sort((a, b) =>
    compareProjectsDashboardRows(
      a,
      b,
      column,
      direction,
      latestQualityByProjectId[a.id] ?? null,
      latestQualityByProjectId[b.id] ?? null
    )
  );
}
