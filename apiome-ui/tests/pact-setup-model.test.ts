/**
 * The Contracts guided set-up's model — PFX-8.20 (#7317), `lib/pact-setup.ts`.
 *
 * * REST's answer is read defensively: six known sections or nothing; anything missing reads as empty;
 * * the open section is the next one; the minutes left count only what is not done;
 * * a candidate's create body carries its branch, repository and project when known;
 * * an environment name is one word and not a duplicate; production carries the contract switch;
 * * the snippets never contain a key;
 * * the three proxies' bodies are checked: an unknown field, section, id or path is refused by name;
 * * the page's command is `apiome pact setup` with the flags its choices mean.
 */

import fixture from './fixtures/pact-setup.json';
import { PACT_VERBS, pactCommandSurfaces } from '../lib/pact-commands';
import {
  ENVIRONMENT_PRESETS,
  FIRST_PACT_CARDS,
  SETUP_SECTION_IDS,
  candidateCreateBody,
  checkPullRequestsBody,
  checkSaveBody,
  checkSecretsBody,
  ciKeyName,
  environmentCreateBody,
  environmentNameProblem,
  minutesLeft,
  newCandidates,
  openSection,
  readSetupState,
  secretsSnippet,
  setupCommandAction,
  variablesText,
  type SetupState,
} from '../lib/pact-setup';

const REPO = '22222222-2222-4222-8222-222222222222';
const state = readSetupState(fixture) as SetupState;

describe('reading the answer', () => {
  it('reads the six sections, the candidates and the repositories', () => {
    expect(state.sections.map((section) => section.id)).toEqual([...SETUP_SECTION_IDS]);
    expect(state.done).toBe(2);
    expect(state.candidates).toHaveLength(3);
    expect(state.github.repositories.map((repository) => repository.full_name)).toEqual(['acme/billing-service', 'acme/orders-ui']);
    expect(state.can_edit).toBe(true);
  });

  it('answers null for anything that is not six known sections', () => {
    expect(readSetupState(null)).toBeNull();
    expect(readSetupState({ sections: [] })).toBeNull();
    expect(readSetupState({ sections: fixture.sections.slice(0, 5) })).toBeNull();
    expect(readSetupState({ sections: [...fixture.sections.slice(0, 5), { id: 'billing', state: 'done' }] })).toBeNull();
  });

  it('reads what is missing as empty and an unknown state as to do', () => {
    const sparse = readSetupState({ sections: fixture.sections.map((section) => ({ id: section.id, state: 'odd' })) }) as SetupState;
    expect(sparse.sections.every((section) => section.state === 'todo')).toBe(true);
    expect(sparse.facts.environments).toEqual([]);
    expect(sparse.candidates).toEqual([]);
    expect(sparse.github).toEqual({ linked: false, reason: null, repositories: [] });
    expect(sparse.saved).toEqual({ marked: [], first_pact_path: null, ci_key: null });
    expect(sparse.can_edit).toBe(false);
  });

  it('drops a candidate or repository it cannot name, and a mark it does not know', () => {
    const odd = readSetupState({
      ...fixture,
      candidates: [{ slug: 'x' }, fixture.candidates[0]],
      github: { linked: true, repositories: [{ id: REPO }, fixture.github.repositories[0]] },
      saved: { marked: ['gates', 'billing'], first_pact_path: 'mock', ci_key: { id: 'k' } },
    }) as SetupState;
    expect(odd.candidates.map((candidate) => candidate.name)).toEqual(['Billing API']);
    expect(odd.github.repositories).toHaveLength(1);
    expect(odd.saved).toEqual({ marked: ['gates'], first_pact_path: null, ci_key: null });
  });
});

describe('the sections', () => {
  it('opens the next section, or none when all are done', () => {
    expect(openSection(state)).toBe('pipelines');
    const done = { ...state, sections: state.sections.map((section) => ({ ...section, state: 'done' as const })) };
    expect(openSection(done)).toBeNull();
    expect(minutesLeft(done)).toBe(0);
  });

  it('counts the minutes of what is not done', () => {
    expect(minutesLeft(state)).toBe(8);
  });
});

describe('pacticipants and environments', () => {
  it('creates only candidates that are not pacticipants yet', () => {
    expect(newCandidates(state).map((candidate) => candidate.name)).toEqual(['Payments API']);
  });

  it('sends the branch, repository and project a candidate has', () => {
    expect(candidateCreateBody(state.candidates[0])).toEqual({
      name: 'Billing API',
      main_branch: 'main',
      repository_url: 'https://github.com/acme/billing-service',
      project: 'billing-api',
    });
    expect(candidateCreateBody(state.candidates[1])).toEqual({ name: 'Payments API', project: 'payments-api' });
  });

  it('refuses an environment name that is empty, has a space or is taken', () => {
    expect(environmentNameProblem('  ', [])).toMatch(/Give/);
    expect(environmentNameProblem('pre prod', [])).toMatch(/one word/);
    expect(environmentNameProblem('Staging', ['staging'])).toMatch(/already there/);
    expect(environmentNameProblem('x'.repeat(256), [])).toMatch(/255/);
    expect(environmentNameProblem('qa', ['staging'])).toBeNull();
  });

  it('marks production and applies the contract switch to it only', () => {
    expect(ENVIRONMENT_PRESETS.map((preset) => preset.name)).toEqual(['production', 'staging', 'development']);
    expect(environmentCreateBody('production', true)).toEqual({
      name: 'production',
      displayName: 'Production',
      production: true,
      contractRequired: true,
      contacts: [],
    });
    expect(environmentCreateBody('production', false).contractRequired).toBe(false);
    expect(environmentCreateBody('staging', true)).toMatchObject({ production: false, contractRequired: false });
    expect(environmentCreateBody('qa', true)).toMatchObject({ name: 'qa', displayName: 'qa', production: false });
  });
});

describe('snippets', () => {
  it('names both variables and never a key', () => {
    const text = variablesText('https://api.apiome.dev/v1/tenants/acme/pact-broker');
    expect(text).toBe('PACT_BROKER_BASE_URL=https://api.apiome.dev/v1/tenants/acme/pact-broker\nPACT_BROKER_TOKEN=<the key above>');
    expect(variablesText(null)).toContain('<workspace>');
  });

  it('sets both secrets with the GitHub CLI, the key from a variable', () => {
    const lines = secretsSnippet('https://api.apiome.dev/v1/tenants/acme/pact-broker', 'acme/orders-ui').split('\n');
    expect(lines).toEqual([
      'gh secret set PACT_BROKER_BASE_URL --repo acme/orders-ui --body "https://api.apiome.dev/v1/tenants/acme/pact-broker"',
      'gh secret set PACT_BROKER_TOKEN --repo acme/orders-ui --body "$APIOME_API_KEY"',
    ]);
    expect(secretsSnippet(null)).toContain('<owner>/<repository>');
  });

  it('names the CI key by when it was made', () => {
    expect(ciKeyName(new Date('2026-11-30T10:15:42Z'))).toBe('Contracts CI (set-up 2026-11-30 10:15)');
  });

  it('sends each first-pact path to a page that exists', () => {
    expect(FIRST_PACT_CARDS.tests.route).toBe('/ade/dashboard/pacts/publish');
    expect(FIRST_PACT_CARDS.spec.route).toBe('/ade/dashboard/pacts/export?kind=pact');
  });
});

describe('checking a save', () => {
  it('passes marks, the path and the key', () => {
    expect(checkSaveBody({ mark: { gates: true, pipelines: false } })).toEqual({ ok: true, body: { mark: { gates: true, pipelines: false } } });
    expect(checkSaveBody({ first_pact_path: 'spec' })).toEqual({ ok: true, body: { first_pact_path: 'spec' } });
    expect(checkSaveBody({ ci_key: { id: REPO, prefix: 'apk_9f2c...' } })).toEqual({ ok: true, body: { ci_key: { id: REPO, prefix: 'apk_9f2c...' } } });
    expect(checkSaveBody({ forget_ci_key: true })).toEqual({ ok: true, body: { forget_ci_key: true } });
  });

  it.each([
    [null, 'JSON object'],
    [{}, 'Nothing to save'],
    [{ done: ['gates'] }, 'Unknown field: done'],
    [{ mark: { billing: true } }, 'Unknown section: billing'],
    [{ mark: { gates: 'yes' } }, 'mark.gates'],
    [{ mark: [] }, 'mark must be'],
    [{ first_pact_path: 'mock' }, 'tests or spec'],
    [{ ci_key: { id: 'nope', prefix: 'p' } }, 'ci_key must be'],
    [{ ci_key: { id: REPO, prefix: 'p', secret: 's' } }, 'ci_key must be'],
    [{ ci_key: { id: REPO, prefix: 'p' }, forget_ci_key: true }, 'not both'],
    [{ forget_ci_key: 'yes' }, 'forget_ci_key'],
  ])('refuses %j', (body, reason) => {
    const checked = checkSaveBody(body);
    expect(checked.ok).toBe(false);
    if (!checked.ok) expect(checked.error).toContain(reason);
  });
});

describe('checking the GitHub requests', () => {
  it('passes repositories and the key, once each, and takes no address from the browser', () => {
    expect(checkSecretsBody({ repository_ids: [REPO, REPO], token: '  apk_live_0123456789  ' })).toEqual({
      ok: true,
      body: { repository_ids: [REPO], token: 'apk_live_0123456789' },
    });
    const refused = checkSecretsBody({ repository_ids: [REPO], token: 'apk_live_0123456789', broker_base_url: 'https://evil.example' });
    expect(refused).toEqual({ ok: false, error: 'Unknown field: broker_base_url.' });
  });

  it.each([
    [{ repository_ids: [], token: 'apk_live_0123456789' }, 'repository_ids'],
    [{ repository_ids: ['nope'], token: 'apk_live_0123456789' }, 'repository_ids'],
    [{ repository_ids: [REPO], token: 'short' }, 'token'],
    [{ repository_ids: [REPO] }, 'token'],
  ])('refuses secrets %j', (body, reason) => {
    const checked = checkSecretsBody(body);
    expect(checked.ok).toBe(false);
    if (!checked.ok) expect(checked.error).toContain(reason);
  });

  it('passes a pull-request request with both steps by default', () => {
    expect(checkPullRequestsBody({ repositories: [{ repository_id: REPO, pacticipant: ' Billing Service ' }], environment: 'production' })).toEqual({
      ok: true,
      body: {
        repositories: [{ repository_id: REPO, pacticipant: 'Billing Service' }],
        environment: 'production',
        can_i_deploy: true,
        record_deployment: true,
        preview: false,
      },
    });
  });

  it.each([
    [{ repositories: [], environment: 'production' }, '1 to 50'],
    [{ repositories: [{ repository_id: 'x', pacticipant: 'a' }], environment: 'production' }, 'repository_id, pacticipant'],
    [{ repositories: [{ repository_id: REPO, pacticipant: '' }], environment: 'production' }, 'needs its pacticipant'],
    [{ repositories: [{ repository_id: REPO, pacticipant: 'a\nb' }], environment: 'production' }, 'needs its pacticipant'],
    [{ repositories: [{ repository_id: REPO, pacticipant: 'a', branch: 'x' }], environment: 'production' }, 'repository_id, pacticipant'],
    [{ repositories: [{ repository_id: REPO, pacticipant: 'a' }], environment: 'pre prod' }, 'environment'],
    [{ repositories: [{ repository_id: REPO, pacticipant: 'a' }], environment: 'production', preview: 'yes' }, 'preview'],
    [{ repositories: [{ repository_id: REPO, pacticipant: 'a' }], environment: 'production', can_i_deploy: false, record_deployment: false }, 'at least one'],
    [{ repositories: [{ repository_id: REPO, pacticipant: 'a' }], environment: 'production', title: 'x' }, 'Unknown field: title'],
  ])('refuses pull requests %j', (body, reason) => {
    const checked = checkPullRequestsBody(body);
    expect(checked.ok).toBe(false);
    if (!checked.ok) expect(checked.error).toContain(reason);
  });
});

describe('the same, from anywhere', () => {
  it('is apiome pact setup with the flags the page means', () => {
    const action = setupCommandAction({ fromProjects: true, environments: ['production', 'staging'], ci: true });
    const apiome = pactCommandSurfaces(action).find((surface) => surface.id === 'apiome');
    expect(apiome?.text).toContain('apiome pact setup');
    expect(apiome?.text).toContain('--from-projects');
    expect(apiome?.text).toContain('--environments production,staging');
    expect(apiome?.text).toContain('--ci github');
    expect(PACT_VERBS.setup.rest).toBe('GET /v1/tenants/{tenant}/pact-setup');
  });

  it('leaves out what was not chosen', () => {
    const action = setupCommandAction({ fromProjects: false, environments: [], ci: false });
    const text = pactCommandSurfaces(action).find((surface) => surface.id === 'apiome')?.text ?? '';
    expect(text).not.toContain('--from-projects');
    expect(text).not.toContain('--environments');
    expect(text).not.toContain('--ci');
  });
});
