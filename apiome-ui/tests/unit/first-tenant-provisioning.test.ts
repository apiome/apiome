/**
 * `provisionFirstTenantViaRest` tests (OLO-4.3, #4207).
 *
 * The helper is the single tenant-provisioning path: it validates name/slug,
 * calls the atomic REST endpoint `POST /v1/onboarding/first-tenant` with a
 * session-minted JWT, and maps the endpoint's structured 409 codes
 * (`tenant-slug-taken`, `tenant-cap-reached`) to human-readable errors.
 */
const mockCreateRestAuthHeaders = jest.fn<Record<string, string>, unknown[]>();

jest.mock('../../lib/rest-auth', () => ({
  createRestAuthHeaders: (...args: unknown[]) => mockCreateRestAuthHeaders(...args),
  REST_API_BASE_URL: 'http://rest.test/v1',
}));

import { provisionFirstTenantViaRest } from '../../lib/auth/first-tenant-provisioning';

const mockFetch = jest.fn<Promise<unknown>, unknown[]>();
(global as { fetch?: unknown }).fetch = mockFetch;

const USER = { user_id: 'user-1', email: 'ada@example.com', name: 'Ada' };

const jsonResponse = (status: number, body: unknown) => ({
  status,
  json: async () => body,
});

const okTenant = { id: 't-1', name: 'Acme Corp', slug: 'acme-corp', created_at: '2026-07-17' };

beforeEach(() => {
  jest.clearAllMocks();
  mockCreateRestAuthHeaders.mockReturnValue({
    'Content-Type': 'application/json',
    Authorization: 'Bearer test-token',
  });
  mockFetch.mockResolvedValue(
    jsonResponse(201, { tenant: okTenant, sample_project_id: null })
  );
});

describe('provisionFirstTenantViaRest', () => {
  it('provisions through the REST endpoint with the caller identity', async () => {
    const result = await provisionFirstTenantViaRest(USER, 'Acme Corp', 'acme-corp');

    expect(result).toEqual({
      success: true,
      tenant: { id: 't-1', name: 'Acme Corp', slug: 'acme-corp' },
    });
    expect(mockCreateRestAuthHeaders).toHaveBeenCalledWith(USER);
    expect(mockFetch).toHaveBeenCalledWith(
      'http://rest.test/v1/onboarding/first-tenant',
      expect.objectContaining({
        method: 'POST',
        cache: 'no-store',
        headers: expect.objectContaining({ Authorization: 'Bearer test-token' }),
      })
    );
    const body = JSON.parse((mockFetch.mock.calls[0][1] as { body: string }).body);
    expect(body).toEqual({
      name: 'Acme Corp',
      slug: 'acme-corp',
      provision_sample_project: true,
    });
  });

  it('derives the slug from the organization name when none is entered', async () => {
    await provisionFirstTenantViaRest(USER, 'Acme, Inc.', '  ');

    const body = JSON.parse((mockFetch.mock.calls[0][1] as { body: string }).body);
    expect(body.slug).toBe('acme-inc');
  });

  it('requires an organization name without calling the endpoint', async () => {
    const result = await provisionFirstTenantViaRest(USER, '   ', 'acme');

    expect(result).toEqual({ success: false, error: expect.stringMatching(/name is required/i) });
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it('validates the slug before calling the endpoint', async () => {
    const result = await provisionFirstTenantViaRest(USER, 'Acme', 'not a slug!');

    expect(result).toEqual({
      success: false,
      error: expect.stringMatching(/lowercase letters, numbers, and dashes/i),
    });
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it('maps 409 tenant-slug-taken to the familiar duplicate-slug message', async () => {
    mockFetch.mockResolvedValue(
      jsonResponse(409, { detail: { code: 'tenant-slug-taken', message: 'taken' } })
    );

    const result = await provisionFirstTenantViaRest(USER, 'Acme', 'acme');

    expect(result).toEqual({
      success: false,
      error: 'A tenant with this slug already exists',
      code: 'tenant-slug-taken',
    });
  });

  it('surfaces 409 tenant-cap-reached with its structured code', async () => {
    mockFetch.mockResolvedValue(
      jsonResponse(409, { detail: { code: 'tenant-cap-reached', message: 'limit' } })
    );

    const result = await provisionFirstTenantViaRest(USER, 'Acme', 'acme');

    expect(result).toMatchObject({ success: false, code: 'tenant-cap-reached' });
  });

  it('passes through a plain-string error detail (e.g. validation 400)', async () => {
    mockFetch.mockResolvedValue(jsonResponse(400, { detail: 'Organization name is required' }));

    const result = await provisionFirstTenantViaRest(USER, 'Acme', 'acme');

    expect(result).toEqual({ success: false, error: 'Organization name is required' });
  });

  it('falls back to a generic error on unrecognized failure bodies', async () => {
    mockFetch.mockResolvedValue(jsonResponse(500, null));

    const result = await provisionFirstTenantViaRest(USER, 'Acme', 'acme');

    expect(result).toEqual({ success: false, error: 'Could not create organization' });
  });

  it('reports an unexpected 201 body instead of pretending success', async () => {
    mockFetch.mockResolvedValue(jsonResponse(201, { nope: true }));

    const result = await provisionFirstTenantViaRest(USER, 'Acme', 'acme');

    expect(result).toEqual({
      success: false,
      error: expect.stringMatching(/unexpected response/i),
    });
  });

  it('degrades gracefully when the REST service is unreachable', async () => {
    const consoleError = jest.spyOn(console, 'error').mockImplementation(() => undefined);
    mockFetch.mockRejectedValue(new Error('connection refused'));

    const result = await provisionFirstTenantViaRest(USER, 'Acme', 'acme');

    expect(result).toEqual({
      success: false,
      error: expect.stringMatching(/could not reach/i),
    });
    consoleError.mockRestore();
  });
});
