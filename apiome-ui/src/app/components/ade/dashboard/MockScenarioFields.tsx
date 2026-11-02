'use client';

/**
 * Two field wrappers for the mock scenarios dialog (round-3 facelift, idea "forms").
 *
 * - {@link EditorPane} frames a JSON textarea as an editor: a caps bar names what the
 *   field holds and how it is read, the control itself drops its own chrome and the pane
 *   carries the hover and focus rings instead (`.vdlg-editor` in globals.css).
 * - {@link Disclosure} folds an advanced block behind a native `<details>` so the common
 *   path — one response per operation — reads without it. It opens by itself when the
 *   block already has content, so a saved rule is never hidden.
 *
 * Both are presentation only: the fields inside keep their labels, refs and handlers, so
 * every test and every keyboard path through the dialog is unchanged.
 */

import { type ReactNode, type SyntheticEvent, useState } from 'react';
import { ChevronRight } from 'lucide-react';

export interface EditorPaneProps {
  /** What the field holds, as the bar reads it: `Headers`, `Body`, `Rules`. */
  label: string;
  /** A short reading hint on the right of the bar: `optional`, `first match wins`. */
  hint?: string;
  /** The language the bar announces after the label; every pane today is JSON. */
  language?: string;
  /** The textarea (and anything that belongs under it). */
  children: ReactNode;
}

/**
 * A JSON field framed as an editor pane. See the module comment.
 *
 * @param props - {@link EditorPaneProps}
 * @returns the pane with its caps bar above the field
 */
export function EditorPane({ label, hint, language = 'JSON', children }: EditorPaneProps) {
  return (
    <div className="vdlg-editor" data-lang={language.toLowerCase()}>
      <div className="vdlg-editor__bar" aria-hidden>
        <span className="vdlg-editor__lang">
          {label} · {language}
        </span>
        {hint ? <span className="vdlg-editor__hint">{hint}</span> : null}
      </div>
      {children}
    </div>
  );
}

export interface DisclosureProps {
  /** The summary's caption. */
  label: string;
  /** A small tag beside the caption — `advanced`. */
  tag?: string;
  /** One sentence under the caption saying what the block does. */
  hint?: string;
  /** Whether the block starts open; it stays wherever the reader leaves it afterwards. */
  defaultOpen?: boolean;
  /** Forwarded to the `<details>` so tests can find one block among many. */
  'data-testid'?: string;
  children: ReactNode;
}

/**
 * An advanced block behind a native disclosure. See the module comment.
 *
 * @param props - {@link DisclosureProps}
 * @returns the `<details>` with its summary and body
 */
export function Disclosure({
  label,
  tag,
  hint,
  defaultOpen = false,
  children,
  ...rest
}: DisclosureProps) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <details
      className="vdlg-disclosure"
      open={open}
      onToggle={(event: SyntheticEvent<HTMLDetailsElement>) => setOpen(event.currentTarget.open)}
      data-testid={rest['data-testid']}
    >
      <summary className="vdlg-disclosure__summary">
        <ChevronRight aria-hidden className="vdlg-disclosure__chevron" />
        <span className="vdlg-caps">{label}</span>
        {tag ? <span className="vdlg-disclosure__tag">{tag}</span> : null}
        {hint ? <span className="vdlg-disclosure__hint">{hint}</span> : null}
      </summary>
      <div className="vdlg-disclosure__body">{children}</div>
    </details>
  );
}
