/**
 * Render tests for the shared read-only Monaco viewer (MFX-43.1, #4361).
 *
 * The viewer must render its text read-only in Monaco with the given language, match the app
 * dark/light theme, forward its word-wrap and overlay, and expose stable test ids. Monaco is stubbed
 * with a lightweight component that echoes the props under test so the assertions never depend on the
 * real editor (or its web workers) loading.
 */

// Stub `@monaco-editor/react` with a component that surfaces the props under test.
jest.mock('@monaco-editor/react', () => ({
  __esModule: true,
  default: ({
    value,
    language,
    theme,
    options,
  }: {
    value?: string;
    language?: string;
    theme?: string;
    options?: { wordWrap?: string; readOnly?: boolean };
  }) => (
    <div
      data-testid="mock-monaco"
      data-language={language}
      data-theme={theme}
      data-wordwrap={options?.wordWrap}
      data-readonly={String(options?.readOnly)}
    >
      {value}
    </div>
  ),
}));

import React from 'react';
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';
import { ReadOnlyCodeViewer } from '../src/app/components/ade/dashboard/export/ReadOnlyCodeViewer';

const PROTO = 'syntax = "proto3";\nmessage Order { string id = 1; }';

afterEach(() => {
  document.documentElement.classList.remove('dark');
});

describe('ReadOnlyCodeViewer (MFX-43.1)', () => {
  it('renders the text read-only in Monaco with the given language', async () => {
    render(<ReadOnlyCodeViewer value={PROTO} language="protobuf" />);

    const editor = await screen.findByTestId('mock-monaco');
    expect(editor).toHaveTextContent('syntax = "proto3"');
    expect(editor).toHaveAttribute('data-language', 'protobuf');
    expect(editor).toHaveAttribute('data-readonly', 'true');
    // Word-wrap is off by default (specs read horizontally).
    expect(editor).toHaveAttribute('data-wordwrap', 'off');
  });

  it('tags the container with the language for assertions and defaults its test id', async () => {
    render(<ReadOnlyCodeViewer value="scalar JSON" language="graphql" />);

    const container = await screen.findByTestId('read-only-code-editor');
    expect(container).toHaveAttribute('data-language', 'graphql');
  });

  it('honours custom test ids and an overlay control', async () => {
    render(
      <ReadOnlyCodeViewer
        value={PROTO}
        language="protobuf"
        editorTestId="export-artifact-editor"
        overlay={<button data-testid="my-overlay">Copy</button>}
      />,
    );

    expect(await screen.findByTestId('export-artifact-editor')).toBeInTheDocument();
    expect(screen.getByTestId('my-overlay')).toBeInTheDocument();
  });

  it('forwards word-wrap when requested', async () => {
    render(<ReadOnlyCodeViewer value={PROTO} language="protobuf" wordWrap="on" />);

    const editor = await screen.findByTestId('mock-monaco');
    expect(editor).toHaveAttribute('data-wordwrap', 'on');
  });

  it('uses the light theme by default', async () => {
    render(<ReadOnlyCodeViewer value={PROTO} language="protobuf" />);

    const editor = await screen.findByTestId('mock-monaco');
    expect(editor).toHaveAttribute('data-theme', 'light');
  });

  it('matches the app dark theme when the html carries the dark class', async () => {
    document.documentElement.classList.add('dark');
    render(<ReadOnlyCodeViewer value={PROTO} language="protobuf" />);

    const editor = await screen.findByTestId('mock-monaco');
    expect(editor).toHaveAttribute('data-theme', 'vs-dark');
  });
});
