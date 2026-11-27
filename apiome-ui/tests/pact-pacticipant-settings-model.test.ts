/**
 * @jest-environment node
 */
/**
 * Create, edit and delete a pacticipant — PFX-8.10 (#7307): the model and the write proxies.
 *
 * * **Form**: a pacticipant read into the form; saving sends only what changed (`null` clears),
 *   and the labels to add and remove; the New dialog's body leaves empty fields out.
 * * **Checks**: what REST would refuse is named per field before anything is sent.
 * * **Proxy bodies**: an unknown field is refused with its name, never dropped; `null` only where
 *   REST clears; a delete reason of at most 500 characters.
 * * **Delete**: the consequence sentences (versions, pacts, results, who loses a partner, the
 *   grace period, what blocks it) and type-to-confirm.
 * * **The same, from anywhere**: the form as `apiome pact create-or-update-pacticipant` /
 *   `delete-pacticipant`, with what the command cannot carry listed.
 * * **Proxies**: forward as the signed-in user in the session tenant, refuse bad input without
 *   calling REST, keep REST's refusal.
 */

import { jest } from '@jest/globals';
import { NextRequest, NextResponse } from 'next/server';

let tenant: { user: { user_id: string }; slug: string } | { error: NextResponse } = {
  user: { user_id: 'u-1' },
  slug: 'acme',
};
const forwarded: Array<{ url: string; method: string; body?: unknown }> = [];
let restAnswer: { status: number; body: unknown } = { status: 200, body: { ok: true } };

jest.mock('@lib/connectors-proxy', () => ({
  resolveConnectorTenant: async () => tenant,
  tenantUrl: (slug: string, path: string) => `http://rest/v1/tenants/${slug}/${path}`,
  forwardConnectorRequest: async (url: string, init: { method: string; body?: unknown }) => {
    forwarded.push({ url, method: init.method, body: init.body });
    return restAnswer.status < 400
      ? NextResponse.json(restAnswer.body)
      : NextResponse.json(
          { success: false, error: 'A pacticipant named Ledger already exists.' },
          { status: restAnswer.status },
        );
  },
}));

jest.mock('@lib/rest-auth', () => ({
  createRestAuthHeaders: () => ({ Authorization: 'Bearer session' }),
  REST_API_BASE_URL: 'http://rest/v1',
}));

import {
  checkCreateBody,
  checkPatchBody,
  checkReason,
  confirmMatches,
  createBody,
  deleteCommandAction,
  deleteSentences,
  formFromPacticipant,
  handleOf,
  isDirty,
  isSendable,
  namesPhrase,
  pacticipantCommandAction,
  settingsChanges,
  settingsProblems,
  type DeletionImpact,
  type SettingsForm,
} from '../lib/pact-pacticipant-settings';
import { pactCommandSurfaces, unsupportedLines } from '../lib/pact-commands';
import type { Pacticipant } from '../lib/pact-pacticipants';
import { POST as createPost } from '../src/app/api/pact/pacticipants/route';
import {
  DELETE as deleteOne,
  PATCH as patchOne,
} from '../src/app/api/pact/pacticipants/[pacticipant]/route';
import { POST as restorePost } from '../src/app/api/pact/pacticipants/[pacticipant]/restore/route';
import { GET as impactGet } from '../src/app/api/pact/pacticipants/[pacticipant]/deletion-impact/route';
import {
  DELETE as labelDelete,
  PUT as labelPut,
} from '../src/app/api/pact/pacticipants/[pacticipant]/labels/[label]/route';

const ORDERS: Pacticipant = {
  id: '22222222-2222-4222-8222-222222222222',
  slug: 'orders-ui',
  name: 'Orders UI',
  display_name: null,
  aliases: [],
  main_branch: 'main',
  repository_url: 'https://github.com/acme/orders-ui',
  project_id: null,
  labels: ['web', 'storefront'],
};

const IMPACT: DeletionImpact = {
  slug: 'orders-ui',
  name: 'Orders UI',
  versions: 214,
  pacts: 31,
  verification_results: 90,
  providers: ['Billing Service', 'Orders API'],
  providers_total: 2,
  consumers: [],
  consumers_total: 0,
  in_use: [],
  blocked: false,
  grace_days: 30,
};

const form = (patch: Partial<SettingsForm> = {}): SettingsForm => ({
  ...formFromPacticipant(ORDERS),
  ...patch,
});

describe('the settings form', () => {
  it('reads a pacticipant into the form, empty strings for what is not set', () => {
    expect(formFromPacticipant(ORDERS)).toEqual({
      name: 'Orders UI',
      displayName: '',
      mainBranch: 'main',
      repositoryUrl: 'https://github.com/acme/orders-ui',
      projectId: '',
      labels: ['web', 'storefront'],
    });
  });

  it('sends only what changed, null to clear, and the labels to add and remove', () => {
    const original = form();
    expect(settingsChanges(original, original)).toEqual({
      patch: null,
      addLabels: [],
      removeLabels: [],
    });
    expect(isDirty(original, original)).toBe(false);
    const edited = form({
      name: ' Orders Web ',
      displayName: 'Orders (web)',
      repositoryUrl: '  ',
      projectId: 'p-1',
      labels: ['web', 'checkout', 'checkout'],
    });
    expect(settingsChanges(edited, original)).toEqual({
      patch: {
        name: 'Orders Web',
        display_name: 'Orders (web)',
        repository_url: null,
        project: 'p-1',
      },
      addLabels: ['checkout'],
      removeLabels: ['storefront'],
    });
    expect(isDirty(edited, original)).toBe(true);
    expect(settingsChanges(form({ projectId: '' }), form({ projectId: 'p-1' })).patch).toEqual({
      project: null,
    });
  });

  it('names what REST would refuse, per field', () => {
    expect(settingsProblems(form())).toEqual({});
    expect(isSendable(settingsProblems(form()))).toBe(true);
    const bad = settingsProblems(
      form({
        name: '!!!',
        mainBranch: 'main\tx',
        repositoryUrl: 'git@github.com:a/b.git',
        labels: [' padded'],
      }),
    );
    expect(bad).toEqual({
      name: 'A name needs at least one letter or digit.',
      mainBranch: 'A branch has no control characters.',
      repositoryUrl: 'Use an http(s) URL, such as https://github.com/acme/orders-ui.',
      labels: 'A label has no leading or trailing space.',
    });
    expect(settingsProblems(form({ name: '  ' })).name).toBe('Give the pacticipant a name.');
    expect(settingsProblems(form({ name: 'x'.repeat(256) })).name).toContain('255');
    expect(settingsProblems(form({ displayName: 'x'.repeat(256) })).displayName).toContain('255');
  });

  it('derives the handle the way REST does', () => {
    expect(handleOf('Billing Service')).toBe('billing-service');
    expect(handleOf('  Crème Brûlée  API ')).toBe('creme-brulee-api');
    expect(handleOf('!!!')).toBe('');
  });

  it('leaves empty fields out of a new pacticipant', () => {
    expect(
      createBody(form({ displayName: '', mainBranch: ' ', repositoryUrl: '', name: ' Billing ' })),
    ).toEqual({
      name: 'Billing',
    });
    expect(createBody(form({ projectId: 'p-1' }))).toMatchObject({
      project: 'p-1',
      main_branch: 'main',
    });
  });
});

describe('the proxy bodies', () => {
  it('refuses an unknown field by name, and anything that is not text', () => {
    expect(checkPatchBody({ name: 'x', slug: 'y', owner: 'z' })).toEqual({
      ok: false,
      error:
        'Not a pacticipant field: slug, owner. Send only name, display_name, main_branch, repository_url, project.',
    });
    expect(checkPatchBody({ main_branch: 3 })).toEqual({
      ok: false,
      error: 'main_branch must be text or null.',
    });
    expect(checkPatchBody({ name: null })).toEqual({ ok: false, error: 'name must be text.' });
    expect(checkPatchBody({})).toEqual({ ok: false, error: 'Nothing to change.' });
    expect(checkPatchBody([])).toEqual({ ok: false, error: 'Send a JSON object.' });
    expect(checkPatchBody({ repository_url: null, name: 'Orders Web' })).toEqual({
      ok: true,
      body: { repository_url: null, name: 'Orders Web' },
    });
  });

  it('needs a name to create, and never a null', () => {
    expect(checkCreateBody({ name: ' ' })).toEqual({
      ok: false,
      error: 'Give the pacticipant a name.',
    });
    expect(checkCreateBody({ name: 'A', main_branch: null })).toEqual({
      ok: false,
      error: 'main_branch must be text.',
    });
    expect(checkCreateBody({ name: 'A', labels: [] }).ok).toBe(false);
  });

  it('keeps a delete reason to 500 characters', () => {
    expect(checkReason(null)).toEqual({ ok: true, body: null });
    expect(checkReason('  retired  ')).toEqual({ ok: true, body: 'retired' });
    expect(checkReason('x'.repeat(501)).ok).toBe(false);
  });
});

describe('the delete dialog', () => {
  it('spells out what goes, who is affected and how long it can be restored', () => {
    const sentences = deleteSentences(IMPACT, 'Orders UI');
    expect(sentences.removes).toBe(
      'Its 214 versions, 31 pacts and 90 verification results go with it.',
    );
    expect(sentences.affects).toBe(
      '2 providers lose a consumer (Billing Service and Orders API); their can-i-deploy answers change.',
    );
    expect(sentences.restore).toBe('You can restore it for 30 days.');
    expect(sentences.blocked).toBeNull();
  });

  it('says one of each in the singular, and names both sides', () => {
    const sentences = deleteSentences(
      {
        ...IMPACT,
        versions: 1,
        pacts: 1,
        verification_results: 0,
        providers: ['Ledger'],
        providers_total: 1,
        consumers: ['Web'],
        consumers_total: 1,
        grace_days: 1,
      },
      'Orders UI',
    );
    expect(sentences.removes).toBe('Its 1 version, 1 pact and 0 verification results go with it.');
    expect(sentences.affects).toBe(
      '1 provider loses a consumer (Ledger); their can-i-deploy answers change. 1 consumer loses a provider (Web).',
    );
    expect(sentences.restore).toBe('You can restore it for 1 day.');
  });

  it('says which versions block the delete', () => {
    const sentences = deleteSentences(
      { ...IMPACT, in_use: ['3.3.2+77c0aa1'], blocked: true },
      'Orders UI',
    );
    expect(sentences.blocked).toBe(
      '3.3.2+77c0aa1 of Orders UI is deployed or released. Record the undeployment first.',
    );
  });

  it('lists at most three names and counts the rest', () => {
    expect(namesPhrase(['A', 'B', 'C', 'D'], 25)).toBe('A, B, C and 22 more');
    expect(namesPhrase(['A'], 1)).toBe('A');
  });

  it('confirms only on the exact handle', () => {
    expect(confirmMatches(' orders-ui ', 'orders-ui')).toBe(true);
    expect(confirmMatches('Orders UI', 'orders-ui')).toBe(false);
  });
});

describe('the same, from anywhere', () => {
  it('writes an edit as create-or-update-pacticipant by its stored name, and the rename as REST', () => {
    const original = form();
    const action = pacticipantCommandAction(
      form({ name: 'Orders Web', mainBranch: 'trunk', labels: ['web'] }),
      {
        tenant: 'acme',
        original: { slug: 'orders-ui', form: original },
      },
    );
    const surfaces = pactCommandSurfaces(action);
    expect(surfaces[0].text).toContain('apiome pact create-or-update-pacticipant');
    expect(surfaces[0].text).toContain("--name 'Orders UI'");
    expect(surfaces[0].text).toContain('--main-branch trunk');
    expect(surfaces[1].text).toContain('pact-broker create-or-update-pacticipant');
    const rest = surfaces.find((surface) => surface.id === 'rest');
    expect(rest?.text).toContain('PATCH /v1/tenants/acme/pacticipants/orders-ui');
    expect(rest?.text).toContain('"name": "Orders Web"');
    expect(unsupportedLines(action)).toEqual([
      expect.stringMatching(/^The new name is not carried by the command \(REST carries it\)/),
      expect.stringMatching(/^The labels is not carried by the command:/),
    ]);
  });

  it('writes a new pacticipant as the CLI and a REST POST, the linked project listed', () => {
    const action = pacticipantCommandAction(
      form({ name: 'Billing', labels: [], projectId: 'p-1' }),
      { tenant: '' },
    );
    expect(action.rest).toMatchObject({
      method: 'POST',
      path: '/v1/tenants/{tenant}/pacticipants',
    });
    expect(unsupportedLines(action)).toEqual([
      expect.stringMatching(/^The linked project is not carried/),
    ]);
  });

  it('writes a delete as delete-pacticipant, which Pact CLI does not have', () => {
    const surfaces = pactCommandSurfaces(deleteCommandAction('orders-ui', 'Orders UI', 'retired'));
    expect(surfaces[0].text).toContain('apiome pact delete-pacticipant');
    expect(surfaces[0].text).toContain('--reason retired');
    expect(surfaces[1].text).toBeNull();
    expect(surfaces.find((surface) => surface.id === 'rest')?.text).toContain(
      'DELETE /v1/tenants/{tenant}/pacticipants/orders-ui?reason=retired',
    );
  });
});

describe('the /api/pact/pacticipants write proxies', () => {
  const ctx = (params: Record<string, string>) => ({ params: Promise.resolve(params) }) as never;
  const req = (path: string, init?: { method: string; body?: string }) =>
    new NextRequest(`http://ui${path}`, init as never);
  const json = (method: string, value: unknown) => ({ method, body: JSON.stringify(value) });
  const rest = 'http://rest/v1/tenants/acme';

  beforeEach(() => {
    tenant = { user: { user_id: 'u-1' }, slug: 'acme' };
    forwarded.length = 0;
    restAnswer = { status: 200, body: { ok: true } };
  });

  it('forwards create, patch, delete, restore, impact and labels to their REST routes', async () => {
    const one = ctx({ pacticipant: 'orders-ui' });
    await createPost(req('/api/pact/pacticipants', json('POST', { name: 'Billing' })));
    await patchOne(
      req('/api/pact/pacticipants/orders-ui', json('PATCH', { name: 'Orders Web' })),
      one,
    );
    await deleteOne(
      req('/api/pact/pacticipants/orders-ui?reason=retired', { method: 'DELETE' }),
      one,
    );
    await deleteOne(req('/api/pact/pacticipants/orders-ui', { method: 'DELETE' }), one);
    await restorePost(req('/api/pact/pacticipants/orders-ui/restore', { method: 'POST' }), one);
    await impactGet(req('/api/pact/pacticipants/orders-ui/deletion-impact'), one);
    await labelPut(
      req('/api/pact/pacticipants/orders-ui/labels/team%20a', { method: 'PUT' }),
      ctx({ pacticipant: 'orders-ui', label: 'team a' }),
    );
    await labelDelete(
      req('/api/pact/pacticipants/orders-ui/labels/web', { method: 'DELETE' }),
      ctx({ pacticipant: 'orders-ui', label: 'web' }),
    );
    expect(forwarded).toEqual([
      { method: 'POST', url: `${rest}/pacticipants`, body: { name: 'Billing' } },
      { method: 'PATCH', url: `${rest}/pacticipants/orders-ui`, body: { name: 'Orders Web' } },
      { method: 'DELETE', url: `${rest}/pacticipants/orders-ui?reason=retired`, body: undefined },
      { method: 'DELETE', url: `${rest}/pacticipants/orders-ui`, body: undefined },
      { method: 'POST', url: `${rest}/pacticipants/orders-ui/restore`, body: undefined },
      { method: 'GET', url: `${rest}/pacticipants/orders-ui/deletion-impact`, body: undefined },
      { method: 'PUT', url: `${rest}/pacticipants/orders-ui/labels/team%20a`, body: undefined },
      { method: 'DELETE', url: `${rest}/pacticipants/orders-ui/labels/web`, body: undefined },
    ]);
  });

  it('refuses bad input without calling REST, saying what was wrong', async () => {
    const bad = ctx({ pacticipant: 'Not A Handle' });
    const answers = [
      await createPost(req('/api/pact/pacticipants', { method: 'POST', body: 'not json' })),
      await createPost(req('/api/pact/pacticipants', json('POST', { name: 'A', owner: 'x' }))),
      await patchOne(
        req('/api/pact/pacticipants/x', json('PATCH', { slug: 'y' })),
        ctx({ pacticipant: 'orders-ui' }),
      ),
      await patchOne(req('/api/pact/pacticipants/x', json('PATCH', { name: 'A' })), bad),
      await deleteOne(
        req('/api/pact/pacticipants/orders-ui?force=true', { method: 'DELETE' }),
        ctx({ pacticipant: 'orders-ui' }),
      ),
      await deleteOne(
        req(`/api/pact/pacticipants/orders-ui?reason=${'x'.repeat(501)}`, { method: 'DELETE' }),
        ctx({ pacticipant: 'orders-ui' }),
      ),
      await restorePost(req('/api/pact/pacticipants/x/restore', { method: 'POST' }), bad),
      await impactGet(req('/api/pact/pacticipants/x/deletion-impact'), bad),
      await labelPut(
        req('/api/pact/pacticipants/orders-ui/labels/%20x', { method: 'PUT' }),
        ctx({ pacticipant: 'orders-ui', label: ' x' }),
      ),
      await labelDelete(
        req('/api/pact/pacticipants/x/labels/web', { method: 'DELETE' }),
        ctx({ pacticipant: 'Not A Handle', label: 'web' }),
      ),
    ];
    expect(answers.map((answer) => answer.status)).toEqual([
      400, 400, 400, 404, 400, 400, 404, 404, 400, 404,
    ]);
    expect(((await answers[1].json()) as { error: string }).error).toContain(
      'Not a pacticipant field: owner',
    );
    // `force` is never forwarded: a deployed pacticipant cannot be deleted from the UI.
    expect(((await answers[4].json()) as { error: string }).error).toBe(
      'Unknown parameter: force. Send only reason.',
    );
    expect(forwarded).toHaveLength(0);
  });

  it('keeps REST’s refusal and the session’s own', async () => {
    restAnswer = { status: 409, body: {} };
    const taken = await patchOne(
      req('/api/pact/pacticipants/orders-ui', json('PATCH', { name: 'Ledger' })),
      ctx({ pacticipant: 'orders-ui' }),
    );
    expect(taken.status).toBe(409);
    expect(((await taken.json()) as { error: string }).error).toBe(
      'A pacticipant named Ledger already exists.',
    );
    tenant = {
      error: NextResponse.json({ success: false, error: 'Unauthorized' }, { status: 401 }),
    };
    expect(
      (await createPost(req('/api/pact/pacticipants', json('POST', { name: 'A' })))).status,
    ).toBe(401);
    expect(forwarded).toHaveLength(1);
  });
});
