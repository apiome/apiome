/**
 * PR-back sync: Apiome → repository — REPO-5.8 (#2793).
 *
 * The browser-side model of PR-back: render a project version and open a pull request into the
 * repository files the project was imported from. apiome-rest owns the rules (which projects a
 * repository allows, which file gets which paths and schemas, the change report); this module
 * only
 *
 * - parses apiome-rest's replies into typed shapes (`parse*`), refusing anything malformed;
 * - whitelists what the BFF forwards (`sanitize*`), so a hand-made request cannot smuggle a field
 *   through;
 * - holds the words and tones the screens use for each outcome and policy.
 */

/** `allow`: only the listed projects may PR back. `deny`: every project except them. */
export type PrBackPolicy = 'allow' | 'deny';

/** What a PR-back did. */
export type PrBackStatus = 'preview' | 'opened' | 'updated' | 'unchanged' | 'up_to_date' | 'failed';

/** A project a repository's policy lists. */
export interface PrBackProjectRef {
  id: string;
  /** Null when the project was deleted. */
  name: string | null;
}

/** A repository's PR-back settings. */
export interface PrBackSettings {
  repositoryId: string;
  /** False when the repository has no settings — no project may PR back. */
  configured: boolean;
  projectPolicy: PrBackPolicy;
  projects: PrBackProjectRef[];
  /** Null for the branch the files were imported from. */
  targetBranch: string | null;
  /** Null for {@link PrBackSettings.defaultCommitMessageTemplate}. */
  commitMessageTemplate: string | null;
  defaultCommitMessageTemplate: string;
  /** GitHub logins or `org/team` slugs. */
  reviewers: string[];
  updatedAt: string | null;
}

/** What the settings form saves. */
export interface PrBackSettingsInput {
  projectPolicy: PrBackPolicy;
  projectIds: string[];
  targetBranch: string | null;
  commitMessageTemplate: string | null;
  reviewers: string[];
}

/** One source file of a project in a repository. */
export interface PrBackFileRef {
  path: string;
  branch: string;
  precedence: number;
}

/** A repository a project was imported from, and whether the project may PR back into it. */
export interface PrBackRepository {
  repositoryId: string;
  repositoryFullName: string | null;
  files: PrBackFileRef[];
  eligible: boolean;
  baseBranch: string | null;
  reasonCode: string | null;
  reason: string | null;
}

/** One rendered file and its change report counts. */
export interface PrBackFileReport {
  path: string;
  /** `added`, `modified` or `unchanged`. */
  status: string;
  paths: number;
  schemas: number;
  counts: Record<string, number>;
  foreignRefs: string[];
  notes: string[];
}

/** What a PR-back did (or, for a dry run, would do). */
export interface PrBackOutcome {
  status: PrBackStatus;
  dryRun: boolean;
  versionLabel: string | null;
  repositoryFullName: string | null;
  baseBranch: string | null;
  branchName: string | null;
  pullRequestNumber: number | null;
  pullRequestUrl: string | null;
  title: string | null;
  body: string | null;
  commitMessage: string | null;
  reviewers: string[];
  files: PrBackFileReport[];
  skipped: string[];
  errorCode: string | null;
  errorMessage: string | null;
}

/** What the sync request carries. */
export interface PrBackRequest {
  repositoryId: string;
  version?: string;
  dryRun?: boolean;
}

/** Labels for each outcome. */
export const PR_BACK_STATUS_LABEL: Record<PrBackStatus, string> = {
  preview: 'Preview',
  opened: 'Pull request opened',
  updated: 'Pull request updated',
  unchanged: 'Already up to date',
  up_to_date: 'Nothing to sync',
  failed: 'Failed',
};

/** Badge tones for each outcome. */
export const PR_BACK_STATUS_TONE: Record<PrBackStatus, 'ok' | 'danger' | 'neutral' | 'accent'> = {
  preview: 'accent',
  opened: 'ok',
  updated: 'ok',
  unchanged: 'neutral',
  up_to_date: 'neutral',
  failed: 'danger',
};

/** What each policy does, in the words the settings card uses. */
export const PR_BACK_POLICY_COPY: Record<PrBackPolicy, { label: string; description: string }> = {
  allow: {
    label: 'Only the projects listed',
    description: 'Only the projects you tick may open pull requests into this repository.',
  },
  deny: {
    label: 'Every project except those listed',
    description: 'Every project imported from this repository may open pull requests, except the ones you tick.',
  },
};

/** How many reviewers a pull request may request (apiome-rest's limit). */
export const MAX_REVIEWERS = 15;

const STATUSES: readonly PrBackStatus[] = ['preview', 'opened', 'updated', 'unchanged', 'up_to_date', 'failed'];

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

type Json = Record<string, unknown>;

function isObject(value: unknown): value is Json {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function str(value: unknown): string | null {
  return typeof value === 'string' ? value : null;
}

function num(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [];
}

/**
 * Parse a settings reply.
 *
 * @param payload - The BFF's JSON.
 * @returns The settings, or null when the reply is not a settings object.
 */
export function parsePrBackSettings(payload: unknown): PrBackSettings | null {
  if (!isObject(payload) || typeof payload.repositoryId !== 'string') return null;
  const policy = payload.projectPolicy === 'deny' ? 'deny' : 'allow';
  const projects = Array.isArray(payload.projects)
    ? payload.projects.filter(isObject).flatMap((p) =>
        typeof p.id === 'string' ? [{ id: p.id, name: str(p.name) }] : [],
      )
    : [];
  return {
    repositoryId: payload.repositoryId,
    configured: payload.configured === true,
    projectPolicy: policy,
    projects,
    targetBranch: str(payload.targetBranch),
    commitMessageTemplate: str(payload.commitMessageTemplate),
    defaultCommitMessageTemplate: str(payload.defaultCommitMessageTemplate) ?? '',
    reviewers: strings(payload.reviewers),
    updatedAt: str(payload.updatedAt),
  };
}

/**
 * Parse the list of repositories a project can PR back into.
 *
 * @param payload - The BFF's JSON.
 * @returns The repositories, or null when the reply is malformed.
 */
export function parsePrBackRepositories(payload: unknown): PrBackRepository[] | null {
  if (!isObject(payload) || !Array.isArray(payload.repositories)) return null;
  return payload.repositories.filter(isObject).flatMap((r) => {
    if (typeof r.repositoryId !== 'string') return [];
    const files = Array.isArray(r.files)
      ? r.files.filter(isObject).flatMap((f) =>
          typeof f.path === 'string'
            ? [{ path: f.path, branch: str(f.branch) ?? '', precedence: num(f.precedence) ?? 1 }]
            : [],
        )
      : [];
    return [
      {
        repositoryId: r.repositoryId,
        repositoryFullName: str(r.repositoryFullName),
        files,
        eligible: r.eligible === true,
        baseBranch: str(r.baseBranch),
        reasonCode: str(r.reasonCode),
        reason: str(r.reason),
      },
    ];
  });
}

/**
 * Parse a sync outcome.
 *
 * @param payload - The BFF's JSON.
 * @returns The outcome, or null when the reply is not one.
 */
export function parsePrBackOutcome(payload: unknown): PrBackOutcome | null {
  if (!isObject(payload) || !STATUSES.includes(payload.status as PrBackStatus)) return null;
  const files = Array.isArray(payload.files)
    ? payload.files.filter(isObject).flatMap((f) => {
        if (typeof f.path !== 'string') return [];
        const counts: Record<string, number> = {};
        if (isObject(f.counts)) {
          for (const [key, value] of Object.entries(f.counts)) {
            if (typeof value === 'number') counts[key] = value;
          }
        }
        return [
          {
            path: f.path,
            status: str(f.status) ?? 'modified',
            paths: num(f.paths) ?? 0,
            schemas: num(f.schemas) ?? 0,
            counts,
            foreignRefs: strings(f.foreignRefs),
            notes: strings(f.notes),
          },
        ];
      })
    : [];
  return {
    status: payload.status as PrBackStatus,
    dryRun: payload.dryRun === true,
    versionLabel: str(payload.versionLabel),
    repositoryFullName: str(payload.repositoryFullName),
    baseBranch: str(payload.baseBranch),
    branchName: str(payload.branchName),
    pullRequestNumber: num(payload.pullRequestNumber),
    pullRequestUrl: str(payload.pullRequestUrl),
    title: str(payload.title),
    body: str(payload.body),
    commitMessage: str(payload.commitMessage),
    reviewers: strings(payload.reviewers),
    files,
    skipped: strings(payload.skipped),
    errorCode: str(payload.errorCode),
    errorMessage: str(payload.errorMessage),
  };
}

/**
 * Whitelist a sync request body.
 *
 * @param body - What the browser sent.
 * @returns The request, or null when it names no valid repository.
 */
export function sanitizePrBackRequest(body: unknown): PrBackRequest | null {
  if (!isObject(body) || typeof body.repositoryId !== 'string' || !UUID_RE.test(body.repositoryId)) return null;
  const request: PrBackRequest = { repositoryId: body.repositoryId, dryRun: body.dryRun === true };
  const version = str(body.version)?.trim();
  if (version) request.version = version.slice(0, 128);
  return request;
}

/**
 * Whitelist a settings body.
 *
 * @param body - What the browser sent.
 * @returns The settings to save, or null when the body is not a settings object.
 */
export function sanitizePrBackSettingsInput(body: unknown): PrBackSettingsInput | null {
  if (!isObject(body)) return null;
  const text = (value: unknown) => {
    const trimmed = str(value)?.trim();
    return trimmed ? trimmed : null;
  };
  return {
    projectPolicy: body.projectPolicy === 'deny' ? 'deny' : 'allow',
    projectIds: strings(body.projectIds).slice(0, 500),
    targetBranch: text(body.targetBranch),
    commitMessageTemplate: text(body.commitMessageTemplate),
    reviewers: strings(body.reviewers).slice(0, MAX_REVIEWERS + 1),
  };
}

/**
 * Split what a person typed into the reviewers field.
 *
 * @param text - Logins and teams separated by commas, spaces or new lines; `@` is optional.
 * @returns The entries, `@` dropped, duplicates (ignoring case) removed, in order.
 */
export function parseReviewers(text: string): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of text.split(/[\s,]+/)) {
    const entry = raw.replace(/^@/, '').trim();
    if (entry && !seen.has(entry.toLowerCase())) {
      seen.add(entry.toLowerCase());
      out.push(entry);
    }
  }
  return out;
}

/**
 * Summarize a repository's settings in one sentence.
 *
 * @param settings - The settings.
 * @returns e.g. "2 projects may open pull requests into main."
 */
export function settingsSummary(settings: PrBackSettings): string {
  if (!settings.configured) return 'PR-back is off: no project may open pull requests into this repository yet.';
  const count = settings.projects.length;
  const target = settings.targetBranch ? ` into ${settings.targetBranch}` : '';
  if (settings.projectPolicy === 'allow') {
    if (count === 0) return 'No project may open pull requests yet — tick the projects to allow.';
    return `${count} project${count === 1 ? '' : 's'} may open pull requests${target}.`;
  }
  if (count === 0) return `Every project imported from this repository may open pull requests${target}.`;
  return `Every project except ${count} may open pull requests${target}.`;
}

/**
 * Describe what an outcome means for the person who asked for it.
 *
 * @param outcome - The outcome.
 * @returns One sentence.
 */
export function outcomeSentence(outcome: PrBackOutcome): string {
  const pull = outcome.pullRequestNumber ? `#${outcome.pullRequestNumber}` : 'the pull request';
  const changed = outcome.files.filter((f) => f.status !== 'unchanged').length;
  switch (outcome.status) {
    case 'preview':
      return `Opening a pull request would write ${changed} of ${outcome.files.length} file(s) into ${outcome.baseBranch ?? 'the base branch'}.`;
    case 'opened':
      return `Opened pull request ${pull} into ${outcome.baseBranch ?? 'the base branch'}.`;
    case 'updated':
      return `Updated the open pull request ${pull} with this version.`;
    case 'unchanged':
      return `Pull request ${pull} already carries exactly this version.`;
    case 'up_to_date':
      return `${outcome.baseBranch ?? 'The base branch'} already holds this version's spec — nothing to sync.`;
    default:
      return outcome.errorMessage ?? 'The sync failed.';
  }
}
