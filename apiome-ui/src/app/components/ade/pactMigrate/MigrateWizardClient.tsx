'use client';

/**
 * **Migrate from a broker** — `/ade/dashboard/pacts/migrate` (PFX-8.16, #7313), built to
 * `docs/mockups/contracts/migrate.html`: the screen for `apiome pact migrate`.
 *
 * A four-step wizard (`DESIGN.md` §8: one primary per step, a ghost **Back**, **Save & close**):
 *
 * 1. **Connect** — the broker's URL and credentials, and **Test connection**.
 * 2. **Choose** — a dry run counts what the source holds; tick what to copy, how much history, and
 *    what happens on a conflict; everything not portable is one status strip.
 * 3. **Copy** — the server runs the migration: progress, a per-kind table, failures and a live log.
 *    It survives leaving the page, can be stopped, and resumes without copying anything twice.
 * 4. **Switch over** — whether both brokers give the same can-i-deploy answers, the two variables
 *    that point a pipeline at Apiome, who has moved, keep-in-sync (PFX-8.17), and the report.
 *
 * **Past migrations** (the header's one action) lists every run and reopens one. The page's **The
 * same, from anywhere** block writes the wizard as `apiome pact migrate` and as the REST request.
 *
 * The source is only read. Its token or password stays in this component's memory and in the request
 * that starts or resumes a run; it is not stored, so reopening a run asks for it again — except while
 * keep-in-sync is on, which REST keeps it for, sealed.
 * Without `pacts:create` and `pacts:edit` the wizard is read-only and says who to ask.
 */

import * as React from 'react';
import { History, Import } from 'lucide-react';
import PageHeader from '@/app/components/shell/PageHeader';
import { Page, PageBody } from '@/app/components/shell/pageChrome';
import { Button, CommandBlock, Stepper } from '@/app/components/ui';
import { pactCommandSurfaces, unsupportedLines } from '@lib/pact-commands';
import { CONTRACTS_ROUTE } from '@lib/pact-overview';
import {
  DEFAULT_OPTIONS,
  EMPTY_SOURCE,
  MIGRATE_DESCRIPTION,
  MIGRATE_TITLE,
  WIZARD_STEPS,
  chooseProblem,
  connectProblem,
  credentialsOf,
  hasCredentials,
  migrateCommandAction,
  runIsOver,
  syncCommandAction,
  stepForRun,
  type MigrationOptions,
  type MigrationRun,
  type MigrationRunList,
  type SourceForm,
  type WizardStep,
} from '@lib/pact-migration';
import { ContractsTabs } from '../pactOverview/ContractsTabs';
import { describeFailure } from '../pactPacticipants/describeFailure';
import { ChooseStep } from './ChooseStep';
import { ConnectStep, type TestState } from './ConnectStep';
import { CopyStep } from './CopyStep';
import {
  fetchBrokerAddress,
  fetchMigrations,
  readMigration,
  resumeMigration,
  startMigration,
  testSource,
} from './migrateApi';
import { PastMigrationsDrawer } from './PastMigrationsDrawer';
import { SwitchOverStep } from './SwitchOverStep';
import { useMigrationRun } from './useMigrationRun';

/** What the wizard says when the viewer may not migrate (mockup Notes → States). */
export const ASK_AN_ADMIN = 'Ask a workspace admin to run this migration.';

/** Why **Start copying** waits when the wizard no longer holds the source's credentials. */
export const ENTER_CREDENTIALS_AGAIN =
  'Go back to Connect and enter the credentials again: they are never stored, so a reopened migration has none.';

/** The source of a form as REST stores it (no trailing slash), to tell whether a dry run is still its. */
function normalized(source: string): string {
  return source.trim().replace(/\/+$/, '');
}

/**
 * The wizard.
 *
 * @param props - `pollMs` shortens the polling in tests.
 * @returns The page.
 */
export default function MigrateWizardClient({ pollMs }: { pollMs?: number }) {
  const [list, setList] = React.useState<MigrationRunList | null>(null);
  const [listError, setListError] = React.useState<string | null>(null);
  const [step, setStep] = React.useState<WizardStep>('connect');
  const [form, setForm] = React.useState<SourceForm>(EMPTY_SOURCE);
  const [test, setTest] = React.useState<TestState>({ kind: 'idle' });
  const [options, setOptions] = React.useState<MigrationOptions>(DEFAULT_OPTIONS);
  const [dry, setDry] = React.useState<MigrationRun | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [actionError, setActionError] = React.useState<string | null>(null);
  const [drawerOpen, setDrawerOpen] = React.useState(false);
  const [dismissed, setDismissed] = React.useState<string | null>(null);
  const [broker, setBroker] = React.useState<string | null>(null);

  const refreshList = React.useCallback(async (): Promise<MigrationRunList | null> => {
    try {
      const next = await fetchMigrations();
      setList(next);
      setListError(null);
      return next;
    } catch (caught) {
      setListError(describeFailure(caught, 'Could not load the migrations'));
      return null;
    }
  }, []);

  const onFinished = React.useCallback(
    (finished: MigrationRun) => {
      if (finished.mode === 'dry-run' && finished.status === 'completed') setDry(finished);
      void refreshList();
    },
    [refreshList],
  );
  const tracked = useMigrationRun(onFinished, pollMs);
  const { run, follow } = tracked;

  /** Put a run in the wizard: its source in Connect, its choices in Choose, on the step it belongs to. */
  const adopt = React.useCallback(
    (next: MigrationRun, keepSecrets: boolean) => {
      follow(next);
      setDismissed(null);
      setActionError(null);
      setStep(stepForRun(next));
      if (next.mode === 'copy') setOptions({ ...DEFAULT_OPTIONS, ...next.options });
      setDry(next.mode === 'dry-run' && next.status === 'completed' ? next : null);
      if (!keepSecrets) {
        setForm({ ...EMPTY_SOURCE, source: next.source, auth: next.auth_kind === 'basic' ? 'basic' : 'token' });
        setTest({ kind: 'idle' });
      }
    },
    [follow],
  );

  const openRun = React.useCallback(
    async (summary: MigrationRun) => {
      setDrawerOpen(false);
      const full = await readMigration(summary.id);
      if ('failure' in full) {
        setListError(full.failure);
        return;
      }
      adopt(full, false);
    },
    [adopt],
  );

  // On arrival: the list, the broker address, and — because a copy survives leaving the page — the
  // run that is still going, if there is one.
  React.useEffect(() => {
    let live = true;
    void refreshList().then((loaded) => {
      const going = loaded?.runs.find((candidate) => candidate.status === 'running');
      if (live && going) void openRun(going);
    });
    fetchBrokerAddress()
      .then((address) => live && setBroker(address))
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [refreshList, openRun]);

  const canMigrate = list?.can_migrate === true;
  const urlProblem = connectProblem(form);

  const changeForm = (next: SourceForm) => {
    setForm(next);
    setTest({ kind: 'idle' });
    setActionError(null);
  };

  const runTest = async () => {
    setTest({ kind: 'testing' });
    try {
      setTest({ kind: 'ok', result: await testSource(form.source.trim(), credentialsOf(form)) });
    } catch (caught) {
      setTest({ kind: 'failed', error: describeFailure(caught, 'Could not reach the broker') });
    }
  };

  /** Start a run and follow it; a refusal is shown on the step that asked. */
  const launch = async (work: () => Promise<MigrationRun>, then: WizardStep) => {
    setBusy(true);
    setActionError(null);
    try {
      const started = await work();
      follow(started);
      // A run can end before its first read (an empty source): nothing will poll it, so note it now.
      if (runIsOver(started)) onFinished(started);
      setDismissed(null);
      setStep(then);
      void refreshList();
    } catch (caught) {
      setActionError(describeFailure(caught, 'Could not start the migration'));
    } finally {
      setBusy(false);
    }
  };

  const count = () => {
    setDry(null);
    return launch(() => startMigration(form.source.trim(), credentialsOf(form), 'dry-run'), 'choose');
  };

  const continueFromConnect = () => {
    // A dry run of this very source is already on Choose: going back and forth does not count again.
    if (dry && dry.source === normalized(form.source)) {
      setStep('choose');
      return undefined;
    }
    return count();
  };

  const startCopy = () => launch(() => startMigration(form.source.trim(), credentialsOf(form), 'copy', options), 'copy');
  const resume = () => (run ? launch(() => resumeMigration(run.id, credentialsOf(form)), 'copy') : undefined);

  const counting = run && run.mode === 'dry-run' && !(dry && dry.id === run.id) ? run : null;
  const copy = run && run.mode === 'copy' ? run : null;
  const copyRunning = copy !== null && !runIsOver(copy);
  const authKind = form.auth === 'basic' ? 'basic' : 'token';
  const startProblem =
    chooseProblem(options) ??
    (copyRunning ? 'A copy is already running: open the Copy step to watch or stop it.' : null) ??
    (!hasCredentials(form, form.token || form.username || form.password ? authKind : (dry?.auth_kind ?? authKind))
      ? ENTER_CREDENTIALS_AGAIN
      : null);

  const mode: MigrationRun['mode'] = step === 'connect' || (step === 'choose' && !copy) ? 'dry-run' : 'copy';
  const action =
    step === 'switch' && copy ? syncCommandAction(form, copy.id) : migrateCommandAction(form, options, step === 'choose' ? 'copy' : mode);

  return (
    <Page>
      <PageHeader
        title={MIGRATE_TITLE}
        breadcrumb={[{ label: 'Home', href: '/ade/dashboard' }, { label: 'Contracts', href: CONTRACTS_ROUTE }, { label: 'Migrate' }]}
        description={MIGRATE_DESCRIPTION}
        tabs={<ContractsTabs active="overview" />}
        actions={
          <Button variant="outline" onClick={() => setDrawerOpen(true)} data-testid="pmg-past">
            <History aria-hidden />
            Past migrations
          </Button>
        }
      />
      <PageBody>
        <div className="pmg" data-testid="pact-migrate">
          {list && !canMigrate ? (
            <div className="pcx-callout" role="note" data-testid="pmg-read-only">
              {ASK_AN_ADMIN} Migrating needs the pacts:create and pacts:edit permissions; you can still read past
              migrations.
            </div>
          ) : null}
          {listError ? (
            <p className="ppub-hint ppub-hint--danger" role="alert" data-testid="pmg-list-error">
              {listError}
            </p>
          ) : null}

          <section className="pmg-wizard" aria-labelledby="pmg-title">
            <div className="pmg-head">
              <span className="pmg-head__icon" aria-hidden>
                <Import />
              </span>
              <div>
                <h2 id="pmg-title" className="pmg-head__title">
                  Move a broker into Apiome
                </h2>
                <p className="pmg-subtle">
                  Your source is only read. Run it as often as you like — repeats copy only what changed.
                </p>
              </div>
            </div>
            <div className="pmg-steps">
              <Stepper aria-label="Migration steps" steps={WIZARD_STEPS} current={step} fill />
            </div>

            {step === 'connect' ? (
              <ConnectStep
                form={form}
                onChange={changeForm}
                test={test}
                onTest={() => void runTest()}
                problem={urlProblem}
                canMigrate={canMigrate}
                busy={busy}
                error={actionError}
                onContinue={() => void continueFromConnect()}
              />
            ) : null}
            {step === 'choose' ? (
              <ChooseStep
                dry={dry}
                counting={counting}
                options={options}
                onOptions={(next) => {
                  setOptions(next);
                  setActionError(null);
                }}
                problem={startProblem}
                canMigrate={canMigrate}
                busy={busy}
                error={actionError}
                onBack={() => setStep('connect')}
                onStart={() => void startCopy()}
                onRecount={() => void count()}
              />
            ) : null}
            {step === 'copy' && copy ? (
              <CopyStep
                run={copy}
                log={tracked.log}
                problem={tracked.problem}
                stopping={tracked.stopping}
                canMigrate={canMigrate}
                form={form}
                onForm={setForm}
                failuresDismissed={dismissed === copy.id}
                onDismissFailures={() => setDismissed(copy.id)}
                busy={busy}
                error={actionError}
                onStop={() => void tracked.stop()}
                onResume={() => void resume()}
                onBack={() => setStep('choose')}
                onContinue={() => setStep('switch')}
              />
            ) : null}
            {step === 'switch' && copy ? (
              <SwitchOverStep
                run={copy}
                log={tracked.log}
                broker={broker}
                canMigrate={canMigrate}
                form={form}
                onForm={setForm}
                onBack={() => setStep('copy')}
              />
            ) : null}
          </section>

          <section className="pmg-wizard pmg-wizard--plain" aria-label="The same, from anywhere">
            <CommandBlock
              headingLevel={2}
              surfaces={pactCommandSurfaces(action)}
              unsupported={unsupportedLines(action)}
              footnote={
                step === 'switch'
                  ? 'apiome pact migrate --follow keeps copying from your machine, every 15 minutes (--interval), until you stop it or the source has been unreachable for 24 hours; the switch above does the same on the server. Replace {tenant} with your workspace’s handle in the REST path.'
                  : 'The command keeps its progress in a state file (--state) on your machine; the wizard keeps it on the server, under Past migrations. Replace {tenant} with your workspace’s handle in the REST path.'
              }
              data-testid="pmg-command-block"
            />
          </section>
        </div>
      </PageBody>
      <PastMigrationsDrawer
        open={drawerOpen}
        onOpenChange={(open) => {
          setDrawerOpen(open);
          if (open) void refreshList();
        }}
        runs={list?.runs ?? []}
        error={drawerOpen ? listError : null}
        onOpenRun={(summary) => void openRun(summary)}
      />
    </Page>
  );
}
