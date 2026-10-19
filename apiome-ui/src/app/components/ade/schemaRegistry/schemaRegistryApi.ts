/**
 * Browser calls for the schema registry screens (CDG-4.5, #5977), through `/api/schema-registry/*`.
 */

import type {
  CompatibilityLevel,
  RegistryConfig,
  RegistryMode,
  SchemaSubject,
  SubjectStrategy,
  SubjectVersion,
} from '@lib/schema-registry';

/** The proxy's base path. */
const BASE = '/api/schema-registry';

/**
 * Read a proxy answer, or throw its message.
 *
 * @param response - The proxy response.
 * @param fallback - The message when the answer carries none.
 * @returns The parsed body.
 */
async function readJson<T>(response: Response, fallback: string): Promise<T> {
  const body = (await response.json().catch(() => ({}))) as Record<string, unknown>;
  if (!response.ok) {
    throw new Error(typeof body.error === 'string' && body.error ? body.error : fallback);
  }
  return body as T;
}

/** The URL of one subject. */
function subjectUrl(subject: string): string {
  return `${BASE}/subjects/${encodeURIComponent(subject)}`;
}

/**
 * The tenant's registry defaults, slug and Confluent-compatible URL.
 *
 * @returns The config.
 */
export async function fetchRegistryConfig(): Promise<RegistryConfig> {
  return readJson<RegistryConfig>(await fetch(`${BASE}/config`, { cache: 'no-store' }), 'Could not load the registry settings');
}

/**
 * Change the tenant's default compatibility level and/or mode.
 *
 * @param change - The fields to change; an omitted one is kept.
 * @returns The defaults after the change.
 */
export async function saveRegistryConfig(change: {
  compatibilityLevel?: CompatibilityLevel;
  mode?: RegistryMode;
}): Promise<RegistryConfig> {
  const response = await fetch(`${BASE}/config`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(change),
  });
  return readJson<RegistryConfig>(response, 'Could not save the registry settings');
}

/**
 * The tenant's live subjects.
 *
 * @returns Every live subject, by name.
 */
export async function fetchSubjects(): Promise<SchemaSubject[]> {
  const body = await readJson<{ subjects?: SchemaSubject[] }>(
    await fetch(`${BASE}/subjects`, { cache: 'no-store' }),
    'Could not load the subjects',
  );
  return Array.isArray(body.subjects) ? body.subjects : [];
}

/**
 * One subject's live versions, oldest first.
 *
 * @param subject - The subject name.
 * @returns The versions.
 */
export async function fetchSubjectVersions(subject: string): Promise<SubjectVersion[]> {
  const body = await readJson<{ versions?: SubjectVersion[] }>(
    await fetch(`${subjectUrl(subject)}/versions`, { cache: 'no-store' }),
    'Could not load the versions',
  );
  return Array.isArray(body.versions) ? body.versions : [];
}

/**
 * Change a subject's compatibility level, mode or strategy.
 *
 * @param subject - The subject name.
 * @param change - The fields to change; an omitted one is kept.
 * @returns The subject after the change.
 */
export async function saveSubjectSettings(
  subject: string,
  change: { compatibilityLevel?: CompatibilityLevel; mode?: RegistryMode; strategy?: SubjectStrategy },
): Promise<SchemaSubject> {
  const response = await fetch(subjectUrl(subject), {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(change),
  });
  return readJson<SchemaSubject>(response, 'Could not save the subject');
}

/**
 * Back an empty subject with a catalog item; its latest revision becomes version 1.
 *
 * @param subject - The subject name (created when it does not exist).
 * @param projectId - The catalog item id.
 * @param strategy - The naming strategy for a subject this creates.
 * @returns The version the attach created.
 */
export async function attachSubject(
  subject: string,
  projectId: string,
  strategy?: SubjectStrategy,
): Promise<SubjectVersion> {
  const response = await fetch(`${subjectUrl(subject)}/attach`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(strategy ? { projectId, strategy } : { projectId }),
  });
  return readJson<SubjectVersion>(response, 'Could not attach the catalog item');
}

/**
 * Detach a subject: soft-delete it and its versions. The catalog item and its revisions stay, and
 * the schema ids keep resolving.
 *
 * @param subject - The subject name.
 * @returns The versions that were deleted.
 */
export async function detachSubject(subject: string): Promise<number[]> {
  const body = await readJson<unknown>(
    await fetch(subjectUrl(subject), { method: 'DELETE' }),
    'Could not detach the subject',
  );
  return Array.isArray(body) ? (body as number[]) : [];
}
