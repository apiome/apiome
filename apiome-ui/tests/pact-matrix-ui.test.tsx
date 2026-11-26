/**
 * The **Matrix** and **Can I deploy** pages — PFX-5.4 (#6948).
 *
 * * Matrix: an address with a whole query is asked straight away; the verdict is explained
 *   (headline, broker sentence, counts, blocking / warning notices with hints); the grid draws a
 *   cell per pair with its mark, accessible name and pact link; every row is in the table; axe
 *   passes. The builder writes the query to the address and the proxy; an unfinished query says
 *   what it needs without asking; an unreadable address says why; a refusal offers **Try again**;
 *   a full answer says rows may be missing; an empty workspace shows the publish command.
 * * Can I deploy: the same for one version — an unknown verdict with REST's retry hint and
 *   **Check again**, the rows, the CLI command; the environment picker and version suggestions;
 *   ignoring pacticipants; tags; problems said before asking.
 *
 * `A11Y_FIXTURE_DUMP=1` writes the docs-screenshot fixtures `pact-matrix` and `pact-can-i-deploy`.
 */

import React from 'react';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { axe } from 'jest-axe';
import 'jest-axe/extend-expect';

jest.mock('next/link', () => ({
  __esModule: true,
  default: ({ children, href, ...props }: { children: React.ReactNode; href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

import fixture from './fixtures/pact-matrix.json';
import MatrixClient from '../src/app/components/ade/pactMatrix/MatrixClient';
import CanIDeployClient from '../src/app/components/ade/pactMatrix/CanIDeployClient';
import { liveMarkup, writeA11yFixture } from './helpers/a11y-fixture-dump';

const AXE_OPTIONS = { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } };

/** What each proxy answers; a test overrides one. */
let answers: Record<string, () => { status: number; body: unknown }>;
let calls: string[];

beforeEach(() => {
  calls = [];
  answers = {
    '/api/pact/pacticipants': () => ({ status: 200, body: fixture.pacticipants }),
    '/api/pact/environments': () => ({ status: 200, body: fixture.environments }),
    '/api/pact/pacticipants/billing-service/versions': () => ({
      status: 200,
      body: fixture.versions,
    }),
    '/api/pact/matrix': () => ({ status: 200, body: fixture.matrix }),
    '/api/pact/can-i-deploy': () => ({ status: 200, body: fixture.canIDeploy }),
  };
  global.fetch = jest.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    calls.push(decodeURIComponent(url));
    const answer = answers[url.split('?')[0]];
    const { status, body } = answer
      ? answer()
      : { status: 404, body: { success: false, error: 'not found' } };
    return { ok: status < 400, status, json: async () => body } as Response;
  }) as unknown as typeof fetch;
  window.history.replaceState(null, '', '/');
});

/** The proxy reads of one path. */
const readsOf = (path: string) => calls.filter((url) => url.split('?')[0] === path);

describe('MatrixClient', () => {
  const QUERY = 'q[0][pacticipant]=billing-service&latestby=cvpv&limit=100';

  it('asks an address’s query, explains the verdict, draws the grid and rows, and passes axe', async () => {
    const { container } = render(<MatrixClient initialQuery={QUERY} />);
    expect(await screen.findByTestId('pmx-verdict')).toHaveTextContent('No — not deployable');
    expect(readsOf('/api/pact/matrix')).toEqual([
      '/api/pact/matrix?q[0][pacticipant]=billing-service&latestby=cvpv&limit=100',
    ]);
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Matrix');
    expect(screen.getByTestId('pmx-asked')).toHaveTextContent(
      'Asked about every version of billing-service.',
    );
    expect(screen.getByTestId('pmx-counts')).toHaveTextContent('3 verified · 1 failed · 1 unknown');
    expect(screen.getByTestId('pmx-row-counts')).toHaveTextContent(
      '7 rows count towards the verdict · 1 ignored',
    );
    expect(screen.queryByTestId('pmx-retry')).not.toBeInTheDocument();
    expect(screen.queryByTestId('pmx-truncated')).not.toBeInTheDocument();

    const blocking = screen.getByTestId('pmx-blocking');
    expect(within(blocking).getAllByRole('listitem')).toHaveLength(2);
    expect(blocking).toHaveTextContent('Ledger API failed');
    expect(blocking).toHaveTextContent('Fix the provider or change the consumer’s pact');
    expect(blocking).toHaveTextContent('Run the provider’s verification');
    expect(screen.getByTestId('pmx-warnings')).toHaveTextContent(
      'apiome pact publish-provider-contract',
    );

    const failed = screen.getByTestId('pmx-cell-billing-service@2.0.0→ledger-api@5.1.0');
    expect(failed).toHaveAttribute('data-tone', 'danger');
    expect(failed).toHaveTextContent('✕');
    expect(failed).toHaveAttribute(
      'href',
      '/ade/dashboard/pacts/pacticipants/billing-service/pacts/ledger-api?version=2.0.0',
    );
    expect(failed).toHaveAccessibleName(
      'Billing Service 2.0.0 → Ledger API 5.1.0: Failed (verification failed). Open the pact.',
    );
    const twice = screen.getByTestId('pmx-cell-billing-service@1.9.0→ledger-api@5.0.0');
    expect(twice).toHaveTextContent('✓2');
    expect(screen.getByTestId('pmx-cell-mobile-app@3.2.0→billing-service@2.0.0')).toHaveAttribute(
      'data-ignored',
      'true',
    );
    const grid = screen.getByTestId('pmx-grid');
    expect(within(grid).getAllByRole('columnheader')).toHaveLength(7);
    expect(within(grid).getAllByText('No row').length).toBeGreaterThan(0);
    expect(within(grid).getByText('no result')).toBeInTheDocument();

    const rows = screen.getByTestId('pmx-rows');
    expect(within(rows).getAllByRole('row')).toHaveLength(9);
    expect(within(rows).getByText('Bi-directional')).toBeInTheDocument();
    expect(within(rows).getAllByText('Ignored')).toHaveLength(1);
    expect(screen.getByTestId('pmx-row-total')).toHaveTextContent('8 rows');

    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
    writeA11yFixture('pact-matrix', liveMarkup(container.firstElementChild!));
  });

  it('builds a query, writes it to the address and asks it; says what an unfinished one needs', async () => {
    render(<MatrixClient initialQuery="" />);
    expect(await screen.findByText('Choose the versions to look at')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Show matrix' }));
    expect(screen.getByTestId('pmx-problem')).toHaveTextContent(
      'Selector 1: choose a pacticipant.',
    );
    expect(readsOf('/api/pact/matrix')).toHaveLength(0);

    fireEvent.change(screen.getByLabelText('Pacticipant'), {
      target: { value: 'billing-service' },
    });
    fireEvent.change(screen.getByLabelText('Versions'), { target: { value: 'branch' } });
    fireEvent.click(screen.getByRole('button', { name: 'Show matrix' }));
    expect(screen.getByTestId('pmx-problem')).toHaveTextContent('Selector 1: enter the branch.');
    fireEvent.change(screen.getByLabelText('Branch'), { target: { value: 'main' } });
    fireEvent.click(screen.getByLabelText('Latest only'));

    fireEvent.click(screen.getByRole('button', { name: 'Add selector' }));
    const second = screen.getByTestId('pmx-selector-1');
    fireEvent.change(within(second).getByLabelText('Pacticipant'), {
      target: { value: 'ledger-api' },
    });
    fireEvent.change(within(second).getByLabelText('Versions'), {
      target: { value: 'environment' },
    });
    fireEvent.change(within(second).getByLabelText('Environment'), {
      target: { value: 'production' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Add selector' }));
    fireEvent.click(screen.getByRole('button', { name: 'Remove selector 3' }));
    expect(screen.queryByTestId('pmx-selector-2')).not.toBeInTheDocument();
    fireEvent.change(screen.getByTestId('pmx-latestby'), { target: { value: '' } });
    fireEvent.change(screen.getByTestId('pmx-limit'), { target: { value: '500' } });

    fireEvent.click(screen.getByRole('button', { name: 'Show matrix' }));
    expect(await screen.findByTestId('pmx-verdict')).toBeInTheDocument();
    const asked =
      'q[0][pacticipant]=billing-service&q[0][branch]=main&q[0][latest]=true&q[1][pacticipant]=ledger-api&' +
      'q[1][environment]=production&limit=500';
    expect(readsOf('/api/pact/matrix')).toEqual([`/api/pact/matrix?${asked}`]);
    expect(decodeURIComponent(window.location.search)).toBe(`?${asked}`);
    expect(screen.queryByTestId('pmx-problem')).not.toBeInTheDocument();
    expect(screen.getByTestId('pmx-asked')).toHaveTextContent(
      'the latest version of billing-service on branch main; the versions of ledger-api in production',
    );
  });

  it('says why it cannot read an address, and does not ask', async () => {
    render(<MatrixClient initialQuery="q[0][pacticipant]=a&success[]=true" />);
    expect(await screen.findByTestId('pmx-address-error')).toHaveTextContent(
      'The address carries a query the matrix cannot read: Unsupported parameter success[]',
    );
    expect(readsOf('/api/pact/matrix')).toHaveLength(0);
  });

  it('shows a refusal with Try again, and says when rows may be missing', async () => {
    answers['/api/pact/matrix'] = () => ({
      status: 400,
      body: { success: false, error: 'Environment nowhere does not exist' },
    });
    render(<MatrixClient initialQuery="q[0][pacticipant]=a&q[0][environment]=nowhere&limit=8" />);
    expect(await screen.findByText('Environment nowhere does not exist')).toBeInTheDocument();
    answers['/api/pact/matrix'] = () => ({ status: 200, body: fixture.matrix });
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    });
    expect(await screen.findByTestId('pmx-truncated')).toHaveTextContent(
      'The answer holds 8 rows, the most asked for',
    );
    expect(readsOf('/api/pact/matrix')).toHaveLength(2);
    expect(screen.getByTestId('pmx-limit')).toHaveValue('8');
  });

  it('shows the publish command in an empty workspace, and an answer with no rows', async () => {
    answers['/api/pact/pacticipants'] = () => ({
      status: 200,
      body: { pacticipants: [], count: 0, has_more: false },
    });
    answers['/api/pact/matrix'] = () => ({
      status: 200,
      body: {
        summary: {
          deployable: true,
          reason: 'There are no missing dependencies',
          success: 0,
          failed: 0,
          unknown: 0,
        },
        notices: [
          { type: 'success', code: 'no-dependencies', text: 'There are no missing dependencies' },
        ],
        matrix: [],
      },
    });
    render(<MatrixClient initialQuery="q[0][pacticipant]=nobody" />);
    expect(await screen.findByTestId('pmx-empty')).toHaveTextContent('apiome pact publish');
    expect(await screen.findByTestId('pmx-verdict')).toHaveTextContent('Yes — deployable');
    expect(screen.getByTestId('pmx-passing')).toHaveTextContent(
      'There are no missing dependencies',
    );
    expect(screen.getByText('No rows')).toBeInTheDocument();
    expect(screen.queryByTestId('pmx-grid')).not.toBeInTheDocument();
  });
});

describe('CanIDeployClient', () => {
  const QUERY =
    'pacticipant=billing-service&version=2.0.0&toEnvironment=production&ignore=mobile-app';

  it('asks an address’s question, explains an unknown verdict, lists the rows and the command, and passes axe', async () => {
    const { container } = render(<CanIDeployClient initialQuery={QUERY} />);
    expect(await screen.findByTestId('pmx-verdict')).toHaveTextContent('Not known yet');
    expect(readsOf('/api/pact/can-i-deploy')).toEqual([`/api/pact/can-i-deploy?${QUERY}`]);
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Can I deploy?');
    expect(screen.getByTestId('pcd-asked')).toHaveTextContent(
      'Asked whether billing-service 2.0.0 can be deployed to production, ignoring mobile-app.',
    );
    expect(screen.getByTestId('pmx-retry')).toHaveTextContent('Ask again in about 10 seconds');
    expect(screen.getByTestId('pmx-blocking')).toHaveTextContent(
      'Audit Log currently in production',
    );
    expect(screen.getByTestId('pmx-warnings')).toHaveTextContent('Cannot ignore Payments Gateway');
    expect(screen.getByTestId('pmx-row-counts')).toHaveTextContent(
      '2 rows count towards the verdict · 1 ignored',
    );
    expect(within(screen.getByTestId('pmx-rows')).getAllByRole('row')).toHaveLength(4);
    expect(screen.getByTestId('pcd-row-total')).toHaveTextContent('3 rows');
    expect(screen.getByLabelText('The same question from the CLI')).toHaveTextContent(
      'apiome pact can-i-deploy \\ --pacticipant billing-service \\ --version 2.0.0 \\ --to-environment production \\ --ignore mobile-app',
    );
    expect(
      within(screen.getByTestId('pcd-ignored')).getByRole('button', {
        name: 'Stop ignoring mobile-app',
      }),
    ).toBeInTheDocument();
    expect(await screen.findByRole('option', { name: 'staging' })).toBeInTheDocument();

    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
    writeA11yFixture('pact-can-i-deploy', liveMarkup(container.firstElementChild!));

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Check again' }));
    });
    expect(readsOf('/api/pact/can-i-deploy')).toHaveLength(2);
  });

  it('starts with the CLI command, says what is missing, and asks a filled form', async () => {
    render(<CanIDeployClient initialQuery="" />);
    expect(screen.getByTestId('pcd-start')).toHaveTextContent('apiome pact can-i-deploy');
    const environment = await screen.findByRole('combobox', { name: 'Environment' });
    expect(
      within(environment)
        .getAllByRole('option')
        .map((o) => o.textContent),
    ).toEqual(['Choose an environment', 'production', 'staging']);
    fireEvent.click(screen.getByRole('button', { name: 'Check' }));
    expect(screen.getByTestId('pcd-problem')).toHaveTextContent(
      'Choose the pacticipant being deployed',
    );
    expect(readsOf('/api/pact/can-i-deploy')).toHaveLength(0);

    fireEvent.change(screen.getByLabelText('Pacticipant'), {
      target: { value: 'billing-service' },
    });
    expect(await screen.findByText('', { selector: 'option[value="1.9.0"]' })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Version'), { target: { value: '2.0.0' } });
    fireEvent.click(screen.getByRole('button', { name: 'Check' }));
    expect(screen.getByTestId('pcd-problem')).toHaveTextContent('Choose where it is deployed');
    fireEvent.change(environment, { target: { value: 'staging' } });

    const ignore = screen.getByLabelText('Ignore a pacticipant');
    fireEvent.change(ignore, { target: { value: 'audit-log' } });
    fireEvent.click(screen.getByRole('button', { name: 'Ignore' }));
    fireEvent.change(ignore, { target: { value: 'audit-log' } });
    fireEvent.keyDown(ignore, { key: 'Enter' });
    expect(screen.getByTestId('pcd-problem')).toHaveTextContent('audit-log is already ignored.');
    fireEvent.change(ignore, { target: { value: 'ledger-api' } });
    fireEvent.keyDown(ignore, { key: 'Enter' });
    fireEvent.click(screen.getByRole('button', { name: 'Stop ignoring ledger-api' }));

    fireEvent.click(screen.getByRole('button', { name: 'Check' }));
    expect(await screen.findByTestId('pmx-verdict')).toBeInTheDocument();
    const asked =
      'pacticipant=billing-service&version=2.0.0&toEnvironment=staging&ignore=audit-log';
    expect(readsOf('/api/pact/can-i-deploy')).toEqual([`/api/pact/can-i-deploy?${asked}`]);
    expect(decodeURIComponent(window.location.search)).toBe(`?${asked}`);
  });

  it('asks about a tag, with the --to command', async () => {
    answers['/api/pact/can-i-deploy'] = () => ({
      status: 200,
      body: {
        summary: {
          deployable: true,
          reason: 'All required verification results are published and successful',
          success: 1,
          failed: 0,
          unknown: 0,
        },
        notices: [
          {
            type: 'success',
            code: 'verified',
            text: 'All required verification results are published and successful',
          },
        ],
        matrix: [fixture.canIDeploy.matrix[0]],
      },
    });
    render(<CanIDeployClient initialQuery="" />);
    fireEvent.click(screen.getByLabelText('Tag'));
    fireEvent.change(screen.getByRole('textbox', { name: 'Tag' }), { target: { value: 'prod' } });
    fireEvent.change(screen.getByLabelText('Pacticipant'), {
      target: { value: 'Billing Service' },
    });
    fireEvent.change(screen.getByLabelText('Version'), { target: { value: '2.0.0' } });
    fireEvent.click(screen.getByRole('button', { name: 'Check' }));
    expect(await screen.findByTestId('pmx-verdict')).toHaveTextContent('Yes — deployable');
    expect(screen.queryByTestId('pmx-retry')).not.toBeInTheDocument();
    expect(screen.getByLabelText('The same question from the CLI')).toHaveTextContent(
      "--pacticipant 'Billing Service'",
    );
    expect(screen.getByLabelText('The same question from the CLI')).toHaveTextContent('--to prod');
    expect(readsOf('/api/pact/pacticipants/billing-service/versions')).toHaveLength(0);
  });

  it('says why it cannot ask an address, keeps an unknown environment, and offers Try again', async () => {
    const first = render(
      <CanIDeployClient initialQuery="pacticipant=a&version=1&toEnvironment=p&to=t" />,
    );
    expect(await screen.findByTestId('pcd-problem')).toHaveTextContent(
      'The address carries a question that cannot be asked: Give an environment (toEnvironment) or a tag (to), not both.',
    );
    expect(readsOf('/api/pact/can-i-deploy')).toHaveLength(0);
    first.unmount();

    answers['/api/pact/can-i-deploy'] = () => ({
      status: 403,
      body: { success: false, error: 'Permission denied' },
    });
    render(<CanIDeployClient initialQuery="pacticipant=a&version=1&toEnvironment=moon" />);
    expect(await screen.findByText('Permission denied')).toBeInTheDocument();
    expect(
      await screen.findByRole('option', { name: 'moon (not in this workspace)' }),
    ).toBeInTheDocument();
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    });
    expect(readsOf('/api/pact/can-i-deploy')).toHaveLength(2);
  });

  it('shows the publish command in an empty workspace, and free-text fields when the pickers fail', async () => {
    answers['/api/pact/pacticipants'] = () => ({
      status: 200,
      body: { pacticipants: [], count: 0, has_more: false },
    });
    answers['/api/pact/environments'] = () => ({
      status: 403,
      body: { success: false, error: 'Permission denied' },
    });
    render(<CanIDeployClient initialQuery="" />);
    expect(await screen.findByTestId('pcd-empty')).toHaveTextContent('apiome pact publish');
    expect(screen.getByRole('textbox', { name: 'Environment' })).toBeInTheDocument();
  });
});
