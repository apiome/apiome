/**
 * The route half of the release gate (`lib/feature-release.ts`): every page under an
 * unreleased route answers with the "not available yet" state, and the feature itself only
 * renders once it is released (or re-opened by the build-time preview override).
 */
import React from 'react';
import { cleanup, render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';
import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

import UnreleasedFeatureGate from '../src/app/components/shell/UnreleasedFeatureGate';
import { UNRELEASED_FEATURE_IDS } from '../lib/feature-release';

jest.mock('next/navigation', () => ({
  usePathname: () => '/ade/dashboard/connectors',
  useRouter: () => ({ push: jest.fn(), replace: jest.fn(), prefetch: jest.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

afterEach(() => {
  cleanup();
  delete process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES;
});

describe('UnreleasedFeatureGate', () => {
  it('withholds the feature and points the reader at Projects', () => {
    render(
      <UnreleasedFeatureGate feature="connectors">
        <p>feature body</p>
      </UnreleasedFeatureGate>
    );

    expect(screen.queryByText('feature body')).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 1, name: 'Connectors' })).toBeInTheDocument();
    const gate = screen.getByTestId('unreleased-feature-gate');
    expect(gate).toHaveTextContent('Not available yet');
    expect(gate).toHaveTextContent('Connectors opens in a later release, once it is finished.');
    expect(screen.getByRole('link', { name: 'Go to Projects' })).toHaveAttribute(
      'href',
      '/ade/dashboard/projects'
    );
  });

  it('renders the feature once the preview override re-opens it', () => {
    process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES = 'connectors';
    render(
      <UnreleasedFeatureGate feature="connectors">
        <p>feature body</p>
      </UnreleasedFeatureGate>
    );

    expect(screen.getByText('feature body')).toBeInTheDocument();
    expect(screen.queryByTestId('unreleased-feature-gate')).not.toBeInTheDocument();
  });
});

describe('route layouts', () => {
  /** The route folder each held-back id gates, under `src/app/ade/dashboard`. */
  const ROUTES: Record<string, string> = {
    'dependency-graph': 'graph',
    'schema-registry': 'schema-registry',
    connectors: 'connectors',
    'shadow-apis': 'connectors/shadow',
    products: 'products',
  };

  it.each(UNRELEASED_FEATURE_IDS)('wraps the %s route in the gate', (id) => {
    const file = join(__dirname, '..', 'src/app/ade/dashboard', ROUTES[id], 'layout.tsx');
    expect(existsSync(file)).toBe(true);
    expect(readFileSync(file, 'utf8')).toContain(`<UnreleasedFeatureGate feature="${id}">`);
  });
});
