/**
 * First-tenant onboarding wizard tests (OLO-4.1, #4205).
 *
 * The wizard is mounted by the onboarding guard for zero-tenant users:
 * welcome → organization (name/slug) → summary (Free license shown before
 * confirm) → security (skippable two-factor enrolment, TFA-1.4) → done. Covers step navigation with value retention, form
 * validation, the non-dismissible contract, provisioning success/failure, and
 * completion landing in the new tenant's dashboard (session update + /ade).
 */
import React from 'react';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';

const mockSignOut = jest.fn();
const mockSignOutEverywhere = jest.fn();
const mockUpdate = jest.fn<Promise<unknown>, [unknown]>(async () => null);
const mockPush = jest.fn();
const mockRefresh = jest.fn();
const mockProvisionFirstTenant = jest.fn<Promise<unknown>, [string, string]>();

// The wizard reads the session through the OLO-10.12 engine-aware compat hook; mock it so the test
// controls `update` without pulling the Better Auth browser client.
jest.mock('@lib/auth/session-client', () => ({
  useAuthSession: () => ({ data: null, status: 'authenticated', update: mockUpdate }),
  AuthSessionProvider: ({ children }: { children: unknown }) => children,
  signIn: (...args: unknown[]) => mockSignOut(...args),
  signOut: (...args: unknown[]) => mockSignOut(...args),
}));

jest.mock('@lib/auth/sign-out-client', () => ({
  signOutEverywhere: (...args: unknown[]) => mockSignOutEverywhere(...args),
}));

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush, refresh: mockRefresh }),
}));

jest.mock('@lib/auth/first-tenant-actions', () => ({
  provisionFirstTenant: (name: string, slug: string) => mockProvisionFirstTenant(name, slug),
}));

// The organization step's live availability probe (OLO-4.2) is covered in
// depth by onboarding-organization-step.test.tsx; here it always reports the
// slug free so wizard flows continue past the submit-time check.
const mockCheckSlugAvailability = jest.fn<Promise<{ status: string }>, [string]>();
jest.mock('@lib/auth/tenant-slug-availability', () => ({
  checkTenantSlugAvailability: (slug: string) => mockCheckSlugAvailability(slug),
}));

// Resumability + funnel telemetry (OLO-4.5, #4209): the wizard hydrates its
// step from `loadOnboardingWizardState` on mount and persists each step change
// via `saveOnboardingWizardStep` / `completeOnboardingWizard`.
const mockLoadState = jest.fn<Promise<unknown>, []>();
const mockSaveStep = jest.fn<Promise<void>, unknown[]>();
const mockCompleteWizard = jest.fn<Promise<void>, []>();
jest.mock('@lib/auth/onboarding-wizard-state-actions', () => ({
  loadOnboardingWizardState: () => mockLoadState(),
  saveOnboardingWizardStep: (...args: unknown[]) => mockSaveStep(...args),
  completeOnboardingWizard: () => mockCompleteWizard(),
}));

// The security step (TFA-1.4 #5658) draws the shared enrolment dialog: keep the Better Auth
// client and the server actions out of the test.
const mockGetReauthStatus = jest.fn();
jest.mock('@lib/auth/two-factor-profile-actions', () => ({
  getTwoFactorReauthStatus: () => mockGetReauthStatus(),
  dismissTwoFactorResetNotice: jest.fn(async () => undefined),
}));
const mockTwoFactorEnable = jest.fn();
const mockVerifyTotp = jest.fn();
jest.mock('@lib/auth/auth-client', () => ({
  authClient: {
    twoFactor: {
      enable: (...args: unknown[]) => mockTwoFactorEnable(...args),
      verifyTotp: (...args: unknown[]) => mockVerifyTotp(...args),
    },
  },
}));
jest.mock('react-qr-code', () => ({
  __esModule: true,
  default: ({ value }: { value: string }) => <div data-testid="qr-code" data-value={value} />,
}));

import FirstTenantOnboardingWizard from '@/app/components/auth/onboarding/FirstTenantOnboardingWizard';
import { FREE_LICENSE_SUMMARY } from '@lib/auth/free-license';
import {
  isFirstTenantWizardStep,
  isResumableWizardStep,
  nextWizardStep,
  previousWizardStep,
} from '@/app/components/auth/onboarding/wizard-steps';

beforeEach(() => {
  jest.clearAllMocks();
  mockProvisionFirstTenant.mockResolvedValue({
    success: true,
    tenant: { id: 't-1', name: 'Acme Corp', slug: 'acme-corp' },
  });
  mockCheckSlugAvailability.mockResolvedValue({ status: 'available' });
  mockLoadState.mockResolvedValue(null);
  mockSaveStep.mockResolvedValue(undefined);
  mockCompleteWizard.mockResolvedValue(undefined);
  mockGetReauthStatus.mockResolvedValue({ hasPassword: true, fresh: true, providers: [] });
  // `clearAllMocks` keeps implementations; one completion test makes `update` reject.
  mockUpdate.mockResolvedValue(null);
});

/**
 * From the review step: create the organization, then skip the security step. Resolves with
 * the done step's body.
 */
const createAndSkipSecurity = async () => {
  fireEvent.click(await screen.findByRole('button', { name: /create organization/i }));
  fireEvent.click(await screen.findByRole('button', { name: /skip for now/i }));
  return screen.findByTestId('onboarding-step-done');
};

/**
 * Clicks through welcome → organization with the given form values. Submit is
 * async (availability check); happy-path callers must await the summary step
 * (`await screen.findByTestId('onboarding-step-summary')`) before continuing.
 */
const fillOrganizationStep = (name: string, slug = '') => {
  fireEvent.click(screen.getByRole('button', { name: /set up your organization/i }));
  fireEvent.change(screen.getByPlaceholderText('Acme, Inc.'), { target: { value: name } });
  fireEvent.change(screen.getByPlaceholderText('acme-inc'), { target: { value: slug } });
  fireEvent.click(screen.getByRole('button', { name: /continue/i }));
};

describe('wizard step order helpers', () => {
  it('walks forward welcome → organization → summary → security → done and clamps at the end', () => {
    expect(nextWizardStep('welcome')).toBe('organization');
    expect(nextWizardStep('organization')).toBe('summary');
    expect(nextWizardStep('summary')).toBe('security');
    expect(nextWizardStep('security')).toBe('done');
    expect(nextWizardStep('done')).toBe('done');
  });

  it('walks backward and clamps at the start', () => {
    expect(previousWizardStep('done')).toBe('security');
    expect(previousWizardStep('security')).toBe('summary');
    expect(previousWizardStep('summary')).toBe('organization');
    expect(previousWizardStep('organization')).toBe('welcome');
    expect(previousWizardStep('welcome')).toBe('welcome');
  });

  it('recognizes valid wizard steps and rejects anything else', () => {
    expect(isFirstTenantWizardStep('welcome')).toBe(true);
    expect(isFirstTenantWizardStep('done')).toBe(true);
    expect(isFirstTenantWizardStep('nope')).toBe(false);
    expect(isFirstTenantWizardStep(undefined)).toBe(false);
    expect(isFirstTenantWizardStep(3)).toBe(false);
  });

  it('never treats a post-provisioning step as resumable', () => {
    expect(isResumableWizardStep('summary')).toBe(true);
    expect(isResumableWizardStep('security')).toBe(false);
    expect(isResumableWizardStep('done')).toBe(false);
    expect(isResumableWizardStep('nope')).toBe(false);
  });
});

describe('FirstTenantOnboardingWizard: welcome step', () => {
  it('opens on the welcome step with setup progress shown', () => {
    render(<FirstTenantOnboardingWizard />);

    expect(screen.getByTestId('onboarding-step-welcome')).toBeInTheDocument();
    expect(screen.getByRole('list', { name: /setup progress/i })).toBeInTheDocument();
  });

  it('offers no dismiss or skip control — the wizard is not skippable', () => {
    render(<FirstTenantOnboardingWizard />);

    const labels = screen
      .getAllByRole('button')
      .map((button) => button.textContent?.toLowerCase() ?? '');
    // The wizard's own three, plus the top row's sign-out (HIVE-4.4): setup, check
    // again, and two ways out of the account. None of them leaves the wizard behind.
    expect(labels).toHaveLength(4);
    for (const label of labels) {
      expect(label).not.toMatch(/skip|close|dismiss|cancel/);
    }
  });

  it('re-checks memberships via a server refresh', () => {
    render(<FirstTenantOnboardingWizard />);

    fireEvent.click(screen.getByRole('button', { name: /check again/i }));

    expect(mockRefresh).toHaveBeenCalledTimes(1);
  });

  it('signs the user out back to the login page', () => {
    render(<FirstTenantOnboardingWizard />);

    // Two controls do this since HIVE-4.4 — the step's own and the top row's — and
    // both go through the same handler, so both are exercised.
    for (const testId of ['onboarding-sign-out', 'onboarding-topbar-sign-out']) {
      mockSignOutEverywhere.mockClear();
      fireEvent.click(screen.getByTestId(testId));

      // Logout goes through signOutEverywhere, which clears the session +
      // last-active-tenant cookies server-side before NextAuth's client signOut.
      expect(mockSignOutEverywhere).toHaveBeenCalledWith('/login');
    }
  });
});

describe('FirstTenantOnboardingWizard: organization step', () => {
  it('requires an organization name', () => {
    render(<FirstTenantOnboardingWizard />);

    fireEvent.click(screen.getByRole('button', { name: /set up your organization/i }));
    fireEvent.click(screen.getByRole('button', { name: /continue/i }));

    expect(screen.getByText(/organization name is required/i)).toBeInTheDocument();
    expect(screen.getByTestId('onboarding-step-organization')).toBeInTheDocument();
  });

  it('rejects a malformed slug', () => {
    render(<FirstTenantOnboardingWizard />);

    fillOrganizationStep('Acme Corp', 'not a slug!');

    // Matched on the message's own opening rather than the shared tail: the field's
    // standing hint names the same three characters, and since HIVE-4.4 the hint and
    // the error are both on screen (the rule and this attempt say different things).
    expect(
      screen.getByText(/must contain only lowercase letters, numbers, and dashes/i)
    ).toBeInTheDocument();
    expect(screen.getByTestId('onboarding-step-organization')).toBeInTheDocument();
  });

  it('flags the name when no slug can be derived from it', () => {
    render(<FirstTenantOnboardingWizard />);

    fillOrganizationStep('!!!');

    expect(screen.getByText(/could not derive a url slug/i)).toBeInTheDocument();
  });

  it('keeps entered values when navigating back to the welcome step', async () => {
    render(<FirstTenantOnboardingWizard />);

    fillOrganizationStep('Acme Corp', 'acme-corp');
    await screen.findByTestId('onboarding-step-summary');
    fireEvent.click(screen.getByRole('button', { name: /^back$/i })); // summary → organization
    fireEvent.click(screen.getByRole('button', { name: /^back$/i })); // organization → welcome
    fireEvent.click(screen.getByRole('button', { name: /set up your organization/i }));

    expect(screen.getByPlaceholderText('Acme, Inc.')).toHaveValue('Acme Corp');
    expect(screen.getByPlaceholderText('acme-inc')).toHaveValue('acme-corp');
  });
});

describe('FirstTenantOnboardingWizard: summary step', () => {
  it('shows the entered details with the slug derived from the name when blank', async () => {
    render(<FirstTenantOnboardingWizard />);

    fillOrganizationStep('Acme, Inc.');

    expect(await screen.findByTestId('onboarding-step-summary')).toBeInTheDocument();
    expect(screen.getByText('Acme, Inc.')).toBeInTheDocument();
    expect(screen.getByText('acme-inc')).toBeInTheDocument();
  });

  it('renders the Free-license summary before confirm', async () => {
    render(<FirstTenantOnboardingWizard />);

    fillOrganizationStep('Acme Corp');

    const summary = await screen.findByTestId('free-license-summary');
    expect(summary).toHaveTextContent(`${FREE_LICENSE_SUMMARY.planName} plan`);
    for (const limit of FREE_LICENSE_SUMMARY.limits) {
      expect(summary).toHaveTextContent(limit.label);
      expect(summary).toHaveTextContent(limit.value);
    }
    for (const item of FREE_LICENSE_SUMMARY.includes) {
      expect(summary).toHaveTextContent(item);
    }
    expect(mockProvisionFirstTenant).not.toHaveBeenCalled();
  });

  it('provisions the tenant on confirm and reaches the done step', async () => {
    render(<FirstTenantOnboardingWizard />);

    fillOrganizationStep('Acme Corp', 'acme-corp');
    expect(await createAndSkipSecurity()).toBeInTheDocument();
    expect(mockProvisionFirstTenant).toHaveBeenCalledWith('Acme Corp', 'acme-corp');
    expect(screen.getByRole('heading', { name: /acme corp is ready/i })).toBeInTheDocument();
  });

  it('stays on the summary and shows the error when provisioning fails', async () => {
    mockProvisionFirstTenant.mockResolvedValue({
      success: false,
      error: 'A tenant with this slug already exists',
    });
    render(<FirstTenantOnboardingWizard />);

    fillOrganizationStep('Acme Corp', 'acme-corp');
    fireEvent.click(await screen.findByRole('button', { name: /create organization/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/slug already exists/i);
    expect(screen.getByTestId('onboarding-step-summary')).toBeInTheDocument();
  });

  it('shows a generic error when the provisioning call throws', async () => {
    const consoleError = jest.spyOn(console, 'error').mockImplementation(() => undefined);
    mockProvisionFirstTenant.mockRejectedValue(new Error('network down'));
    render(<FirstTenantOnboardingWizard />);

    fillOrganizationStep('Acme Corp');
    fireEvent.click(await screen.findByRole('button', { name: /create organization/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/something went wrong/i);
    consoleError.mockRestore();
  });
});

describe('FirstTenantOnboardingWizard: completion', () => {
  it('activates the new tenant in the session and lands in its dashboard', async () => {
    render(<FirstTenantOnboardingWizard />);

    fillOrganizationStep('Acme Corp', 'acme-corp');
    await createAndSkipSecurity();
    fireEvent.click(await screen.findByRole('button', { name: /go to your dashboard/i }));

    await waitFor(() => expect(mockPush).toHaveBeenCalledWith('/ade'));
    expect(mockUpdate).toHaveBeenCalledWith({ current_tenant_id: 't-1' });
    expect(mockRefresh).toHaveBeenCalled();
  });

  it('lands in the dashboard even when the session update fails', async () => {
    const consoleError = jest.spyOn(console, 'error').mockImplementation(() => undefined);
    mockUpdate.mockRejectedValue(new Error('session update failed'));
    render(<FirstTenantOnboardingWizard />);

    fillOrganizationStep('Acme Corp', 'acme-corp');
    await createAndSkipSecurity();
    fireEvent.click(await screen.findByRole('button', { name: /go to your dashboard/i }));

    await waitFor(() => expect(mockPush).toHaveBeenCalledWith('/ade'));
    consoleError.mockRestore();
  });
});

describe('FirstTenantOnboardingWizard: protect your account (TFA-1.4)', () => {
  /** Walks to the security step, which follows a successful create. */
  const openSecurity = async () => {
    render(<FirstTenantOnboardingWizard />);
    fillOrganizationStep('Acme Corp', 'acme-corp');
    fireEvent.click(await screen.findByRole('button', { name: /create organization/i }));
    return screen.findByTestId('onboarding-step-security');
  };

  it('follows the review step once the tenant exists, confirming it first', async () => {
    const body = await openSecurity();

    expect(within(body).getByRole('heading', { name: 'Protect your account' })).toBeInTheDocument();
    expect(body).toHaveTextContent('Acme Corp is ready.');
    expect(within(body).getByText(/authy or google authenticator/i)).toBeInTheDocument();
    // The tenant already exists: there is no way back to the review step.
    expect(screen.queryByRole('button', { name: /^back$/i })).not.toBeInTheDocument();
    // Nothing to resume any more, so the resume footnote is gone.
    expect(screen.queryByText(/progress is saved server-side/i)).not.toBeInTheDocument();
  });

  it('is the last step of the progress row', async () => {
    await openSecurity();

    const list = screen.getByRole('list', { name: /setup progress/i });
    expect(within(list).getByText('Step 4 of 4')).toBeInTheDocument();
  });

  it('skips to the last screen with two-factor left off', async () => {
    await openSecurity();

    fireEvent.click(screen.getByRole('button', { name: /skip for now/i }));

    expect(await screen.findByTestId('onboarding-step-done')).toBeInTheDocument();
    expect(mockTwoFactorEnable).not.toHaveBeenCalled();
  });

  it('runs the profile enrolment and finishes once the backup codes are saved', async () => {
    mockTwoFactorEnable.mockResolvedValue({
      data: { totpURI: 'otpauth://totp/apiome:ada?secret=ABC', backupCodes: ['aaaa-bbbb'] },
    });
    mockVerifyTotp.mockResolvedValue({ data: { status: true } });
    await openSecurity();

    fireEvent.click(screen.getByRole('button', { name: /set up two-factor/i }));
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText('Enable two-factor authentication')).toBeInTheDocument();

    fireEvent.change(within(dialog).getByLabelText('Current password'), {
      target: { value: 'hunter2!' },
    });
    fireEvent.click(within(dialog).getByTestId('two-factor-enroll-continue'));
    await waitFor(() => expect(mockTwoFactorEnable).toHaveBeenCalledWith({ password: 'hunter2!' }));

    fireEvent.change(await within(dialog).findByTestId('two-factor-enroll-code'), {
      target: { value: '123456' },
    });
    fireEvent.click(within(dialog).getByTestId('two-factor-enroll-verify'));
    await waitFor(() => expect(mockVerifyTotp).toHaveBeenCalledWith({ code: '123456' }));
    // The session is refetched so it carries the new two-factor flag.
    expect(mockUpdate).toHaveBeenCalledWith({});
    // Inside the wizard, the backup step points at the profile rather than "this page".
    expect(
      await within(dialog).findByText(/regenerate a new set later from your profile/i)
    ).toBeInTheDocument();

    fireEvent.click(within(dialog).getByTestId('two-factor-enroll-done'));
    expect(await screen.findByTestId('onboarding-step-done')).toBeInTheDocument();
  });

  it('stays on the step when the enrolment dialog is cancelled', async () => {
    await openSecurity();

    fireEvent.click(screen.getByRole('button', { name: /set up two-factor/i }));
    const dialog = await screen.findByRole('dialog');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }));

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(screen.getByTestId('onboarding-step-security')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /skip for now/i })).toBeInTheDocument();
  });

  it('asks a passwordless account for no password', async () => {
    mockGetReauthStatus.mockResolvedValue({
      hasPassword: false,
      fresh: true,
      providers: [{ id: 'github', label: 'GitHub' }],
    });
    await openSecurity();

    fireEvent.click(screen.getByRole('button', { name: /set up two-factor/i }));
    const dialog = await screen.findByRole('dialog');

    expect(await within(dialog).findByTestId('two-factor-reauth-fresh')).toBeInTheDocument();
    expect(within(dialog).queryByLabelText('Current password')).not.toBeInTheDocument();
  });
});

describe('FirstTenantOnboardingWizard: resumability + funnel telemetry (OLO-4.5)', () => {
  it('reopens on the saved step with entered values pre-filled', async () => {
    mockLoadState.mockResolvedValue({ step: 'summary', orgName: 'Acme Corp', slug: 'acme-corp' });
    render(<FirstTenantOnboardingWizard />);

    // Hydration jumps straight to the review step the user abandoned on.
    expect(await screen.findByTestId('onboarding-step-summary')).toBeInTheDocument();
    expect(screen.getByText('Acme Corp')).toBeInTheDocument();
    expect(screen.getByText('acme-corp')).toBeInTheDocument();
  });

  it('never resumes onto the terminal done step (no provisioned tenant in memory)', async () => {
    mockLoadState.mockResolvedValue({ step: 'done', orgName: 'Acme Corp', slug: 'acme-corp' });
    render(<FirstTenantOnboardingWizard />);

    // `done` needs the just-provisioned tenant, so resume caps at the welcome
    // start rather than rendering an empty done step.
    await waitFor(() => expect(mockLoadState).toHaveBeenCalled());
    expect(screen.getByTestId('onboarding-step-welcome')).toBeInTheDocument();
  });

  it('never resumes onto the security step either (it follows provisioning)', async () => {
    mockLoadState.mockResolvedValue({ step: 'security', orgName: 'Acme Corp', slug: 'acme-corp' });
    render(<FirstTenantOnboardingWizard />);

    await waitFor(() => expect(mockLoadState).toHaveBeenCalled());
    expect(screen.getByTestId('onboarding-step-welcome')).toBeInTheDocument();
  });

  it('seeds the funnel and resume row with a welcome-reached event on a fresh start', async () => {
    render(<FirstTenantOnboardingWizard />);

    await waitFor(() =>
      expect(mockSaveStep).toHaveBeenCalledWith('welcome', '', '', 'reached')
    );
  });

  it('records a reached event when advancing forward through the wizard', async () => {
    render(<FirstTenantOnboardingWizard />);

    // welcome → organization records the organization-reached event...
    fireEvent.click(screen.getByRole('button', { name: /set up your organization/i }));
    await waitFor(() =>
      expect(mockSaveStep).toHaveBeenCalledWith('organization', '', '', 'reached')
    );

    // ...and organization → summary records summary-reached with entered values.
    fireEvent.change(screen.getByPlaceholderText('Acme, Inc.'), {
      target: { value: 'Acme Corp' },
    });
    fireEvent.change(screen.getByPlaceholderText('acme-inc'), { target: { value: 'acme-corp' } });
    fireEvent.click(screen.getByRole('button', { name: /continue/i }));

    await screen.findByTestId('onboarding-step-summary');
    expect(mockSaveStep).toHaveBeenCalledWith('summary', 'Acme Corp', 'acme-corp', 'reached');
  });

  it('persists backward navigation without recording a funnel event', async () => {
    render(<FirstTenantOnboardingWizard />);

    fillOrganizationStep('Acme Corp', 'acme-corp');
    await screen.findByTestId('onboarding-step-summary');
    mockSaveStep.mockClear();
    fireEvent.click(screen.getByRole('button', { name: /^back$/i })); // summary → organization

    await waitFor(() =>
      expect(mockSaveStep).toHaveBeenCalledWith('organization', 'Acme Corp', 'acme-corp', undefined)
    );
  });

  it('records completion and clears state after provisioning succeeds', async () => {
    render(<FirstTenantOnboardingWizard />);

    fillOrganizationStep('Acme Corp', 'acme-corp');
    fireEvent.click(await screen.findByRole('button', { name: /create organization/i }));

    // Completion is recorded when the tenant exists, not when the security step is left.
    expect(await screen.findByTestId('onboarding-step-security')).toBeInTheDocument();
    await waitFor(() => expect(mockCompleteWizard).toHaveBeenCalledTimes(1));
    // ...and the step after provisioning is never saved for resume.
    expect(mockSaveStep).not.toHaveBeenCalledWith(
      'security',
      expect.anything(),
      expect.anything(),
      expect.anything()
    );
  });

  it('still navigates when persisting the wizard step rejects', async () => {
    const consoleError = jest.spyOn(console, 'error').mockImplementation(() => undefined);
    mockSaveStep.mockRejectedValue(new Error('persist down'));
    render(<FirstTenantOnboardingWizard />);

    fireEvent.click(screen.getByRole('button', { name: /set up your organization/i }));

    expect(await screen.findByTestId('onboarding-step-organization')).toBeInTheDocument();
    consoleError.mockRestore();
  });
});
