'use client';

/**
 * **The provider's side** — section 5 of **Set up contracts** (PFX-8.20, #7317).
 *
 * Two ways for a provider to answer a pact; most teams turn on both.
 *
 * * **The spec as the contract** (bi-directional) — for each provider pacticipant bound to a project,
 *   turn on "each published version of the project is the provider contract" through
 *   `PUT /api/pact/provider-contracts/sources`. One already on says so and cannot be turned on twice.
 * * **Replay pacts against a running provider** — the hosted verifier, set up on **Run a verification**
 *   (its target and sign-in live there).
 *
 * A provider verified in its own pipeline marks the section done by hand.
 */

import * as React from 'react';
import Link from 'next/link';
import { Button } from '@/app/components/ui';
import { VERIFY_RUN_ROUTE } from '@lib/pact-verify-run';
import type { SectionBodyProps } from './PacticipantsSection';
import { saveSetup, turnOnSpecAsContract } from './setupApi';
import { AskAnAdmin, SectionMessage } from './SetupSection';

/**
 * The section's body.
 *
 * @param props - The set-up and what to do after a change.
 * @returns The body.
 */
export function ProviderSection({ state, onChanged }: SectionBodyProps) {
  const providers = state.candidates.filter((candidate) => candidate.pacticipant !== null && candidate.project !== null);
  const [busy, setBusy] = React.useState<string | null>(null);
  const [message, setMessage] = React.useState<{ tone: 'ok' | 'error'; text: string } | null>(null);
  const marked = state.saved.marked.includes('provider');

  const run = async (key: string, work: () => Promise<void>, done: string) => {
    setBusy(key);
    setMessage(null);
    try {
      await work();
      await onChanged();
      setMessage({ tone: 'ok', text: done });
    } catch (caught) {
      setMessage({ tone: 'error', text: caught instanceof Error ? caught.message : 'Could not save.' });
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="pset-body" data-testid="pset-provider-form">
      <p className="ppx__muted">Two ways for a provider to answer a pact. Most teams turn on both.</p>

      <h3 className="pcx-caps">The spec as the contract</h3>
      <p className="ppx__muted">Bi-directional: pacts are compared with the spec. No provider test to write.</p>
      {providers.length === 0 ? (
        <p className="ppx__muted" data-testid="pset-no-providers">
          No pacticipant is bound to a project yet. Create one from a project in the first section, then come back.
        </p>
      ) : (
        <ul className="pset-rows">
          {providers.map((provider) => (
            <li key={provider.pacticipant} className="pset-row" data-testid={`pset-provider-${provider.pacticipant}`}>
              <span>
                Use each published version of <strong>{provider.name}</strong> as the provider contract of{' '}
                <strong>{provider.pacticipant_name ?? provider.pacticipant}</strong>
              </span>
              {provider.contract_source ? (
                <span className="pset-badge" data-state="done">
                  On
                </span>
              ) : state.can_edit ? (
                <Button
                  variant="outline"
                  size="sm"
                  disabled={busy !== null}
                  onClick={() =>
                    void run(
                      provider.pacticipant as string,
                      () => turnOnSpecAsContract(provider.pacticipant as string),
                      `Turned on for ${provider.pacticipant_name ?? provider.pacticipant}.`,
                    )
                  }
                  data-testid={`pset-provider-${provider.pacticipant}-on`}
                >
                  {busy === provider.pacticipant ? 'Turning on…' : 'Turn on'}
                </Button>
              ) : (
                <span className="pset-badge" data-state="todo">
                  Off
                </span>
              )}
            </li>
          ))}
        </ul>
      )}

      <h3 className="pcx-caps">Replay pacts against a running provider</h3>
      <p className="ppx__muted">
        The hosted verifier calls a real instance. Choose the target and how to sign in on Run a verification
        {state.facts.verification_results > 0 ? ' — this workspace already has verification results.' : '.'}
      </p>
      <div className="ppx__actions">
        <Button variant="outline" asChild>
          <Link href={VERIFY_RUN_ROUTE} data-testid="pset-provider-verify">
            Run a verification
          </Link>
        </Button>
      </div>

      <SectionMessage message={message} testId="pset-provider-message" />
      {state.can_edit ? (
        <div className="ppx__actions">
          <Button
            variant="ghost"
            disabled={busy !== null}
            onClick={() => void run('mark', async () => void (await saveSetup({ mark: { provider: !marked } })), marked ? 'Unmarked.' : 'Marked as handled.')}
            data-testid="pset-provider-mark"
          >
            {marked ? 'Not handled after all' : 'Our pipeline verifies the provider'}
          </Button>
        </div>
      ) : (
        <AskAnAdmin />
      )}
    </div>
  );
}

export default ProviderSection;
