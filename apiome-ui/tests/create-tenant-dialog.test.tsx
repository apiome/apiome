/**
 * Tests for the header "Create tenant" dialog (OLO-6.1, #4218): reuses the
 * onboarding organization form, provisions through `provisionAdditionalTenant`,
 * reports the created tenant, and renders cap/slug errors inline.
 */
import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';

const mockProvisionAdditionalTenant = jest.fn<
  Promise<
    | { success: true; tenant: { id: string; name: string; slug: string } }
    | { success: false; error: string }
  >,
  [string, string]
>();

jest.mock('@lib/auth/first-tenant-actions', () => ({
  provisionAdditionalTenant: (name: string, slug: string) =>
    mockProvisionAdditionalTenant(name, slug),
}));

// The live availability probe is exercised by the onboarding wizard tests;
// here it always reports available so submits reach provisioning.
jest.mock('@lib/auth/tenant-slug-availability', () => ({
  checkTenantSlugAvailability: jest.fn(async () => ({ status: 'available' })),
}));

import { CreateTenantDialog } from '../src/app/components/ade/CreateTenantDialog';

beforeEach(() => {
  jest.clearAllMocks();
});

/** Fills the organization name and submits the form. */
async function submitOrganization(user: ReturnType<typeof userEvent.setup>, name: string) {
  await user.type(screen.getByPlaceholderText('Acme, Inc.'), name);
  await user.click(screen.getByRole('button', { name: /Continue/ }));
}

describe('CreateTenantDialog (OLO-6.1)', () => {
  it('renders the organization form when open', () => {
    render(<CreateTenantDialog open onOpenChange={jest.fn()} onCreated={jest.fn()} />);
    expect(screen.getByTestId('create-tenant-dialog')).toBeInTheDocument();
    expect(screen.getByTestId('onboarding-step-organization')).toBeInTheDocument();
  });

  it('provisions with the entered name and derived slug, then reports the tenant', async () => {
    const user = userEvent.setup();
    const onCreated = jest.fn();
    mockProvisionAdditionalTenant.mockResolvedValue({
      success: true,
      tenant: { id: 'tenant-new', name: 'Globex Two', slug: 'globex-two' },
    });

    render(<CreateTenantDialog open onOpenChange={jest.fn()} onCreated={onCreated} />);
    await submitOrganization(user, 'Globex Two');

    await waitFor(() =>
      expect(mockProvisionAdditionalTenant).toHaveBeenCalledWith('Globex Two', 'globex-two')
    );
    await waitFor(() =>
      expect(onCreated).toHaveBeenCalledWith({
        id: 'tenant-new',
        name: 'Globex Two',
        slug: 'globex-two',
      })
    );
  });

  it('shows the provisioning error inline and returns to the form', async () => {
    const user = userEvent.setup();
    mockProvisionAdditionalTenant.mockResolvedValue({
      success: false,
      error: "You've reached your plan's tenant limit. Upgrade your plan to create more tenants.",
    });

    render(<CreateTenantDialog open onOpenChange={jest.fn()} onCreated={jest.fn()} />);
    await submitOrganization(user, 'Over Cap Org');

    const alert = await screen.findByTestId('create-tenant-error');
    expect(alert).toHaveTextContent("tenant limit");
    // The form is available again for a retry or a different slug.
    expect(screen.getByTestId('onboarding-step-organization')).toBeInTheDocument();
  });

  it('closes via the form Back button', async () => {
    const user = userEvent.setup();
    const onOpenChange = jest.fn();
    render(<CreateTenantDialog open onOpenChange={onOpenChange} onCreated={jest.fn()} />);
    await user.click(screen.getByRole('button', { name: /Back/ }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});
