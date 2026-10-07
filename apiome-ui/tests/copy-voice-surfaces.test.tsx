/**
 * The shared error surfaces speak the DESIGN.md §10 voice (HIVE-10.4, #5340).
 *
 * The app has some four hundred error strings, most of them "Failed to X" / "Could not Y"
 * fallbacks or a server's own message. Rather than trust each to name a next action, every
 * surface that shows one — `ErrorState`, `ErrorBanner`, a danger `Alert`, the app `toast.error`, the
 * `AlertDialog` in its danger tone and the provider's `perform` failures — makes sure it does.
 * These tests pin that, and pin the cases where the surface must leave the copy alone: a retry
 * button or action already names the way out, and a React node is the caller's own words.
 *
 * The rule itself is `tests/copy-voice-gate.test.ts`.
 */

import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';

const sonnerError = jest.fn();
const sonnerSuccess = jest.fn();
const sonnerCall = jest.fn();
jest.mock('sonner', () => {
  const toast = (...args: unknown[]) => sonnerCall(...args);
  toast.error = (...args: unknown[]) => sonnerError(...args);
  toast.success = (...args: unknown[]) => sonnerSuccess(...args);
  return { toast };
});

import { toast } from '../src/app/components/ui/toast';
import {
  ERROR_FALLBACK_GUIDANCE,
  ErrorBanner,
  ErrorState,
  guideErrorDescription,
} from '../src/app/components/ui/ErrorState';
import AlertDialog from '../src/app/components/dialogs/AlertDialog';
import { Alert } from '../src/app/components/ui/Alert';
import { DialogProvider, useDialog } from '../src/app/components/providers/DialogProvider';
import { UNKNOWN_FAILURE } from '../lib/copy-voice';

beforeEach(() => {
  sonnerError.mockClear();
  sonnerSuccess.mockClear();
  sonnerCall.mockClear();
});

describe('guideErrorDescription', () => {
  it('leaves the copy alone when the surface already has a way out', () => {
    expect(guideErrorDescription('Could not load branches', true)).toBe('Could not load branches');
    expect(guideErrorDescription(undefined, true)).toBeUndefined();
  });

  it('adds a next action to a bare string', () => {
    expect(guideErrorDescription('Could not load branches', false)).toBe(
      'Could not load branches — try again.'
    );
  });

  it('fills a missing description with the fallback guidance', () => {
    expect(guideErrorDescription(undefined, false)).toBe(ERROR_FALLBACK_GUIDANCE);
    expect(guideErrorDescription(null, false)).toBe(ERROR_FALLBACK_GUIDANCE);
    expect(guideErrorDescription('', false)).toBe(ERROR_FALLBACK_GUIDANCE);
    expect(guideErrorDescription(false, false)).toBe(ERROR_FALLBACK_GUIDANCE);
  });

  it('never rewrites a React node', () => {
    const node = <span>Custom</span>;
    expect(guideErrorDescription(node, false)).toBe(node);
  });
});

describe('ErrorState', () => {
  it('names a next action when it has no retry', () => {
    render(<ErrorState title="Couldn't load projects" description="Server returned 500" />);
    expect(screen.getByText('Server returned 500 — try again.')).toBeInTheDocument();
  });

  it('says what to do even with no description at all', () => {
    render(<ErrorState />);
    expect(screen.getByText(ERROR_FALLBACK_GUIDANCE)).toBeInTheDocument();
  });

  it('keeps the caller’s words when a retry button carries the action', () => {
    render(<ErrorState description="Server returned 500" onRetry={jest.fn()} />);
    expect(screen.getByText('Server returned 500')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument();
  });
});

describe('ErrorBanner', () => {
  it('names a next action when it has no retry or action', () => {
    render(<ErrorBanner title="Couldn't save" description="Failed to update version" />);
    expect(screen.getByText('Failed to update version — try again.')).toBeInTheDocument();
  });

  it('draws no empty description line beside a retry', () => {
    const { container } = render(<ErrorBanner title="Couldn't save" onRetry={jest.fn()} />);
    expect(screen.getByText("Couldn't save")).toBeInTheDocument();
    expect(container.textContent).not.toContain(ERROR_FALLBACK_GUIDANCE);
  });
});

describe('Alert', () => {
  it('voices a bare failure string in the danger tone', () => {
    render(<Alert variant="danger">Failed to load roles</Alert>);
    expect(screen.getByRole('alert')).toHaveTextContent('Failed to load roles — try again.');
  });

  it('voices the pre-Hive error alias too', () => {
    render(<Alert variant="error">Could not save these settings</Alert>);
    expect(screen.getByRole('alert')).toHaveTextContent('Could not save these settings — try again.');
  });

  it('leaves the body alone when the banner carries its own action', () => {
    render(
      <Alert variant="danger" actions={<button type="button">Retry</button>}>
        Failed to load roles
      </Alert>
    );
    expect(screen.getByRole('alert')).not.toHaveTextContent('try again.');
  });

  it('leaves rules, rich bodies and other tones alone', () => {
    const { rerender } = render(<Alert variant="danger">That name is taken</Alert>);
    expect(screen.getByRole('alert')).toHaveTextContent(/^That name is taken$/);
    rerender(
      <Alert variant="danger">
        <span>Failed to load roles</span>
      </Alert>
    );
    expect(screen.getByRole('alert')).not.toHaveTextContent('try again.');
    rerender(<Alert variant="info">Failed to load roles</Alert>);
    expect(screen.getByRole('alert')).not.toHaveTextContent('try again.');
  });
});

describe('toast', () => {
  it('adds a next action to an error toast that lacks one', () => {
    toast.error('Could not create tag');
    expect(sonnerError).toHaveBeenCalledWith('Could not create tag — try again.');
  });

  it('passes an error that already advises through untouched, with its options', () => {
    toast.error('Could not sign out. Try again.', { id: 'x' });
    expect(sonnerError).toHaveBeenCalledWith('Could not sign out. Try again.', { id: 'x' });
  });

  it('leaves a rule-shaped message as written — retrying cannot help', () => {
    toast.error('System primitives cannot be edited');
    expect(sonnerError).toHaveBeenCalledWith('System primitives cannot be edited');
  });

  it('passes a non-string message through', () => {
    const node = <b>Custom</b>;
    toast.error(node);
    expect(sonnerError).toHaveBeenCalledWith(node);
  });

  it('leaves every other kind of toast exactly as sonner has it', () => {
    toast.success('Saved');
    toast('Heads up');
    expect(sonnerSuccess).toHaveBeenCalledWith('Saved');
    expect(sonnerCall).toHaveBeenCalledWith('Heads up');
  });
});

describe('AlertDialog', () => {
  it('names a next action in its danger tone', () => {
    render(<AlertDialog open message="Failed to publish" variant="error" onClose={jest.fn()} />);
    expect(screen.getByText('Failed to publish — try again.')).toBeInTheDocument();
  });

  it('leaves a rule in its danger tone as written', () => {
    render(<AlertDialog open message="That name is taken" variant="error" onClose={jest.fn()} />);
    expect(screen.getByText('That name is taken')).toBeInTheDocument();
  });

  it('leaves info copy alone', () => {
    render(<AlertDialog open message="Copied" onClose={jest.fn()} />);
    expect(screen.getByText('Copied')).toBeInTheDocument();
  });

  it('dismisses with a verb, not “OK”', () => {
    render(<AlertDialog open message="Copied" onClose={jest.fn()} />);
    expect(screen.getByRole('button', { name: 'Close' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'OK' })).not.toBeInTheDocument();
  });
});

describe('DialogProvider perform failures', () => {
  /** A button that opens a confirm whose `perform` throws `cause`. */
  function Harness({ cause }: { cause: unknown }) {
    const { confirm } = useDialog();
    return (
      <button
        type="button"
        onClick={() =>
          void confirm({
            title: 'Delete it?',
            message: 'Gone for good.',
            confirmLabel: 'Delete',
            perform: () => {
              throw cause;
            },
          })
        }
      >
        Open
      </button>
    );
  }

  it('shows a thrown message with a next action', async () => {
    render(
      <DialogProvider>
        <Harness cause={new Error('Could not delete project')} />
      </DialogProvider>
    );
    await userEvent.click(screen.getByRole('button', { name: 'Open' }));
    await userEvent.click(screen.getByRole('button', { name: 'Delete' }));
    expect(await screen.findByText('Could not delete project — try again.')).toBeInTheDocument();
  });

  it('shows the generic failure for a non-Error throw', async () => {
    render(
      <DialogProvider>
        <Harness cause={42} />
      </DialogProvider>
    );
    await userEvent.click(screen.getByRole('button', { name: 'Open' }));
    await userEvent.click(screen.getByRole('button', { name: 'Delete' }));
    expect(await screen.findByText(UNKNOWN_FAILURE)).toBeInTheDocument();
  });
});
