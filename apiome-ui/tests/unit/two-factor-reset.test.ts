/**
 * Shared pieces of the admin two-factor reset (TFA-1.2, #5656).
 *
 * `lib/auth/two-factor-reset.ts` is what the two reset routes and the dialog have in common: the
 * limits a dialog checks before sending, the wording of a refusal, and the step that turns
 * apiome-rest's reply into the browser's answer — including whether the user was emailed.
 */
import {
  RESET_REASON_MAX_LENGTH,
  RESET_REASON_MIN_LENGTH,
  describeResetRefusal,
  finishTwoFactorReset,
  isValidResetReason,
  matchesResetConfirmation,
  parseResetRequest,
} from '@lib/auth/two-factor-reset';

const REST_OK = {
  user_id: 'u1',
  email: 'priya@example.com',
  name: 'Priya Raman',
  had_two_factor: true,
  sessions_revoked: 3,
  trusted_devices_revoked: 2,
};

describe('isValidResetReason', () => {
  it('mirrors the limits apiome-rest enforces', () => {
    expect(RESET_REASON_MIN_LENGTH).toBe(10);
    expect(RESET_REASON_MAX_LENGTH).toBe(500);
  });

  it.each([
    ['x'.repeat(10), true],
    ['x'.repeat(500), true],
    [`   ${'x'.repeat(10)}  `, true],
    ['x'.repeat(9), false],
    ['x'.repeat(501), false],
    [' '.repeat(40), false],
    ['', false],
  ])('%#', (reason, expected) => {
    expect(isValidResetReason(reason)).toBe(expected);
  });
});

describe('matchesResetConfirmation', () => {
  it.each([
    ['priya@example.com', 'priya@example.com', true],
    ['  PRIYA@Example.com ', 'priya@example.com', true],
    ['priya@example.com', 'Priya@Example.COM', true],
    ['priya@example.co', 'priya@example.com', false],
    ['Priya Raman', 'priya@example.com', false],
    ['', 'priya@example.com', false],
    ['', '', false],
    ['anything', null, false],
    ['anything', undefined, false],
  ])('typing %p for %p → %p', (typed, email, expected) => {
    expect(matchesResetConfirmation(typed, email)).toBe(expected);
  });
});

describe('parseResetRequest', () => {
  it('reads a reason and a confirmation', () => {
    expect(parseResetRequest({ reason: 'because', confirm: 'a@b.co', extra: 1 })).toEqual({
      reason: 'because',
      confirm: 'a@b.co',
    });
  });

  it.each([null, undefined, 'text', 12, [], {}, { reason: 'x' }, { confirm: 'x' }, { reason: 1, confirm: 'x' }])(
    'refuses %p',
    (body) => {
      expect(parseResetRequest(body)).toBeNull();
    }
  );
});

describe('describeResetRefusal', () => {
  it('reads the structured refusal apiome-rest sends', () => {
    expect(
      describeResetRefusal({ detail: { error: 'multi_tenant_member', message: 'Also belongs elsewhere.' } })
    ).toEqual({ code: 'multi_tenant_member', message: 'Also belongs elsewhere.' });
  });

  it('reads a plain-string detail', () => {
    expect(describeResetRefusal({ detail: 'Invalid or expired super-admin session.' })).toEqual({
      code: null,
      message: 'Invalid or expired super-admin session.',
    });
  });

  it('reads a proxy failure', () => {
    expect(describeResetRefusal({ error: 'rest_unreachable', message: 'Could not reach it.' })).toEqual({
      code: 'rest_unreachable',
      message: 'Could not reach it.',
    });
  });

  it.each([null, undefined, 'x', {}, { detail: {} }, { detail: { error: 'x' } }])(
    'falls back to a general sentence for %p',
    (body) => {
      expect(describeResetRefusal(body)).toEqual({
        code: null,
        message: 'The two-factor reset could not be completed. Try again.',
      });
    }
  );
});

describe('finishTwoFactorReset', () => {
  it('emails the user after a successful reset and says so', async () => {
    const sendEmail = jest.fn(async () => true);
    const answer = await finishTwoFactorReset(200, REST_OK, sendEmail);

    expect(sendEmail).toHaveBeenCalledWith({ email: 'priya@example.com', name: 'Priya Raman' });
    expect(answer).toEqual({
      status: 200,
      body: {
        success: true,
        data: {
          userId: 'u1',
          hadTwoFactor: true,
          sessionsRevoked: 3,
          trustedDevicesRevoked: 2,
          emailSent: true,
        },
      },
    });
  });

  it('still reports the reset when the email could not be sent', async () => {
    const answer = await finishTwoFactorReset(200, REST_OK, async () => false);
    expect(answer.status).toBe(200);
    expect(answer.body).toMatchObject({ success: true, data: { emailSent: false } });
  });

  it('does not put the user’s address or name in the answer', async () => {
    const answer = await finishTwoFactorReset(200, REST_OK, async () => true);
    expect(JSON.stringify(answer.body)).not.toContain('priya@example.com');
    expect(JSON.stringify(answer.body)).not.toContain('Priya');
  });

  it.each([400, 401, 403, 404, 409, 422, 502])(
    'passes a %i refusal on with its code and sends no email',
    async (status) => {
      const sendEmail = jest.fn(async () => true);
      const answer = await finishTwoFactorReset(
        status,
        { detail: { error: 'owner_required', message: 'Only an owner can do this.' } },
        sendEmail
      );
      expect(answer).toEqual({
        status,
        body: { success: false, error: 'Only an owner can do this.', code: 'owner_required' },
      });
      expect(sendEmail).not.toHaveBeenCalled();
    }
  );

  it('omits the code when the refusal carried none', async () => {
    const answer = await finishTwoFactorReset(500, null, async () => true);
    expect(answer.body).toEqual({
      success: false,
      error: 'The two-factor reset could not be completed. Try again.',
    });
  });
});
