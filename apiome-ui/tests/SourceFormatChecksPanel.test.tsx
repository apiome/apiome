/**
 * Integration tests for SourceFormatChecksPanel (CLX-2.4 / #4854).
 */

import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { SourceFormatChecksPanel } from '@/app/components/ade/dashboard/lint/SourceFormatChecksPanel';

describe('SourceFormatChecksPanel', () => {
  const originalFetch = global.fetch;

  afterEach(() => {
    global.fetch = originalFetch;
    jest.restoreAllMocks();
  });

  it('renders scanner chips from evidence coverage', async () => {
    global.fetch = jest.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes('/lint/evidence')) {
        return {
          ok: true,
          json: async () => ({
            success: true,
            coverage: [
              {
                scannerId: 'apiome.native-lint',
                outcome: 'passed',
                coverage: { state: 'full' },
              },
              {
                scannerId: 'graphql.eslint',
                outcome: 'unavailable',
                coverage: { state: 'none' },
              },
            ],
          }),
        } as Response;
      }
      if (url.includes('/format-capabilities')) {
        return {
          ok: true,
          json: async () => ({
            success: true,
            formats: [{ format: 'graphql', mode: 'native', adaptedScanners: ['graphql.eslint'] }],
          }),
        } as Response;
      }
      return { ok: false, json: async () => ({}) } as Response;
    }) as typeof fetch;

    render(
      <SourceFormatChecksPanel
        projectId="proj-1"
        versionRecordId="ver-1"
        sourceFormat="graphql"
      />
    );

    await waitFor(() => {
      expect(screen.getByTestId('source-format-checks-list')).toBeInTheDocument();
    });
    expect(screen.getByTestId('source-format-check-apiome.native-lint')).toHaveTextContent(
      /Native lint/i
    );
    expect(screen.getByTestId('source-format-check-graphql.eslint')).toHaveTextContent(
      /unavailable/i
    );
  });

  it('shows unsupported empty state with related issue link', async () => {
    global.fetch = jest.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes('/lint/evidence')) {
        return {
          ok: true,
          json: async () => ({
            success: true,
            coverage: [
              {
                scannerId: 'apiome.native-lint',
                outcome: 'passed',
                coverage: { state: 'full' },
              },
            ],
          }),
        } as Response;
      }
      if (url.includes('/format-capabilities')) {
        return {
          ok: true,
          json: async () => ({
            success: true,
            formats: [
              {
                format: 'smithy',
                mode: 'unsupported',
                commonPackOnly: true,
                relatedIssues: ['https://github.com/apiome/apiome/issues/3810'],
              },
            ],
          }),
        } as Response;
      }
      return { ok: false, json: async () => ({}) } as Response;
    }) as typeof fetch;

    render(
      <SourceFormatChecksPanel
        projectId="proj-1"
        versionRecordId="ver-1"
        sourceFormat="smithy"
      />
    );

    await waitFor(() => {
      expect(screen.getByTestId('source-format-checks-unsupported')).toBeInTheDocument();
    });
    expect(screen.getByText(/Planned pack issue/i)).toHaveAttribute(
      'href',
      'https://github.com/apiome/apiome/issues/3810'
    );
  });
});
