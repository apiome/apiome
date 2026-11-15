/**
 * Export studio's SDK compatibility tab — SGD-2.1 (#4735).
 *
 * Renders the golden manifest (shared with apiome-rest and apiome-cli) through the BFF contract and
 * checks the tab shows findings first, each with its action, then every artifact. With
 * `A11Y_FIXTURE_DUMP=1` it writes `e2e/fixtures/hive-a11y/sdk-compat.html`, the docs screenshot fixture.
 */

import React from 'react';
import * as fs from 'fs';
import * as path from 'path';
import { render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';

import { writeA11yFixture } from './helpers/a11y-fixture-dump';

jest.mock('next/navigation', () => ({
  usePathname: () => '/ade/dashboard/export/studio',
  useSearchParams: () => new URLSearchParams('tab=sdk-compat'),
}));

import SdkCompatClient from '@/app/components/ade/export-studio/compat/SdkCompatClient';
import type { SdkCompatManifest } from '@lib/sdk-compat-manifest';

const GOLDEN = path.resolve(__dirname, '..', '..', 'apiome-rest', 'tests', 'golden', 'sdk_compat_manifest', 'widgets.json');
const MANIFEST = JSON.parse(fs.readFileSync(GOLDEN, 'utf8')) as SdkCompatManifest;

const calls: string[] = [];

beforeEach(() => {
  calls.length = 0;
  global.fetch = jest.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    calls.push(url);
    const body = url.startsWith('/api/projects?') || url === '/api/projects'
      ? { success: true, projects: [{ id: 'p-1', name: 'Widgets API' }] }
      : url.startsWith('/api/versions')
        ? { success: true, versions: [{ id: 'rev-1', version_id: '1.0.0' }] }
        : url.startsWith('/api/projects/p-1/sdk-compatibility')
          ? { success: true, data: MANIFEST }
          : { success: false, error: 'unexpected' };
    return { ok: true, json: async () => body } as Response;
  }) as unknown as typeof fetch;
});

describe('SDK compatibility tab', () => {
  it('loads the latest revision of the first project and shows findings before artifacts', async () => {
    const preview = process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES;
    process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES = 'all';
    try {
      // The tab strip is the route's (covered by export-studio-route.test.tsx); a stand-in keeps this
      // test independent of it.
      render(<SdkCompatClient tabs={<nav data-testid="tabs-stub" />} />);
      await screen.findByTestId('sdk-compat-manifest');
      expect(calls).toContain('/api/projects/p-1/sdk-compatibility');

      const findings = within(screen.getByTestId('sdk-compat-findings')).getAllByTestId('sdk-compat-finding');
      expect(findings).toHaveLength(MANIFEST.findings_count);
      expect(findings[0]).toHaveTextContent('What to do:');

      for (const artifact of MANIFEST.artifacts) {
        expect(screen.getByTestId(`sdk-compat-artifact-${artifact.id}`)).toBeInTheDocument();
      }
      const body = screen.getByTestId('sdk-compat-manifest');
      const html = body.innerHTML;
      expect(html.indexOf('sdk-compat-findings')).toBeLessThan(html.indexOf('sdk-compat-artifacts'));
      expect(screen.getByText(/Non-breaking since 0\.9\.0/)).toBeInTheDocument();
      expect(screen.getByTestId('tabs-stub')).toBeInTheDocument();
      writeA11yFixture('sdk-compat', (document.querySelector('.page') as HTMLElement).outerHTML);
    } finally {
      if (preview === undefined) delete process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES;
      else process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES = preview;
    }
  });

  it('shows a clean state when nothing is left out', async () => {
    const clean = { ...MANIFEST, findings_count: 0, artifacts: MANIFEST.artifacts.map((a) => ({ ...a, findings: [] })) };
    (global.fetch as jest.Mock).mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      const body = url === '/api/projects'
        ? { success: true, projects: [{ id: 'p-1', name: 'Widgets API' }] }
        : url.startsWith('/api/versions')
          ? { success: true, versions: [] }
          : { success: true, data: clean };
      return { ok: true, json: async () => body } as Response;
    });
    render(<SdkCompatClient tabs={null} />);
    expect(await screen.findByTestId('sdk-compat-clean')).toBeInTheDocument();
  });

  it('shows the REST error and offers a retry', async () => {
    (global.fetch as jest.Mock).mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      const body = url === '/api/projects'
        ? { success: true, projects: [{ id: 'p-1', name: 'Widgets API' }] }
        : url.startsWith('/api/versions')
          ? { success: true, versions: [] }
          : { success: false, error: 'This revision has no usable source.' };
      return { ok: true, json: async () => body } as Response;
    });
    render(<SdkCompatClient tabs={null} />);
    const error = await screen.findByTestId('sdk-compat-error');
    expect(error).toHaveTextContent('This revision has no usable source.');
    await waitFor(() => expect(within(error).getByRole('button')).toBeInTheDocument());
  });
});
