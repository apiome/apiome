/**
 * `onboarding-wizard-state-actions.ts` server-action tests (OLO-4.5, #4209).
 *
 * The actions are thin session wrappers over the REST client: they resolve the
 * caller's identity from the server session (never from the client) and
 * delegate load/save/complete to `onboarding-wizard-state.ts`. Completion both
 * records the `completed` funnel event and clears the resume state.
 */
const mockLoad = jest.fn<Promise<unknown>, unknown[]>();
const mockSave = jest.fn<Promise<unknown>, unknown[]>();
const mockClear = jest.fn<Promise<unknown>, unknown[]>();

jest.mock('../../lib/auth/onboarding-wizard-state', () => ({
  loadWizardStateViaRest: (...args: unknown[]) => mockLoad(...args),
  saveWizardStateViaRest: (...args: unknown[]) => mockSave(...args),
  clearWizardStateViaRest: (...args: unknown[]) => mockClear(...args),
}));

// Mocked explicitly: the `^@lib/` moduleNameMapper outranks the shared
// server-session mock mapping, so the action would otherwise pull in next-auth.
jest.mock('@lib/auth/server-session', () => ({
  getAuthSession: jest.fn(async () => null),
}));

import { getAuthSession } from '@lib/auth/server-session';
import {
  completeOnboardingWizard,
  loadOnboardingWizardState,
  saveOnboardingWizardStep,
} from '../../lib/auth/onboarding-wizard-state-actions';

const mockGetAuthSession = getAuthSession as jest.Mock;
const IDENTITY = { user_id: 'user-1', email: 'ada@example.com', name: 'Ada' };

beforeEach(() => {
  jest.clearAllMocks();
  mockGetAuthSession.mockResolvedValue({ user: IDENTITY });
  mockLoad.mockResolvedValue(null);
  mockSave.mockResolvedValue(true);
  mockClear.mockResolvedValue(true);
});

describe('loadOnboardingWizardState', () => {
  it('delegates to the REST client with the session identity', async () => {
    mockLoad.mockResolvedValue({ step: 'summary', orgName: 'Acme', slug: 'acme' });

    const result = await loadOnboardingWizardState();

    expect(result).toEqual({ step: 'summary', orgName: 'Acme', slug: 'acme' });
    expect(mockLoad).toHaveBeenCalledWith(IDENTITY);
  });

  it('returns null without an authenticated session', async () => {
    mockGetAuthSession.mockResolvedValue(null);

    expect(await loadOnboardingWizardState()).toBeNull();
    expect(mockLoad).not.toHaveBeenCalled();
  });
});

describe('saveOnboardingWizardStep', () => {
  it('forwards step, values and event to the REST client', async () => {
    await saveOnboardingWizardStep('summary', 'Acme', 'acme', 'reached');

    expect(mockSave).toHaveBeenCalledWith(IDENTITY, 'summary', 'Acme', 'acme', 'reached');
  });

  it('is a no-op without an authenticated session', async () => {
    mockGetAuthSession.mockResolvedValue(null);

    await saveOnboardingWizardStep('summary', 'Acme', 'acme', 'reached');

    expect(mockSave).not.toHaveBeenCalled();
  });
});

describe('completeOnboardingWizard', () => {
  it('records the completed funnel event then clears the state', async () => {
    await completeOnboardingWizard();

    expect(mockSave).toHaveBeenCalledWith(IDENTITY, 'done', '', '', 'completed');
    expect(mockClear).toHaveBeenCalledWith(IDENTITY);
  });

  it('is a no-op without an authenticated session', async () => {
    mockGetAuthSession.mockResolvedValue(null);

    await completeOnboardingWizard();

    expect(mockSave).not.toHaveBeenCalled();
    expect(mockClear).not.toHaveBeenCalled();
  });
});
