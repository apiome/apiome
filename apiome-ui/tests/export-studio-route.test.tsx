/**
 * Export Studio route — deep-link entry (MFX-41.1, #4348; MFX-41.4, #4351).
 *
 * The route is the boundary where an untrusted URL becomes Studio state. These tests cover that
 * hand-off: a shared link arrives as validated props (source, target, compact options, resumable
 * step), anything unverifiable arrives as a notice instead, credentials never arrive at all, and a
 * link with no source still lands somewhere useful.
 */

import React from 'react';
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';

const mockSearchParams = jest.fn();
jest.mock('next/navigation', () => ({
  useSearchParams: () => mockSearchParams(),
  usePathname: () => '/ade/dashboard/export/studio',
}));

jest.mock('@lib/auth/session-client', () => ({
  AuthSessionProvider: ({ children }: { children: unknown }) => children,
  signOut: jest.fn(),
  useAuthSession: () => ({ data: { user: { id: 'u-1' } }, status: 'authenticated' }),
}));

jest.mock('next/link', () => ({
  __esModule: true,
  default: ({
    children,
    href,
    ...rest
  }: { children: React.ReactNode; href: string } & Record<string, unknown>) => (
    <a href={typeof href === 'string' ? href : '#'} {...rest}>
      {children}
    </a>
  ),
}));

/** Capture the props the route hands the Studio, instead of mounting the whole workspace. */
const studioProps: Record<string, unknown>[] = [];
jest.mock('../src/app/components/ade/dashboard/export/ExportStudio', () => ({
  __esModule: true,
  ExportStudio: (props: Record<string, unknown>) => {
    studioProps.push(props);
    return <div data-testid="export-studio-stub" />;
  },
}));

/** The SDK & branding tab mounts the SDK settings client; stub it and record its props. */
const sdkProps: Record<string, unknown>[] = [];
jest.mock('../src/app/ade/dashboard/sdk-settings/SdkSettingsClient', () => ({
  __esModule: true,
  default: (props: Record<string, unknown>) => {
    sdkProps.push(props);
    return (
      <div data-testid="sdk-settings-stub">
        {props.tabs as React.ReactNode}
      </div>
    );
  },
}));

import ExportStudioPage from '../src/app/ade/dashboard/export/studio/page';
import { encodeStudioOptions } from '../src/app/components/ade/dashboard/export/exportStudioUrlState';

/** Render the route for one query string and return the props the Studio received. */
function renderRoute(query: string): Record<string, unknown> {
  studioProps.length = 0;
  mockSearchParams.mockReturnValue(new URLSearchParams(query));
  render(<ExportStudioPage />);
  return studioProps[studioProps.length - 1];
}

beforeEach(() => {
  studioProps.length = 0;
  mockSearchParams.mockReset();
});

describe('Export Studio route — deep links (MFX-41.4)', () => {
  it('hands a shared session to the Studio as validated state', () => {
    const opts = encodeStudioOptions({ package: 'com.example' });
    const props = renderRoute(
      `artifact=proj-1&version=rev-9&label=Pet+Store+API&target=proto&from=catalog&sourceFormat=graphql&opts=${opts}&step=verify`,
    );
    expect(props).toMatchObject({
      artifact: 'proj-1',
      version: 'rev-9',
      artifactLabel: 'Pet Store API',
      initialTarget: 'proto',
      initialOptions: { package: 'com.example' },
      initialStep: 'verify',
      origin: 'catalog',
      sourceFormat: 'graphql',
    });
    expect(props.linkIssues).toEqual([]);
  });

  it('still opens a link minted before the compact encoding (MFX-41.3)', () => {
    const props = renderRoute(
      `artifact=proj-1&target=proto&options=${encodeURIComponent('{"package":"com.legacy"}')}`,
    );
    expect(props.initialOptions).toEqual({ package: 'com.legacy' });
    expect(props.initialStep).toBeNull();
  });

  it('never lets a credential out of the URL and into the form', () => {
    const props = renderRoute(
      `artifact=proj-1&target=proto&options=${encodeURIComponent(
        '{"package":"p","registry_token":"sk-live-1"}',
      )}`,
    );
    expect(props.initialOptions).toEqual({ package: 'p' });
    expect(props.linkIssues).toEqual([
      expect.objectContaining({ code: 'options-redacted' }),
    ]);
  });

  it('degrades an unreadable options payload into a notice', () => {
    const props = renderRoute('artifact=proj-1&target=proto&opts=%7Bnope');
    expect(props.initialOptions).toBeNull();
    expect(props.linkIssues).toEqual([
      expect.objectContaining({ code: 'options-unreadable' }),
    ]);
  });

  it('ignores an unknown step rather than resuming somewhere arbitrary', () => {
    expect(renderRoute('artifact=proj-1&step=teleport').initialStep).toBeNull();
  });

  it('shows how to open the Studio when the link carries no source', () => {
    mockSearchParams.mockReturnValue(new URLSearchParams(''));
    render(<ExportStudioPage />);
    expect(screen.getByText(/open the export studio from a source/i)).toBeInTheDocument();
    expect(screen.queryByTestId('export-studio-stub')).not.toBeInTheDocument();
  });
});

describe('Export Studio route — the SDK & branding tab (HIVE-12.2)', () => {
  afterEach(() => {
    delete process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES;
    sdkProps.length = 0;
  });

  it('mounts the SDK settings screen for ?tab=sdk, with the tab strip, whether or not a source is set', () => {
    process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES = 'all';
    for (const query of ['tab=sdk', 'tab=sdk&artifact=proj-1']) {
      mockSearchParams.mockReturnValue(new URLSearchParams(query));
      const { unmount } = render(<ExportStudioPage />);
      expect(screen.getByTestId('sdk-settings-stub')).toBeInTheDocument();
      expect(screen.queryByTestId('export-studio-stub')).not.toBeInTheDocument();
      expect(screen.getByTestId('export-studio-tabs')).toBeInTheDocument();
      unmount();
    }
  });

  it('marks SDK & branding current, and links back to Export keeping the session', () => {
    process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES = 'all';
    mockSearchParams.mockReturnValue(new URLSearchParams('tab=sdk&artifact=proj-1&step=verify'));
    render(<ExportStudioPage />);
    const strip = screen.getByRole('navigation', { name: 'Export studio sections' });
    const links = strip.querySelectorAll('a');
    expect([...links].map((link) => link.textContent)).toEqual(['Export', 'SDK & branding']);
    expect(screen.getByRole('link', { name: 'SDK & branding' })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByRole('link', { name: 'Export' })).not.toHaveAttribute('aria-current');
    expect(screen.getByRole('link', { name: 'Export' })).toHaveAttribute(
      'href',
      '/ade/dashboard/export/studio?artifact=proj-1&step=verify'
    );
  });

  it('passes the strip to the Studio and draws it on the no-source screen too', () => {
    process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES = 'all';
    const props = renderRoute('artifact=proj-1');
    expect(props.tabs).toBeTruthy();

    mockSearchParams.mockReturnValue(new URLSearchParams(''));
    render(<ExportStudioPage />);
    expect(screen.getByRole('heading', { level: 1, name: /Export studio/ })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'SDK & branding' })).toHaveAttribute(
      'href',
      '/ade/dashboard/export/studio?tab=sdk'
    );
  });

  it('keeps the SDK settings release gate on the tab', () => {
    process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES = 'export-studio';
    mockSearchParams.mockReturnValue(new URLSearchParams('tab=sdk'));
    render(<ExportStudioPage />);
    expect(screen.getByTestId('unreleased-feature-gate')).toBeInTheDocument();
    expect(screen.queryByTestId('sdk-settings-stub')).not.toBeInTheDocument();
  });
});

