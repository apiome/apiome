/**
 * The "Reset two-factor" confirmation (TFA-1.2, #5656).
 *
 * One dialog serves the admin console and the member drawer. It will not send a reset until a
 * reason is given and the user's email is typed out, it shows a refusal where it happened, and
 * after a reset it stays open on the result — which says whether the user was emailed.
 */

import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { axe } from 'jest-axe';
import 'jest-axe/extend-expect';
import {
  ResetTwoFactorDialog,
  describeResetOutcome,
} from '@/app/components/ade/account/ResetTwoFactorDialog';

const TARGET = { userId: 'u1', email: 'priya@example.com', name: 'Priya Raman' };
const REASON = 'Lost her phone and her backup codes.';
const OUTCOME = { userId: 'u1', hadTwoFactor: true, sessionsRevoked: 3, trustedDevicesRevoked: 1, emailSent: true };

const endpoint = (userId: string) => `/api/admin/users/${userId}/two-factor/reset`;
let fetchMock: jest.Mock;

/** Answer the reset call with `payload` at `status`. */
const answer = (payload: unknown, status = 200) =>
  fetchMock.mockResolvedValue({ ok: status >= 200 && status < 300, status, json: async () => payload });

/** Render the dialog open on {@link TARGET}. */
function mount(props: Partial<React.ComponentProps<typeof ResetTwoFactorDialog>> = {}) {
  const onOpenChange = jest.fn();
  const onReset = jest.fn();
  const view = render(
    <ResetTwoFactorDialog
      open
      onOpenChange={onOpenChange}
      target={TARGET}
      endpoint={endpoint}
      onReset={onReset}
      {...props}
    />
  );
  return { ...view, onOpenChange, onReset };
}

/** Fill in both fields. */
const fill = (reason = REASON, confirm = TARGET.email) => {
  fireEvent.change(screen.getByTestId('reset-two-factor-reason'), { target: { value: reason } });
  fireEvent.change(screen.getByTestId('reset-two-factor-confirm'), { target: { value: confirm } });
};

beforeEach(() => {
  fetchMock = jest.fn();
  global.fetch = fetchMock as unknown as typeof fetch;
});

describe('ResetTwoFactorDialog', () => {
  it('names who it is about and what will happen', () => {
    mount();
    expect(screen.getByRole('alertdialog', { name: 'Reset two-factor for Priya Raman?' })).toBeInTheDocument();
    expect(screen.getByText(/signed out everywhere/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Type priya@example.com to confirm/)).toBeInTheDocument();
  });

  it('falls back to the email address when the user has no name', () => {
    mount({ target: { ...TARGET, name: null } });
    expect(screen.getByRole('alertdialog', { name: 'Reset two-factor for priya@example.com?' })).toBeInTheDocument();
  });

  it.each([
    ['nothing typed', '', ''],
    ['a reason but no confirmation', REASON, ''],
    ['a confirmation but no reason', '', TARGET.email],
    ['a reason that is too short', 'too short', TARGET.email],
    ['the wrong email', REASON, 'someone.else@example.com'],
    ['the name instead of the email', REASON, 'Priya Raman'],
  ])('keeps the button disabled with %s', (_name, reason, confirm) => {
    mount();
    fill(reason, confirm);
    expect(screen.getByTestId('reset-two-factor-submit')).toBeDisabled();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('sends the trimmed reason and confirmation, then shows the result', async () => {
    answer({ success: true, data: OUTCOME });
    const { onReset, onOpenChange } = mount();
    fill(`  ${REASON}  `, ' PRIYA@example.com ');

    fireEvent.click(screen.getByTestId('reset-two-factor-submit'));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith('/api/admin/users/u1/two-factor/reset', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason: REASON, confirm: 'PRIYA@example.com' }),
      })
    );
    expect(await screen.findByTestId('reset-two-factor-result')).toHaveTextContent(
      'Two-factor was reset for priya@example.com and they were signed out everywhere. They have been emailed.'
    );
    expect(onReset).toHaveBeenCalledWith(OUTCOME, TARGET);
    // It stays open on the result: the reader has to see whether the user was told.
    expect(onOpenChange).not.toHaveBeenCalled();
    expect(screen.queryByTestId('reset-two-factor-submit')).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId('reset-two-factor-done'));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it('tells the reader to pass the word on when no email was sent', async () => {
    answer({ success: true, data: { ...OUTCOME, emailSent: false } });
    mount();
    fill();
    fireEvent.click(screen.getByTestId('reset-two-factor-submit'));

    expect(await screen.findByTestId('reset-two-factor-result')).toHaveTextContent(
      'No email was sent, because this installation cannot send email — let them know yourself.'
    );
  });

  it('shows a refusal in the dialog and lets the reader try again', async () => {
    answer(
      { success: false, error: 'This member also belongs to another workspace.', code: 'multi_tenant_member' },
      409
    );
    const { onReset } = mount();
    fill();
    fireEvent.click(screen.getByTestId('reset-two-factor-submit'));

    expect(await screen.findByText('This member also belongs to another workspace.')).toBeInTheDocument();
    expect(onReset).not.toHaveBeenCalled();
    expect(screen.getByTestId('reset-two-factor-reason')).toHaveValue(REASON);
    expect(screen.getByTestId('reset-two-factor-submit')).toBeEnabled();
  });

  it('says so when the request itself fails', async () => {
    fetchMock.mockRejectedValue(new Error('offline'));
    mount();
    fill();
    fireEvent.click(screen.getByTestId('reset-two-factor-submit'));
    expect(await screen.findByText(/Check your connection and try again/)).toBeInTheDocument();
  });

  it('uses the route it was given — the member drawer’s', async () => {
    answer({ success: true, data: OUTCOME });
    mount({ endpoint: (userId) => `/api/access/members/${userId}/two-factor/reset` });
    fill();
    fireEvent.click(screen.getByTestId('reset-two-factor-submit'));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith('/api/access/members/u1/two-factor/reset', expect.anything())
    );
  });

  it('starts empty for the next person', () => {
    const { rerender } = mount();
    fill();
    rerender(
      <ResetTwoFactorDialog
        open
        onOpenChange={jest.fn()}
        target={{ userId: 'u2', email: 'sam@example.com', name: 'Sam' }}
        endpoint={endpoint}
      />
    );
    expect(screen.getByTestId('reset-two-factor-reason')).toHaveValue('');
    expect(screen.getByTestId('reset-two-factor-confirm')).toHaveValue('');
  });

  it('has no axe violations', async () => {
    const { baseElement } = mount();
    expect(await axe(baseElement)).toHaveNoViolations();
  });
});

describe('describeResetOutcome', () => {
  it('differs only in whether the user was emailed', () => {
    expect(describeResetOutcome(OUTCOME, TARGET)).toContain('They have been emailed.');
    expect(describeResetOutcome({ ...OUTCOME, emailSent: false }, TARGET)).toContain('let them know yourself');
  });
});
