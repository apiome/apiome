'use client';

/**
 * **Gate deploys and tell people** — section 6 of **Set up contracts** (PFX-8.20, #7317).
 *
 * Make the verdict count where decisions are made.
 *
 * * **Pull requests** — for each ticked GitHub repository, a pull request adding a workflow that asks
 *   can-i-deploy and records the deployment, for the pacticipant and environment chosen here. Each
 *   repository answers opened, already open, or skipped with the reason. Without a linked GitHub
 *   account — or for a skipped repository — **Show the workflow** gives the file to add by hand.
 * * **Commit statuses** and **notifications** — already on by default / set on their own pages, which
 *   the section links to.
 *
 * **Finish set-up** marks the section done.
 */

import * as React from 'react';
import Link from 'next/link';
import { Button, Input } from '@/app/components/ui';
import { CI_TAB_ROUTE } from '@lib/pact-contract-settings';
import { WEBHOOKS_ROUTE } from '@lib/pact-webhooks';
import type { PullRequestResult, PullRequestsBody } from '@lib/pact-setup';
import type { SectionBodyProps } from './PacticipantsSection';
import { openPullRequests, saveSetup } from './setupApi';
import { AskAnAdmin, CopyBlock, SectionMessage } from './SetupSection';

/** What each result reads as. */
const STATUS_TEXT: Record<PullRequestResult['status'], string> = {
  opened: 'Pull request opened',
  exists: 'Pull request already open',
  preview: 'The workflow to add',
  skipped: 'No pull request',
};

/**
 * The section's body.
 *
 * @param props - The set-up and what to do after a change.
 * @returns The body.
 */
export function GatesSection({ state, onChanged }: SectionBodyProps) {
  const repositories = state.github.repositories;
  const environments = state.facts.environments;
  const [names, setNames] = React.useState<Record<string, string>>(() =>
    Object.fromEntries(repositories.map((repository) => [repository.id, repository.pacticipant_name ?? ''])),
  );
  const [picked, setPicked] = React.useState<Set<string>>(
    () => new Set(repositories.filter((repository) => repository.pacticipant_name && !repository.pull_request_url).map((repository) => repository.id)),
  );
  const [environment, setEnvironment] = React.useState(environments.includes('production') ? 'production' : (environments[0] ?? 'production'));
  const [canIDeploy, setCanIDeploy] = React.useState(true);
  const [recordDeployment, setRecordDeployment] = React.useState(true);
  const [byHand, setByHand] = React.useState('');
  const [busy, setBusy] = React.useState<'open' | 'preview' | 'mark' | null>(null);
  const [message, setMessage] = React.useState<{ tone: 'ok' | 'error'; text: string } | null>(null);
  const [results, setResults] = React.useState<PullRequestResult[] | null>(null);
  const marked = state.saved.marked.includes('gates');

  const chosen = repositories.filter((repository) => picked.has(repository.id));
  const unnamed = chosen.filter((repository) => !(names[repository.id] ?? '').trim());
  const writable = chosen.filter((repository) => repository.linked);
  const stepsChosen = canIDeploy || recordDeployment;

  const body = (preview: boolean, rows: typeof chosen): PullRequestsBody => ({
    repositories: rows.map((repository) => ({ repository_id: repository.id, pacticipant: (names[repository.id] ?? '').trim() })),
    environment,
    can_i_deploy: canIDeploy,
    record_deployment: recordDeployment,
    preview,
  });

  const send = async (preview: boolean) => {
    const rows = preview ? chosen : writable;
    setBusy(preview ? 'preview' : 'open');
    setMessage(null);
    setResults(null);
    try {
      setResults(await openPullRequests(body(preview, rows)));
      if (!preview) await onChanged();
    } catch (caught) {
      setMessage({ tone: 'error', text: caught instanceof Error ? caught.message : 'Could not open the pull requests.' });
    } finally {
      setBusy(null);
    }
  };

  const mark = async () => {
    setBusy('mark');
    setMessage(null);
    try {
      await saveSetup({ mark: { gates: !marked } });
      await onChanged();
    } catch (caught) {
      setMessage({ tone: 'error', text: caught instanceof Error ? caught.message : 'Could not save.' });
    } finally {
      setBusy(null);
    }
  };

  const toggle = (id: string) =>
    setPicked((current) => {
      const next = new Set(current);
      if (!next.delete(id)) next.add(id);
      return next;
    });

  return (
    <div className="pset-body" data-testid="pset-gates-form">
      <p className="ppx__muted">Make the verdict count where decisions are made.</p>
      <div className="pset-checks" role="group" aria-label="What the pipeline does">
        <label htmlFor="pset-gate-cid" className="pset-check">
          <input id="pset-gate-cid" type="checkbox" checked={canIDeploy} disabled={busy !== null || !state.can_edit} onChange={(event) => setCanIDeploy(event.target.checked)} data-testid="pset-gate-cid" />
          Add a can-i-deploy step to each pipeline
        </label>
        <label htmlFor="pset-gate-record" className="pset-check">
          <input id="pset-gate-record" type="checkbox" checked={recordDeployment} disabled={busy !== null || !state.can_edit} onChange={(event) => setRecordDeployment(event.target.checked)} data-testid="pset-gate-record" />
          Record deployments on merge
        </label>
      </div>
      <div className="pset-inline">
        <label htmlFor="pset-gate-environment" className="pset-inline__label">
          Environment
        </label>
        {environments.length > 0 ? (
          <select id="pset-gate-environment" className="pset-select" value={environment} disabled={busy !== null} onChange={(event) => setEnvironment(event.target.value)} data-testid="pset-gate-environment">
            {environments.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        ) : (
          <Input id="pset-gate-environment" value={environment} disabled={busy !== null} onChange={(event) => setEnvironment(event.target.value)} data-testid="pset-gate-environment" />
        )}
      </div>

      {repositories.length > 0 ? (
        <div className="pset-table-wrap">
          <table className="pset-table">
            <thead>
              <tr>
                <th scope="col">
                  <span className="sr-only">Include</span>
                </th>
                <th scope="col">Repository</th>
                <th scope="col">Pacticipant its pipeline asks about</th>
                <th scope="col">Pull request</th>
              </tr>
            </thead>
            <tbody>
              {repositories.map((repository) => {
                const inputId = `pset-gate-repo-${repository.id}`;
                return (
                  <tr key={repository.id} data-testid={inputId}>
                    <td>
                      <input id={inputId} type="checkbox" checked={picked.has(repository.id)} disabled={busy !== null} onChange={() => toggle(repository.id)} aria-label={`Include ${repository.full_name}`} />
                    </td>
                    <td>
                      <label htmlFor={inputId} className="pcx-mono">
                        {repository.full_name}
                      </label>
                    </td>
                    <td>
                      <Input
                        value={names[repository.id] ?? ''}
                        onChange={(event) => setNames((current) => ({ ...current, [repository.id]: event.target.value }))}
                        placeholder="Pacticipant name"
                        aria-label={`Pacticipant for ${repository.full_name}`}
                        disabled={busy !== null}
                        data-testid={`${inputId}-name`}
                      />
                    </td>
                    <td className="ppx__muted">
                      {repository.pull_request_url ? (
                        <a className="ppx__panel-link" href={repository.pull_request_url} target="_blank" rel="noreferrer">
                          Opened
                        </a>
                      ) : repository.linked ? (
                        'Not opened'
                      ) : (
                        'By hand: no linked account'
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="pset-inline" data-testid="pset-gate-by-hand">
          <label htmlFor="pset-gate-pacticipant" className="pset-inline__label">
            Pacticipant
          </label>
          <Input id="pset-gate-pacticipant" value={byHand} onChange={(event) => setByHand(event.target.value)} placeholder="Pacticipant name" disabled={busy !== null} data-testid="pset-gate-pacticipant" />
        </div>
      )}
      {!state.github.linked ? (
        <p className="ppx__muted" data-testid="pset-gates-degraded">
          {state.github.reason ?? 'Apiome cannot open a pull request from this workspace.'}
        </p>
      ) : null}
      {unnamed.length > 0 ? (
        <p className="ppx__error" role="alert" data-testid="pset-gate-unnamed">
          Give the pacticipant for {unnamed.map((repository) => repository.full_name).join(', ')}, or untick it.
        </p>
      ) : null}
      {!stepsChosen ? (
        <p className="ppx__error" role="alert">
          Tick at least one of can-i-deploy and record deployments.
        </p>
      ) : null}

      <div className="ppx__actions">
        {state.can_edit && state.github.linked ? (
          <Button onClick={() => void send(false)} disabled={busy !== null || writable.length === 0 || unnamed.length > 0 || !stepsChosen || !environment.trim()} data-testid="pset-open-pull-requests">
            {busy === 'open' ? 'Opening…' : `Open ${writable.length} pull ${writable.length === 1 ? 'request' : 'requests'}`}
          </Button>
        ) : null}
        {repositories.length > 0 ? (
          <Button variant="outline" onClick={() => void send(true)} disabled={busy !== null || chosen.length === 0 || unnamed.length > 0 || !stepsChosen || !environment.trim()} data-testid="pset-show-workflow">
            {busy === 'preview' ? 'Reading…' : 'Show the workflow'}
          </Button>
        ) : null}
        <Button variant="link" asChild>
          <Link href={CI_TAB_ROUTE} data-testid="pset-gates-settings">
            All CI and notification settings
          </Link>
        </Button>
      </div>
      {repositories.length === 0 ? (
        <p className="ppx__muted" data-testid="pset-gates-recipes">
          With no GitHub repository registered, copy a working pipeline for GitHub Actions, GitLab CI, Jenkins or Azure
          Pipelines from{' '}
          <Link className="ppx__panel-link" href={CI_TAB_ROUTE}>
            Settings → CI and commit statuses
          </Link>
          {byHand.trim() ? ` and set its pacticipant to ${byHand.trim()}.` : '.'}
        </p>
      ) : null}

      {results ? (
        <ul className="pset-results" data-testid="pset-pull-request-results">
          {results.map((result) => (
            <li key={result.repository_id} data-status={result.status}>
              <p>
                <span className="pcx-mono">{result.full_name ?? result.repository_id}</span> — {STATUS_TEXT[result.status]}
                {result.url ? (
                  <>
                    {': '}
                    <a className="ppx__panel-link" href={result.url} target="_blank" rel="noreferrer">
                      {result.number ? `#${result.number}` : result.url}
                    </a>
                  </>
                ) : null}
                {result.reason ? `. ${result.reason}` : ''}
              </p>
              {result.status === 'preview' || result.status === 'skipped' ? (
                <>
                  <p className="ppx__muted">
                    Save it as <span className="pcx-mono">{result.path}</span>.
                  </p>
                  <CopyBlock text={result.content} label={`Workflow for ${result.full_name ?? 'the repository'}`} testId={`pset-workflow-${result.repository_id}`} />
                </>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}

      <h3 className="pcx-caps">Commit statuses and notifications</h3>
      <p className="ppx__muted">
        The verdict is shown as a commit status on pull requests by default (
        <Link className="ppx__panel-link" href={CI_TAB_ROUTE}>
          Settings → CI and commit statuses
        </Link>
        ). To tell a channel or an owner when a pact fails or goes stale, add a webhook on{' '}
        <Link className="ppx__panel-link" href={WEBHOOKS_ROUTE}>
          Webhooks
        </Link>
        {state.facts.webhooks > 0 ? ` — this workspace has ${state.facts.webhooks >= 100 ? '100 or more' : state.facts.webhooks}.` : '.'}
      </p>

      <SectionMessage message={message} testId="pset-gates-message" />
      {state.can_edit ? (
        <div className="ppx__actions">
          <Button variant={marked ? 'ghost' : 'outline'} onClick={() => void mark()} disabled={busy !== null} data-testid="pset-finish">
            {marked ? 'Reopen this section' : 'Finish set-up'}
          </Button>
        </div>
      ) : (
        <AskAnAdmin />
      )}
    </div>
  );
}

export default GatesSection;
