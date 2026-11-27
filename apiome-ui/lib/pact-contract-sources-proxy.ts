/**
 * The BFF side of a provider's standing contract sources — PFX-8.7 (#7304).
 *
 * `/api/pact/provider-contracts/sources`:
 *
 * - `GET ?provider=<name>` reads `GET /v1/tenants/{slug}/pacticipants/{p}/contract-sources`.
 * - `PUT { provider, onProjectPublish?, repository?, bindProject? }` changes it: REST's `PUT` takes
 *   the whole setting, so {@link saveSources} reads what is stored and changes only what the page
 *   sent. With `bindProject` (the page's **Do this on every publish**), a provider bound to no
 *   project is first bound to that one (`PATCH …/pacticipants/{p}`); a provider bound to another
 *   project is refused with the reason — it is never silently re-bound.
 *
 * {@link pickSourcesRequest} refuses, naming it, any field the page does not send, so nothing
 * reaches REST the page did not mean. Everything runs as the signed-in user: tenancy, `pacts:edit`
 * and `imports:view` (for a repository) are REST's. Pure apart from the injected {@link RestCall}.
 */

import { MAX_FIELD_CHARS } from './pact-publish';
import { mergedSourcesBody, pathProblem, readContractSources, sourcesPath, type SourcesPatch } from './pact-contract-sources';
import { CONTRACT_UNAVAILABLE, refusal, type ProxyAnswer, type RestCall } from './pact-provider-contract-proxy';

/** The fields `PUT` accepts. */
const FIELDS = new Set(['provider', 'onProjectPublish', 'repository', 'bindProject']);

/** The fields of `repository`. */
const REPOSITORY_FIELDS = new Set(['repositoryId', 'path', 'branch']);

/** A checked `PUT`, or why it is refused. */
export type PickedSources = { ok: true; provider: string; patch: SourcesPatch } | { ok: false; error: string };

/** A short required string, trimmed, or the refusal. */
function required(value: unknown, name: string): { value: string } | { error: string } {
  if (typeof value !== 'string' || !value.trim()) return { error: `${name} is required.` };
  if (value.trim().length > MAX_FIELD_CHARS) return { error: `${name} is longer than ${MAX_FIELD_CHARS} characters.` };
  return { value: value.trim() };
}

/**
 * Check the browser's `PUT` body.
 *
 * @param raw - The parsed JSON.
 * @returns The provider and the patch, or the refusal naming the field.
 */
export function pickSourcesRequest(raw: unknown): PickedSources {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return { ok: false, error: 'The body must be a JSON object.' };
  const body = raw as Record<string, unknown>;
  const unknown = Object.keys(body).filter((key) => !FIELDS.has(key));
  if (unknown.length) return { ok: false, error: `Unknown field${unknown.length > 1 ? 's' : ''}: ${unknown.join(', ')}.` };
  const provider = required(body.provider, 'provider');
  if ('error' in provider) return { ok: false, error: provider.error };
  const patch: SourcesPatch = {};
  if ('onProjectPublish' in body) {
    if (typeof body.onProjectPublish !== 'boolean') return { ok: false, error: 'onProjectPublish must be true or false.' };
    patch.onProjectPublish = body.onProjectPublish;
  }
  if ('bindProject' in body) {
    const project = required(body.bindProject, 'bindProject');
    if ('error' in project) return { ok: false, error: project.error };
    if (patch.onProjectPublish !== true) return { ok: false, error: 'bindProject is only sent with onProjectPublish: true.' };
    patch.bindProject = project.value;
  }
  if ('repository' in body) {
    if (body.repository === null) patch.repository = null;
    else if (!body.repository || typeof body.repository !== 'object' || Array.isArray(body.repository)) {
      return { ok: false, error: 'repository must be an object or null.' };
    } else {
      const repo = body.repository as Record<string, unknown>;
      const extra = Object.keys(repo).filter((key) => !REPOSITORY_FIELDS.has(key));
      if (extra.length) return { ok: false, error: `Unknown repository field${extra.length > 1 ? 's' : ''}: ${extra.join(', ')}.` };
      const repositoryId = required(repo.repositoryId, 'repository.repositoryId');
      if ('error' in repositoryId) return { ok: false, error: repositoryId.error };
      const branch = required(repo.branch, 'repository.branch');
      if ('error' in branch) return { ok: false, error: branch.error };
      if (typeof repo.path !== 'string') return { ok: false, error: 'repository.path is required.' };
      const problem = pathProblem(repo.path);
      if (problem) return { ok: false, error: problem };
      patch.repository = { repositoryId: repositoryId.value, path: repo.path.trim(), branch: branch.value };
    }
  }
  if (!('onProjectPublish' in patch) && !('repository' in patch)) return { ok: false, error: 'Send onProjectPublish, repository, or both.' };
  return { ok: true, provider: provider.value, patch };
}

/**
 * Change a provider's standing sources: read, bind the project when asked, write the whole setting.
 *
 * @param call - REST as the signed-in user.
 * @param provider - The provider's name or handle.
 * @param patch - What to change.
 * @returns REST's stored sources, or its refusal (a 404 for a provider not registered yet, a 409
 *   for a provider bound to another project, REST's own 4xx with its message).
 */
export async function saveSources(call: RestCall, provider: string, patch: SourcesPatch): Promise<ProxyAnswer> {
  const path = sourcesPath(provider);
  if (!path) return { status: 400, body: { success: false, error: 'provider is not a usable name.' } };
  const read = await call('GET', path);
  if (!read) return { status: 503, body: { success: false, error: CONTRACT_UNAVAILABLE } };
  if (read.status === 404) {
    return {
      status: 404,
      body: { success: false, error: `${provider} is not registered yet: publish its first contract, then choose where the next ones come from.` },
    };
  }
  if (read.status >= 400) return refusal(read.status, read.body);
  const current = readContractSources(read.body);
  if (patch.onProjectPublish && patch.bindProject) {
    const bound = current?.project ?? null;
    if (bound && bound.slug !== patch.bindProject) {
      return {
        status: 409,
        body: {
          success: false,
          error: `${provider} is bound to ${bound.name ?? bound.slug ?? 'another project'}, so its versions are the ones published. To follow ${patch.bindProject} instead, change the provider’s project on its pacticipant page.`,
        },
      };
    }
    if (!bound) {
      const bind = await call('PATCH', `pacticipants/${encodeURIComponent(provider)}`, { project: patch.bindProject });
      if (!bind) return { status: 503, body: { success: false, error: CONTRACT_UNAVAILABLE } };
      if (bind.status >= 400) return refusal(bind.status, bind.body);
    }
  }
  const saved = await call('PUT', path, mergedSourcesBody(current, patch));
  if (!saved) return { status: 503, body: { success: false, error: CONTRACT_UNAVAILABLE } };
  if (saved.status >= 400) return refusal(saved.status, saved.body);
  return { status: 200, body: { success: true, ...(saved.body as Record<string, unknown>) } };
}
