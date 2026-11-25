/**
 * Pact comparisons and the comparison fidelity report — PFX-2.5 (#6929).
 *
 * * **Report**: the verdict reads with its strength (never "Pass" alone when part of the pact was
 *   not compared), every check shows its status as an icon *and* a word, a check that did not run
 *   says why, and unsupported matching rules and could-not-compare items are listed with their
 *   pointer. A comparison that could not run shows its error.
 * * **Page**: the list selects its first row and loads its report; another row loads its own; an
 *   empty workspace says how comparisons happen; a failed read offers a retry.
 *
 * The report fixture is the real REST builder's output over four golden comparisons
 * (`tests/fixtures/pact-comparison-fidelity.json`). `A11Y_FIXTURE_DUMP=1` writes the docs-screenshot
 * fixture `pact-comparison-fidelity`.
 */

import React from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
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

import fixture from './fixtures/pact-comparison-fidelity.json';
import { ComparisonFidelityReport } from '../src/app/components/ade/pactComparisons/ComparisonFidelityReport';
import PactComparisonsClient from '../src/app/components/ade/pactComparisons/PactComparisonsClient';
import type { ComparisonFidelityReport as Report, ComparisonListEntry } from '../lib/pact-comparisons';
import { writeA11yFixture } from './helpers/a11y-fixture-dump';

const AXE_OPTIONS = { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } };
const REPORT = fixture as unknown as Report;
const OTHER = '33333333-3333-4333-8333-333333333333';

/** A report whose first interaction's operation is unknown, so every later check did not run. */
function failedReport(): Report {
  const report: Report = JSON.parse(JSON.stringify(REPORT));
  const first = report.interactions[0];
  first.verdict = 'fail';
  first.checks = first.checks.map((check, index) =>
    index === 0
      ? { ...check, status: 'failed', failures: 1 }
      : { ...check, status: 'not-run', reason: 'not run because an earlier check failed (Operation (method and path))' }
  );
  report.interactions = [first];
  return { ...report, verdict: 'fail', comparisonVerdict: 'fail', strength: 'failed', statement: 'The provider contract contradicts 1 of 1 interaction; also 7 checks not run.' };
}

function entry(id: string, overrides: Partial<ComparisonListEntry> = {}): ComparisonListEntry {
  return {
    ...REPORT.result,
    id,
    verdict: REPORT.verdict,
    comparisonVerdict: REPORT.comparisonVerdict,
    strength: REPORT.strength,
    statement: REPORT.statement,
    selfVerification: 'verified',
    summary: REPORT.summary,
    fidelityPath: `/v1/tenants/acme/pact-comparisons/${id}/fidelity`,
    ...overrides,
  };
}

// --- the report -------------------------------------------------------------------------------

describe('ComparisonFidelityReport', () => {
  it('reads a partial pass with its strength, never as a plain pass', () => {
    render(<ComparisonFidelityReport report={REPORT} />);
    expect(screen.getByTestId('pcf-verdict')).toHaveTextContent('Pass (partial) · Not everything compared');
    expect(screen.getByTestId('pcf-statement')).toHaveTextContent(
      'Passed, but not everything was compared: 1 of 4 interactions compared in full'
    );
    expect(screen.getByText('Billing Service 2.0.0 against the provider contract of Ledger API 5.1.0 · self-verification verified')).toBeInTheDocument();
  });

  it('shows every check as an icon and a word', () => {
    render(<ComparisonFidelityReport report={REPORT} />);
    const body = screen.getByTestId('pcf-check-1-response.body');
    expect(body).toHaveAttribute('data-status', 'partial');
    expect(within(body).getByText('Response body')).toBeInTheDocument();
    expect(within(body).getByText('Partly compared')).toBeInTheDocument();
    expect(body.querySelector('svg')).not.toBeNull();
    expect(within(screen.getByTestId('pcf-check-0-request.operation')).getByText('Compared')).toBeInTheDocument();
  });

  it('lists unsupported matching rules and could-not-compare items with their pointers', () => {
    render(<ComparisonFidelityReport report={REPORT} />);
    const events = screen.getByTestId('pcf-interaction-1');
    const gaps = within(events).getByRole('region', { name: /could not compare/i });
    expect(within(gaps).getByText('oneof-relaxed')).toBeInTheDocument();
    expect(gaps.querySelector('.pcf__pointer')?.textContent).toMatch(/^\/interactions\/1\/response\/body/);
    const rules = within(screen.getByTestId('pcf-interaction-2')).getByRole('region', { name: /unsupported matching rules/i });
    expect(within(rules).getByText('matching-rule-not-mapped')).toBeInTheDocument();
    // A fully compared interaction lists neither.
    expect(within(screen.getByTestId('pcf-interaction-0')).queryByRole('region', { name: /could not compare/i })).toBeNull();
  });

  it('says why a check did not run', () => {
    render(<ComparisonFidelityReport report={failedReport()} />);
    expect(screen.getByTestId('pcf-verdict')).toHaveTextContent('Fail · Contradicts the pact');
    const query = screen.getByTestId('pcf-check-0-request.query');
    expect(within(query).getByText('Not run')).toBeInTheDocument();
    expect(within(query).getByText('not run because an earlier check failed (Operation (method and path))')).toBeInTheDocument();
  });

  it('shows the error of a comparison that could not run', () => {
    const report: Report = {
      ...REPORT,
      verdict: 'fail',
      strength: 'none',
      statement: 'Nothing was compared: the provider contract is not OpenAPI 3.x.',
      interactions: [],
      error: { code: 'comparison-not-possible', message: 'the provider contract is not OpenAPI 3.x' },
    };
    render(<ComparisonFidelityReport report={report} />);
    expect(screen.getByTestId('pcf-verdict')).toHaveTextContent('Fail · Nothing compared');
    expect(screen.getByRole('note')).toHaveTextContent('comparison-not-possible the provider contract is not OpenAPI 3.x');
  });

  it('passes axe and dumps the docs fixture', async () => {
    const { container } = render(<ComparisonFidelityReport report={REPORT} />);
    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
    writeA11yFixture('pact-comparison-fidelity', container.innerHTML);
  });
});

// --- the page ---------------------------------------------------------------------------------

describe('PactComparisonsClient', () => {
  let routes: Record<string, () => { status: number; body: unknown }>;

  beforeEach(() => {
    routes = {
      '/api/pact-comparisons': () => ({
        status: 200,
        body: { comparisons: [entry(REPORT.result.id), entry(OTHER, { strength: 'full', verdict: 'pass' })], limit: 50 },
      }),
      [`/api/pact-comparisons/${REPORT.result.id}/fidelity`]: () => ({ status: 200, body: REPORT }),
      [`/api/pact-comparisons/${OTHER}/fidelity`]: () => ({ status: 200, body: failedReport() }),
    };
    global.fetch = jest.fn(async (input: RequestInfo | URL) => {
      const route = routes[String(input)];
      const { status, body } = route ? route() : { status: 404, body: { success: false, error: 'not found' } };
      return { ok: status < 400, status, json: async () => body } as Response;
    }) as unknown as typeof fetch;
  });

  it('selects the first comparison and loads its report', async () => {
    render(<PactComparisonsClient />);
    expect(await screen.findByTestId('pact-comparison-fidelity')).toHaveAttribute('data-strength', 'partial');
    expect(screen.getByTestId(`pcl-row-${REPORT.result.id}`)).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByTestId(`pcl-row-${REPORT.result.id}`)).toHaveTextContent(
      '4 interactions · 1 not compared · 3 rules unsupported'
    );
  });

  it('loads another row’s report when it is chosen', async () => {
    render(<PactComparisonsClient />);
    await screen.findByTestId('pact-comparison-fidelity');
    fireEvent.click(screen.getByTestId(`pcl-row-${OTHER}`));
    expect(await screen.findByText('Fail · Contradicts the pact')).toBeInTheDocument();
    expect(screen.getByTestId(`pcl-row-${OTHER}`)).toHaveAttribute('aria-pressed', 'true');
  });

  it('says how comparisons happen in an empty workspace', async () => {
    routes['/api/pact-comparisons'] = () => ({ status: 200, body: { comparisons: [], limit: 50 } });
    render(<PactComparisonsClient />);
    expect(await screen.findByText('No bi-directional comparisons yet')).toBeInTheDocument();
  });

  it('offers a retry when the list or the report cannot be read', async () => {
    routes['/api/pact-comparisons'] = () => ({ status: 403, body: { success: false, error: 'Permission denied' } });
    render(<PactComparisonsClient />);
    expect(await screen.findByText('Permission denied')).toBeInTheDocument();
    routes['/api/pact-comparisons'] = () => ({ status: 200, body: { comparisons: [entry(REPORT.result.id)], limit: 50 } });
    routes[`/api/pact-comparisons/${REPORT.result.id}/fidelity`] = () => ({
      status: 404,
      body: { success: false, error: 'this workspace has no bi-directional result' },
    });
    fireEvent.click(screen.getByRole('button', { name: /try again/i }));
    expect(await screen.findByText('this workspace has no bi-directional result')).toBeInTheDocument();
    routes[`/api/pact-comparisons/${REPORT.result.id}/fidelity`] = () => ({ status: 200, body: REPORT });
    fireEvent.click(screen.getByRole('button', { name: /try again/i }));
    expect(await screen.findByTestId('pact-comparison-fidelity')).toBeInTheDocument();
  });

  it('passes axe with a report open', async () => {
    const { container } = render(<PactComparisonsClient />);
    await screen.findByTestId('pact-comparison-fidelity');
    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
  });
});
