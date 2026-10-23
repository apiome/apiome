/**
 * Ownership on Projects — CDG-2.4 (#5963).
 *
 * The Projects screen with each project's `owner` on the wire. Pinned: `?team=` reaches the BFF (the
 * server filters), the table and the cards show the owner, confirming from a card updates it in
 * place, and bulk **Assign owner** sends every selected project in one call.
 */

import React from 'react';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';

let searchParams = new URLSearchParams();

jest.mock('@lib/auth/session-client', () => ({
  useAuthSession: () => ({
    data: { user: { user_id: 'u-ada', current_tenant_id: 't-acme', email: 'ada@acme.io' } },
    status: 'authenticated',
    update: jest.fn(),
  }),
  AuthSessionProvider: ({ children }: { children: React.ReactNode }) => children,
}));

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn(), replace: jest.fn() }),
  useSearchParams: () => searchParams,
  usePathname: () => '/ade/dashboard/projects',
}));

jest.mock('@/app/components/providers/DialogProvider', () => ({
  useDialog: () => ({ confirm: jest.fn(async () => true), alert: jest.fn(async () => undefined) }),
}));

jest.mock('@lib/db/helper', () => ({
  createProject: jest.fn(),
  updateProject: jest.fn(),
  deleteProject: jest.fn(),
  restoreProject: jest.fn(),
  permanentDeleteProject: jest.fn(),
}));

jest.mock('@/app/components/ade/dashboard/ImportDialog', () => ({ __esModule: true, default: () => null }));
jest.mock('@/app/components/ade/dashboard/LLMImportDialog', () => ({ __esModule: true, LLMChatPanel: () => null }));

import ProjectsClient from '../src/app/ade/dashboard/projects/ProjectsClient';

const TEAM = { id: 't-1', slug: 'payments', name: 'Payments' };
const base = {
  tenant_id: 't-acme',
  creator_id: 'u-ada',
  enabled: true,
  deleted_at: null,
  created_at: '2026-06-01T10:00:00.000Z',
  updated_at: '2026-10-15T09:12:00.000Z',
  creator_name: 'Ada Lovelace',
  creator_email: 'ada@example.com',
  versionsCount: 2,
  publishable: true,
};
const PAYMENTS = {
  ...base,
  id: '8f2a1c00-0000-4000-8000-000000000001',
  name: 'Payments API',
  slug: 'payments-api',
  owner: { team: TEAM, status: 'suggested', source: 'codeowners' },
};
const ORDERS = { ...base, id: '8f2a1c00-0000-4000-8000-000000000002', name: 'Orders Service', slug: 'orders', owner: null };

let calls: Array<{ url: string; body: unknown }> = [];

// Ownership is held back in RC6 (lib/feature-release.ts); these suites test it, so re-open it.
const PREVIEW_FEATURES = process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES;
beforeAll(() => {
  process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES = 'teams';
});
afterAll(() => {
  if (PREVIEW_FEATURES === undefined) delete process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES;
  else process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES = PREVIEW_FEATURES;
});

beforeEach(() => {
  searchParams = new URLSearchParams();
  calls = [];
  global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push({ url, body: init?.body ? JSON.parse(String(init.body)) : null });
    const reply = (body: unknown) => ({ ok: true, status: 200, statusText: 'OK', json: async () => body }) as Response;
    if (url === '/api/teams') return reply({ teams: [{ ...TEAM, member_count: 2 }], count: 1 });
    if (url.endsWith('/confirm')) return reply({ owner: { team: TEAM, status: 'confirmed', source: 'codeowners' } });
    if (url === '/api/owners/assign') return reply({ results: [], count: 2 });
    if (url.startsWith('/api/projects')) return reply({ success: true, projects: [PAYMENTS, ORDERS] });
    return reply({ success: true, reviews: [], data: [] });
  }) as unknown as typeof fetch;
});

test('?team= is forwarded to the BFF', async () => {
  searchParams = new URLSearchParams('team=payments');
  render(<ProjectsClient />);
  await screen.findAllByText('Payments API');
  expect(calls.filter((call) => call.url.startsWith('/api/projects')).at(-1)?.url).toBe('/api/projects?team=payments');
});

test('a card shows its suggested owner and confirms it in place', async () => {
  const user = userEvent.setup();
  render(<ProjectsClient />);
  const owner = await screen.findByTestId(`project-card-owner-${PAYMENTS.id}`);
  expect(owner).toHaveTextContent('Suggested · CODEOWNERS');
  await user.click(screen.getByTestId(`project-card-owner-${PAYMENTS.id}-confirm`));
  await waitFor(() =>
    expect(screen.getByTestId(`project-card-owner-${PAYMENTS.id}`)).toHaveAttribute('data-status', 'confirmed')
  );
  // A project with no owner draws no owner line on its card.
  expect(screen.queryByTestId(`project-card-owner-${ORDERS.id}`)).not.toBeInTheDocument();
});

test('the table has an Owner column and the bulk bar assigns one team to the selection', async () => {
  const user = userEvent.setup();
  render(<ProjectsClient />);
  await screen.findAllByText('Payments API');
  await user.click(screen.getByTestId('projects-view-table'));
  const table = await screen.findByRole('table');
  expect(within(table).getByRole('columnheader', { name: 'Owner' })).toBeInTheDocument();
  expect(within(table).getByTestId(`projects-owner-${ORDERS.id}`)).toHaveTextContent('No owner');

  await user.click(within(table).getByRole('checkbox', { name: /Select Payments API/ }));
  await user.click(within(table).getByRole('checkbox', { name: /Select Orders Service/ }));
  await user.selectOptions(screen.getByTestId('bulk-owner-team'), 'payments');
  await user.click(screen.getByTestId('bulk-assign-owner'));
  await waitFor(() => expect(calls.some((call) => call.url === '/api/owners/assign')).toBe(true));
  expect(calls.find((call) => call.url === '/api/owners/assign')?.body).toEqual({
    team: 'payments',
    entities: [
      { kind: 'project', id: PAYMENTS.id },
      { kind: 'project', id: ORDERS.id },
    ],
  });
});
