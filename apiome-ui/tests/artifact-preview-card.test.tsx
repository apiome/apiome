/**
 * Render tests for the emitted-artifact preview card (MFX-6.3), now backed by the shared read-only
 * viewer and the registry-driven language resolver (MFX-43.1, #4361).
 *
 * The card must resolve its highlight language registry-driven — the emitter key when known, else the
 * artifact's own media type / filename — and keep the stable test ids the export dialog relies on.
 * Monaco is stubbed so the assertions never depend on the real editor loading.
 */

jest.mock('@monaco-editor/react', () => ({
  __esModule: true,
  default: ({ value, language }: { value?: string; language?: string }) => (
    <div data-testid="mock-monaco" data-language={language}>
      {value}
    </div>
  ),
}));

import React from 'react';
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';
import { ArtifactPreviewCard } from '../src/app/components/ade/dashboard/export/ArtifactPreviewCard';
import type { EmittedArtifact } from '../src/app/components/ade/dashboard/export/exportArtifactPreview';

function renderCard(artifact: EmittedArtifact, targetKey?: string | null) {
  return render(<ArtifactPreviewCard artifact={artifact} report={null} targetKey={targetKey} />);
}

describe('ArtifactPreviewCard language resolution (MFX-43.1)', () => {
  it('keeps its stable test ids and the copy control', async () => {
    renderCard({ filename: 'api.proto', mediaType: 'text/plain', text: 'syntax = "proto3";' }, 'protobuf');

    expect(await screen.findByTestId('export-artifact-preview')).toBeInTheDocument();
    expect(screen.getByTestId('export-artifact-editor')).toBeInTheDocument();
    expect(screen.getByTestId('export-artifact-copy')).toBeInTheDocument();
  });

  it('trusts a known emitter key over the artifact bytes/headers', async () => {
    renderCard({ filename: 'api.proto', mediaType: 'text/plain', text: 'syntax = "proto3";' }, 'protobuf');

    expect(await screen.findByTestId('export-artifact-editor')).toHaveAttribute(
      'data-language',
      'protobuf',
    );
  });

  it('types an unknown emitter from the artifact media type (registry-driven)', async () => {
    renderCard(
      { filename: 'schema.txt', mediaType: 'application/graphql', text: 'type Query { a: Int }' },
      null,
    );

    expect(await screen.findByTestId('export-artifact-editor')).toHaveAttribute(
      'data-language',
      'graphql',
    );
  });

  it('types an unknown emitter from the filename when the media type is silent', async () => {
    renderCard({ filename: 'service.wsdl', mediaType: '', text: '<definitions/>' }, null);

    expect(await screen.findByTestId('export-artifact-editor')).toHaveAttribute('data-language', 'xml');
  });

  it('refines a JSON-or-YAML emitter from the emitted bytes', async () => {
    renderCard(
      { filename: 'openapi.yaml', mediaType: 'application/yaml', text: 'openapi: 3.1.0\ninfo:' },
      'openapi',
    );

    expect(await screen.findByTestId('export-artifact-editor')).toHaveAttribute('data-language', 'yaml');
  });
});
