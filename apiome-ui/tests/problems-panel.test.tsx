/**
 * Render tests for the per-file problems list (MFX-43.3, #4363).
 *
 * The panel must: render one row per located problem with its severity, line:col, message, and
 * rule; report row clicks so the caller can reveal the line; mark the selected row; and render
 * nothing at all for a clean file.
 */

import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import '@testing-library/jest-dom';

import { ProblemsPanel } from '../src/app/components/ade/dashboard/export/ProblemsPanel';
import { collectLocatedProblems } from '../src/app/components/ade/dashboard/export/exportProblemMarkers';

const problems = collectLocatedProblems(
  [{ message: 'Field number 0 is not allowed.', file: 'petstore.proto', line: 12, column: 3, keyword: 'buf.field-number' }],
  [{ severity: 'warning', rule: 'proto-style', message: 'Prefer explicit package.', file: 'petstore.proto', line: 1 }],
);

describe('ProblemsPanel (MFX-43.3)', () => {
  it('renders one row per problem with location, message, and rule', () => {
    render(<ProblemsPanel problems={problems} selectedId={null} onSelect={jest.fn()} />);

    expect(screen.getByTestId('verify-problems-count')).toHaveTextContent('2');
    const errorRow = screen.getByTestId('verify-problem-validation-0');
    expect(errorRow).toHaveTextContent('12:3');
    expect(errorRow).toHaveTextContent('Field number 0 is not allowed.');
    expect(errorRow).toHaveTextContent('buf.field-number');
    // A column-less problem shows just its line.
    expect(screen.getByTestId('verify-problem-lint-0')).toHaveTextContent('1');
  });

  it('reports row clicks and marks the selected row', () => {
    const onSelect = jest.fn();
    render(<ProblemsPanel problems={problems} selectedId="lint-0" onSelect={onSelect} />);

    expect(screen.getByTestId('verify-problem-lint-0')).toHaveAttribute('data-selected', 'true');
    expect(screen.getByTestId('verify-problem-validation-0')).toHaveAttribute('data-selected', 'false');

    fireEvent.click(screen.getByTestId('verify-problem-validation-0'));
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ id: 'validation-0' }));
  });

  it('renders nothing for a clean file', () => {
    render(<ProblemsPanel problems={[]} selectedId={null} onSelect={jest.fn()} />);
    expect(screen.queryByTestId('verify-problems')).not.toBeInTheDocument();
  });
});
