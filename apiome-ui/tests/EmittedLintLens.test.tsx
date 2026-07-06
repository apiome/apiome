/**
 * EmittedLintLens — the Verify workbench's emitted-artifact lint lens (MFX-42.3, #4356).
 *
 * Covers the ticket's acceptance surface:
 *  1. Findings render grouped by severity, each with its rule id, category, and location.
 *  2. The score/grade chip renders consistently with the catalog lint visuals.
 *  3. The empty state ("no lint pack for this target") is explicit.
 *  4. A clean (applicable, zero-finding) report renders a positive confirmation.
 *  5. The lens distinguishes emitted-artifact lint from the source's catalog lint, linking the
 *     source's report when one is supplied.
 */

import React from 'react';
import { render, screen, within } from '@testing-library/react';
import '@testing-library/jest-dom';

import { EmittedLintLens } from '../src/app/components/ade/dashboard/export/EmittedLintLens';
import type {
  EmittedArtifactLintReport,
  EmittedLintFinding,
} from '../src/app/components/ade/dashboard/export/exportVerify';

/** A lint report with the given findings; override any field. */
function report(
  findings: EmittedLintFinding[],
  overrides: Partial<EmittedArtifactLintReport> = {},
): EmittedArtifactLintReport {
  return {
    applicable: true,
    pack: 'spectral:oas',
    score: 88,
    grade: 'B',
    findings,
    ...overrides,
  };
}

describe('EmittedLintLens — findings grouped by severity with locations (MFX-42.3)', () => {
  it('groups findings error → warning → info, each with rule id, category, and location', () => {
    render(
      <EmittedLintLens
        targetLabel="OpenAPI 3.1"
        lint={report([
          { severity: 'warning', rule: 'oas3-schema', category: 'structure', message: 'Missing example.', file: 'openapi.yaml', line: 20, column: 5 },
          { severity: 'error', rule: 'no-eval-in-markdown', category: 'security', message: 'Script in description.', path: '#/info/description' },
          { severity: 'info', rule: 'info-contact', message: 'Add a contact.', file: 'openapi.yaml', line: 3 },
        ])}
      />,
    );

    const lens = screen.getByTestId('verify-lint');
    expect(lens).toHaveAttribute('data-lint-state', 'findings');

    // Three severity groups render, each with its count.
    expect(screen.getByTestId('verify-lint-group-error')).toBeInTheDocument();
    expect(screen.getByTestId('verify-lint-group-warning')).toBeInTheDocument();
    expect(screen.getByTestId('verify-lint-group-info')).toBeInTheDocument();
    expect(screen.getByTestId('verify-lint-group-count-error')).toHaveTextContent('1');

    // Errors come before warnings before info in the DOM (matches the catalog tier order).
    const html = lens.innerHTML;
    expect(html.indexOf('verify-lint-group-error')).toBeLessThan(html.indexOf('verify-lint-group-warning'));
    expect(html.indexOf('verify-lint-group-warning')).toBeLessThan(html.indexOf('verify-lint-group-info'));

    // The warning finding shows its rule id, category, message, and location.
    const warningGroup = screen.getByTestId('verify-lint-group-warning');
    expect(warningGroup).toHaveTextContent('oas3-schema');
    expect(warningGroup).toHaveTextContent('structure');
    expect(warningGroup).toHaveTextContent('Missing example.');
    const loc = within(warningGroup).getByTestId('verify-finding-location');
    expect(loc).toHaveTextContent('openapi.yaml');
    expect(loc).toHaveTextContent('20:5');

    // The error finding's location falls back to its JSON pointer when it has no line.
    expect(within(screen.getByTestId('verify-lint-group-error')).getByTestId('verify-finding-location')).toHaveTextContent(
      '#/info/description',
    );
  });
});

describe('EmittedLintLens — score/grade consistent with catalog lint visuals (MFX-42.3)', () => {
  it('renders the pack score and letter grade as a chip', () => {
    render(<EmittedLintLens lint={report([{ severity: 'info', rule: 'r', message: 'm' }], { score: 88, grade: 'B' })} />);
    expect(screen.getByTestId('verify-lint-grade')).toHaveTextContent('B · 88/100');
  });

  it('omits the score chip when the pack computes no score', () => {
    render(
      <EmittedLintLens
        lint={report([{ severity: 'warning', rule: 'r', message: 'm' }], { score: null, grade: null })}
      />,
    );
    expect(screen.queryByTestId('verify-lint-grade')).not.toBeInTheDocument();
    // Findings still render without a (misleading) score.
    expect(screen.getByTestId('verify-lint-findings')).toBeInTheDocument();
  });
});

describe('EmittedLintLens — empty state is explicit (MFX-42.3)', () => {
  it('names the target and says there is nothing to lint when no pack applies', () => {
    render(<EmittedLintLens targetLabel="Postman Collection" lint={{ applicable: false, findings: [] }} />);
    const empty = screen.getByTestId('verify-lint-empty');
    expect(empty).toHaveTextContent('Postman Collection');
    expect(empty).toHaveTextContent(/no lint pack is registered/i);
    expect(empty).toHaveTextContent(/not blocked by lint/i);
  });

  it('treats a null report as not-applicable (the endpoint ran no lint pass)', () => {
    render(<EmittedLintLens lint={null} />);
    expect(screen.getByTestId('verify-lint-empty')).toBeInTheDocument();
    expect(screen.queryByTestId('verify-lint')).not.toBeInTheDocument();
  });
});

describe('EmittedLintLens — clean report renders a positive confirmation (MFX-42.3)', () => {
  it('confirms the pack reported no findings when applicable and empty', () => {
    render(<EmittedLintLens lint={report([], { score: 100, grade: 'A' })} />);
    const lens = screen.getByTestId('verify-lint');
    expect(lens).toHaveAttribute('data-lint-state', 'clean');
    expect(screen.getByTestId('verify-lint-clean')).toHaveTextContent(/no findings/i);
    expect(screen.queryByTestId('verify-lint-findings')).not.toBeInTheDocument();
    // The score chip still shows so a clean result reads as scored, not unscored.
    expect(screen.getByTestId('verify-lint-grade')).toHaveTextContent('A · 100/100');
  });
});

describe('EmittedLintLens — distinguishes emitted lint from the source catalog lint (MFX-42.3)', () => {
  it('always notes the findings lint the emitted artifact, not the source', () => {
    render(<EmittedLintLens targetLabel="gRPC / Protobuf" lint={report([{ severity: 'warning', rule: 'r', message: 'm' }])} />);
    const note = screen.getByTestId('verify-lint-source-note');
    expect(note).toHaveTextContent(/emitted gRPC \/ Protobuf/i);
    expect(note).toHaveTextContent(/not the source's catalog lint/i);
    // No source report supplied → no link.
    expect(screen.queryByTestId('verify-lint-source-link')).not.toBeInTheDocument();
  });

  it('links the source report when one is supplied', () => {
    render(
      <EmittedLintLens
        targetLabel="gRPC / Protobuf"
        lint={report([{ severity: 'warning', rule: 'r', message: 'm' }])}
        sourceReport={{ href: '/ade/dashboard/catalog/item-7', label: 'Pet Store' }}
      />,
    );
    const link = screen.getByTestId('verify-lint-source-link');
    expect(link).toHaveAttribute('href', '/ade/dashboard/catalog/item-7');
    expect(link).toHaveTextContent(/Pet Store/);
  });
});
