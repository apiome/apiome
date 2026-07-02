/**
 * Client-side sort for the project Versions timeline table (#2983).
 */

export type VersionsDashboardSortColumn =
  | 'version'
  | 'revision'
  | 'status'
  | 'creator'
  | 'created';

export type VersionsDashboardSortDirection = 'asc' | 'desc';

/** Minimal revision row shape used by the sorter. */
export type VersionSortRow = {
  id: string;
  version_id: string;
  shortMessage: string | null;
  changelog: string | null;
  message?: string | null;
  published: boolean;
  enabled: boolean;
  lifecycle?: string;
  creator_name: string;
  creator_email: string;
  created_at: string;
};

function compareStringsCaseInsensitive(a: string, b: string, dir: 1 | -1): number {
  const ac = a.trim().toLowerCase();
  const bc = b.trim().toLowerCase();
  if (ac === bc) return 0;
  return ac < bc ? -dir : dir;
}

function revisionSortText(v: VersionSortRow): string {
  return [v.shortMessage, v.message, v.changelog]
    .filter((x): x is string => typeof x === 'string' && x.length > 0)
    .join('\n')
    .trim();
}

/** Draft+enabled=0 … published+disabled=3 for a stable status ordering. */
function statusComposite(v: VersionSortRow): number {
  let k = 0;
  if (v.published) k += 2;
  if (!v.enabled) k += 1;
  return k * 10 + lifecycleRank(v.lifecycle);
}

function lifecycleRank(lc: string | undefined): number {
  const v = (lc ?? 'stable').toLowerCase();
  if (v === 'beta') return 1;
  if (v === 'deprecated') return 2;
  if (v === 'archived') return 3;
  return 0;
}

function compareVersionIds(a: string, b: string, dir: 1 | -1): number {
  const ac = a.trim();
  const bc = b.trim();
  if (ac === bc) return 0;
  const c = ac.localeCompare(bc, undefined, { numeric: true, sensitivity: 'base' });
  if (c === 0) return 0;
  return c < 0 ? -dir : dir;
}

export function compareVersionsDashboardRows(
  a: VersionSortRow,
  b: VersionSortRow,
  column: VersionsDashboardSortColumn,
  direction: VersionsDashboardSortDirection
): number {
  const dir: 1 | -1 = direction === 'asc' ? 1 : -1;

  switch (column) {
    case 'version': {
      const c = compareVersionIds(a.version_id, b.version_id, dir);
      if (c !== 0) return c;
      return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
    }
    case 'revision': {
      const c = compareStringsCaseInsensitive(revisionSortText(a), revisionSortText(b), dir);
      if (c !== 0) return c;
      return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
    }
    case 'status': {
      const ka = statusComposite(a);
      const kb = statusComposite(b);
      if (ka !== kb) return ka < kb ? -dir : dir;
      return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
    }
    case 'creator': {
      const c = compareStringsCaseInsensitive(a.creator_name ?? '', b.creator_name ?? '', dir);
      if (c !== 0) return c;
      const e = compareStringsCaseInsensitive(a.creator_email ?? '', b.creator_email ?? '', dir);
      if (e !== 0) return e;
      return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
    }
    case 'created': {
      const ta = Date.parse(a.created_at);
      const tb = Date.parse(b.created_at);
      const aOk = Number.isFinite(ta);
      const bOk = Number.isFinite(tb);
      if (!aOk && !bOk) return a.id.localeCompare(b.id);
      if (!aOk) return 1;
      if (!bOk) return -1;
      if (ta !== tb) return ta < tb ? -dir : dir;
      return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
    }
    default:
      return 0;
  }
}

export function sortVersionsDashboardRows<T extends VersionSortRow>(
  rows: readonly T[],
  column: VersionsDashboardSortColumn | null,
  direction: VersionsDashboardSortDirection
): T[] {
  if (!column) return [...rows];
  return [...rows].sort((a, b) => compareVersionsDashboardRows(a, b, column, direction));
}
