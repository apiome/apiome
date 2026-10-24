/**
 * @jest-environment node
 *
 * The OAuth sign-up intent route's IP limit leaves an `auth_events` row (SGN-1.5, #5654).
 *
 * The per-IP request budget (OLO-7.1) is the one abuse guard provider sign-up shares with the email
 * form. These tests drive the real handler with the real budget: the first refused request of a
 * window is recorded once — later refusals in the same window are not — and requests within budget
 * record nothing.
 */

import { beforeEach, describe, expect, jest, test } from '@jest/globals';

jest.mock('@lib/auth/provider-config-resolver', () => ({ resolveProviderEnv: jest.fn(async () => ({})) }));
jest.mock('@lib/auth/provider-registry', () => ({ isProviderEnabled: jest.fn(() => true) }));
jest.mock('@lib/auth/same-origin', () => ({ isSameOriginRequest: jest.fn(() => true) }));
jest.mock('@lib/auth/signup-guard-events', () => ({ recordSignupGuardEvent: jest.fn(async () => undefined) }));

import { NextRequest } from 'next/server';
import { _resetLoginRateLimit, AUTH_ROUTE_MAX_REQUESTS } from '@lib/auth/login-rate-limit';
import { recordSignupGuardEvent } from '@lib/auth/signup-guard-events';
import { POST } from '@/app/api/auth/signup-intent/route';

const mockRecord = recordSignupGuardEvent as unknown as jest.Mock;

/** One sign-up intent from a client at 203.0.113.7. */
const post = () =>
  POST(
    new NextRequest('https://app.apiome.dev/api/auth/signup-intent', {
      method: 'POST',
      headers: { 'content-type': 'application/json', 'x-forwarded-for': '203.0.113.7' },
      body: JSON.stringify({ provider: 'github' }),
    })
  );

beforeEach(() => {
  jest.clearAllMocks();
  _resetLoginRateLimit();
});

describe('POST /api/auth/signup-intent — IP limit audit', () => {
  test('within budget records nothing', async () => {
    for (let i = 0; i < AUTH_ROUTE_MAX_REQUESTS; i += 1) expect((await post()).status).toBe(200);
    expect(mockRecord).not.toHaveBeenCalled();
  });

  test('the first refusal of a window is recorded once, with the rate-limit code', async () => {
    for (let i = 0; i < AUTH_ROUTE_MAX_REQUESTS; i += 1) await post();
    const refused = await post();
    expect(refused.status).toBe(429);
    expect(await refused.json()).toMatchObject({ code: 'auth-rate-limited' });
    expect((await post()).status).toBe(429);

    expect(mockRecord).toHaveBeenCalledTimes(1);
    expect(mockRecord.mock.calls[0][0]).toMatchObject({
      guard: 'rate_limit',
      scope: 'ip',
      code: 'auth-rate-limited',
      provider: null,
    });
  });
});
