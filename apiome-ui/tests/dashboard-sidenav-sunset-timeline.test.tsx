/**
 * Side-nav active state for Sunset timeline vs Projects.
 */
import React from 'react';
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';

const mockUsePathname = jest.fn<string, []>();
const mockUseSession = jest.fn<{ data: unknown }, []>();

jest.mock('next/navigation', () => ({
  usePathname: () => mockUsePathname(),
}));

jest.mock('next-auth/react', () => ({
  useSession: () => mockUseSession(),
}));

jest.mock('@/app/hooks/useDarkMode', () => ({
  useDarkMode: () => false,
}));

jest.mock('next/link', () => ({
  __esModule: true,
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

import DashboardSideNav from '../src/app/components/ade/dashboard/DashboardSideNav';

const SUNSET_HREF = '/ade/dashboard/versions/sunset-timeline';
const PROJECTS_HREF = '/ade/dashboard/projects';

const withTenant = () => mockUseSession.mockReturnValue({ data: { user: { current_tenant_id: 't-1' } } });

const activeClass = 'border-indigo-200';

beforeEach(() => {
  mockUsePathname.mockReset();
  mockUseSession.mockReset();
  withTenant();
});

describe('DashboardSideNav — Sunset timeline active state', () => {
  it('highlights only Sunset timeline on the sunset-timeline route', () => {
    mockUsePathname.mockReturnValue(SUNSET_HREF);
    render(<DashboardSideNav />);

    const sunsetLink = screen.getByText('Sunset timeline').closest('a');
    const projectsLink = screen.getByText('Projects').closest('a');

    expect(sunsetLink?.className).toContain(activeClass);
    expect(projectsLink?.className).not.toContain(activeClass);
  });

  it('highlights Projects on the versions route', () => {
    mockUsePathname.mockReturnValue('/ade/dashboard/versions');
    render(<DashboardSideNav />);

    const sunsetLink = screen.getByText('Sunset timeline').closest('a');
    const projectsLink = screen.getByText('Projects').closest('a');

    expect(projectsLink?.className).toContain(activeClass);
    expect(sunsetLink?.className).not.toContain(activeClass);
  });

  it('links Sunset timeline to the correct href', () => {
    mockUsePathname.mockReturnValue('/ade/dashboard');
    render(<DashboardSideNav />);

    const link = screen.getByText('Sunset timeline').closest('a');
    expect(link).toHaveAttribute('href', SUNSET_HREF);
  });

  it('links Projects to the correct href', () => {
    mockUsePathname.mockReturnValue('/ade/dashboard');
    render(<DashboardSideNav />);

    const link = screen.getByText('Projects').closest('a');
    expect(link).toHaveAttribute('href', PROJECTS_HREF);
  });
});
