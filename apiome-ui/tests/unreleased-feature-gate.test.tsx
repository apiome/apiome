/**
 * The route half of the release gate (`lib/feature-release.ts`): every page under an
 * unreleased route answers with the "not available yet" state, and the feature itself only
 * renders once it is released (or re-opened by the build-time preview override).
 */
import React from 'react';
import { cleanup, render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';

import UnreleasedFeatureGate from '../src/app/components/shell/UnreleasedFeatureGate';

jest.mock('next/navigation', () => ({
  usePathname: () => '/ade/dashboard/style-guides',
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
      <UnreleasedFeatureGate feature="style-guides">
        <p>feature body</p>
      </UnreleasedFeatureGate>
    );

    expect(screen.queryByText('feature body')).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 1, name: 'Style guides' })).toBeInTheDocument();
    const gate = screen.getByTestId('unreleased-feature-gate');
    expect(gate).toHaveTextContent('Not available yet');
    expect(gate).toHaveTextContent('Style guides opens once Catalog and Projects are ready.');
    expect(screen.getByRole('link', { name: 'Go to Projects' })).toHaveAttribute(
      'href',
      '/ade/dashboard/projects'
    );
  });

  it('renders the feature once the preview override re-opens it', () => {
    process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES = 'style-guides';
    render(
      <UnreleasedFeatureGate feature="style-guides">
        <p>feature body</p>
      </UnreleasedFeatureGate>
    );

    expect(screen.getByText('feature body')).toBeInTheDocument();
    expect(screen.queryByTestId('unreleased-feature-gate')).not.toBeInTheDocument();
  });
});

describe('UnreleasedFeatureGate — features embedded in Catalog and Projects', () => {
  it('names an embedded feature and its section, though it has no rail item', () => {
    render(
      <UnreleasedFeatureGate feature="consumers">
        <p>feature body</p>
      </UnreleasedFeatureGate>
    );

    expect(screen.queryByText('feature body')).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 1, name: 'Consumer contracts' })).toBeInTheDocument();
    // The section crumb, beside the "Go to Projects" action.
    expect(screen.getByText('Projects', { exact: true })).toBeInTheDocument();
    expect(screen.getByTestId('unreleased-feature-gate')).toHaveTextContent(
      'Consumer contracts opens once Catalog and Projects are ready.'
    );
  });
});
