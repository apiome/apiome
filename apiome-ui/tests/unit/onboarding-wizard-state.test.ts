/**
 * `onboarding-wizard-state.ts` REST-client tests (OLO-4.5, #4209).
 *
 * The client persists the onboarding wizard's resume position and funnel events
 * through `GET/PUT/DELETE /v1/onboarding/wizard-state` with a session-minted
 * JWT. It runs server-side only and must never throw — persistence/telemetry is
 * best-effort and cannot be allowed to break the wizard the user is using.
 */
const mockCreateRestAuthHeaders = jest.fn<Record<string, string>, unknown[]>();

jest.mock('../../lib/rest-auth', () => ({
  createRestAuthHeaders: (...args: unknown[]) => mockCreateRestAuthHeaders(...args),
  REST_API_BASE_URL: 'http://rest.test/v1',
}));

import {
  clearWizardStateViaRest,
  loadWizardStateViaRest,
  saveWizardStateViaRest,
} from '../../lib/auth/onboarding-wizard-state';

const mockFetch = jest.fn<Promise<unknown>, unknown[]>();
(global as { fetch?: unknown }).fetch = mockFetch;

const USER = { user_id: 'user-1', email: 'ada@example.com', name: 'Ada' };

beforeEach(() => {
  jest.clearAllMocks();
  mockCreateRestAuthHeaders.mockReturnValue({
    'Content-Type': 'application/json',
    Authorization: 'Bearer test-token',
  });
});

describe('loadWizardStateViaRest', () => {
  it('returns the parsed state on 200', async () => {
    mockFetch.mockResolvedValue({
      status: 200,
      ok: true,
      json: async () => ({ step: 'summary', org_name: 'Acme Corp', slug: 'acme-corp' }),
    });

    const result = await loadWizardStateViaRest(USER);

    expect(result).toEqual({ step: 'summary', orgName: 'Acme Corp', slug: 'acme-corp' });
    expect(mockFetch).toHaveBeenCalledWith(
      'http://rest.test/v1/onboarding/wizard-state',
      expect.objectContaining({
        method: 'GET',
        cache: 'no-store',
        headers: expect.objectContaining({ Authorization: 'Bearer test-token' }),
      })
    );
  });

  it('returns null on 204 (no saved state)', async () => {
    mockFetch.mockResolvedValue({ status: 204, ok: true, json: async () => null });

    expect(await loadWizardStateViaRest(USER)).toBeNull();
  });

  it('normalizes a missing org_name/slug to null', async () => {
    mockFetch.mockResolvedValue({
      status: 200,
      ok: true,
      json: async () => ({ step: 'organization' }),
    });

    expect(await loadWizardStateViaRest(USER)).toEqual({
      step: 'organization',
      orgName: null,
      slug: null,
    });
  });

  it('returns null (never throws) when the request fails', async () => {
    const consoleError = jest.spyOn(console, 'error').mockImplementation(() => undefined);
    mockFetch.mockRejectedValue(new Error('network down'));

    expect(await loadWizardStateViaRest(USER)).toBeNull();
    consoleError.mockRestore();
  });

  it('returns null on a malformed body (no step)', async () => {
    mockFetch.mockResolvedValue({ status: 200, ok: true, json: async () => ({}) });

    expect(await loadWizardStateViaRest(USER)).toBeNull();
  });
});

describe('saveWizardStateViaRest', () => {
  it('PUTs step, values and funnel event', async () => {
    mockFetch.mockResolvedValue({ ok: true });

    const ok = await saveWizardStateViaRest(USER, 'summary', 'Acme Corp', 'acme-corp', 'reached');

    expect(ok).toBe(true);
    expect(mockFetch).toHaveBeenCalledWith(
      'http://rest.test/v1/onboarding/wizard-state',
      expect.objectContaining({ method: 'PUT', cache: 'no-store' })
    );
    const body = JSON.parse((mockFetch.mock.calls[0][1] as { body: string }).body);
    expect(body).toEqual({
      step: 'summary',
      org_name: 'Acme Corp',
      slug: 'acme-corp',
      event: 'reached',
    });
  });

  it('sends null event and null values when omitted/blank (backward navigation)', async () => {
    mockFetch.mockResolvedValue({ ok: true });

    await saveWizardStateViaRest(USER, 'welcome', '', '');

    const body = JSON.parse((mockFetch.mock.calls[0][1] as { body: string }).body);
    expect(body).toEqual({ step: 'welcome', org_name: null, slug: null, event: null });
  });

  it('returns false (never throws) when the request fails', async () => {
    const consoleError = jest.spyOn(console, 'error').mockImplementation(() => undefined);
    mockFetch.mockRejectedValue(new Error('network down'));

    expect(await saveWizardStateViaRest(USER, 'summary', 'Acme', 'acme', 'reached')).toBe(false);
    consoleError.mockRestore();
  });
});

describe('clearWizardStateViaRest', () => {
  it('DELETEs the wizard state', async () => {
    mockFetch.mockResolvedValue({ ok: true });

    expect(await clearWizardStateViaRest(USER)).toBe(true);
    expect(mockFetch).toHaveBeenCalledWith(
      'http://rest.test/v1/onboarding/wizard-state',
      expect.objectContaining({ method: 'DELETE', cache: 'no-store' })
    );
  });

  it('returns false (never throws) when the request fails', async () => {
    const consoleError = jest.spyOn(console, 'error').mockImplementation(() => undefined);
    mockFetch.mockRejectedValue(new Error('network down'));

    expect(await clearWizardStateViaRest(USER)).toBe(false);
    consoleError.mockRestore();
  });
});
