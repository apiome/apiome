'use client';

/**
 * One collapsible section of **Set up contracts** (PFX-8.20, #7317): its number (a check once done),
 * title, one-line summary and state — Done, Next or To do — and, when open, its body. The header is
 * one button, so the whole row toggles and a screen reader hears the state with the title.
 */

import * as React from 'react';
import { Check, ChevronDown } from 'lucide-react';
import { ASK_AN_ADMIN, SECTION_STATE_LABELS, type SetupSection as Section } from '@lib/pact-setup';

/** Props of {@link SetupSection}. */
export interface SetupSectionProps {
  section: Section;
  /** Its place in the list, from 1. */
  number: number;
  open: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}

/**
 * The section.
 *
 * @param props - The section, whether it is open, and its body.
 * @returns The card.
 */
export function SetupSection({ section, number, open, onToggle, children }: SetupSectionProps) {
  const bodyId = `pset-${section.id}-body`;
  return (
    <section className="pset-section" data-state={section.state} data-testid={`pset-${section.id}`}>
      <h2 className="pset-section__heading">
        <button
          type="button"
          className="pset-section__head"
          aria-expanded={open}
          aria-controls={bodyId}
          onClick={onToggle}
          data-testid={`pset-${section.id}-toggle`}
        >
          <span className="pset-section__step" aria-hidden>
            {section.state === 'done' ? <Check className="pset-section__check" /> : number}
          </span>
          <span className="pset-section__titles">
            <span className="pset-section__title">{section.title}</span>
            <span className="pset-section__summary">{section.summary}</span>
          </span>
          <span className="pset-badge" data-state={section.state} data-testid={`pset-${section.id}-state`}>
            {SECTION_STATE_LABELS[section.state]}
          </span>
          <ChevronDown className="pset-section__chevron" aria-hidden />
        </button>
      </h2>
      {open ? (
        <div id={bodyId} className="pset-section__body" data-testid={bodyId}>
          {children}
        </div>
      ) : null}
    </section>
  );
}

/**
 * What a section shows in place of its actions to someone who cannot act on the page.
 *
 * @returns The line.
 */
export function AskAnAdmin() {
  return (
    <p className="pset-ask" role="note" data-testid="pset-ask-admin">
      {ASK_AN_ADMIN}
    </p>
  );
}

/**
 * A section's message line: what just happened, or why it did not.
 *
 * @param props - The tone and the text.
 * @returns The line, or nothing without a message.
 */
export function SectionMessage({ message, testId }: { message: { tone: 'ok' | 'error'; text: string } | null; testId: string }) {
  if (!message) return null;
  return (
    <p className={message.tone === 'ok' ? 'ppx__muted' : 'ppx__error'} role={message.tone === 'ok' ? 'status' : 'alert'} data-testid={testId}>
      {message.text}
    </p>
  );
}

/**
 * A block of text to copy, with a **Copy** button.
 *
 * @param props - The text, what it is (for the label), and a test id.
 * @returns The block.
 */
export function CopyBlock({ text, label, testId }: { text: string; label: string; testId: string }) {
  const [copied, setCopied] = React.useState<'idle' | 'copied' | 'failed'>('idle');
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied('copied');
    } catch {
      setCopied('failed');
    }
  };
  return (
    <div className="pset-copy" data-testid={testId}>
      <pre className="pcx-code" tabIndex={0} aria-label={label}>
        {text}
      </pre>
      <button type="button" className="pcx-chip" onClick={() => void copy()} data-testid={`${testId}-copy`}>
        {copied === 'copied' ? 'Copied' : 'Copy'}
      </button>
      <span className="sr-only" role="status">
        {copied === 'copied' ? `${label} copied.` : copied === 'failed' ? 'Could not copy: select the text and copy it.' : ''}
      </span>
    </div>
  );
}
