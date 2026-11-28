'use client';

/**
 * **Set up contracts** — PFX-8.20 (#7317), `/ade/dashboard/pacts/setup`
 * (docs/mockups/contracts/setup.html).
 *
 * From nothing to a yes-or-no before every deploy, as one resumable page: six sections in the order
 * they depend on each other, each collapsible and each showing **Done**, **Next** or **To do**. Only
 * the next one is open when the page loads. REST decides every state from what the workspace has, so
 * nothing is set up twice on a resume and a workspace that migrated from a broker arrives with the
 * first two sections done.
 *
 * The header has no primary (DESIGN.md §5.3): each section has its own. Its two secondaries are
 * **I already have a broker** (the Migration wizard) and **Finish later** (back to Contracts;
 * progress is saved as each step is done). The aside shows progress, what the set-up gives, and
 * **The same, from anywhere** for `apiome pact setup`.
 *
 * States (mockup Notes → States): nothing detected (section 1 offers Add one by hand and a link to
 * import a project); no linked GitHub account (the secret and pull-request actions become copyable
 * snippets); a migrated workspace; not an admin (readable, every action replaced by "Ask a Contracts
 * admin"); loading; a failed read with **Try again**.
 */

import * as React from 'react';
import Link from 'next/link';
import { Button, CommandBlock, LoadingState } from '@/app/components/ui';
import PageHeader from '@/app/components/shell/PageHeader';
import { Page, PageBody } from '@/app/components/shell/pageChrome';
import { pactCommandSurfaces, unsupportedLines } from '@lib/pact-commands';
import { MIGRATE_ROUTE } from '@lib/pact-migration';
import { CONTRACTS_CRUMBS, CONTRACTS_ROUTE } from '@lib/pact-overview';
import { minutesLeft, openSection, setupCommandAction, type SetupSectionId, type SetupState } from '@lib/pact-setup';
import { ContractsTabs } from '../pactOverview/ContractsTabs';
import { describeFailure } from '../pactPacticipants/describeFailure';
import { fetchBrokerAddress } from '../pactSettings/contractSettingsApi';
import { SectionError } from '../pactVerification/PactVerificationClient';
import { EnvironmentsSection } from './EnvironmentsSection';
import { FirstPactSection } from './FirstPactSection';
import { GatesSection } from './GatesSection';
import { PacticipantsSection } from './PacticipantsSection';
import { PipelinesSection } from './PipelinesSection';
import { ProviderSection } from './ProviderSection';
import { fetchSetup } from './setupApi';
import { SetupSection } from './SetupSection';

/** What the set-up gives, for the aside. */
export const SETUP_OUTCOMES = [
  'Every change to a provider checked against its real consumers',
  'A yes or no before each deploy',
  'Owners told when something breaks',
] as const;

/**
 * The page.
 *
 * @returns The set-up.
 */
export function SetupClient() {
  const [state, setState] = React.useState<SetupState | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [open, setOpen] = React.useState<Set<SetupSectionId> | null>(null);
  const [broker, setBroker] = React.useState<string | null>(null);
  const [secret, setSecret] = React.useState<string | null>(null);

  const load = React.useCallback(async () => {
    setError(null);
    try {
      const next = await fetchSetup();
      setState(next);
      // Open the next section once; after that the reader's own toggles stand.
      setOpen((current) => current ?? new Set(openSection(next) ? [openSection(next) as SetupSectionId] : []));
    } catch (caught) {
      setError(describeFailure(caught, 'Could not load the set-up'));
    }
  }, []);

  React.useEffect(() => {
    void load();
    fetchBrokerAddress()
      .then(setBroker)
      .catch(() => setBroker(null));
  }, [load]);

  const toggle = (id: SetupSectionId) =>
    setOpen((current) => {
      const next = new Set(current ?? []);
      if (!next.delete(id)) next.add(id);
      return next;
    });

  const action = state
    ? setupCommandAction({
        fromProjects: state.candidates.some((candidate) => candidate.source === 'project'),
        environments: state.facts.environments.length ? state.facts.environments : ['production', 'staging'],
        ci: true,
      })
    : null;
  const left = state ? minutesLeft(state) : 0;
  const shared = state ? { state, onChanged: load } : null;

  return (
    <Page>
      <PageHeader
        title="Set up contracts"
        breadcrumb={[...CONTRACTS_CRUMBS, { label: 'Set-up' }]}
        description="From nothing to a yes-or-no before every deploy. Six steps; stop and resume whenever you like."
        tabs={<ContractsTabs active="overview" />}
        actions={
          <>
            <Button variant="outline" asChild>
              <Link href={MIGRATE_ROUTE} data-testid="pset-migrate">
                I already have a broker
              </Link>
            </Button>
            <Button variant="ghost" asChild>
              <Link href={CONTRACTS_ROUTE} data-testid="pset-finish-later">
                Finish later
              </Link>
            </Button>
          </>
        }
      />
      <PageBody>
        <div className="pset" data-testid="pact-setup">
          {error && !state ? (
            <SectionError title="The set-up could not be read" error={error} onRetry={() => void load()} />
          ) : !state || !shared ? (
            <LoadingState message="Reading the set-up…" minHeightClassName="min-h-[12rem]" />
          ) : (
            <div className="pcx-split">
              <div className="pcx-split__main">
                {error ? <SectionError title="The set-up could not be read again" error={error} onRetry={() => void load()} /> : null}
                {!state.can_edit ? (
                  <div className="pcx-callout" role="note" data-testid="pset-read-only">
                    You can read the set-up. Acting on it needs the Contracts admin permission (pacts:delete): ask a
                    Contracts admin.
                  </div>
                ) : null}
                {state.complete ? (
                  <div className="pcx-callout" role="status" data-testid="pset-complete">
                    All six steps are done. Ask{' '}
                    <Link className="ppx__panel-link" href="/ade/dashboard/pacts/can-i-deploy">
                      Can I deploy?
                    </Link>{' '}
                    for the first verdict.
                  </div>
                ) : null}
                {state.sections.map((section, index) => (
                  <SetupSection key={section.id} section={section} number={index + 1} open={open?.has(section.id) ?? false} onToggle={() => toggle(section.id)}>
                    {section.id === 'pacticipants' ? <PacticipantsSection {...shared} /> : null}
                    {section.id === 'environments' ? <EnvironmentsSection {...shared} /> : null}
                    {section.id === 'pipelines' ? <PipelinesSection {...shared} brokerBaseUrl={broker} secret={secret} onSecret={setSecret} /> : null}
                    {section.id === 'first-pact' ? <FirstPactSection {...shared} /> : null}
                    {section.id === 'provider' ? <ProviderSection {...shared} /> : null}
                    {section.id === 'gates' ? <GatesSection {...shared} /> : null}
                  </SetupSection>
                ))}
              </div>
              <aside className="pcx-split__aside" aria-label="Progress and commands">
                <section className="ppx__panel" aria-labelledby="pset-progress-title" data-testid="pset-progress">
                  <h2 id="pset-progress-title" className="pcx-caps">
                    Progress
                  </h2>
                  <p className="pset-progress__count">
                    <span className="pset-progress__done">{state.done}</span>/{state.total}
                  </p>
                  <progress className="pset-progress__bar" max={state.total} value={state.done} aria-label="Steps done" />
                  <p className="ppx__muted" data-testid="pset-minutes">
                    {state.complete ? 'Everything is set up.' : `About ${left} ${left === 1 ? 'minute' : 'minutes'} left`}
                  </p>
                  <p className="ppx__muted">Progress is saved. Anyone with the Contracts admin role can pick it up.</p>
                  {state.facts.migrated ? (
                    <p className="ppx__muted" data-testid="pset-migrated">
                      This workspace was copied from another broker, so its pacticipants and environments are already here.
                    </p>
                  ) : null}
                </section>
                <section className="ppx__panel" aria-labelledby="pset-outcomes-title">
                  <h2 id="pset-outcomes-title" className="pcx-caps">
                    What you get at the end
                  </h2>
                  <ul className="pset-outcomes">
                    {SETUP_OUTCOMES.map((line) => (
                      <li key={line}>{line}</li>
                    ))}
                  </ul>
                </section>
                {action ? (
                  <section className="ppx__panel" aria-labelledby="pset-command-title">
                    <h2 id="pset-command-title" className="pcx-caps">
                      The same, from anywhere
                    </h2>
                    <CommandBlock
                      surfaces={pactCommandSurfaces(action)}
                      unsupported={unsupportedLines(action)}
                      footnote="The same set-up as a command, for workspaces that are created by script."
                      data-testid="pset-command-block"
                    />
                  </section>
                ) : null}
              </aside>
            </div>
          )}
        </div>
      </PageBody>
    </Page>
  );
}

export default SetupClient;
