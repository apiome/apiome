/**
 * Related artifacts — pending and failed reads (RC6-H3, #6210).
 *
 * The Versions timeline's Related artifacts section reads its project, and the panel's **Suggest
 * links** reads identity suggestions. Before RC6-H3 a rejected project read left the section blank
 * forever and a failed suggestion read was a toast that faded. Each now holds its place while
 * pending and says what failed, with a retry.
 */

import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';

jest.mock('next/link', () => ({
  __esModule: true,
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

import { ProjectRelatedArtifactsSection } from '../src/app/components/ade/dashboard/ProjectRelatedArtifactsSection';
import { CatalogRelatedArtifactsPanel } from '../src/app/components/ade/dashboard/catalog/CatalogRelatedArtifactsPanel';

const PROJECT_ID = 'proj-1';

/** A JSON response. */
const json = (body: unknown, status = 200) =>
  Promise.resolve({ ok: status < 400, status, json: () => Promise.resolve(body) } as Response);

/** The project read, answered. */
const PROJECT = { success: true, project: { identityGroupId: 'grp-1', relatedArtifacts: [] } };

afterEach(() => {
  jest.restoreAllMocks();
});

describe('ProjectRelatedArtifactsSection', () => {
  it('holds a card-shaped placeholder while the project reads', async () => {
    global.fetch = jest.fn(() => new Promise(() => {})) as unknown as typeof fetch;
    render(<ProjectRelatedArtifactsSection projectId={PROJECT_ID} />);
    expect(await screen.findByTestId('related-artifacts-loading')).toHaveTextContent('Loading related artifacts…');
  });

  it('says a rejected read failed, with a retry that brings the panel back', async () => {
    let fail = true;
    global.fetch = jest.fn(() =>
      fail ? Promise.reject(new Error('Network unreachable')) : json(PROJECT)
    ) as unknown as typeof fetch;
    render(<ProjectRelatedArtifactsSection projectId={PROJECT_ID} />);
    const error = await screen.findByTestId('related-artifacts-error');
    expect(error).toHaveTextContent("Couldn't load related artifacts");
    expect(error).toHaveTextContent('Network unreachable');
    fail = false;
    fireEvent.click(within(error).getByRole('button', { name: /try again/i }));
    expect(await screen.findByText('Related artifacts')).toBeInTheDocument();
    expect(screen.queryByTestId('related-artifacts-error')).toBeNull();
  });

  it('treats a non-ok answer as a failure too, not as "no linked artifacts"', async () => {
    global.fetch = jest.fn(() => json({ success: false, error: 'Project not visible' }, 403)) as unknown as typeof fetch;
    render(<ProjectRelatedArtifactsSection projectId={PROJECT_ID} />);
    expect(await screen.findByTestId('related-artifacts-error')).toHaveTextContent('Project not visible');
  });
});

describe('CatalogRelatedArtifactsPanel — Suggest links', () => {
  it('says the button is busy while the suggestions read', async () => {
    global.fetch = jest.fn(() => new Promise(() => {})) as unknown as typeof fetch;
    render(<CatalogRelatedArtifactsPanel projectId={PROJECT_ID} identityGroupId="grp-1" relatedArtifacts={[]} />);
    fireEvent.click(screen.getByTestId('catalog-load-suggestions'));
    expect(await screen.findByText('Loading suggestions…')).toBeInTheDocument();
    expect(screen.getByTestId('catalog-load-suggestions')).toBeDisabled();
  });

  it('says a failed read failed in the panel, with a retry — not only a toast', async () => {
    let fail = true;
    global.fetch = jest.fn(() =>
      fail
        ? json({ success: false, error: 'Identity service unavailable' }, 503)
        : json({ success: true, suggestions: [{ projectId: 'p-2', name: 'Orders API (AsyncAPI)', reason: 'Same title' }] })
    ) as unknown as typeof fetch;
    render(<CatalogRelatedArtifactsPanel projectId={PROJECT_ID} identityGroupId="grp-1" relatedArtifacts={[]} />);
    fireEvent.click(screen.getByTestId('catalog-load-suggestions'));
    const error = await screen.findByTestId('catalog-suggestions-error');
    expect(error).toHaveTextContent("Couldn't load link suggestions");
    expect(error).toHaveTextContent('Identity service unavailable');
    fail = false;
    fireEvent.click(within(error).getByRole('button', { name: /try again/i }));
    expect(await screen.findByTestId('catalog-identity-suggestions')).toHaveTextContent('Orders API (AsyncAPI)');
    await waitFor(() => expect(screen.queryByTestId('catalog-suggestions-error')).toBeNull());
  });
});
