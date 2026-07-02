/**
 * Type detail page (#3468).
 *
 * Verifies the read-only registry-type detail renders schema, resolved refs,
 * dependents (graceful empty-state), metadata, base chain, and the export action.
 */

import React from 'react';
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react';
import '@testing-library/jest-dom';

const mockPush = jest.fn();
jest.mock('next/navigation', () => ({
  useParams: () => ({ id: 'prim-1' }),
  useRouter: () => ({ push: mockPush }),
}));

import PrimitiveDetailClient from '../src/app/ade/dashboard/primitives/[id]/PrimitiveDetailClient';

const SYSTEM_MONEY = {
  id: 'prim-1',
  name: 'money',
  description: 'A monetary amount with a currency.',
  category: 'object',
  is_system: true,
  namespace: 'std/v0/types',
  schema_id: 'https://api.apiome.app/types/std/v0/types/money',
  base_uri: 'https://api.apiome.app/types/std/v0/types/',
  draft: '2020-12',
  source: 'system',
  usage_count: 11,
  created_at: '2025-11-02T00:00:00.000Z',
  refs: [
    { relative_ref: './decimal', resolved_target: 'std/v0/types/decimal', status: 'resolved' },
    { relative_ref: './currency-code', resolved_target: 'std/v0/types/currency-code', status: 'unresolved' },
  ],
  schema: {
    $id: 'https://api.apiome.app/types/std/v0/types/money',
    type: 'object',
    properties: {
      amount: { $ref: './decimal' },
      currency: { type: 'string', examples: ['USD'] },
    },
    required: ['amount', 'currency'],
  },
};

function mockFetchOk(primitive: unknown) {
  global.fetch = jest.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ success: true, primitive }),
  }) as unknown as typeof fetch;
}

describe('PrimitiveDetailClient', () => {
  afterEach(() => {
    jest.restoreAllMocks();
    mockPush.mockReset();
  });

  it('renders schema, refs, metadata, base chain, and a graceful dependents empty-state', async () => {
    mockFetchOk(SYSTEM_MONEY);
    render(<PrimitiveDetailClient />);

    await waitFor(() => expect(screen.getByRole('heading', { name: 'money' })).toBeInTheDocument());

    // Reference resolution shows both edges with their status (the relative refs
    // also appear in the base-chain rail, hence getAllByText).
    expect(screen.getAllByText('./decimal').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('std/v0/types/currency-code')).toBeInTheDocument();
    expect(screen.getByText('resolved')).toBeInTheDocument();
    expect(screen.getByText('unresolved')).toBeInTheDocument();

    // Metadata right-rail derives version root + owner; namespace appears in the
    // breadcrumb and the metadata panel.
    expect(screen.getAllByText('std/v0/types').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('v0')).toBeInTheDocument();
    expect(screen.getAllByText('system').length).toBeGreaterThanOrEqual(1);

    // Dependents empty-state (reverse index #3477 not yet populated).
    expect(screen.getByText(/No types reference this primitive yet/i)).toBeInTheDocument();

    // System type → immutable badge + disabled Edit.
    expect(screen.getByText(/immutable \(core\)/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Edit/i })).toBeDisabled();
  });

  it('exports the schema as a downloadable JSON file', async () => {
    mockFetchOk(SYSTEM_MONEY);
    const createObjectURL = jest.fn().mockReturnValue('blob:mock');
    const revokeObjectURL = jest.fn();
    (URL as unknown as { createObjectURL: unknown }).createObjectURL = createObjectURL;
    (URL as unknown as { revokeObjectURL: unknown }).revokeObjectURL = revokeObjectURL;
    const clickSpy = jest.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});

    render(<PrimitiveDetailClient />);
    await waitFor(() => expect(screen.getByRole('heading', { name: 'money' })).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: /Export/i }));
    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(clickSpy).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:mock');
  });

  it('lists dependents when the reverse index returns them', async () => {
    mockFetchOk({
      ...SYSTEM_MONEY,
      dependents: [
        { schema_id: 'a', namespace: 'tenant/acme/v1/payments', name: 'charge', property: 'amount', scope: 'tenant', tenant_label: 'acme' },
      ],
    });
    render(<PrimitiveDetailClient />);

    await waitFor(() => expect(screen.getByRole('heading', { name: 'money' })).toBeInTheDocument());
    const dependentsTable = screen.getByText('tenant/acme/v1/payments/charge').closest('table');
    expect(dependentsTable).not.toBeNull();
    expect(within(dependentsTable as HTMLElement).getByText('amount')).toBeInTheDocument();
    expect(within(dependentsTable as HTMLElement).getByText(/Tenant · acme/i)).toBeInTheDocument();
  });

  it('shows an error alert when the primitive fails to load', async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: false,
      json: async () => ({ success: false, error: 'Primitive not found' }),
    }) as unknown as typeof fetch;
    render(<PrimitiveDetailClient />);

    await waitFor(() => expect(screen.getByText('Primitive not found')).toBeInTheDocument());
  });
});
