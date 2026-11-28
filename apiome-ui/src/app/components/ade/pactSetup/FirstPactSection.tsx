'use client';

/**
 * **The first consumer pact** — section 4 of **Set up contracts** (PFX-8.20, #7317).
 *
 * Two ways to the first pact, as option cards: publish the files Pact tests already produce, or
 * derive one from the provider's spec. The choice is saved with the set-up; its button goes to the
 * page that does it (**Publish a pact**, or **Export → A pact from a project**). The section is done
 * when a pact is published, whichever way it came.
 */

import * as React from 'react';
import Link from 'next/link';
import { Button } from '@/app/components/ui';
import { FIRST_PACT_CARDS, FIRST_PACT_PATHS, type FirstPactPath } from '@lib/pact-setup';
import type { SectionBodyProps } from './PacticipantsSection';
import { saveSetup } from './setupApi';
import { SectionMessage } from './SetupSection';

/**
 * The section's body.
 *
 * @param props - The set-up and what to do after a change.
 * @returns The body.
 */
export function FirstPactSection({ state, onChanged }: SectionBodyProps) {
  const [path, setPath] = React.useState<FirstPactPath>(state.saved.first_pact_path ?? 'tests');
  const [message, setMessage] = React.useState<{ tone: 'ok' | 'error'; text: string } | null>(null);
  const card = FIRST_PACT_CARDS[path];

  const choose = async (next: FirstPactPath) => {
    setPath(next);
    setMessage(null);
    if (!state.can_edit) return;
    try {
      await saveSetup({ first_pact_path: next });
      await onChanged();
    } catch (caught) {
      setMessage({ tone: 'error', text: caught instanceof Error ? caught.message : 'Could not save the choice.' });
    }
  };

  return (
    <div className="pset-body" data-testid="pset-first-pact-form">
      <p className="ppx__muted">Pick how your first pact comes to be. You can use the other way later.</p>
      <div className="pset-options" role="radiogroup" aria-label="How the first pact comes to be">
        {FIRST_PACT_PATHS.map((id) => {
          const inputId = `pset-path-${id}`;
          return (
            <label key={id} htmlFor={inputId} className={path === id ? 'ppc-option is-active' : 'ppc-option'} data-testid={inputId}>
              <input
                id={inputId}
                type="radio"
                name="pset-path"
                className="ppc-option__radio"
                checked={path === id}
                onChange={() => void choose(id)}
                aria-describedby={`${inputId}-desc`}
              />
              <span className="ppc-option__body">
                <span className="ppc-option__title">{FIRST_PACT_CARDS[id].title}</span>
                <span className="ppc-option__desc" id={`${inputId}-desc`}>
                  {FIRST_PACT_CARDS[id].description}
                </span>
              </span>
            </label>
          );
        })}
      </div>
      <SectionMessage message={message} testId="pset-first-pact-message" />
      <div className="ppx__actions">
        <Button asChild>
          <Link href={card.route} data-testid="pset-first-pact-go">
            {card.action}
          </Link>
        </Button>
        <span className="ppx__muted">
          {state.facts.pacts > 0
            ? `${state.facts.pacts >= 100 ? '100 or more pacts are' : state.facts.pacts === 1 ? '1 pact is' : `${state.facts.pacts} pacts are`} published.`
            : 'This section is done when the first pact is published.'}
        </span>
      </div>
    </div>
  );
}

export default FirstPactSection;
