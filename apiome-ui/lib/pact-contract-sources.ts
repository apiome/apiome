/**
 * Standing sources of a provider contract — PFX-8.7 (#7304).
 *
 * A provider can say once where its contract comes from, so nobody has to publish it for every
 * version (`GET` / `PUT /v1/tenants/{t}/pacticipants/{p}/contract-sources`):
 *
 * - **Do this on every publish** — each published version of the provider's project becomes its
 *   contract (provider version = the version label). Drafts never do.
 * - **Repository** — every push to a branch of a registered repository publishes a file, the
 *   pushed commit being the provider version.
 *
 * This module reads REST's answer, words it for the page, checks the Repository tab, and builds
 * the body the BFF (`/api/pact/provider-contracts/sources`) sends. Pure: no I/O.
 */

/** The repository providers whose files a push can be read from (REST reads GitHub's contents API). */
export const READABLE_PROVIDERS: readonly string[] = ['github'];

/** The file names a contract may be read from. */
export const CONTRACT_FILE_SUFFIXES: readonly string[] = ['.yaml', '.yml', '.json'];

/** The longest repository path REST stores. */
export const MAX_PATH_CHARS = 1024;

/** Why the aside has no preview on the Repository tab. */
export const REPOSITORY_NO_PREVIEW =
  'The verdicts appear after the next push: each push to the branch publishes the file and records them against every consumer.';

/** Why pushes carry no evidence. */
export const PUSH_EVIDENCE_NOTE =
  'A push publishes the file without self-verification evidence, so its verdicts read unverified until evidence is published for that commit from your pipeline.';

/** Why the command block cannot carry a standing source. */
export const SOURCES_HAVE_NO_FLAG =
  'apiome pact publish-provider-contract publishes one version; a standing source is set here, or with PUT …/pacticipants/{p}/contract-sources.';

/** Turning a source off: what it does and does not undo. */
export const STOPS_NEW_ONLY = 'Turning a source off stops new publishes only; contracts already published stay.';

/** A repository file published on every push. */
export interface RepositorySource {
  repositoryId: string | null;
  fullName: string | null;
  provider: string | null;
  path: string;
  branch: string;
  /** Whether the repository has a push webhook (without one no push arrives). */
  webhook: boolean;
}

/** A provider's standing sources, as REST answers them. */
export interface ContractSources {
  pacticipant: string;
  onProjectPublish: boolean;
  project: { id: string; slug: string | null; name: string | null } | null;
  repository: RepositorySource | null;
  /** Why a stored source will not fire right now. */
  warnings: string[];
}

/** A registered repository the Repository tab offers. */
export interface RepositoryChoice {
  id: string;
  fullName: string;
  provider: string;
  defaultBranch: string;
  /** Whether its files can be read on a push. */
  readable: boolean;
}

/** What the page asks the BFF to change; a field left out keeps what is stored. */
export interface SourcesPatch {
  onProjectPublish?: boolean;
  repository?: { repositoryId: string; path: string; branch: string } | null;
  /** With `onProjectPublish: true`: bind the provider to this project (by handle) when it is bound to none. */
  bindProject?: string;
}

/** The REST body of `PUT …/contract-sources` (the whole setting). */
export interface SourcesBody {
  onProjectPublish: boolean;
  repository: { repositoryId: string; path: string; branch: string } | null;
}

/** A string, or `null`. */
function text(value: unknown): string | null {
  return typeof value === 'string' && value ? value : null;
}

/**
 * Read REST's `ContractSourcesRecord`.
 *
 * @param raw - The JSON body.
 * @returns The sources, or `null` when the body is not one.
 */
export function readContractSources(raw: unknown): ContractSources | null {
  if (!raw || typeof raw !== 'object') return null;
  const body = raw as Record<string, unknown>;
  if (typeof body.pacticipant !== 'string') return null;
  const project = body.project && typeof body.project === 'object' ? (body.project as Record<string, unknown>) : null;
  const repository = body.repository && typeof body.repository === 'object' ? (body.repository as Record<string, unknown>) : null;
  return {
    pacticipant: body.pacticipant,
    onProjectPublish: body.onProjectPublish === true,
    project: project && typeof project.id === 'string' ? { id: project.id, slug: text(project.slug), name: text(project.name) } : null,
    repository:
      repository && typeof repository.path === 'string' && typeof repository.branch === 'string'
        ? {
            repositoryId: text(repository.repositoryId),
            fullName: text(repository.fullName),
            provider: text(repository.provider),
            path: repository.path,
            branch: repository.branch,
            webhook: repository.webhook === true,
          }
        : null,
    warnings: Array.isArray(body.warnings) ? body.warnings.filter((w): w is string => typeof w === 'string') : [],
  };
}

/**
 * Read the `/api/repositories` list.
 *
 * @param raw - `{ repositories: [...] }` (REST's `TenantRepositoryRecord`s).
 * @returns The repositories, GitHub ones first, each marked readable or not.
 */
export function readRepositories(raw: unknown): RepositoryChoice[] {
  const list = raw && typeof raw === 'object' ? (raw as Record<string, unknown>).repositories : null;
  if (!Array.isArray(list)) return [];
  const rows: RepositoryChoice[] = [];
  for (const item of list) {
    if (!item || typeof item !== 'object') continue;
    const row = item as Record<string, unknown>;
    if (typeof row.id !== 'string') continue;
    const provider = (text(row.provider) ?? 'github').toLowerCase();
    rows.push({
      id: row.id,
      fullName: text(row.full_name) ?? text(row.name) ?? row.id,
      provider,
      defaultBranch: text(row.default_branch) ?? 'main',
      readable: READABLE_PROVIDERS.includes(provider),
    });
  }
  return rows.sort((a, b) => Number(b.readable) - Number(a.readable) || a.fullName.localeCompare(b.fullName));
}

/**
 * Why a repository path cannot be followed, or `null` (REST's rules, checked before sending).
 *
 * @param path - The path as typed.
 * @returns The problem, or `null`.
 */
export function pathProblem(path: string): string | null {
  let value = path.trim().replace(/\\/g, '/');
  while (value.startsWith('./')) value = value.slice(2);
  if (!value) return 'Give the path of the OpenAPI or AsyncAPI document in the repository.';
  if (value.startsWith('/')) return 'Give the path relative to the repository root, without a leading “/”.';
  if (value.split('/').some((part) => part === '' || part === '.' || part === '..')) return 'The path cannot contain “..”, “.” or an empty folder.';
  if (value.length > MAX_PATH_CHARS) return `The path is longer than ${MAX_PATH_CHARS} characters.`;
  if (!CONTRACT_FILE_SUFFIXES.some((suffix) => value.toLowerCase().endsWith(suffix))) return 'The file must be an OpenAPI or AsyncAPI document ending in .yaml, .yml or .json.';
  return null;
}

/**
 * The whole setting `PUT …/contract-sources` takes: what is stored, changed by the patch.
 *
 * @param current - What REST holds (`null` when nothing was ever set or the provider is new).
 * @param patch - What the page changes.
 * @returns The body.
 */
export function mergedSourcesBody(current: ContractSources | null, patch: SourcesPatch): SourcesBody {
  const stored =
    current?.repository && current.repository.repositoryId
      ? { repositoryId: current.repository.repositoryId, path: current.repository.path, branch: current.repository.branch }
      : null;
  return {
    onProjectPublish: patch.onProjectPublish ?? current?.onProjectPublish ?? false,
    repository: patch.repository === undefined ? stored : patch.repository,
  };
}

/** The project's name, or its handle. */
function projectName(sources: ContractSources): string {
  return sources.project?.name ?? sources.project?.slug ?? 'its project';
}

/**
 * The standing sources in words, one line each.
 *
 * @param sources - The sources.
 * @returns E.g. “Each published version of Billing API becomes its contract.”; empty when none is on.
 */
export function sourcesLines(sources: ContractSources): string[] {
  const lines: string[] = [];
  if (sources.onProjectPublish) lines.push(`Each published version of ${projectName(sources)} becomes its contract. Drafts never do.`);
  if (sources.repository) {
    const where = sources.repository.fullName ?? 'a deleted repository';
    lines.push(`Every push to ${sources.repository.branch} of ${where} publishes ${sources.repository.path}, the commit being the provider version.`);
  }
  return lines;
}

/**
 * What following a file says once it is saved.
 *
 * @param sources - The sources REST stored.
 * @returns The notice.
 */
export function followedNotice(sources: ContractSources): string {
  const repo = sources.repository;
  const head = repo ? `Following ${repo.path} on ${repo.branch} of ${repo.fullName ?? 'the repository'}: every push publishes it.` : 'Saved.';
  return sources.warnings.length ? `${head} ${sources.warnings.join(' ')}` : head;
}

/**
 * The REST path of a provider’s sources below `/v1/tenants/{slug}/`, or `null` for an unusable name.
 *
 * @param provider - The provider's name or handle.
 * @returns The path.
 */
export function sourcesPath(provider: string): string | null {
  const name = provider.trim();
  if (!name || name.length > 255) return null;
  return `pacticipants/${encodeURIComponent(name)}/contract-sources`;
}
