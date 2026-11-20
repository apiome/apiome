/**
 * Upgrade OpenAPI version — the dialog's data and pure helpers (COA-2.6, #7049).
 *
 * Mirrors the REST plan (`POST /v1/openapi-upgrade/{slug}/plan`) and apply responses, and holds the
 * request helpers the dialog calls through the `/api/openapi-upgrade/*` proxy. Everything that is
 * not a `fetch` is pure so the tests can drive it directly.
 */

/** The target version families REST accepts. */
export const UPGRADE_TARGETS = ['3.0', '3.1', '3.2'] as const;
/** One target family. */
export type UpgradeTarget = (typeof UPGRADE_TARGETS)[number];

/** One rewrite in a plan. */
export interface UpgradeChange {
  /** The hop that made it (`2.0→3.0`, `3.0→3.1`, `3.1→3.2`). */
  hop: string;
  /** Rule id, e.g. `nullable-to-type-array`. */
  rule: string;
  /** Rule title, e.g. `nullable → type array`. */
  title: string;
  /** JSON Pointer of the object changed (in the document entering the hop); `""` is the root. */
  pointer: string;
  /** Where the object lives after the hop, when it moved. */
  target_pointer?: string | null;
  /** One sentence on what changed. */
  summary: string;
  /** True when the rewrite may change the document's meaning. */
  review: boolean;
}

/** Changes per rule. */
export interface UpgradeRuleCount {
  rule: string;
  title: string;
  hop: string;
  count: number;
}

/** The plan REST returns. */
export interface UpgradePlan {
  source_version: string;
  source_family: string;
  target: UpgradeTarget;
  target_version: string;
  hops: string[];
  already_current: boolean;
  change_count: number;
  review_count: number;
  rules: UpgradeRuleCount[];
  changes: UpgradeChange[];
  plan_digest: string;
  /** `captured` (the import's source), `rebuilt` (from the stored model) or `request`. */
  origin: 'captured' | 'rebuilt' | 'request';
  version_record_id?: string;
  version_label?: string | null;
}

/** What an apply created. */
export interface UpgradeApplyResult {
  project_id: string;
  version_record_id: string;
  version_label: string;
  source_version_record_id: string;
  target_version: string;
  change_count: number;
}

/** The changes of one hop, for the grouped list. */
export interface UpgradeHopGroup {
  hop: string;
  changes: UpgradeChange[];
}

/** The largest number of changes listed per hop before the list says how many more there are. */
export const MAX_LISTED_CHANGES = 200;

/**
 * Human name of a version family: `Swagger 2.0` or `OpenAPI 3.x`.
 *
 * @param family - `2.0`, `3.0`, `3.1` or `3.2`.
 * @returns The name.
 */
export function familyName(family: string): string {
  return family === '2.0' ? 'Swagger 2.0' : `OpenAPI ${family}`;
}

/**
 * The headline of a plan, e.g. `Swagger 2.0 (2.0) → OpenAPI 3.2.0 — 46 changes, 1 to review`.
 *
 * @param plan - The plan.
 * @returns The sentence.
 */
export function planHeadline(plan: UpgradePlan): string {
  if (plan.already_current) {
    return `This version is already ${familyName(plan.source_family)} (${plan.source_version}). Nothing to upgrade.`;
  }
  const changes = `${plan.change_count} change${plan.change_count === 1 ? '' : 's'}`;
  const review = plan.review_count ? `, ${plan.review_count} to review` : '';
  return `${familyName(plan.source_family)} (${plan.source_version}) → OpenAPI ${plan.target_version} — ${changes}${review}`;
}

/**
 * Where the plan's source document came from, as a sentence.
 *
 * @param origin - The plan's `origin`.
 * @returns The note.
 */
export function originNote(origin: UpgradePlan['origin']): string {
  if (origin === 'rebuilt') {
    return 'This version keeps no imported file, so the plan starts from the document Apiome generates for it (OpenAPI 3.1).';
  }
  if (origin === 'captured') return 'The plan starts from the file this version was imported from.';
  return 'The plan starts from the document you supplied.';
}

/**
 * The plan's changes grouped by hop, in hop order.
 *
 * @param plan - The plan.
 * @returns One group per hop that has changes.
 */
export function groupChangesByHop(plan: UpgradePlan): UpgradeHopGroup[] {
  return plan.hops
    .map((hop) => ({ hop, changes: plan.changes.filter((change) => change.hop === hop) }))
    .filter((group) => group.changes.length > 0);
}

/**
 * The targets a version of `family` can be upgraded to (later families only).
 *
 * @param family - The source family, or `null` while unknown (every target is offered).
 * @returns The targets.
 */
export function targetsAfter(family: string | null): UpgradeTarget[] {
  if (!family) return [...UPGRADE_TARGETS];
  const order = ['2.0', ...UPGRADE_TARGETS];
  const index = order.indexOf(family);
  return UPGRADE_TARGETS.filter((target) => order.indexOf(target) > index);
}

/**
 * Why the version label is not usable, or `null` when it is (empty is fine: REST mints one).
 *
 * @param label - The label typed.
 * @param existing - The project's labels.
 * @returns The problem, or `null`.
 */
export function versionLabelProblem(label: string, existing: readonly string[]): string | null {
  const trimmed = label.trim();
  if (!trimmed) return null;
  if (trimmed.length > 128) return 'Use 128 characters or fewer.';
  if (existing.includes(trimmed)) return `Version ${trimmed} already exists. Choose another label.`;
  return null;
}

/**
 * POST JSON to an upgrade proxy route, throwing REST's message on a refusal.
 *
 * @param url - `/api/openapi-upgrade/plan` or `/apply`.
 * @param body - The request body.
 * @param fallback - Message when the response carries none.
 * @returns The parsed response.
 */
async function postUpgrade<T>(url: string, body: unknown, fallback: string): Promise<T> {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const data = await response.json().catch(() => null);
  if (!response.ok || !data || data.success === false) {
    throw new Error((data && typeof data.error === 'string' && data.error) || fallback);
  }
  return data as T;
}

/**
 * Plan the upgrade of a version (the upgraded document is not fetched — the dialog lists changes).
 *
 * @param projectId - Project or catalog item id.
 * @param versionId - Version id (default: the latest).
 * @param target - Target family.
 * @returns The plan.
 */
export function requestUpgradePlan(projectId: string, versionId: string | undefined, target: UpgradeTarget) {
  return postUpgrade<UpgradePlan>(
    '/api/openapi-upgrade/plan',
    { target, project_id: projectId, ...(versionId ? { version: versionId } : {}), include_document: false },
    'The upgrade could not be planned.',
  );
}

/**
 * Apply a reviewed plan as a new version.
 *
 * @param projectId - Project or catalog item id.
 * @param versionId - The version that was planned.
 * @param plan - The reviewed plan (its digest is sent).
 * @param versionLabel - Label of the new version; empty lets REST mint one.
 * @returns What was created.
 */
export function applyUpgradePlan(
  projectId: string,
  versionId: string | undefined,
  plan: UpgradePlan,
  versionLabel: string,
) {
  const label = versionLabel.trim();
  return postUpgrade<UpgradeApplyResult>(
    '/api/openapi-upgrade/apply',
    {
      target: plan.target,
      project_id: projectId,
      ...(versionId ? { version: versionId } : {}),
      plan_digest: plan.plan_digest,
      ...(label ? { version_label: label } : {}),
    },
    'The upgrade could not be applied.',
  );
}
