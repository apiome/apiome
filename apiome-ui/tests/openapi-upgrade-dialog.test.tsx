/**
 * Upgrade OpenAPI version dialog — COA-2.6 (#7049).
 *
 * Pins: the model's wording and helpers (headline, origin note, hop groups, the targets offered,
 * label checks, the request bodies); the dialog plans on open and again when the target changes,
 * lists the per-rule counts and every change with **Review** marks, applies with the plan digest and
 * the label, refuses a taken label before sending, shows REST's refusal instead of closing, and has
 * nothing to apply for a version already at the target. The Versions row menu offers the item only
 * with `versions:create`; the catalog header only for an OpenAPI / Swagger item an editor may import
 * into. Plus axe on the dialog.
 *
 * The docs screenshot fixture (`openapi-upgrade-plan`) is written when `OPENAPI_UPGRADE_FIXTURE_DUMP=1`:
 *
 *     OPENAPI_UPGRADE_FIXTURE_DUMP=1 npx jest tests/openapi-upgrade-dialog.test.tsx
 */

import fs from 'fs';
import path from 'path';
import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { axe } from 'jest-axe';
import 'jest-axe/extend-expect';

import { OpenapiUpgradeDialog } from '../src/app/components/ade/openapi-upgrade/OpenapiUpgradeDialog';
import {
  applyUpgradePlan,
  familyName,
  groupChangesByHop,
  originNote,
  planHeadline,
  requestUpgradePlan,
  targetsAfter,
  versionLabelProblem,
  type UpgradePlan,
} from '../src/app/components/ade/openapi-upgrade/openapiUpgradeModel';
import { catalogDetailActions, isOpenapiSourceFormat } from '../src/app/components/ade/catalog/detail/catalogItemView';

const AXE_OPTIONS = {
  rules: { 'color-contrast': { enabled: false }, region: { enabled: false } },
} as const;

const PROJECT = 'proj-1';
const VERSION = 'ver-1';

const PLAN: UpgradePlan = {
  source_version: '2.0',
  source_family: '2.0',
  target: '3.2',
  target_version: '3.2.0',
  hops: ['2.0→3.0', '3.0→3.1', '3.1→3.2'],
  already_current: false,
  change_count: 6,
  review_count: 1,
  origin: 'captured',
  plan_digest: 'sha256:plan',
  version_record_id: VERSION,
  version_label: '1.4.0',
  rules: [
    { rule: 'openapi-version', title: 'Version string', hop: '*', count: 3 },
    { rule: 'definition-to-component-schema', title: 'definitions → components.schemas', hop: '2.0→3.0', count: 1 },
    { rule: 'collection-format-to-style', title: 'collectionFormat → style / explode', hop: '2.0→3.0', count: 1 },
    { rule: 'nullable-to-type-array', title: 'nullable → type array', hop: '3.0→3.1', count: 1 },
  ],
  changes: [
    { hop: '2.0→3.0', rule: 'openapi-version', title: 'Version string', pointer: '/swagger', summary: 'swagger 2.0 becomes openapi 3.0.4', review: false },
    { hop: '2.0→3.0', rule: 'definition-to-component-schema', title: 'definitions → components.schemas', pointer: '/definitions/Book', summary: 'definitions/Book moves to components/schemas/Book', review: false, target_pointer: '/components/schemas/Book' },
    { hop: '2.0→3.0', rule: 'collection-format-to-style', title: 'collectionFormat → style / explode', pointer: '/paths/~1books/get/parameters/1', summary: 'collectionFormat tsv has no OpenAPI 3 style; kept as x-collectionFormat', review: true },
    { hop: '3.0→3.1', rule: 'openapi-version', title: 'Version string', pointer: '/openapi', summary: 'openapi 3.0.4 becomes 3.1.2', review: false },
    { hop: '3.0→3.1', rule: 'nullable-to-type-array', title: 'nullable → type array', pointer: '/components/schemas/Book/properties/title', summary: 'nullable: true becomes type ["string", "null"]', review: false },
    { hop: '3.1→3.2', rule: 'openapi-version', title: 'Version string', pointer: '/openapi', summary: 'openapi 3.1.2 becomes 3.2.0', review: false },
  ],
};

type FetchCall = { url: string; body: Record<string, unknown> };

/** Mock fetch: plan answers `plan` (or `planFor(target)`), apply answers `applyResponse`. */
function mockFetch(options: {
  planFor?: (target: string) => UpgradePlan;
  apply?: { status: number; body: unknown };
} = {}): FetchCall[] {
  const calls: FetchCall[] = [];
  global.fetch = jest.fn(async (url: string, init?: RequestInit) => {
    const body = JSON.parse(String(init?.body ?? '{}'));
    calls.push({ url, body });
    if (url.endsWith('/plan')) {
      const plan = options.planFor ? options.planFor(String(body.target)) : PLAN;
      return { ok: true, status: 200, json: async () => plan } as Response;
    }
    const apply = options.apply ?? {
      status: 200,
      body: {
        project_id: PROJECT,
        version_record_id: 'ver-new',
        version_label: '2.0.0',
        source_version_record_id: VERSION,
        target_version: '3.2.0',
        change_count: 6,
      },
    };
    return { ok: apply.status < 400, status: apply.status, json: async () => apply.body } as Response;
  }) as unknown as typeof fetch;
  return calls;
}

function renderDialog(props: Partial<React.ComponentProps<typeof OpenapiUpgradeDialog>> = {}) {
  const onApplied = jest.fn();
  render(
    <OpenapiUpgradeDialog
      open
      onOpenChange={() => undefined}
      projectId={PROJECT}
      versionId={VERSION}
      versionLabel="1.4.0"
      existingLabels={['1.4.0']}
      onApplied={onApplied}
      {...props}
    />,
  );
  return { onApplied };
}

// ---------------------------------------------------------------------------------------
// Model
// ---------------------------------------------------------------------------------------

describe('openapiUpgradeModel', () => {
  it('names families and writes the headline', () => {
    expect(familyName('2.0')).toBe('Swagger 2.0');
    expect(familyName('3.1')).toBe('OpenAPI 3.1');
    expect(planHeadline(PLAN)).toBe('Swagger 2.0 (2.0) → OpenAPI 3.2.0 — 6 changes, 1 to review');
    expect(planHeadline({ ...PLAN, change_count: 1, review_count: 0 })).toBe('Swagger 2.0 (2.0) → OpenAPI 3.2.0 — 1 change');
    expect(planHeadline({ ...PLAN, already_current: true, source_family: '3.2', source_version: '3.2.0' })).toBe(
      'This version is already OpenAPI 3.2 (3.2.0). Nothing to upgrade.',
    );
  });

  it('explains where the plan starts', () => {
    expect(originNote('rebuilt')).toContain('OpenAPI 3.1');
    expect(originNote('captured')).toContain('imported from');
    expect(originNote('request')).toContain('you supplied');
  });

  it('groups changes by hop in hop order', () => {
    expect(groupChangesByHop(PLAN).map((g) => [g.hop, g.changes.length])).toEqual([
      ['2.0→3.0', 3],
      ['3.0→3.1', 2],
      ['3.1→3.2', 1],
    ]);
  });

  it('offers only later targets', () => {
    expect(targetsAfter(null)).toEqual(['3.0', '3.1', '3.2']);
    expect(targetsAfter('2.0')).toEqual(['3.0', '3.1', '3.2']);
    expect(targetsAfter('3.0')).toEqual(['3.1', '3.2']);
    expect(targetsAfter('3.2')).toEqual([]);
  });

  it('checks the new label', () => {
    expect(versionLabelProblem('', ['1.0.0'])).toBeNull();
    expect(versionLabelProblem(' 2.0.0 ', ['1.0.0'])).toBeNull();
    expect(versionLabelProblem('1.0.0', ['1.0.0'])).toContain('already exists');
    expect(versionLabelProblem('x'.repeat(129), [])).toContain('128');
  });

  it('sends the plan and apply bodies', async () => {
    const calls = mockFetch();
    await requestUpgradePlan(PROJECT, VERSION, '3.1');
    await applyUpgradePlan(PROJECT, VERSION, PLAN, '  2.0.0 ');
    await applyUpgradePlan(PROJECT, undefined, PLAN, '');
    expect(calls[0]).toEqual({
      url: '/api/openapi-upgrade/plan',
      body: { target: '3.1', project_id: PROJECT, version: VERSION, include_document: false },
    });
    expect(calls[1].body).toEqual({
      target: '3.2',
      project_id: PROJECT,
      version: VERSION,
      plan_digest: 'sha256:plan',
      version_label: '2.0.0',
    });
    expect(calls[2].body).toEqual({ target: '3.2', project_id: PROJECT, plan_digest: 'sha256:plan' });
  });

  it('throws the proxy error message', async () => {
    mockFetch({ apply: { status: 409, body: { success: false, error: 'The version changed since the plan was made.' } } });
    await expect(applyUpgradePlan(PROJECT, VERSION, PLAN, '')).rejects.toThrow('The version changed since the plan was made.');
  });
});

// ---------------------------------------------------------------------------------------
// Dialog
// ---------------------------------------------------------------------------------------

describe('OpenapiUpgradeDialog', () => {
  it('plans on open and lists every change with review marks', async () => {
    const calls = mockFetch();
    renderDialog();
    expect(screen.getByTestId('openapi-upgrade-planning')).toBeInTheDocument();
    expect(await screen.findByTestId('openapi-upgrade-headline')).toHaveTextContent(
      'Swagger 2.0 (2.0) → OpenAPI 3.2.0 — 6 changes, 1 to review',
    );
    expect(calls[0].body).toMatchObject({ target: '3.2', project_id: PROJECT, version: VERSION });
    const rules = screen.getByTestId('openapi-upgrade-rules');
    expect(within(rules).getAllByRole('row')).toHaveLength(PLAN.rules.length + 1);
    expect(screen.getAllByRole('listitem')).toHaveLength(PLAN.changes.length);
    expect(screen.getAllByText('Review')).toHaveLength(1);
    expect(screen.getByText('/components/schemas/Book/properties/title')).toBeInTheDocument();
  });

  it('plans again when the target changes', async () => {
    const calls = mockFetch({ planFor: (target) => ({ ...PLAN, target: target as UpgradePlan['target'], target_version: `${target}.x` }) });
    renderDialog();
    await screen.findByTestId('openapi-upgrade-headline');
    fireEvent.click(screen.getByRole('radio', { name: 'OpenAPI 3.1' }));
    await waitFor(() => expect(screen.getByTestId('openapi-upgrade-headline')).toHaveTextContent('OpenAPI 3.1.x'));
    expect(calls.map((call) => call.body.target)).toEqual(['3.2', '3.1']);
  });

  it('applies with the digest and the label, then reports the new version', async () => {
    const calls = mockFetch();
    const { onApplied } = renderDialog();
    await screen.findByTestId('openapi-upgrade-headline');
    fireEvent.change(screen.getByTestId('openapi-upgrade-label'), { target: { value: '2.0.0' } });
    fireEvent.click(screen.getByTestId('openapi-upgrade-apply'));
    expect(await screen.findByTestId('openapi-upgrade-applied')).toHaveTextContent('Created version 2.0.0 (OpenAPI 3.2.0).');
    expect(calls[1]).toEqual({
      url: '/api/openapi-upgrade/apply',
      body: { target: '3.2', project_id: PROJECT, version: VERSION, plan_digest: 'sha256:plan', version_label: '2.0.0' },
    });
    expect(onApplied).toHaveBeenCalledWith(expect.objectContaining({ version_record_id: 'ver-new' }));
    expect(screen.queryByTestId('openapi-upgrade-apply')).not.toBeInTheDocument();
  });

  it('refuses a taken label before sending', async () => {
    const calls = mockFetch();
    renderDialog();
    await screen.findByTestId('openapi-upgrade-headline');
    fireEvent.change(screen.getByTestId('openapi-upgrade-label'), { target: { value: '1.4.0' } });
    expect(screen.getByText('Version 1.4.0 already exists. Choose another label.')).toBeInTheDocument();
    expect(screen.getByTestId('openapi-upgrade-apply')).toBeDisabled();
    expect(calls).toHaveLength(1);
  });

  it('shows a refusal and stays open', async () => {
    mockFetch({ apply: { status: 409, body: { success: false, error: 'The version changed since the plan was made.' } } });
    renderDialog();
    await screen.findByTestId('openapi-upgrade-headline');
    fireEvent.click(screen.getByTestId('openapi-upgrade-apply'));
    expect(await screen.findByTestId('openapi-upgrade-error')).toHaveTextContent('The version changed since the plan was made.');
    expect(screen.getByTestId('openapi-upgrade-dialog')).toBeInTheDocument();
  });

  it('shows a plan refusal', async () => {
    global.fetch = jest.fn(async () => ({ ok: false, status: 409, json: async () => ({ success: false, error: 'This version has no OpenAPI source to upgrade.' }) })) as unknown as typeof fetch;
    renderDialog();
    expect(await screen.findByTestId('openapi-upgrade-error')).toHaveTextContent('no OpenAPI source');
    expect(screen.getByTestId('openapi-upgrade-apply')).toBeDisabled();
  });

  it('has nothing to apply for a version already at the target', async () => {
    mockFetch({ planFor: () => ({ ...PLAN, already_current: true, source_family: '3.2', source_version: '3.2.0', hops: [], changes: [], rules: [], change_count: 0, review_count: 0 }) });
    renderDialog();
    expect(await screen.findByTestId('openapi-upgrade-headline')).toHaveTextContent('Nothing to upgrade');
    expect(screen.getByTestId('openapi-upgrade-apply')).toBeDisabled();
    expect(screen.queryByTestId('openapi-upgrade-label')).not.toBeInTheDocument();
    expect(screen.getByRole('radio', { name: 'OpenAPI 3.1' })).toBeDisabled();
  });

  it('has no axe violations with a plan', async () => {
    mockFetch();
    renderDialog();
    await screen.findByTestId('openapi-upgrade-headline');
    expect(await axe(screen.getByTestId('openapi-upgrade-dialog'), AXE_OPTIONS)).toHaveNoViolations();
  });

  it('renders the docs fixture from a given plan (and writes it on request)', async () => {
    global.fetch = jest.fn() as unknown as typeof fetch;
    renderDialog({ initialPlan: PLAN });
    const dialog = screen.getByTestId('openapi-upgrade-dialog');
    expect(global.fetch).not.toHaveBeenCalled();
    expect(within(dialog).getByTestId('openapi-upgrade-headline')).toBeInTheDocument();
    if (process.env.OPENAPI_UPGRADE_FIXTURE_DUMP !== '1') return;
    const out = path.join(__dirname, '..', 'e2e', 'fixtures', 'hive-version-dialogs');
    fs.mkdirSync(out, { recursive: true });
    // Radix portals the overlay and the dialog straight into <body>: keep just those two, as siblings
    // (a wrapper around two fixed boxes has no size, so the screenshot would never see it).
    const overlay = document.querySelector('.hive-overlay') as HTMLElement;
    fs.writeFileSync(path.join(out, 'openapi-upgrade-plan.html'), overlay.outerHTML + dialog.outerHTML);
  });
});

// ---------------------------------------------------------------------------------------
// Entry points
// ---------------------------------------------------------------------------------------

describe('entry points', () => {
  it('offers the catalog action only for an OpenAPI / Swagger item an editor may import into', () => {
    expect(isOpenapiSourceFormat('openapi')).toBe(true);
    expect(isOpenapiSourceFormat('swagger-2.0')).toBe(true);
    expect(isOpenapiSourceFormat('graphql')).toBe(false);
    expect(isOpenapiSourceFormat(null)).toBe(false);
    const item = { deleted_at: null, sourceFormat: 'swagger-2.0', conversion: null };
    expect(catalogDetailActions(item).upgradeOpenapi.shown).toBe(true);
    expect(catalogDetailActions({ ...item, sourceFormat: 'asyncapi' }).upgradeOpenapi.shown).toBe(false);
    expect(catalogDetailActions({ ...item, deleted_at: '2026-11-01' }).upgradeOpenapi.shown).toBe(false);
    expect(catalogDetailActions(item, (grant) => grant !== 'imports:create').upgradeOpenapi.shown).toBe(false);
  });
});
