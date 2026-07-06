/**
 * ValidationResultsLens — the Verify workbench's emitted-output validation lens (MFX-42.2, #4355).
 *
 * Covers the ticket's acceptance surface:
 *  1. Deliberately broken fixtures render actionable errors with their locations, naming the tool.
 *  2. A toolchain-missing verdict renders as a distinct warning (not silent success).
 *  3. A zero-error verdict renders a positive confirmation.
 *  4. A not-applicable format renders an explicit neutral state.
 */

import React from 'react';
import { render, screen, within } from '@testing-library/react';
import '@testing-library/jest-dom';

import { ValidationResultsLens } from '../src/app/components/ade/dashboard/export/ValidationResultsLens';
import type { EmittedValidationReport } from '../src/app/components/ade/dashboard/export/exportVerify';

/** A validation report with the given verdict; override any field. */
function report(
  verdict: EmittedValidationReport['verdict'],
  overrides: Partial<EmittedValidationReport> = {},
): EmittedValidationReport {
  return {
    verdict,
    target: 'proto-3',
    blocks_delivery: verdict === 'invalid',
    warns: verdict === 'skipped',
    valid: verdict === 'valid',
    findings: [],
    detail: null,
    headline:
      verdict === 'invalid'
        ? 'Invalid — export blocked'
        : verdict === 'skipped'
          ? 'Validation skipped'
          : verdict === 'not_applicable'
            ? 'No validator for this format'
            : 'Valid',
    message: 'The emitted artifact was checked.',
    ...overrides,
  };
}

describe('ValidationResultsLens — invalid renders actionable errors with locations (MFX-42.2)', () => {
  it('lists each structured error with its file, line:col, and rule, and names the validator', () => {
    render(
      <ValidationResultsLens
        validation={report('invalid', {
          tool: 'buf build',
          findings: [
            {
              message: 'Field number 0 is not allowed.',
              file: 'petstore.proto',
              path: '#/messages/Pet',
              line: 12,
              column: 3,
              keyword: 'buf.field-number',
            },
          ],
        })}
      />,
    );

    const lens = screen.getByTestId('verify-validation');
    expect(lens).toHaveAttribute('data-validation-state', 'invalid');
    // The validator identity is surfaced.
    expect(screen.getByTestId('verify-validation-tool')).toHaveTextContent('buf build');
    expect(screen.getByTestId('verify-validation-tool')).toHaveTextContent(/validated with/i);

    // The actionable error and its full location render.
    const findings = screen.getByTestId('verify-validation-findings');
    expect(findings).toHaveTextContent('Field number 0 is not allowed.');
    const loc = within(findings).getByTestId('verify-finding-location');
    expect(loc).toHaveTextContent('petstore.proto');
    expect(loc).toHaveTextContent('#/messages/Pet');
    expect(loc).toHaveTextContent('12:3');
    expect(loc).toHaveTextContent('buf.field-number');
  });

  it('renders a line-only location when no column is provided', () => {
    render(
      <ValidationResultsLens
        validation={report('invalid', {
          findings: [{ message: 'Broken.', file: 'schema.xsd', line: 7 }],
        })}
      />,
    );
    expect(screen.getByTestId('verify-finding-location')).toHaveTextContent('line 7');
  });
});

describe('ValidationResultsLens — toolchain unavailable is a distinct warning (MFX-42.2)', () => {
  it('shows an explicit warning that the artifact was not validated, with the reason and tool', () => {
    render(
      <ValidationResultsLens
        validation={report('skipped', {
          warns: true,
          tool: 'buf build',
          detail: 'buf is not installed on the server.',
        })}
      />,
    );
    const lens = screen.getByTestId('verify-validation');
    expect(lens).toHaveAttribute('data-validation-state', 'unavailable');

    const warning = screen.getByTestId('verify-validation-unavailable');
    expect(warning).toHaveTextContent(/not validated/i);
    expect(warning).toHaveTextContent('buf is not installed on the server.');

    // It names the missing toolchain, framed as unavailable — not as a clean pass.
    expect(screen.getByTestId('verify-validation-tool')).toHaveTextContent('buf build');
    expect(screen.getByTestId('verify-validation-tool')).toHaveTextContent(/not installed/i);
    expect(screen.queryByTestId('verify-validation-clean')).not.toBeInTheDocument();
  });
});

describe('ValidationResultsLens — zero errors render a positive verdict (MFX-42.2)', () => {
  it('confirms the artifact re-parsed cleanly and lists no findings', () => {
    render(<ValidationResultsLens validation={report('valid', { tool: 'xmlschema' })} />);
    const lens = screen.getByTestId('verify-validation');
    expect(lens).toHaveAttribute('data-validation-state', 'valid');
    expect(screen.getByTestId('verify-validation-clean')).toHaveTextContent(/no validation errors/i);
    expect(screen.getByTestId('verify-validation-tool')).toHaveTextContent('xmlschema');
    expect(screen.queryByTestId('verify-validation-findings')).not.toBeInTheDocument();
  });
});

describe('ValidationResultsLens — not applicable renders a neutral state (MFX-42.2)', () => {
  it('explains there is nothing to validate for the target', () => {
    render(<ValidationResultsLens validation={report('not_applicable', { tool: null })} />);
    const lens = screen.getByTestId('verify-validation');
    expect(lens).toHaveAttribute('data-validation-state', 'not_applicable');
    expect(screen.getByTestId('verify-validation-not-applicable')).toHaveTextContent(
      /nothing to validate/i,
    );
    // No validator ran, so no tool line and no findings.
    expect(screen.queryByTestId('verify-validation-tool')).not.toBeInTheDocument();
    expect(screen.queryByTestId('verify-validation-findings')).not.toBeInTheDocument();
  });
});
