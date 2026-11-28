/**
 * **Contracts settings → Clean-up** — PFX-8.14 (#7311).
 *
 * * the rules read as sentences with how much each keeps; deployed / released has no remove
 *   button; the preview headline, its list, and Recently deleted with Restore; axe passes;
 * * editing a rule previews the draft (not saved) and **Save rules** puts every rule; **Discard**
 *   goes back; an invalid count or a repeated tag is refused before anything is sent;
 * * REST refusing a rule set that would remove a deployed version shows the sentence;
 * * clean-up off: the preview reads "Nothing is removed while clean-up is off.";
 * * without the Contracts admin permission every control is read-only, said once, no Restore;
 * * **Restore** restores a version (by its pacticipant and number) or a pacticipant (by id);
 * * the tabs link Clean-up and Verification; a refused read offers **Try again**.
 *
 * `A11Y_FIXTURE_DUMP=1` writes the docs-screenshot fixture `pact-settings-cleanup`.
 */

import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { axe } from 'jest-axe';
import 'jest-axe/extend-expect';

jest.mock('next/navigation', () => ({ useRouter: () => ({ replace: jest.fn(), push: jest.fn() }) }));
jest.mock('next/link', () => ({
  __esModule: true,
  default: ({ children, href, ...props }: { children: React.ReactNode; href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

import fixture from './fixtures/pact-retention.json';
import ContractsSettingsClient from '../src/app/components/ade/pactSettings/ContractsSettingsClient';
import { liveMarkup, writeA11yFixture } from './helpers/a11y-fixture-dump';

const AXE_OPTIONS = { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } };
const POLICY = '/api/pact/retention/policy';
const PREVIEW = '/api/pact/retention/policy/preview';
const DELETED = '/api/pact/retention/deleted';
const [VERSION, PACTICIPANT] = fixture.deleted.items;

type Answer = { status: number; body: unknown };
let answers: Record<string, (method: string, body: unknown) => Answer>;
let calls: Array<{ url: string; method: string; body?: unknown }>;

/** REST through the proxies: the longest route key the URL starts with answers. */
function installFetch() {
  global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? 'GET';
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ url, method, body });
    const key = Object.keys(answers)
      .sort((a, b) => b.length - a.length)
      .find((candidate) => url.startsWith(candidate));
    const answer = key ? answers[key](method, body) : { status: 404, body: { success: false, error: 'not found' } };
    return { ok: answer.status < 400, status: answer.status, json: async () => answer.body } as Response;
  }) as unknown as typeof fetch;
}

const callsTo = (prefix: string, method?: string) =>
  calls.filter((call) => call.url.startsWith(prefix) && (!method || call.method === method));

beforeEach(() => {
  calls = [];
  answers = {
    [POLICY]: (method, body) =>
      method === 'PUT'
        ? { status: 200, body: { ...fixture.policy, ...(body as object), updated_at: '2026-11-28T10:00:00+00:00' } }
        : { status: 200, body: fixture.policy },
    [PREVIEW]: (_method, body) => ({
      status: 200,
      body: { ...fixture.preview, draft: Boolean((body as { rules?: unknown })?.rules) },
    }),
    [DELETED]: () => ({ status: 200, body: fixture.deleted }),
    [`/api/pact/pacticipants/${VERSION.pacticipant_slug}/versions/`]: () => ({
      status: 200,
      body: { number: VERSION.number, branches: [], tags: [] },
    }),
    [`/api/pact/pacticipants/${PACTICIPANT.id}/restore`]: () => ({
      status: 200,
      body: { id: PACTICIPANT.id, slug: PACTICIPANT.pacticipant_slug, name: PACTICIPANT.pacticipant_name },
    }),
  };
  installFetch();
});

async function renderPage() {
  const view = render(<ContractsSettingsClient />);
  await screen.findByTestId('pcx-rules');
  await waitFor(() => expect(screen.getByTestId('pcx-preview-count')).toHaveTextContent('412'));
  await screen.findByTestId('pcx-deleted-table');
  return view;
}

describe('Clean-up', () => {
  it('shows the rules as sentences, the preview and Recently deleted, and passes axe', async () => {
    const { container } = await renderPage();
    expect(screen.getByRole('heading', { name: 'Contracts settings' })).toBeInTheDocument();
    const deployed = screen.getByTestId('pcx-rule-deployed');
    expect(deployed).toHaveTextContent('Every version deployed or released anywhere');
    expect(deployed).toHaveTextContent('always · 9 versions');
    expect(screen.queryByTestId('pcx-remove-deployed')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Versions kept on each main branch')).toHaveValue('5');
    expect(screen.getByTestId('pcx-rule-main')).toHaveTextContent('55 versions');
    expect(screen.getByTestId('pcx-rule-other')).toHaveTextContent('131 versions');
    expect(screen.getByLabelText('Days the other-branch versions are kept (empty: however old)')).toHaveValue('90');
    expect(screen.getByLabelText('Tags to keep, separated by commas')).toHaveValue('keep');
    expect(screen.getByTestId('pcx-nightly')).toBeChecked();
    expect(screen.getByLabelText('Keep deleted items restorable for')).toHaveValue('30');
    expect(screen.getByTestId('pcx-preview')).toHaveTextContent('412 of 1,904 versions would go');
    expect(screen.getByTestId('pcx-preview')).toHaveTextContent('with 618 pacts and 2,140 results');
    expect(screen.getByTestId('pcx-save')).toBeDisabled();
    // The saved rules are previewed as they are: no draft.
    expect(callsTo(PREVIEW)[0].body).toEqual({});

    fireEvent.click(screen.getByTestId('pcx-preview-toggle'));
    const list = screen.getByTestId('pcx-preview-table');
    expect(list).toHaveTextContent('Orders UI 3.2.2+a1c9e02');
    expect(list).toHaveTextContent('Orders UI: and 258 more versions');

    const deleted = screen.getByTestId('pcx-deleted-table');
    expect(within(deleted).getByTestId(`pcx-deleted-${VERSION.id}`)).toHaveTextContent('Orders UI 3.2.9+c4410b7');
    expect(within(deleted).getByTestId(`pcx-deleted-${VERSION.id}`)).toHaveTextContent('Clean-up');
    expect(within(deleted).getByTestId(`pcx-deleted-${PACTICIPANT.id}`)).toHaveTextContent('41 versions · 6 pacts');
    expect(screen.getByTestId('pcx-command-block')).toHaveTextContent('apiome pact retention set');
    expect(screen.getByTestId('pcx-command-block')).toHaveTextContent('--main-branch-latest 5');

    fireEvent.click(screen.getByTestId('pcx-preview-toggle'));
    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
    writeA11yFixture('pact-settings-cleanup', liveMarkup(container.firstElementChild!));
  });

  it('previews an edit as a draft, then saves every rule', async () => {
    await renderPage();
    fireEvent.change(screen.getByLabelText('Versions kept on each main branch'), { target: { value: '3' } });
    await waitFor(() => expect(callsTo(PREVIEW).length).toBeGreaterThan(1));
    const last = callsTo(PREVIEW).at(-1)!;
    expect(last.body).toEqual({ rules: expect.objectContaining({ keep_main_branch_latest: 3 }) });
    await waitFor(() => expect(screen.getByTestId('pcx-preview')).toHaveTextContent('not saved yet'));
    expect(callsTo(POLICY, 'PUT')).toHaveLength(0);

    fireEvent.click(screen.getByTestId('pcx-save'));
    await waitFor(() => expect(screen.getByTestId('pcx-save-message')).toHaveTextContent('Clean-up rules saved.'));
    expect(callsTo(POLICY, 'PUT')[0].body).toEqual({
      keep_main_branch_latest: 3,
      keep_other_branch_latest: 1,
      keep_other_branch_days: 90,
      keep_tags: ['keep'],
      nightly_enabled: true,
      restore_window_days: 30,
    });
  });

  it('removes and adds back a rule, and Discard goes back to the saved rules', async () => {
    await renderPage();
    fireEvent.click(screen.getByTestId('pcx-remove-tags'));
    expect(screen.queryByTestId('pcx-rule-tags')).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId('pcx-add-rule'));
    fireEvent.click(screen.getByTestId('pcx-add-tags'));
    expect(screen.getByTestId('pcx-rule-tags')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('pcx-remove-main'));
    expect(screen.getByTestId('pcx-save')).toBeEnabled();
    fireEvent.click(screen.getByTestId('pcx-discard'));
    expect(screen.getByTestId('pcx-rule-main')).toBeInTheDocument();
    expect(screen.getByTestId('pcx-save')).toBeDisabled();
  });

  it.each([
    ['Versions kept on each main branch', '0', 'The main-branch count must be a whole number from 1 to 1000.'],
    ['Tags to keep, separated by commas', 'keep, keep', 'The tag keep is listed more than once.'],
    ['Tags to keep, separated by commas', ' , ', 'Name at least one tag, or remove the tag rule.'],
  ])('refuses %s = %p before sending anything', async (label, value, message) => {
    await renderPage();
    const previews = callsTo(PREVIEW).length;
    fireEvent.change(screen.getByLabelText(label), { target: { value } });
    expect(screen.getByTestId('pcx-form-error')).toHaveTextContent(message);
    expect(screen.getByTestId('pcx-save')).toBeDisabled();
    await act(async () => new Promise((resolve) => setTimeout(resolve, 500)));
    expect(callsTo(PREVIEW)).toHaveLength(previews);
    expect(callsTo(POLICY, 'PUT')).toHaveLength(0);
  });

  it('shows the sentence REST refuses a rule set with', async () => {
    answers[POLICY] = (method) =>
      method === 'PUT'
        ? { status: 422, body: { success: false, error: 'Deployed and released versions are always kept. A rule set …' } }
        : { status: 200, body: fixture.policy };
    await renderPage();
    fireEvent.click(screen.getByTestId('pcx-remove-main'));
    fireEvent.click(screen.getByTestId('pcx-save'));
    await waitFor(() =>
      expect(screen.getByTestId('pcx-save-message')).toHaveTextContent('Deployed and released versions are always kept.'),
    );
  });

  it('says nothing is removed while clean-up is off', async () => {
    answers[POLICY] = () => ({ status: 200, body: { ...fixture.policy, nightly_enabled: false, next_run_at: null } });
    answers[PREVIEW] = () => ({ status: 200, body: { ...fixture.preview, nightly_enabled: false } });
    render(<ContractsSettingsClient />);
    expect(await screen.findByTestId('pcx-preview-off')).toHaveTextContent('Nothing is removed while clean-up is off.');
    expect(screen.getByTestId('pcx-preview')).toHaveTextContent('Turned on, 412 of 1,904 versions would go');
    expect(screen.getByTestId('pcx-rules')).toHaveTextContent('Off: nothing is ever removed.');
    expect(screen.getByTestId('pcx-nightly')).not.toBeChecked();
  });

  it('is read-only without the Contracts admin permission, and says so once', async () => {
    answers[POLICY] = () => ({ status: 200, body: { ...fixture.policy, can_edit: false } });
    answers[DELETED] = () => ({ status: 200, body: { ...fixture.deleted, can_restore: false } });
    render(<ContractsSettingsClient />);
    expect(await screen.findByTestId('pcx-read-only')).toHaveTextContent('needs the Contracts admin permission');
    expect(screen.getAllByRole('note')).toHaveLength(1);
    expect(screen.getByLabelText('Versions kept on each main branch')).toBeDisabled();
    expect(screen.getByTestId('pcx-nightly')).toBeDisabled();
    expect(screen.queryByTestId('pcx-save')).not.toBeInTheDocument();
    expect(screen.queryByTestId('pcx-add-rule')).not.toBeInTheDocument();
    await screen.findByTestId('pcx-deleted-table');
    expect(screen.queryByTestId(`pcx-restore-${VERSION.id}`)).not.toBeInTheDocument();
  });

  it('restores a version by its pacticipant and number, and a pacticipant by id', async () => {
    await renderPage();
    fireEvent.click(screen.getByTestId(`pcx-restore-${VERSION.id}`));
    await waitFor(() =>
      expect(callsTo('/api/pact/pacticipants/', 'POST')[0].url).toBe(
        `/api/pact/pacticipants/orders-ui/versions/${encodeURIComponent(VERSION.number!)}/restore`,
      ),
    );
    await waitFor(() => expect(callsTo(DELETED).length).toBe(2));
    fireEvent.click(await screen.findByTestId(`pcx-restore-${PACTICIPANT.id}`));
    await waitFor(() =>
      expect(callsTo('/api/pact/pacticipants/', 'POST')[1].url).toBe(`/api/pact/pacticipants/${PACTICIPANT.id}/restore`),
    );
  });

  it('shows why a restore was refused', async () => {
    answers[`/api/pact/pacticipants/${PACTICIPANT.id}/restore`] = () => ({
      status: 409,
      body: { success: false, error: 'A live pacticipant took the handle legacy-cart since.' },
    });
    await renderPage();
    fireEvent.click(screen.getByTestId(`pcx-restore-${PACTICIPANT.id}`));
    expect(await screen.findByTestId('pcx-restore-error')).toHaveTextContent('took the handle legacy-cart');
  });

  it('links its two tabs', async () => {
    await renderPage();
    expect(screen.getByTestId('pcx-tab-cleanup')).toHaveAttribute('aria-current', 'page');
    expect(screen.getByTestId('pcx-tab-verification')).toHaveAttribute(
      'href',
      '/ade/dashboard/pacts/settings?tab=verification',
    );
  });

  it('offers Try again when the rules cannot be read', async () => {
    answers[POLICY] = () => ({ status: 403, body: { success: false, error: 'Permission denied' } });
    render(<ContractsSettingsClient />);
    expect(await screen.findByText('The clean-up rules could not be read')).toBeInTheDocument();
    answers[POLICY] = () => ({ status: 200, body: fixture.policy });
    fireEvent.click(screen.getByRole('button', { name: /Try again/ }));
    expect(await screen.findByTestId('pcx-rules')).toBeInTheDocument();
  });

  it('says when nothing is waiting to be purged', async () => {
    answers[DELETED] = () => ({ status: 200, body: { ...fixture.deleted, items: [], count: 0 } });
    render(<ContractsSettingsClient />);
    expect(await screen.findByTestId('pcx-deleted-empty')).toHaveTextContent('nothing was deleted in the last 30 days');
  });
});
