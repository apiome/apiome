/**
 * Namespaces & Scopes view + editor dialog (#3471).
 *
 * Verifies the namespaces table renders scope/visibility/default state, that system-core rows are
 * read-only while tenant rows are editable, and that the create flow POSTs the derived request body
 * to the namespace proxy.
 */

import React from 'react';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';

// Radix Dialog needs a few browser APIs jsdom doesn't implement.
beforeAll(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
  if (!Element.prototype.hasPointerCapture) {
    Element.prototype.hasPointerCapture = () => false;
  }
  if (!Element.prototype.setPointerCapture) {
    Element.prototype.setPointerCapture = () => {};
  }
  if (!Element.prototype.releasePointerCapture) {
    Element.prototype.releasePointerCapture = () => {};
  }
  Element.prototype.scrollIntoView = () => {};
});

import PrimitivesNamespacesView from '../src/app/ade/dashboard/primitives/PrimitivesNamespacesView';
import type { TypeNamespaceCollection } from '../src/app/ade/dashboard/primitives/primitivesRegistryTypes';

const NAMESPACES: TypeNamespaceCollection[] = [
  {
    id: 'ns-sys',
    tenant_id: null,
    namespace: 'std/v0/types',
    base_uri: 'https://api.apiome.app/types/std/v0/',
    version_root: 'v0',
    description: null,
    scope: 'system',
    is_system: true,
    is_public: true,
    is_default: true,
    type_count: 56,
  },
  {
    id: 'ns-acme',
    tenant_id: 'tenant-1',
    namespace: 'tenant/acme/v1/types',
    base_uri: 'https://api.apiome.app/types/tenant/acme/v1/',
    version_root: 'v1',
    description: 'Acme types',
    scope: 'tenant',
    is_system: false,
    is_public: false,
    is_default: false,
    type_count: 48,
  },
];

describe('PrimitivesNamespacesView', () => {
  const onRefresh = jest.fn();
  const onMessage = jest.fn();

  afterEach(() => {
    jest.restoreAllMocks();
    onRefresh.mockReset();
    onMessage.mockReset();
  });

  function renderView(namespaces = NAMESPACES) {
    return render(
      <PrimitivesNamespacesView
        namespaces={namespaces}
        unresolvedByNamespace={{}}
        loading={false}
        onRefresh={onRefresh}
        onMessage={onMessage}
      />
    );
  }

  it('renders the scope explainer cards and precedence order', () => {
    renderView();
    expect(screen.getByText(/System root/i)).toBeInTheDocument();
    expect(screen.getByText('Tenant namespaces')).toBeInTheDocument();
    expect(screen.getByText(/Scope precedence/i)).toBeInTheDocument();
    expect(screen.getByText(/Promote to core/i)).toBeInTheDocument();
  });

  it('lists each namespace with scope, version root, and type count', () => {
    renderView();
    expect(screen.getByText('std/v0/types')).toBeInTheDocument();
    expect(screen.getByText('tenant/acme/v1/types')).toBeInTheDocument();
    expect(screen.getAllByText(/System · core/i).length).toBeGreaterThan(0);
    expect(screen.getByText('48')).toBeInTheDocument();
  });

  it('marks system namespaces read-only and tenant namespaces editable', () => {
    renderView();
    const systemRow = screen.getByText('std/v0/types').closest('tr')!;
    expect(within(systemRow).getByText(/Read-only/i)).toBeInTheDocument();
    expect(within(systemRow).queryByText('Edit')).not.toBeInTheDocument();

    const tenantRow = screen.getByText('tenant/acme/v1/types').closest('tr')!;
    expect(within(tenantRow).getByText('Edit')).toBeInTheDocument();
  });

  it('shows an empty state when there are no namespaces', () => {
    renderView([]);
    expect(screen.getByText('No Namespaces Yet')).toBeInTheDocument();
  });

  it('creates a namespace via POST when the dialog form is submitted', async () => {
    const fetchMock = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ success: true, namespace: { id: 'ns-new' } }),
    });
    global.fetch = fetchMock as unknown as typeof fetch;

    renderView();
    fireEvent.click(screen.getByRole('button', { name: /New namespace/i }));

    const pathInput = await screen.findByLabelText('Namespace path');
    fireEvent.change(pathInput, { target: { value: 'tenant/acme/v2/payments' } });

    fireEvent.click(screen.getByRole('button', { name: /Create namespace/i }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/types/namespaces');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body)).toEqual({
      namespace: 'tenant/acme/v2/payments',
      scope: 'tenant',
      is_default: false,
    });
    await waitFor(() => expect(onMessage).toHaveBeenCalledWith('success', 'Namespace created'));
    expect(onRefresh).toHaveBeenCalled();
  });

  it('blocks submission and surfaces a validation error for a bad path', async () => {
    const fetchMock = jest.fn();
    global.fetch = fetchMock as unknown as typeof fetch;

    renderView();
    fireEvent.click(screen.getByRole('button', { name: /New namespace/i }));

    const pathInput = await screen.findByLabelText('Namespace path');
    fireEvent.change(pathInput, { target: { value: 'std/v9/types' } });

    const createBtn = screen.getByRole('button', { name: /Create namespace/i });
    expect(createBtn).toBeDisabled();
    fireEvent.click(createBtn);
    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.getByText(/reserved for platform system-core/i)).toBeInTheDocument();
  });

  it('edits a tenant namespace via PUT without sending the immutable path', async () => {
    const fetchMock = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ success: true, namespace: { id: 'ns-acme' } }),
    });
    global.fetch = fetchMock as unknown as typeof fetch;

    renderView();
    const tenantRow = screen.getByText('tenant/acme/v1/types').closest('tr')!;
    fireEvent.click(within(tenantRow).getByText('Edit'));

    // The path field is disabled (immutable) in edit mode.
    expect(await screen.findByLabelText('Namespace path')).toBeDisabled();

    fireEvent.click(screen.getByRole('button', { name: /Save changes/i }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/types/namespaces/ns-acme');
    expect(init.method).toBe('PUT');
    const body = JSON.parse(init.body);
    expect(body).not.toHaveProperty('namespace');
    expect(body.base_uri).toBe('https://api.apiome.app/types/tenant/acme/v1/');
    await waitFor(() => expect(onMessage).toHaveBeenCalledWith('success', 'Namespace updated'));
  });
});
