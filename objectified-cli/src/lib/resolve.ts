import leven from "leven";

import type { ObjectifiedApi, ProjectSchema } from "./client.js";
import { readCompletionCache } from "./completion/cache.js";
import { ObjectifiedCliError } from "./errors.js";
import { EXIT_CODES } from "./exit-codes.js";

/** Lowercase UUID string with hyphens (36 chars), per #3203 — ambiguous slug-as-UUID resolves as UUID first. */
const PROJECT_UUID_REF_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

export function normalizeProjectRef(raw: string): string {
  return raw.trim();
}

export function projectRefLooksLikeUuid(ref: string): boolean {
  return PROJECT_UUID_REF_RE.test(ref.toLowerCase());
}

/** Same cache key shape as completion candidates (`baseUrl|profile|tenantSlug`). */
export function completionProfileCacheKey(parts: {
  baseUrl: string;
  profile: string;
  tenantSlug: string | undefined;
}): string {
  return `${parts.baseUrl}|${parts.profile}|${parts.tenantSlug ?? ""}`;
}

export async function loadCachedProjectSlugs(
  profileCacheKey: string,
  tenantSlug: string,
): Promise<string[]> {
  const rows = await readCompletionCache(profileCacheKey, ["projects-map", tenantSlug]);
  if (rows === undefined) return [];
  const slugs: string[] = [];
  for (const row of rows) {
    const tab = row.indexOf("\t");
    if (tab <= 0) continue;
    const slug = row.slice(0, tab);
    if (slug !== "") slugs.push(slug);
  }
  return slugs;
}

const DID_YOU_MEAN_MAX = 3;
const DID_YOU_MEAN_MAX_DISTANCE = 8;

/** Closest slugs by Levenshtein distance (used after cache miss / 404). */
export function didYouMeanSlugs(ref: string, slugs: string[]): string[] {
  const needle = ref.trim().toLowerCase();
  if (needle === "") return [];
  const uniq = [...new Set(slugs.map((s) => s.trim()).filter((s) => s !== ""))];
  const scored = uniq
    .filter((s) => s.toLowerCase() !== needle)
    .map((s) => ({ s, d: leven(needle, s.toLowerCase()) }))
    .filter((x) => x.d > 0 && x.d <= DID_YOU_MEAN_MAX_DISTANCE)
    .sort((a, b) => a.d - b.d || a.s.localeCompare(b.s));
  const out: string[] = [];
  for (const row of scored) {
    if (out.length >= DID_YOU_MEAN_MAX) break;
    out.push(row.s);
  }
  return out;
}

async function enrichNotFoundHint(opts: {
  ref: string;
  tenantSlug: string;
  profileCacheKey: string;
  baseHint?: string | undefined;
}): Promise<string | undefined> {
  const base =
    opts.baseHint ??
    "Check slugs, IDs, and tenant scope. Run `objectified projects list` to refresh suggestions.";
  if (projectRefLooksLikeUuid(opts.ref)) {
    return base;
  }
  const cached = await loadCachedProjectSlugs(opts.profileCacheKey, opts.tenantSlug);
  const picks = didYouMeanSlugs(opts.ref, cached);
  if (picks.length === 0) return base;
  return `${base} Did you mean: ${picks.join(", ")}?`;
}

/**
 * Resolve `projects show`-style ref: UUID → GET /v1/projects/{tenant}/{id}; else → …/by-slug/{slug}.
 * On 404, exit **5** with optional Levenshtein hints from cached `projects list` slugs (#3203).
 */
export async function resolveProjectForTenant(
  api: ObjectifiedApi,
  tenantSlug: string,
  rawRef: string,
  profileCacheKey: string,
): Promise<ProjectSchema> {
  const ref = normalizeProjectRef(rawRef);
  if (ref === "") {
    throw new ObjectifiedCliError({
      message: "Project slug or id is required.",
      exitCode: EXIT_CODES.MISUSE,
      title: "Missing argument",
      hint: "Run `objectified projects show <slug-or-id>`.",
    });
  }

  try {
    if (projectRefLooksLikeUuid(ref)) {
      return await api.getProject(tenantSlug, ref.toLowerCase());
    }
    return await api.getProjectBySlug(tenantSlug, ref);
  } catch (e) {
    if (!(e instanceof ObjectifiedCliError) || e.exitCode !== EXIT_CODES.NOT_FOUND) {
      throw e;
    }
    const hint = await enrichNotFoundHint({
      ref,
      tenantSlug,
      profileCacheKey,
      baseHint: e.hint,
    });
    throw new ObjectifiedCliError({
      message: `Project not found: ${ref}`,
      exitCode: EXIT_CODES.NOT_FOUND,
      title: "Not found",
      hint,
      requestId: e.requestId,
      retriesAttempted: e.retriesAttempted,
    });
  }
}
