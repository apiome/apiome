/**
 * Standing sources of a provider contract — PFX-8.7 (#7304): the model (`lib/pact-contract-sources.ts`),
 * the form's Repository source (`lib/pact-provider-contract.ts`) and the BFF logic
 * (`lib/pact-contract-sources-proxy.ts`):
 *
 * * REST's answer and the repository list are read defensively; a non-GitHub repository is marked
 *   unreadable rather than hidden;
 * * a repository path is checked with REST's rules before anything is sent;
 * * a change keeps what it does not name (REST's PUT replaces the whole setting);
 * * the BFF refuses unknown fields, binds an unbound provider to the project it is told to follow,
 *   refuses — never re-binds — a provider bound to another project, and keeps REST's refusals;
 * * the command block says a standing source has no flag, and a repository source is the
 *   pipeline's per-push command.
 */

import {
  followedNotice,
  mergedSourcesBody,
  pathProblem,
  readContractSources,
  readRepositories,
  sourcesLines,
  sourcesPath,
  SOURCES_HAVE_NO_FLAG,
  type ContractSources,
} from '../lib/pact-contract-sources';
import { pickSourcesRequest, saveSources } from '../lib/pact-contract-sources-proxy';
import { EMPTY_FORM, formProblems, providerContractCommandAction, type ProviderContractForm } from '../lib/pact-provider-contract';
import type { RestCall } from '../lib/pact-provider-contract-proxy';

const STORED = {
  pacticipant: 'billing-service',
  onProjectPublish: true,
  project: { id: 'p1', slug: 'billing-api', name: 'Billing API' },
  repository: { repositoryId: 'r1', fullName: 'acme/billing', provider: 'github', path: 'openapi.yaml', branch: 'main', webhook: true },
  warnings: [],
  updatedAt: '2026-11-27T00:00:00Z',
};

describe('reading the standing sources', () => {
  it('reads REST’s record', () => {
    const sources = readContractSources(STORED)!;
    expect(sources.onProjectPublish).toBe(true);
    expect(sources.project).toEqual({ id: 'p1', slug: 'billing-api', name: 'Billing API' });
    expect(sources.repository).toEqual(STORED.repository);
    expect(sourcesLines(sources)).toEqual([
      'Each published version of Billing API becomes its contract. Drafts never do.',
      'Every push to main of acme/billing publishes openapi.yaml, the commit being the provider version.',
    ]);
  });

  it('refuses a body that is not a record, and drops a malformed repository', () => {
    expect(readContractSources(null)).toBeNull();
    expect(readContractSources({ onProjectPublish: true })).toBeNull();
    const sources = readContractSources({ pacticipant: 'x', repository: { path: 1 }, warnings: ['a', 2] })!;
    expect(sources.repository).toBeNull();
    expect(sources.warnings).toEqual(['a']);
    expect(sourcesLines(sources)).toEqual([]);
  });

  it('names a deleted repository and repeats REST’s warnings when a file is followed', () => {
    const sources = readContractSources({
      ...STORED,
      repository: { ...STORED.repository, fullName: null, repositoryId: null },
      warnings: ['The repository was deleted.'],
    })!;
    expect(sourcesLines(sources)[1]).toContain('of a deleted repository');
    expect(followedNotice(sources)).toBe('Following openapi.yaml on main of the repository: every push publishes it. The repository was deleted.');
  });

  it('lists repositories GitHub first and marks the rest unreadable', () => {
    const rows = readRepositories({
      repositories: [
        { id: 'g', full_name: 'acme/gitlab', provider: 'gitlab', default_branch: 'trunk' },
        { id: 'h', full_name: 'acme/billing', provider: 'github' },
        { full_name: 'no id' },
      ],
    });
    expect(rows).toEqual([
      { id: 'h', fullName: 'acme/billing', provider: 'github', defaultBranch: 'main', readable: true },
      { id: 'g', fullName: 'acme/gitlab', provider: 'gitlab', defaultBranch: 'trunk', readable: false },
    ]);
    expect(readRepositories({})).toEqual([]);
  });

  it('builds the REST path, or none for an unusable name', () => {
    expect(sourcesPath('Billing Service')).toBe('pacticipants/Billing%20Service/contract-sources');
    expect(sourcesPath('  ')).toBeNull();
    expect(sourcesPath('x'.repeat(256))).toBeNull();
  });
});

describe('a repository path', () => {
  it.each([
    ['a file at the root', 'openapi.yaml', null],
    ['a ./ path in any case', './specs/billing.JSON', null],
    ['an empty path', '', 'Give the path'],
    ['an absolute path', '/etc/openapi.yaml', 'relative to the repository root'],
    ['a climbing path', 'specs/../x.yaml', '“..”'],
    ['a file that is not a document', 'README.md', '.yaml, .yml or .json'],
    ['an over-long path', `${'a/'.repeat(520)}x.yaml`, 'longer than 1024'],
  ])('%s', (_label, path, says) => {
    const problem = pathProblem(path);
    if (says === null) expect(problem).toBeNull();
    else expect(problem).toContain(says);
  });
});

describe('changing a source keeps the rest', () => {
  const current = readContractSources(STORED);
  it('keeps the repository when only the project source changes', () => {
    expect(mergedSourcesBody(current, { onProjectPublish: false })).toEqual({
      onProjectPublish: false,
      repository: { repositoryId: 'r1', path: 'openapi.yaml', branch: 'main' },
    });
  });
  it('keeps the project source when the repository is removed', () => {
    expect(mergedSourcesBody(current, { repository: null })).toEqual({ onProjectPublish: true, repository: null });
  });
  it('starts from nothing for a provider with no setting', () => {
    expect(mergedSourcesBody(null, { repository: { repositoryId: 'r', path: 'a.json', branch: 'dev' } })).toEqual({
      onProjectPublish: false,
      repository: { repositoryId: 'r', path: 'a.json', branch: 'dev' },
    });
  });
  it('drops a stored repository whose row was deleted', () => {
    const gone = readContractSources({ ...STORED, repository: { ...STORED.repository, repositoryId: null } });
    expect(mergedSourcesBody(gone, { onProjectPublish: true }).repository).toBeNull();
  });
});

describe('the Repository source in the form', () => {
  const form: ProviderContractForm = {
    ...EMPTY_FORM,
    source: 'repository',
    provider: 'Billing Service',
    repositoryId: 'r1',
    repositoryPath: 'openapi/billing.yaml',
    repositoryBranch: 'main',
  };

  it('needs no provider version or evidence, and checks the repository fields', () => {
    expect(formProblems(form)).toEqual([]);
    expect(formProblems({ ...form, evidence: 'report' })).toEqual([]);
    const fields = formProblems({ ...form, repositoryId: '', repositoryPath: 'x.md', repositoryBranch: ' ' }).map((p) => p.field);
    expect(fields).toEqual(['repositoryId', 'repositoryPath', 'repositoryBranch']);
  });

  it('shows the pipeline’s per-push command and says a standing source has no flag', () => {
    const action = providerContractCommandAction(form, 'acme');
    expect(action.args).toEqual([{ value: 'openapi/billing.yaml' }]);
    const options = Object.fromEntries(action.options.map((o) => [o.flag, o.value]));
    expect(options['--provider-app-version']).toBe('<commit sha>');
    expect(options['--branch']).toBe('main');
    expect(action.unsupported).toEqual([{ what: 'Publishing a repository file on every push', reason: SOURCES_HAVE_NO_FLAG, inRest: false }]);
    expect(action.rest?.body).toEqual({ content: '<base64 of the file>', branch: 'main' });
  });

  it('says Do this on every publish has no flag', () => {
    const action = providerContractCommandAction({ ...EMPTY_FORM, project: 'billing-api', version: '2.7.0', followProject: true }, 'acme');
    expect(action.unsupported.map((u) => u.what)).toEqual(['Do this on every publish']);
  });
});

describe('the BFF body', () => {
  it('takes a repository, a project source, and the project to bind', () => {
    expect(
      pickSourcesRequest({
        provider: ' Billing Service ',
        onProjectPublish: true,
        bindProject: 'billing-api',
        repository: { repositoryId: 'r1', path: 'openapi.yaml', branch: 'main' },
      }),
    ).toEqual({
      ok: true,
      provider: 'Billing Service',
      patch: { onProjectPublish: true, bindProject: 'billing-api', repository: { repositoryId: 'r1', path: 'openapi.yaml', branch: 'main' } },
    });
    expect(pickSourcesRequest({ provider: 'x', repository: null })).toEqual({ ok: true, provider: 'x', patch: { repository: null } });
  });

  it.each([
    [null, 'JSON object'],
    [{ provider: 'x', onProjectPublish: true, onEveryTag: true }, 'Unknown field: onEveryTag'],
    [{ onProjectPublish: true }, 'provider is required'],
    [{ provider: 'x', onProjectPublish: 'yes' }, 'true or false'],
    [{ provider: 'x', bindProject: 'p' }, 'only sent with onProjectPublish: true'],
    [{ provider: 'x', repository: { repositoryId: 'r', path: 'a.yaml', branch: 'main', token: 't' } }, 'Unknown repository field: token'],
    [{ provider: 'x', repository: { repositoryId: 'r', path: '../a.yaml', branch: 'main' } }, '“..”'],
    [{ provider: 'x', repository: { repositoryId: 'r', path: 'a.yaml' } }, 'repository.branch is required'],
    [{ provider: 'x', repository: [] }, 'object or null'],
    [{ provider: 'x' }, 'Send onProjectPublish, repository, or both'],
  ])('refuses %j', (body, says) => {
    const picked = pickSourcesRequest(body);
    expect(picked.ok).toBe(false);
    if (!picked.ok) expect(picked.error).toContain(says);
  });
});

/** A fake REST: answers by `METHOD path`, records the calls. */
function rest(answers: Record<string, { status: number; body: unknown } | null>) {
  const calls: { method: string; path: string; body: unknown }[] = [];
  const call: RestCall = async (method, path, body) => {
    calls.push({ method, path, body });
    const key = `${method} ${path}`;
    return key in answers ? answers[key] : { status: 500, body: {} };
  };
  return { call, calls };
}

const PATH = 'pacticipants/Billing%20Service/contract-sources';

describe('saving the sources', () => {
  it('reads, then writes the whole setting with the change', async () => {
    const { call, calls } = rest({ [`GET ${PATH}`]: { status: 200, body: STORED }, [`PUT ${PATH}`]: { status: 200, body: { ...STORED, onProjectPublish: false } } });
    const answer = await saveSources(call, 'Billing Service', { onProjectPublish: false });
    expect(answer.status).toBe(200);
    expect(answer.body).toMatchObject({ success: true, onProjectPublish: false });
    expect(calls.map((c) => c.method)).toEqual(['GET', 'PUT']);
    expect(calls[1].body).toEqual({ onProjectPublish: false, repository: { repositoryId: 'r1', path: 'openapi.yaml', branch: 'main' } });
  });

  it('binds a provider bound to no project before following it', async () => {
    const unbound = { ...STORED, onProjectPublish: false, project: null, repository: null };
    const { call, calls } = rest({
      [`GET ${PATH}`]: { status: 200, body: unbound },
      'PATCH pacticipants/Billing%20Service': { status: 200, body: {} },
      [`PUT ${PATH}`]: { status: 200, body: STORED },
    });
    const answer = await saveSources(call, 'Billing Service', { onProjectPublish: true, bindProject: 'billing-api' });
    expect(answer.status).toBe(200);
    expect(calls.map((c) => `${c.method} ${c.path}`)).toEqual([`GET ${PATH}`, 'PATCH pacticipants/Billing%20Service', `PUT ${PATH}`]);
    expect(calls[1].body).toEqual({ project: 'billing-api' });
  });

  it('does not bind a provider already bound to that project', async () => {
    const { call, calls } = rest({ [`GET ${PATH}`]: { status: 200, body: STORED }, [`PUT ${PATH}`]: { status: 200, body: STORED } });
    await saveSources(call, 'Billing Service', { onProjectPublish: true, bindProject: 'billing-api' });
    expect(calls.map((c) => c.method)).toEqual(['GET', 'PUT']);
  });

  it('refuses — never re-binds — a provider bound to another project', async () => {
    const { call, calls } = rest({ [`GET ${PATH}`]: { status: 200, body: STORED } });
    const answer = await saveSources(call, 'Billing Service', { onProjectPublish: true, bindProject: 'payments-api' });
    expect(answer.status).toBe(409);
    expect(answer.body.error).toContain('bound to Billing API');
    expect(calls).toHaveLength(1);
  });

  it('says a provider that is not registered yet must publish first', async () => {
    const { call } = rest({ [`GET ${PATH}`]: { status: 404, body: { detail: { code: 'pacticipant-not-found' } } } });
    const answer = await saveSources(call, 'Billing Service', { onProjectPublish: true });
    expect(answer.status).toBe(404);
    expect(answer.body.error).toContain('is not registered yet');
  });

  it('keeps REST’s refusal of the write, with its code', async () => {
    const { call } = rest({
      [`GET ${PATH}`]: { status: 200, body: STORED },
      [`PUT ${PATH}`]: {
        status: 422,
        body: { detail: { code: 'contract-source-repository-unsupported', message: 'only GitHub repositories are supported' } },
      },
    });
    const answer = await saveSources(call, 'Billing Service', { repository: { repositoryId: 'g', path: 'a.yaml', branch: 'main' } });
    expect(answer.status).toBe(422);
    expect(answer.body).toMatchObject({ success: false, error: 'only GitHub repositories are supported' });
  });

  it('keeps REST’s refusal of the bind', async () => {
    const { call, calls } = rest({
      [`GET ${PATH}`]: { status: 200, body: { ...STORED, project: null } },
      'PATCH pacticipants/Billing%20Service': { status: 403, body: { detail: 'pacts:edit required' } },
    });
    const answer = await saveSources(call, 'Billing Service', { onProjectPublish: true, bindProject: 'billing-api' });
    expect(answer.status).toBe(403);
    expect(calls.map((c) => c.method)).toEqual(['GET', 'PATCH']);
  });

  it('is a 503 when REST cannot be reached, and a 400 for an unusable name', async () => {
    expect((await saveSources(async () => null, 'Billing Service', { onProjectPublish: true })).status).toBe(503);
    expect((await saveSources(rest({}).call, ' ', { onProjectPublish: true })).status).toBe(400);
  });
});

/** Keeps `ContractSources` in use as a type so a renamed field fails here. */
export const _typed: ContractSources | null = readContractSources(STORED);
