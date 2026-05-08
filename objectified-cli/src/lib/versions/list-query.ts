import type { VersionSchema } from "../client.js";

export type VersionListState = "draft" | "published" | "archived" | "frozen";

export type VersionsSortField = "version" | "published_at" | "created_at";

const STATE_WORDS: VersionListState[] = ["draft", "published", "archived", "frozen"];

/** Whether this revision counts as archived for list/filter semantics (matches projects show). */
export function versionIsArchived(v: VersionSchema): boolean {
  return v.lifecycle === "archived" || v.enabled === false;
}

/** States a version matches for `--state` filtering (OR semantics across selected states). */
export function versionStateMembership(v: VersionSchema): Set<VersionListState> {
  const s = new Set<VersionListState>();
  if (versionIsArchived(v)) {
    s.add("archived");
    return s;
  }
  const pub = Boolean(v.published);
  const frozen = pub && v.publishedImmutable === true;
  if (frozen) s.add("frozen");
  if (pub) s.add("published");
  else s.add("draft");
  return s;
}

export function parseVersionStateFilter(raw: string | undefined): Set<VersionListState> | undefined {
  if (raw === undefined || raw.trim() === "") return undefined;
  const parts = raw.split(",").map((p) => p.trim().toLowerCase());
  const out = new Set<VersionListState>();
  for (const p of parts) {
    if (p === "") continue;
    if (!STATE_WORDS.includes(p as VersionListState)) {
      throw new Error(
        `Invalid --state value "${p}". Expected one of: ${STATE_WORDS.join(", ")} (comma-separated).`,
      );
    }
    out.add(p as VersionListState);
  }
  if (out.size === 0) return undefined;
  return out;
}

export function parseVersionsSortField(raw: string | undefined): VersionsSortField {
  if (raw === undefined || raw.trim() === "") return "version";
  const v = raw.trim().toLowerCase();
  if (v === "version" || v === "published_at" || v === "created_at") return v;
  throw new Error(
    `Invalid --sort field "${raw}". Expected version, published_at, or created_at.`,
  );
}

function stripLeadingV(id: string): string {
  const t = id.trim();
  if (t.startsWith("v") || t.startsWith("V")) return t.slice(1);
  return t;
}

function splitPreRelease(core: string): [string, string] {
  const i = core.indexOf("-");
  if (i <= 0) return [core, ""];
  return [core.slice(0, i), core.slice(i + 1)];
}

function compareDotSegments(a: string, b: string): number {
  const pa = a.split(".");
  const pb = b.split(".");
  const n = Math.max(pa.length, pb.length);
  for (let i = 0; i < n; i++) {
    const sa = pa[i] ?? "";
    const sb = pb[i] ?? "";
    const na = parseInt(sa, 10);
    const nb = parseInt(sb, 10);
    const aNum = !Number.isNaN(na) && String(na) === sa;
    const bNum = !Number.isNaN(nb) && String(nb) === sb;
    if (aNum && bNum) {
      if (na !== nb) return na < nb ? -1 : 1;
    } else {
      const c = sa.localeCompare(sb);
      if (c !== 0) return c;
    }
  }
  return 0;
}

/** Ascending semver-ish order on `version_id` (v-prefix ignored). */
export function compareSemverVersionIdsAsc(a: string, b: string): number {
  const ca = stripLeadingV(a);
  const cb = stripLeadingV(b);
  const [coreA, preA] = splitPreRelease(ca);
  const [coreB, preB] = splitPreRelease(cb);
  const cmp = compareDotSegments(coreA, coreB);
  if (cmp !== 0) return cmp;
  if (preA === "" && preB !== "") return 1;
  if (preA !== "" && preB === "") return -1;
  if (preA === preB) return 0;
  return preA.localeCompare(preB);
}

function compareIsoNullable(a: string | null | undefined, b: string | null | undefined): number {
  const sa = a ?? "";
  const sb = b ?? "";
  if (sa === sb) return 0;
  if (sa === "") return -1;
  if (sb === "") return 1;
  if (sa < sb) return -1;
  if (sa > sb) return 1;
  return 0;
}

function sortComparator(
  field: VersionsSortField,
  descending: boolean,
): (x: VersionSchema, y: VersionSchema) => number {
  return (x, y) => {
    let cmp = 0;
    switch (field) {
      case "version":
        cmp = compareSemverVersionIdsAsc(x.version_id, y.version_id);
        break;
      case "published_at":
        cmp = compareIsoNullable(x.published_at, y.published_at);
        break;
      case "created_at":
        cmp = compareIsoNullable(x.created_at, y.created_at);
        break;
      default:
        cmp = 0;
    }
    if (cmp !== 0) return descending ? -cmp : cmp;
    const tie = compareSemverVersionIdsAsc(x.version_id, y.version_id);
    return descending ? -tie : tie;
  };
}

export function applyVersionsListPipeline(
  versions: VersionSchema[],
  opts: {
    stateFilter: Set<VersionListState> | undefined;
    sortField: VersionsSortField;
    /** When true, reverse the default direction (defaults are descending). */
    reverse: boolean;
  },
): VersionSchema[] {
  let rows = versions;
  const wantedStates = opts.stateFilter;
  if (wantedStates !== undefined && wantedStates.size > 0) {
    rows = rows.filter((v) => {
      const mem = versionStateMembership(v);
      for (const wanted of wantedStates) {
        if (mem.has(wanted)) return true;
      }
      return false;
    });
  }

  const descendingDefault = true;
  const descending = opts.reverse ? !descendingDefault : descendingDefault;
  const cmp = sortComparator(opts.sortField, descending);
  return [...rows].sort(cmp);
}
