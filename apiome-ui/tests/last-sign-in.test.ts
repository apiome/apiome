/**
 * The last-sign-in recorder (`lib/auth/last-sign-in.ts`): every completed sign-in is written to
 * `users.last_login_at`, which the admin console's Users list shows as Last active.
 */

jest.mock('better-auth/api', () => ({
  createAuthMiddleware: (handler: unknown) => handler,
}));
jest.mock('../lib/db/helper', () => ({ updateUserLastLoginAt: jest.fn() }));

import { lastSignInPlugin, recordCompletedSignIn } from '../lib/auth/last-sign-in';
import { updateUserLastLoginAt } from '../lib/db/helper';

describe('recordCompletedSignIn', () => {
  it('records the user of a session the endpoint issued', async () => {
    const recordUserLogin = jest.fn().mockResolvedValue(undefined);
    await recordCompletedSignIn({ context: { newSession: { user: { id: 'user-1' } } } }, { recordUserLogin });
    expect(recordUserLogin).toHaveBeenCalledWith('user-1');
  });

  it('records nothing while a second factor is pending, or when no session was issued', async () => {
    const recordUserLogin = jest.fn();
    await recordCompletedSignIn({ context: { newSession: null } }, { recordUserLogin });
    await recordCompletedSignIn({ context: {} }, { recordUserLogin });
    await recordCompletedSignIn({ context: { newSession: { user: { id: '' } } } }, { recordUserLogin });
    await recordCompletedSignIn(undefined, { recordUserLogin });
    expect(recordUserLogin).not.toHaveBeenCalled();
  });

  it('never fails the sign-in when the write throws', async () => {
    const error = jest.spyOn(console, 'error').mockImplementation(() => undefined);
    const recordUserLogin = jest.fn().mockRejectedValue(new Error('db down'));
    await expect(
      recordCompletedSignIn({ context: { newSession: { user: { id: 'user-1' } } } }, { recordUserLogin })
    ).resolves.toBeUndefined();
    error.mockRestore();
  });
});

describe('lastSignInPlugin', () => {
  it('runs after every endpoint and writes through the users helper', async () => {
    const plugin = lastSignInPlugin();
    expect(plugin.id).toBe('apiome-last-sign-in');
    const [hook] = plugin.hooks.after;
    expect(hook.matcher()).toBe(true);
    await (hook.handler as unknown as (ctx: unknown) => Promise<void>)({
      context: { newSession: { user: { id: 'user-2' } } },
    });
    expect(updateUserLastLoginAt).toHaveBeenCalledWith('user-2');
  });
});
