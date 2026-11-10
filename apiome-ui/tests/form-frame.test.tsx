/**
 * FormFrame and FormSection (SUX-2.4, apiome#6752).
 *
 * 1. **The spacing rule, measured.** jsdom compiles no Tailwind, but it does cascade a real
 *    `<style>`: the "FORM FRAME (SUX-2.4)" section of `globals.css` is loaded into the document
 *    and the rendered frame's computed gaps are asserted — 24 px between sections, 16 px between
 *    fields, a sticky footer, the three widths — plus `FormField`'s 6 px label gap.
 * 2. **Slots.** Header, body, footer; status left (dirty marker, form error), actions right
 *    (secondary, then primary).
 * 3. **Keyboard.** Enter in a single-line field submits, Enter in a text area does not, ⌘S and
 *    Ctrl+S submit, and nothing submits while the primary action is disabled or saving.
 * 4. **Secondary buttons never submit**, and the frame works inside `DialogContent`.
 */

import * as React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';

import {
  Button,
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  FormField,
  FormFrame,
  FormSection,
  Input,
  Textarea,
  isSaveChord,
  type FormFrameProps,
} from '../src/app/components/ui';
import { readGlobalsCss } from './helpers/design-tokens';

/** The FORM FRAME section of globals.css, from its banner to the next one. */
const FORM_FRAME_CSS = (() => {
  const css = readGlobalsCss();
  const start = css.indexOf('FORM FRAME (SUX-2.4');
  if (start < 0) throw new Error('globals.css has no FORM FRAME section');
  const end = css.indexOf('/* ====', start);
  return css.slice(css.lastIndexOf('/*', start), end < 0 ? undefined : end);
})();

beforeAll(() => {
  const style = document.createElement('style');
  style.setAttribute('data-test', 'form-frame');
  style.textContent = FORM_FRAME_CSS;
  document.head.appendChild(style);
});

/**
 * Render a two-section frame.
 *
 * @param props Overrides for the frame's props.
 * @returns The `onSubmit` mock and the render result.
 */
function renderFrame(props: Partial<FormFrameProps> = {}) {
  const onSubmit = jest.fn();
  const result = render(
    <FormFrame
      header={<h2>Project settings</h2>}
      submitLabel="Save"
      onSubmit={onSubmit}
      secondaryActions={<Button variant="ghost">Cancel</Button>}
      {...props}
    >
      <FormSection title="Basics" description="Name and slug.">
        <FormField label="Name" htmlFor="ff-name">
          <Input id="ff-name" defaultValue="Payments" />
        </FormField>
        <FormField label="Slug" htmlFor="ff-slug">
          <Input id="ff-slug" defaultValue="payments" />
        </FormField>
      </FormSection>
      <FormSection title="Access">
        <FormField label="Notes" htmlFor="ff-notes">
          <Textarea id="ff-notes" />
        </FormField>
      </FormSection>
    </FormFrame>,
  );
  return { onSubmit, ...result };
}

/** The frame's `<form>`. */
const form = (container: HTMLElement) => container.querySelector('form.hive-form-frame') as HTMLFormElement;

describe('FormFrame spacing (rendered gaps)', () => {
  it('puts 24 px between sections and 16 px between fields', () => {
    const { container } = renderFrame();
    const body = container.querySelector('.hive-form-frame__body') as HTMLElement;
    expect(getComputedStyle(form(container)).getPropertyValue('--form-frame-section-gap').trim()).toBe('1.5rem');
    expect(getComputedStyle(form(container)).getPropertyValue('--form-frame-field-gap').trim()).toBe('1rem');
    expect(getComputedStyle(body).display).toBe('flex');
    expect(getComputedStyle(body).gap).toBe('var(--form-frame-section-gap)');

    const fields = container.querySelectorAll('.hive-form-section__fields');
    expect(fields).toHaveLength(2);
    fields.forEach((grid) => {
      expect(getComputedStyle(grid).display).toBe('grid');
      expect(getComputedStyle(grid).gap).toBe('var(--form-frame-field-gap, 1rem)');
    });
  });

  it('gives FormField a 6 px label gap (gap-1.5)', () => {
    const { container } = renderFrame();
    const field = container.querySelector('.hive-form-section__fields > div') as HTMLElement;
    expect(field).toHaveClass('flex', 'flex-col', 'gap-1.5');
    expect(field.querySelector('label')).toHaveTextContent('Name');
  });

  it('keeps the footer sticky at the bottom and the body scrollable', () => {
    const { container } = renderFrame();
    const footer = getComputedStyle(container.querySelector('.hive-form-frame__footer') as HTMLElement);
    expect(footer.position).toBe('sticky');
    expect(footer.getPropertyValue('inset-block-end')).toBe('0');
    expect(getComputedStyle(container.querySelector('.hive-form-frame__body') as HTMLElement).overflowY).toBe('auto');
  });

  it.each([
    ['narrow', '35rem'],
    ['default', '45rem'],
    ['wide', '60rem'],
  ] as const)('caps a %s frame at %s', (width, expected) => {
    const { container } = renderFrame({ width });
    expect(form(container)).toHaveAttribute('data-width', width);
    expect(getComputedStyle(form(container)).getPropertyValue('--form-frame-max-inline-size').trim()).toBe(expected);
  });
});

describe('FormFrame slots', () => {
  it('renders header, body and footer in order, actions secondary then primary', () => {
    const { container } = renderFrame();
    const slots = Array.from(form(container).children).map((child) => child.className);
    expect(slots).toEqual(['hive-form-frame__header', 'hive-form-frame__body', 'hive-form-frame__footer']);
    const buttons = Array.from(container.querySelectorAll('.hive-form-frame__actions button')).map((b) => b.textContent);
    expect(buttons).toEqual(['Cancel', 'Save']);
    expect(screen.getByRole('button', { name: 'Save' })).toHaveAttribute('type', 'submit');
  });

  it('omits the header slot when none is given', () => {
    const { container } = renderFrame({ header: undefined });
    expect(container.querySelector('.hive-form-frame__header')).toBeNull();
  });

  it('shows the dirty marker and the form error on the footer left', () => {
    const { container } = renderFrame({ dirty: true, error: 'Could not save.' });
    const status = container.querySelector('.hive-form-frame__status') as HTMLElement;
    expect(status).toContainElement(screen.getByRole('status'));
    expect(screen.getByRole('status')).toHaveTextContent('Unsaved changes');
    expect(status).toContainElement(screen.getByRole('alert'));
    expect(screen.getByRole('alert')).toHaveTextContent('Could not save.');
  });

  it('takes a custom dirty label and hides both when clean', () => {
    const { rerender, onSubmit } = renderFrame({ dirty: true, dirtyLabel: 'Draft not saved' });
    expect(screen.getByRole('status')).toHaveTextContent('Draft not saved');
    rerender(
      <FormFrame submitLabel="Save" onSubmit={onSubmit}>
        <FormSection title="Basics">x</FormSection>
      </FormFrame>,
    );
    expect(screen.queryByRole('status')).toBeNull();
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('shows a spinner and disables the primary action while submitting', () => {
    renderFrame({ submitting: true });
    const save = screen.getByRole('button', { name: /Save/ });
    expect(save).toBeDisabled();
    expect(save).toHaveAttribute('aria-busy', 'true');
    expect(save).toHaveAttribute('title', 'Saving…');
  });

  it('says why the primary action is disabled', () => {
    const { rerender, onSubmit } = renderFrame({ submitDisabled: true });
    expect(screen.getByRole('button', { name: 'Save' })).toHaveAttribute('title', 'Fill in the required fields to save.');
    rerender(
      <FormFrame submitLabel="Save" onSubmit={onSubmit} submitDisabled submitDisabledReason="Pick an owner first.">
        <FormSection title="Basics">x</FormSection>
      </FormFrame>,
    );
    expect(screen.getByRole('button', { name: 'Save' })).toHaveAttribute('title', 'Pick an owner first.');
    rerender(
      <FormFrame submitLabel="Save" onSubmit={onSubmit}>
        <FormSection title="Basics">x</FormSection>
      </FormFrame>,
    );
    expect(screen.getByRole('button', { name: 'Save' })).not.toHaveAttribute('title');
  });
});

describe('FormSection', () => {
  it('is a group named by its title and described by its description', () => {
    renderFrame();
    const basics = screen.getByRole('group', { name: 'Basics' });
    expect(basics).toHaveAccessibleDescription('Name and slug.');
    expect(screen.getByRole('heading', { level: 3, name: 'Basics' })).toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'Access' })).not.toHaveAttribute('aria-describedby');
  });

  it('takes another heading level', () => {
    render(
      <FormSection title="Owner" headingLevel="h2">
        <span>field</span>
      </FormSection>,
    );
    expect(screen.getByRole('heading', { level: 2, name: 'Owner' })).toBeInTheDocument();
  });
});

describe('FormFrame keyboard', () => {
  it('submits on Enter in a single-line field', async () => {
    const user = userEvent.setup();
    const { onSubmit } = renderFrame();
    await user.click(screen.getByLabelText('Name'));
    await user.keyboard('{Enter}');
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it('does not submit on Enter in a text area', async () => {
    const user = userEvent.setup();
    const { onSubmit } = renderFrame();
    await user.click(screen.getByLabelText('Notes'));
    await user.keyboard('{Enter}');
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByLabelText('Notes')).toHaveValue('\n');
  });

  it.each([
    ['Ctrl+S', { ctrlKey: true }],
    ['⌘S', { metaKey: true }],
  ])('submits on %s from inside the frame, swallowing the browser save', (_label, modifiers) => {
    const { onSubmit } = renderFrame();
    const notes = screen.getByLabelText('Notes');
    const notCancelled = fireEvent.keyDown(notes, { key: 's', ...modifiers });
    expect(notCancelled).toBe(false);
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it('ignores S with Shift or Alt, and plain S', () => {
    const { onSubmit } = renderFrame();
    const name = screen.getByLabelText('Name');
    fireEvent.keyDown(name, { key: 's', ctrlKey: true, shiftKey: true });
    fireEvent.keyDown(name, { key: 's', metaKey: true, altKey: true });
    fireEvent.keyDown(name, { key: 's' });
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it.each([
    ['disabled', { submitDisabled: true }],
    ['submitting', { submitting: true }],
  ] as const)('does not submit while %s, but still swallows the chord', async (_label, props) => {
    const user = userEvent.setup();
    const { onSubmit } = renderFrame(props);
    expect(fireEvent.keyDown(screen.getByLabelText('Name'), { key: 's', ctrlKey: true })).toBe(false);
    await user.click(screen.getByLabelText('Name'));
    await user.keyboard('{Enter}');
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('lets a caller handle the chord first', () => {
    const onKeyDown = jest.fn((event: React.KeyboardEvent) => event.preventDefault());
    const { onSubmit } = renderFrame({ onKeyDown });
    fireEvent.keyDown(screen.getByLabelText('Name'), { key: 's', ctrlKey: true });
    expect(onKeyDown).toHaveBeenCalled();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('recognises the save chord', () => {
    const base = { key: 's', metaKey: false, ctrlKey: false, altKey: false, shiftKey: false };
    expect(isSaveChord({ ...base, ctrlKey: true })).toBe(true);
    expect(isSaveChord({ ...base, metaKey: true, key: 'S' })).toBe(true);
    expect(isSaveChord({ ...base })).toBe(false);
    expect(isSaveChord({ ...base, ctrlKey: true, key: 'a' })).toBe(false);
  });
});

describe('FormFrame secondary actions', () => {
  it('makes untyped secondary buttons plain buttons, so Cancel never submits', async () => {
    const user = userEvent.setup();
    const { onSubmit } = renderFrame();
    const cancel = screen.getByRole('button', { name: 'Cancel' });
    expect(cancel).toHaveAttribute('type', 'button');
    await user.click(cancel);
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('leaves a secondary button that names its own type alone', () => {
    renderFrame({ secondaryActions: <Button type="reset">Reset</Button> });
    expect(screen.getByRole('button', { name: 'Reset' })).toHaveAttribute('type', 'reset');
  });
});

describe('FormFrame inside DialogContent', () => {
  it('fills the dialog and keeps the dialog named by its title', async () => {
    const user = userEvent.setup();
    const onSubmit = jest.fn();
    render(
      <Dialog open>
        <DialogContent>
          <FormFrame
            submitLabel="Save"
            onSubmit={onSubmit}
            header={
              <DialogHeader>
                <DialogTitle>Edit project</DialogTitle>
              </DialogHeader>
            }
          >
            <FormSection title="Basics">
              <FormField label="Name" htmlFor="dlg-name">
                <Input id="dlg-name" defaultValue="Payments" />
              </FormField>
            </FormSection>
          </FormFrame>
        </DialogContent>
      </Dialog>,
    );
    const dialog = screen.getByRole('dialog', { name: 'Edit project' });
    const frame = dialog.querySelector(':scope > form.hive-form-frame') as HTMLElement;
    expect(frame).not.toBeNull();
    expect(getComputedStyle(frame).maxInlineSize).toBe('none');
    // Only the body scrolls in a dialog; a sticky footer would sit inside the dialog's padding.
    const footer = frame.querySelector('.hive-form-frame__footer') as HTMLElement;
    expect(getComputedStyle(footer).position).toBe('static');
    expect(getComputedStyle(frame.querySelector('.hive-form-frame__body') as HTMLElement).flexGrow).toBe('1');
    await user.click(screen.getByLabelText('Name'));
    await user.keyboard('{Enter}');
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });
});
