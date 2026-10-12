/**
 * The email a user receives when an administrator resets their two-factor (TFA-1.2, #5656).
 */

const mockSetApiKey = jest.fn();
const mockSend = jest.fn();

jest.mock('@sendgrid/mail', () => ({
  __esModule: true,
  default: {
    setApiKey: (...args: unknown[]) => mockSetApiKey(...args),
    send: (...args: unknown[]) => mockSend(...args),
  },
}));

import {
  buildTwoFactorResetMessage,
  sendTwoFactorResetEmail,
} from '@lib/auth/send-two-factor-reset-email';

const ENV = { SENDGRID_API_KEY: ' sg-key ', EMAIL_FROM: ' apiome <no-reply@example.com> ' };
const USER = { email: 'priya@example.com', name: 'Priya Raman' };

beforeEach(() => {
  jest.clearAllMocks();
  mockSend.mockResolvedValue(undefined);
});

describe('buildTwoFactorResetMessage', () => {
  it('says what happened and what to do next', () => {
    const message = buildTwoFactorResetMessage(USER);
    expect(message.subject).toBe('Your apiome two-factor authentication was reset');
    expect(message.text).toContain('Hello Priya Raman,');
    expect(message.text).toContain('An administrator reset the two-factor authentication');
    expect(message.text).toContain('signed out on every device');
    expect(message.text).toContain('set two-factor up again from Profile, under Security');
    expect(message.text).toContain('If you did not ask for this, contact your administrator');
  });

  it('greets a user with no name plainly', () => {
    expect(buildTwoFactorResetMessage({ email: 'a@b.co', name: '  ' }).text.startsWith('Hello,')).toBe(true);
  });

  it('escapes the name in the HTML body', () => {
    const message = buildTwoFactorResetMessage({ email: 'a@b.co', name: '<img src=x onerror=alert(1)>' });
    expect(message.html).not.toContain('<img');
    expect(message.html).toContain('&lt;img src=x onerror=alert(1)&gt;');
  });

  it('carries the same sentences in both bodies', () => {
    const message = buildTwoFactorResetMessage(USER);
    expect(message.html.replace(/<\/p><p>/g, '\n\n').replace(/<\/?p>/g, '')).toBe(message.text);
  });
});

describe('sendTwoFactorResetEmail', () => {
  it('sends through SendGrid with the configured sender', async () => {
    await expect(sendTwoFactorResetEmail(USER, ENV)).resolves.toBe(true);

    expect(mockSetApiKey).toHaveBeenCalledWith('sg-key');
    expect(mockSend).toHaveBeenCalledWith(
      expect.objectContaining({
        to: 'priya@example.com',
        from: 'apiome <no-reply@example.com>',
        subject: 'Your apiome two-factor authentication was reset',
      })
    );
  });

  it.each([
    ['no sender is configured', USER, {}],
    ['only the API key is set', USER, { SENDGRID_API_KEY: 'sg' }],
    ['the user has no email address', { email: '  ', name: 'X' }, ENV],
    ['the user has a null email address', { email: null }, ENV],
  ])('sends nothing and reports false when %s', async (_name, user, env) => {
    await expect(sendTwoFactorResetEmail(user, env)).resolves.toBe(false);
    expect(mockSend).not.toHaveBeenCalled();
  });

  it('reports false, without throwing, when delivery fails', async () => {
    const consoleError = jest.spyOn(console, 'error').mockImplementation(() => undefined);
    mockSend.mockRejectedValue(new Error('SendGrid 500 for priya@example.com'));

    await expect(sendTwoFactorResetEmail(USER, ENV)).resolves.toBe(false);
    // The log names the failure, not the recipient.
    expect(consoleError.mock.calls.flat().join(' ')).not.toContain('priya@example.com');
    consoleError.mockRestore();
  });
});
