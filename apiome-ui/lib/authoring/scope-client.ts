/**
 * Scope data loading for the Authoring shell (UXE-1.2).
 *
 * Thin wrappers over the existing `/api/projects` and `/api/versions` proxies.
 * Both are already tenant-scoped from the session, so the shell never passes a
 * tenant itself and cannot widen its own access.
 *
 * These exist separately from the style-guide pickers
 * (`src/app/ade/dashboard/style-guides/api.ts`) because the shell needs each
 * version's `published` flag to derive read-only state; those pickers project
 * versions down to a display label and drop it.
 */

import type { AuthoringProjectOption, AuthoringVersionOption } from './commands';

/** Envelope returned by the API proxies. */
type ApiEnvelope<K extends string> = {
  success?: boolean;
} & Partial<Record<K, unknown>>;

/**
 * Load the projects the session can see.
 *
 * Throws on a failed envelope rather than returning an empty list. The
 * difference matters: "you have no projects" is an authoritative answer the
 * shell acts on by clearing an unauthorized scope, whereas "the request
 * failed" proves nothing and must not be mistaken for it.
 *
 * @param signal - Abort signal, so a scope change cancels an in-flight load.
 * @returns Projects the session can see, possibly empty.
 * @throws When the request fails or the response is not a success envelope.
 */
export async function fetchAuthoringProjects(
  signal?: AbortSignal
): Promise<AuthoringProjectOption[]> {
  const response = await fetch('/api/projects', { signal });
  const json = (await response.json()) as ApiEnvelope<'projects'>;
  if (!json.success || !Array.isArray(json.projects)) {
    throw new Error('Failed to load projects');
  }

  return (json.projects as Array<{ id?: unknown; name?: unknown }>)
    .filter((row) => typeof row.id === 'string' && row.id.length > 0)
    .map((row) => ({
      id: row.id as string,
      name: typeof row.name === 'string' && row.name.trim() ? row.name : (row.id as string),
    }));
}

/**
 * Load the version revisions of one project.
 *
 * Throws on a failed envelope, for the same reason as
 * {@link fetchAuthoringProjects}.
 *
 * @param projectId - Project whose versions to list.
 * @param signal - Abort signal, so a project change cancels an in-flight load.
 * @returns Versions of the project, possibly empty.
 * @throws When the request fails or the response is not a success envelope.
 */
export async function fetchAuthoringVersions(
  projectId: string,
  signal?: AbortSignal
): Promise<AuthoringVersionOption[]> {
  const response = await fetch(`/api/versions?projectId=${encodeURIComponent(projectId)}`, {
    signal,
  });
  const json = (await response.json()) as ApiEnvelope<'versions'>;
  if (!json.success || !Array.isArray(json.versions)) {
    throw new Error('Failed to load versions');
  }

  return (
    json.versions as Array<{
      id?: unknown;
      version_id?: unknown;
      description?: unknown;
      published?: unknown;
    }>
  )
    .filter((row) => typeof row.id === 'string' && row.id.length > 0)
    .map((row) => ({
      id: row.id as string,
      versionId:
        typeof row.version_id === 'string' && row.version_id.trim()
          ? row.version_id
          : (row.id as string),
      description: typeof row.description === 'string' ? row.description : null,
      published: row.published === true,
    }));
}

/**
 * True when the selected scope must be treated as read-only.
 *
 * Two independent reasons, either of which is sufficient: the version has been
 * published, so its contents are frozen; or the viewer is looking at the
 * production lane, which is served from an already-promoted immutable release
 * and is changed by promotion and rollback rather than by editing.
 *
 * @param version - Selected version, when one is resolved.
 * @param environmentReadOnly - Whether the selected lane is read-only.
 * @returns True when editing must be disabled.
 */
export function isAuthoringScopeReadOnly(
  version: AuthoringVersionOption | undefined,
  environmentReadOnly: boolean
): boolean {
  return environmentReadOnly || version?.published === true;
}
