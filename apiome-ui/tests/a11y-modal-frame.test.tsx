/**
 * ModalFrame — focus-trapping chrome for legacy modals (HIVE-10.2, #5338), DESIGN.md §9
 * "all overlays trap focus and restore it".
 */

import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import { axe } from 'jest-axe';
import 'jest-axe/extend-expect';

import { ModalFrame, ModalFrameTitle } from '../src/app/components/ui/ModalFrame';

function Harness({ label }: { label?: string }) {
  const [open, setOpen] = React.useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Open
      </button>
      <ModalFrame open={open} onClose={() => setOpen(false)} label={label} overlayClassName="backdrop" data-testid="frame">
        <ModalFrameTitle asChild>
          <h3>Waive finding</h3>
        </ModalFrameTitle>
        <input aria-label="Rationale" />
        <button type="button" onClick={() => setOpen(false)}>
          Cancel
        </button>
      </ModalFrame>
    </>
  );
}

describe('ModalFrame', () => {
  it('is a modal dialog named by its title', async () => {
    render(<Harness />);
    await userEvent.click(screen.getByRole('button', { name: 'Open' }));
    const dialog = screen.getByRole('dialog', { name: 'Waive finding' });
    expect(dialog).toHaveAttribute('data-testid', 'frame');
    expect(await axe(document.body)).toHaveNoViolations();
  });

  it('can carry a fixed name when its visible title changes', async () => {
    render(<Harness label="Waive lint finding" />);
    await userEvent.click(screen.getByRole('button', { name: 'Open' }));
    expect(screen.getByRole('dialog', { name: 'Waive lint finding' })).toBeInTheDocument();
  });

  it('moves focus in, keeps Tab inside, and restores focus to the trigger on Escape', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const trigger = screen.getByRole('button', { name: 'Open' });
    await user.click(trigger);
    const dialog = screen.getByRole('dialog');
    await waitFor(() => expect(dialog).toContainElement(document.activeElement as HTMLElement));
    for (let i = 0; i < 4; i += 1) {
      await user.tab();
      expect(dialog).toContainElement(document.activeElement as HTMLElement);
    }
    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    await waitFor(() => expect(trigger).toHaveFocus());
  });

  it('closes on a press on the backdrop', async () => {
    render(<Harness />);
    await userEvent.click(screen.getByRole('button', { name: 'Open' }));
    const backdrop = document.querySelector('.backdrop') as HTMLElement;
    fireEvent.pointerDown(backdrop);
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });
});
