/**
 * Email sign-up is gated by the installation sign-up policy (SGN-1.4, #5653).
 *
 * `createSignupRequest` is the email form's entry point. It must go through the same gate as every
 * OAuth provider (`resolveEmailSignupDecision`), refusing before it touches the database, and it
 * must behave exactly as before when the policy admits the address.
 */
import { beforeEach, describe, expect, jest, test } from '@jest/globals';

jest.mock('../lib/db/db', () => ({ query: jest.fn() }));
jest.mock('bcrypt', () => ({ compare: jest.fn(), hash: jest.fn(async () => 'hashed') }));
jest.mock('../lib/db/plan-entitlements', () => ({
  getPlanBlockMessageForNewProject: jest.fn(async () => null),
  getPlanBlockMessageForNewVersion: jest.fn(async () => null),
}));

const mockResolveSignupPolicy = jest.fn<() => Promise<unknown>>();
jest.mock('../lib/auth/signup-policy-resolver', () => ({
  resolveSignupPolicy: () => mockResolveSignupPolicy(),
}));

// eslint-disable-next-line @typescript-eslint/no-require-imports
const db = require('../lib/db/db');
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { createSignupRequest } = require('../lib/db/helper');

const mockQuery = db.query as jest.Mock<(...args: unknown[]) => Promise<unknown>>;

const request = (email = 'ada@example.com') =>
  createSignupRequest('Ada', email, 'correct horse battery staple', 'a friend').then(JSON.parse);

beforeEach(() => {
  mockQuery.mockReset();
  mockQuery.mockResolvedValue({ rowCount: 0, rows: [] });
});

describe('createSignupRequest under the sign-up policy', () => {
  test.each([
    ['closed', { mode: 'closed', allowedEmailDomains: [] }, 'signup-disabled'],
    ['invite_only', { mode: 'invite_only', allowedEmailDomains: [] }, 'signup-invite-only'],
    [
      'open + other domain',
      { mode: 'open', allowedEmailDomains: ['corp.example'] },
      'signup-domain-not-allowed',
    ],
  ])('%s refuses the request before touching the database', async (_name, policy, code) => {
    mockResolveSignupPolicy.mockResolvedValue({ ...policy, source: 'db' });

    const result = await request();

    expect(result.success).toBe(false);
    expect(result.code).toBe(code);
    expect(typeof result.error).toBe('string');
    expect(result.error.length).toBeGreaterThan(0);
    expect(mockQuery).not.toHaveBeenCalled();
  });

  test.each([
    ['open', { mode: 'open', allowedEmailDomains: [] }],
    ['open + allowed domain', { mode: 'open', allowedEmailDomains: ['example.com'] }],
  ])('%s files the request as before', async (_name, policy) => {
    mockResolveSignupPolicy.mockResolvedValue({ ...policy, source: 'db' });

    const result = await request();

    expect(result.success).toBe(true);
    expect(mockQuery).toHaveBeenCalledTimes(2);
    expect(String(mockQuery.mock.calls[1][0])).toContain('INSERT INTO apiome.signup');
  });
});
