/**
 * Tests for QuickSnapshotCaptureDialog (#173)
 */
import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import { QuickSnapshotCaptureDialog } from '../src/app/ade/studio/editor/components/QuickSnapshotCaptureDialog';

describe('QuickSnapshotCaptureDialog', () => {
  test('shows author label and requires summary before confirm', async () => {
    const user = userEvent.setup();
    const onConfirm = jest.fn();

    render(
      <QuickSnapshotCaptureDialog
        open
        onOpenChange={() => {}}
        authorLabel="Alex Example"
        isSaving={false}
        onConfirm={onConfirm}
      />
    );

    expect(screen.getByText('Alex Example')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /save snapshot/i }));
    expect(onConfirm).not.toHaveBeenCalled();
    expect(screen.getByText(/enter a short summary/i)).toBeInTheDocument();

    await user.type(screen.getByRole('textbox', { name: /summary/i }), 'Morning layout');
    await user.click(screen.getByRole('button', { name: /save snapshot/i }));
    expect(onConfirm).toHaveBeenCalledWith({
      summary: 'Morning layout',
      description: '',
    });
  });

  test('passes trimmed description', async () => {
    const user = userEvent.setup();
    const onConfirm = jest.fn();

    render(
      <QuickSnapshotCaptureDialog
        open
        onOpenChange={() => {}}
        authorLabel="A"
        isSaving={false}
        onConfirm={onConfirm}
      />
    );

    await user.type(screen.getByRole('textbox', { name: /summary/i }), 'S');
    await user.type(screen.getByRole('textbox', { name: /description/i }), '  note  ');
    await user.click(screen.getByRole('button', { name: /save snapshot/i }));
    expect(onConfirm).toHaveBeenCalledWith({ summary: 'S', description: 'note' });
  });
});
