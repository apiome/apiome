'use client';

/**
 * Step 4 of the **Migration wizard** — **Switch over** (PFX-8.16 #7313, PFX-8.17 #7314), built to
 * `docs/mockups/contracts/migrate.html`.
 *
 * * **The agreement check** — REST asked both brokers the same can-i-deploy questions after the copy:
 *   “Copied. Apiome and acme.pactflow.io give the same answers.”, or “38 of 40 agree.” with each
 *   difference and why (a result not copied, a selector the old broker does not support).
 * * **1 · Point your pipelines here** — the two variables a pipeline changes; the official Pact CLI
 *   and libraries keep working.
 * * **2 · Watch who has moved** — where each pacticipant last published: Apiome or the old broker.
 * * **Keep copying until everyone has moved** — keep-in-sync: every 15 minutes what is new at the old
 *   broker is brought over. Switching it on sends the source's credentials once more (REST keeps them
 *   sealed while it is on); a wizard reopened from **Past migrations** asks for them first. A sync
 *   that stopped itself (the old broker unreachable for 24 hours) says so here.
 *
 * **Download report** saves the run — its counts, failures, what is not portable, the agreement
 * check, who has moved and the log — as JSON.
 */

import * as React from 'react';
import Link from 'next/link';
import { AlertTriangle, Check, Download, Info, KeyRound } from 'lucide-react';
import { Badge, Button, Switch } from '@/app/components/ui';
import { CONTRACTS_ROUTE } from '@lib/pact-overview';
import {
  agreementDifferences,
  agreementSummary,
  credentialsOf,
  failedCount,
  formatCount,
  hasCredentials,
  movedRows,
  reportDocument,
  reportFileName,
  syncNote,
  syncSentence,
  type MigrationLogLine,
  type MigrationRun,
  type MigrationSync,
  type SourceForm,
} from '@lib/pact-migration';
import { downloadBlob } from '../dashboard/export/exportDownload';
import { describeFailure } from '../pactPacticipants/describeFailure';
import { API_KEYS_ROUTE } from '../pactSettings/CiTab';
import { CredentialFields } from './ConnectStep';
import { fetchSync, switchSync } from './migrateApi';

/** What the switch says to someone who may not migrate (mockup Notes → States). */
export const SYNC_ASK_AN_ADMIN = 'Ask a workspace admin to keep this migration in sync.';

/** Props for {@link SwitchOverStep}. */
export interface SwitchOverStepProps {
  run: MigrationRun;
  log: MigrationLogLine[];
  /** The workspace's `PACT_BROKER_BASE_URL`, once read. */
  broker: string | null;
  /** Whether the viewer may migrate (and so switch keep-in-sync). */
  canMigrate: boolean;
  /** The **Connect** step: the credentials keep-in-sync is switched on with. */
  form: SourceForm;
  onForm: (form: SourceForm) => void;
  onBack: () => void;
  /** The current time (fixtures pin it). */
  now?: Date;
}

/** The icon of the agreement headline, by tone. */
function HeadlineIcon({ tone }: { tone: 'ok' | 'warn' | 'info' | 'danger' }) {
  const Icon = tone === 'ok' ? Check : tone === 'info' ? Info : AlertTriangle;
  return (
    <span className={`pmg-done__icon pmg-done__icon--${tone}`} aria-hidden>
      <Icon />
    </span>
  );
}

/**
 * The **Switch over** step.
 *
 * @param props - See {@link SwitchOverStepProps}.
 * @returns The step's body and footer.
 */
export function SwitchOverStep({ run, log, broker, canMigrate, form, onForm, onBack, now }: SwitchOverStepProps) {
  const [sync, setSync] = React.useState<MigrationSync | null>(null);
  const [syncError, setSyncError] = React.useState<string | null>(null);
  const [switching, setSwitching] = React.useState(false);
  const [askCredentials, setAskCredentials] = React.useState(false);

  React.useEffect(() => {
    let live = true;
    fetchSync(run.id)
      .then((read) => live && setSync(read))
      .catch((caught) => live && setSyncError(describeFailure(caught, 'Could not read keep-in-sync')));
    return () => {
      live = false;
    };
  }, [run.id]);

  const failed = failedCount(run);
  const summary = agreementSummary(run);
  const differences = agreementDifferences(run);
  const moved = movedRows(run, now);
  const note = syncNote(sync, run.host, now);
  const signedIn = hasCredentials(form, run.auth_kind);

  const download = () =>
    downloadBlob(
      new Blob([JSON.stringify(reportDocument(run, log), null, 2)], { type: 'application/json' }),
      reportFileName(run),
    );

  const flip = async (on: boolean) => {
    setSyncError(null);
    if (on && !signedIn) {
      setAskCredentials(true);
      return;
    }
    setSwitching(true);
    try {
      setSync(await switchSync(run.id, on, on ? credentialsOf(form) : {}));
      setAskCredentials(false);
    } catch (caught) {
      setSyncError(describeFailure(caught, on ? 'Could not switch keep-in-sync on' : 'Could not switch keep-in-sync off'));
    } finally {
      setSwitching(false);
    }
  };

  const syncDisabled = !canMigrate || switching || !sync || (!sync.enabled && !sync.available);

  return (
    <>
      <div className="pmg-body" data-testid="pmg-switch">
        <div className="pmg-done" data-testid="pmg-agreement" data-tone={summary.tone}>
          <HeadlineIcon tone={summary.tone} />
          <div>
            <div className="pmg-strong" data-testid="pmg-headline">
              {summary.title}
            </div>
            <div className="pmg-subtle" data-testid="pmg-agreement-detail">
              {summary.detail}
            </div>
            {failed > 0 ? (
              <div className="pmg-subtle">
                {formatCount(failed)} {failed === 1 ? 'record was' : 'records were'} not copied; the report lists each
                with its reason.
              </div>
            ) : null}
          </div>
        </div>

        {differences.rows.length ? (
          <section className="pmg-card" aria-labelledby="pmg-differences-title">
            <h3 id="pmg-differences-title" className="pmg-heading">
              Where the answers differ
            </h3>
            <table className="pvl-table" data-testid="pmg-differences">
              <thead>
                <tr>
                  <th scope="col">Can I deploy…</th>
                  <th scope="col">{run.host}</th>
                  <th scope="col">Apiome</th>
                  <th scope="col">Why</th>
                </tr>
              </thead>
              <tbody>
                {differences.rows.map((row) => (
                  <tr key={row.question}>
                    <td className="pmg-mono">{row.question}</td>
                    <td>{row.source}</td>
                    <td>{row.apiome}</td>
                    <td>{row.cause}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {differences.more > 0 ? (
              <p className="pmg-subtle">
                {formatCount(differences.more)} more differ and are counted above; the report has the first{' '}
                {formatCount(differences.rows.length)}.
              </p>
            ) : null}
          </section>
        ) : null}

        <div className="pmg-columns">
          <section className="pmg-card" aria-labelledby="pmg-point-title">
            <h3 id="pmg-point-title" className="pmg-heading">
              1 · Point your pipelines here
            </h3>
            <pre className="pcx-code" tabIndex={0} aria-label="The two variables" data-testid="pmg-variables">
              {`PACT_BROKER_BASE_URL=${broker ?? 'https://<api>/v1/tenants/<workspace>/pact-broker'}\nPACT_BROKER_TOKEN=<an Apiome API key>`}
            </pre>
            <p className="pmg-subtle">Nothing else changes: the official Pact CLI and libraries keep working.</p>
            <div>
              <Button variant="outline" size="sm" asChild>
                <Link href={API_KEYS_ROUTE}>
                  <KeyRound aria-hidden />
                  Create a key with Pact scopes
                </Link>
              </Button>
            </div>
          </section>

          <section className="pmg-card" aria-labelledby="pmg-moved-title">
            <h3 id="pmg-moved-title" className="pmg-heading">
              2 · Watch who has moved
            </h3>
            {moved.error ? (
              <p className="ppub-hint" role="status" data-testid="pmg-moved-error">
                {moved.error}
              </p>
            ) : null}
            {moved.rows.length ? (
              <>
                <p className="pmg-subtle" data-testid="pmg-moved-summary">
                  {moved.summary}
                </p>
                <table className="pvl-table" data-testid="pmg-moved">
                  <thead>
                    <tr>
                      <th scope="col">Pacticipant</th>
                      <th scope="col">Last published to</th>
                    </tr>
                  </thead>
                  <tbody>
                    {moved.rows.map((row) => (
                      <tr key={row.name}>
                        <td>{row.name}</td>
                        <td>
                          <span className="pmg-moved">
                            <Badge status={row.status} dot>
                              {row.label}
                            </Badge>
                            {row.when ? <span className="pmg-subtle">{row.when}</span> : null}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {moved.more > 0 ? (
                  <p className="pmg-subtle">{formatCount(moved.more)} more are not listed; the report counts them.</p>
                ) : null}
              </>
            ) : !moved.error ? (
              <p className="pmg-subtle" data-testid="pmg-moved-empty">
                {moved.summary || 'Who has moved is worked out after a copy.'}
              </p>
            ) : null}
          </section>
        </div>

        <div className="pcx-switch-row" data-testid="pmg-sync">
          <div>
            <div className="pcx-switch-row__title" id="pmg-sync-label">
              Keep copying until everyone has moved
            </div>
            <div className="pmg-subtle" id="pmg-sync-hint">
              {canMigrate ? syncSentence(sync) : SYNC_ASK_AN_ADMIN}
            </div>
          </div>
          <Switch
            checked={sync?.enabled === true}
            onCheckedChange={(on) => void flip(on)}
            disabled={syncDisabled}
            aria-labelledby="pmg-sync-label"
            aria-describedby="pmg-sync-hint"
            data-testid="pmg-sync-switch"
          />
        </div>
        {note ? (
          <p
            className={note.tone === 'danger' ? 'ppub-hint ppub-hint--danger' : 'ppub-hint'}
            role={note.tone === 'info' ? 'status' : 'alert'}
            data-testid="pmg-sync-note"
          >
            {note.text}
          </p>
        ) : null}
        {askCredentials ? (
          <section className="pmg-card" aria-labelledby="pmg-sync-credentials-title" data-testid="pmg-sync-credentials">
            <h3 id="pmg-sync-credentials-title" className="pmg-heading">
              Sign in to {run.host} to keep copying
            </h3>
            <p className="pmg-subtle">The credentials were not kept after the copy; keeping on copying needs them.</p>
            <CredentialFields form={form} onChange={onForm} idPrefix="pmg-sync" kept />
            <div>
              <Button size="sm" onClick={() => void flip(true)} disabled={switching || !signedIn} data-testid="pmg-sync-on">
                {switching ? 'Switching on…' : 'Keep copying'}
              </Button>
            </div>
          </section>
        ) : null}
        {syncError ? (
          <p className="ppub-hint ppub-hint--danger" role="alert" data-testid="pmg-sync-error">
            {syncError}
          </p>
        ) : null}
      </div>
      <div className="pmg-footer">
        <Button variant="outline" className="pmg-footer__start" onClick={download} data-testid="pmg-download">
          <Download aria-hidden />
          Download report
        </Button>
        <Button variant="ghost" onClick={onBack} data-testid="pmg-back">
          Back
        </Button>
        <Button asChild>
          <Link href={CONTRACTS_ROUTE} data-testid="pmg-finish">
            Finish
          </Link>
        </Button>
      </div>
    </>
  );
}

export default SwitchOverStep;
