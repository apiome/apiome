/**
 * Render tests for the dashboard first-run checklist component (#3614).
 */

import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';

// next/link → plain anchor so the component renders without app-router context.
jest.mock('next/link', () => ({
  __esModule: true,
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={typeof href === 'string' ? href : '#'} {...rest}>
      {children}
    </a>
  ),
}));

import { FirstRunChecklist } from '@/app/components/ade/dashboard/FirstRunChecklist';
import { FIRST_RUN_DISMISS_KEY } from '@/app/components/ade/dashboard/firstRunChecklist';

const EMPTY = { total_projects: 0, total_classes: 0, total_versions: 0, published_versions: 0 };
const SEEDED = { total_projects: 1, total_classes: 3, total_versions: 1, published_versions: 1 };

/** OSS build omits commercial Designer checklist steps. */
const OSS_STEP_COUNT = 3;

beforeEach(() => {
  window.localStorage.clear();
});

describe('FirstRunChecklist', () => {
  it('renders core guided steps in OSS build', () => {
    render(<FirstRunChecklist stats={EMPTY} />);
    expect(screen.queryByText(/Create your first project/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Add a class from a starter template/)).not.toBeInTheDocument();
    expect(screen.getByText(/Cut a version/)).toBeInTheDocument();
    expect(screen.getByText(/Publish it/)).toBeInTheDocument();
    expect(screen.getByText(/View it in Browse/)).toBeInTheDocument();
  });

  it('shows 0/N progress for an empty tenant', () => {
    render(<FirstRunChecklist stats={EMPTY} />);
    expect(screen.getByText(`0/${OSS_STEP_COUNT} done`)).toBeInTheDocument();
    expect(screen.getByText('Get started')).toBeInTheDocument();
  });

  it('shows N/N and the completed header for a seeded tenant', () => {
    render(<FirstRunChecklist stats={SEEDED} />);
    expect(screen.getByText(`${OSS_STEP_COUNT}/${OSS_STEP_COUNT} done`)).toBeInTheDocument();
    expect(screen.getByText("You're all set")).toBeInTheDocument();
  });

  it('links the Browse step to an external new tab', () => {
    render(<FirstRunChecklist stats={SEEDED} />);
    const browseLink = screen.getByText(/View it in Browse/).closest('a');
    expect(browseLink).toHaveAttribute('target', '_blank');
    expect(browseLink).toHaveAttribute('rel', expect.stringContaining('noopener'));
  });

  it('dismisses and persists the dismissal', async () => {
    render(<FirstRunChecklist stats={EMPTY} />);
    fireEvent.click(screen.getByLabelText('Dismiss getting-started checklist'));
    await waitFor(() => {
      expect(screen.queryByText('Get started')).not.toBeInTheDocument();
    });
    expect(window.localStorage.getItem(FIRST_RUN_DISMISS_KEY)).toBe('1');
  });

  it('stays hidden when already dismissed', async () => {
    window.localStorage.setItem(FIRST_RUN_DISMISS_KEY, '1');
    render(<FirstRunChecklist stats={EMPTY} />);
    await waitFor(() => {
      expect(screen.queryByText('Get started')).not.toBeInTheDocument();
    });
  });
});
