/**
 * Unit tests for ImportOptionsForm — the shared import-options editor used by both
 * the Projects dashboard import dialog (PreviewPanel) and the repository file import
 * flow (RepositoryFileImportMapping).
 *
 * The component is controlled (parent owns the ImportOptions), so these tests assert
 * the rendered controls and that each edit calls onOptionChange(key, value) correctly.
 */

import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';

import { ImportOptionsForm } from '../src/app/components/ade/dashboard/ImportOptionsForm';
import type { ImportOptions } from '../src/app/components/ade/dashboard/PreviewPanel';

function baseOptions(overrides: Partial<ImportOptions> = {}): ImportOptions {
  return {
    projectName: 'Petstore',
    projectSlug: 'petstore',
    versionSource: 'spec',
    targetVersion: '1.0.0',
    selectedSchemas: ['Pet'],
    applyNamingConvention: true,
    classNamingConvention: 'PascalCase',
    propertyNamingConvention: 'camelCase',
    classPrefix: '',
    classSuffix: '',
    generateExamples: false,
    dryRun: false,
    incrementalMode: false,
    ...overrides,
  };
}

describe('ImportOptionsForm', () => {
  it('renders naming and flag controls by default', () => {
    render(<ImportOptionsForm options={baseOptions()} onOptionChange={jest.fn()} />);

    expect(screen.getByRole('checkbox', { name: /apply naming convention/i })).toBeInTheDocument();
    expect(screen.getByDisplayValue('PascalCase')).toBeInTheDocument(); // class convention select
    expect(screen.getByDisplayValue('camelCase')).toBeInTheDocument(); // property convention select
    expect(screen.getByPlaceholderText('e.g. Api')).toBeInTheDocument(); // prefix
    expect(screen.getByPlaceholderText('e.g. Dto')).toBeInTheDocument(); // suffix
    expect(screen.getByRole('checkbox', { name: /generate examples/i })).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: /dry run/i })).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: /incremental mode/i })).toBeInTheDocument();
  });

  it('toggling apply-naming-convention reports the negated value', () => {
    const onOptionChange = jest.fn();
    render(<ImportOptionsForm options={baseOptions({ applyNamingConvention: true })} onOptionChange={onOptionChange} />);

    fireEvent.click(screen.getByRole('checkbox', { name: /apply naming convention/i }));
    expect(onOptionChange).toHaveBeenCalledWith('applyNamingConvention', false);
  });

  it('hides the convention selects when naming convention is off', () => {
    render(<ImportOptionsForm options={baseOptions({ applyNamingConvention: false })} onOptionChange={jest.fn()} />);

    expect(screen.queryByDisplayValue('PascalCase')).not.toBeInTheDocument();
    expect(screen.queryByDisplayValue('camelCase')).not.toBeInTheDocument();
    // The prefix/suffix inputs remain available.
    expect(screen.getByPlaceholderText('e.g. Api')).toBeInTheDocument();
  });

  it('reports class and property naming convention changes', () => {
    const onOptionChange = jest.fn();
    render(<ImportOptionsForm options={baseOptions()} onOptionChange={onOptionChange} />);

    fireEvent.change(screen.getByDisplayValue('PascalCase'), { target: { value: 'snake_case' } });
    expect(onOptionChange).toHaveBeenCalledWith('classNamingConvention', 'snake_case');

    fireEvent.change(screen.getByDisplayValue('camelCase'), { target: { value: 'kebab-case' } });
    expect(onOptionChange).toHaveBeenCalledWith('propertyNamingConvention', 'kebab-case');
  });

  it('reports class prefix and suffix edits', () => {
    const onOptionChange = jest.fn();
    render(<ImportOptionsForm options={baseOptions()} onOptionChange={onOptionChange} />);

    fireEvent.change(screen.getByPlaceholderText('e.g. Api'), { target: { value: 'Api' } });
    expect(onOptionChange).toHaveBeenCalledWith('classPrefix', 'Api');

    fireEvent.change(screen.getByPlaceholderText('e.g. Dto'), { target: { value: 'Dto' } });
    expect(onOptionChange).toHaveBeenCalledWith('classSuffix', 'Dto');
  });

  it('reports flag toggles', () => {
    const onOptionChange = jest.fn();
    render(<ImportOptionsForm options={baseOptions()} onOptionChange={onOptionChange} />);

    fireEvent.click(screen.getByRole('checkbox', { name: /generate examples/i }));
    expect(onOptionChange).toHaveBeenCalledWith('generateExamples', true);

    fireEvent.click(screen.getByRole('checkbox', { name: /dry run/i }));
    expect(onOptionChange).toHaveBeenCalledWith('dryRun', true);

    fireEvent.click(screen.getByRole('checkbox', { name: /incremental mode/i }));
    expect(onOptionChange).toHaveBeenCalledWith('incrementalMode', true);
  });

  it('renders only the naming section when requested', () => {
    render(<ImportOptionsForm options={baseOptions()} onOptionChange={jest.fn()} sections={['naming']} />);

    expect(screen.getByRole('checkbox', { name: /apply naming convention/i })).toBeInTheDocument();
    expect(screen.queryByRole('checkbox', { name: /generate examples/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('checkbox', { name: /dry run/i })).not.toBeInTheDocument();
  });

  it('renders only the flags section when requested', () => {
    render(<ImportOptionsForm options={baseOptions()} onOptionChange={jest.fn()} sections={['flags']} />);

    expect(screen.queryByRole('checkbox', { name: /apply naming convention/i })).not.toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: /generate examples/i })).toBeInTheDocument();
  });

  it('can hide the dry-run and incremental-mode flags', () => {
    render(
      <ImportOptionsForm
        options={baseOptions()}
        onOptionChange={jest.fn()}
        sections={['flags']}
        showDryRun={false}
        showIncrementalMode={false}
      />
    );

    expect(screen.getByRole('checkbox', { name: /generate examples/i })).toBeInTheDocument();
    expect(screen.queryByRole('checkbox', { name: /dry run/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('checkbox', { name: /incremental mode/i })).not.toBeInTheDocument();
  });
});
