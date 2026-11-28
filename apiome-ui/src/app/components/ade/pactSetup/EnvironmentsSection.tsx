'use client';

/**
 * **Where things run** — section 2 of **Set up contracts** (PFX-8.20, #7317).
 *
 * can-i-deploy needs to know where things run. The section offers production, staging and
 * development, takes any other name, and creates the ticked ones through
 * `POST /api/pact/environments`. An environment that already exists is shown ticked and cannot be
 * created twice. **Require a verified contract** applies to the production environment being created.
 */

import * as React from 'react';
import Link from 'next/link';
import { Button, Input } from '@/app/components/ui';
import { ENVIRONMENTS_ROUTE } from '@lib/pact-environments';
import { ENVIRONMENT_PRESETS, environmentCreateBody, environmentNameProblem } from '@lib/pact-setup';
import type { SectionBodyProps } from './PacticipantsSection';
import { createEnvironment } from './setupApi';
import { AskAnAdmin, SectionMessage } from './SetupSection';

/**
 * The section's body.
 *
 * @param props - The set-up and what to do after a change.
 * @returns The body.
 */
export function EnvironmentsSection({ state, onChanged }: SectionBodyProps) {
  const existing = state.facts.environments;
  const has = (name: string) => existing.some((other) => other.toLowerCase() === name.toLowerCase());
  const [extra, setExtra] = React.useState<string[]>([]);
  const [picked, setPicked] = React.useState<Set<string>>(
    () => new Set(existing.length === 0 ? ['production', 'staging'] : []),
  );
  const [another, setAnother] = React.useState('');
  const [requireContract, setRequireContract] = React.useState(true);
  const [busy, setBusy] = React.useState(false);
  const [message, setMessage] = React.useState<{ tone: 'ok' | 'error'; text: string } | null>(null);

  const offered = [
    ...ENVIRONMENT_PRESETS.map((preset) => preset.name),
    ...existing.filter((name) => !ENVIRONMENT_PRESETS.some((preset) => preset.name === name.toLowerCase())),
    ...extra,
  ];
  const chosen = offered.filter((name) => picked.has(name) && !has(name));
  const createsProduction = chosen.includes('production');

  const toggle = (name: string) =>
    setPicked((current) => {
      const next = new Set(current);
      if (!next.delete(name)) next.add(name);
      return next;
    });

  const add = () => {
    const problem = environmentNameProblem(another, offered);
    if (problem) {
      setMessage({ tone: 'error', text: problem });
      return;
    }
    const name = another.trim();
    setExtra((current) => [...current, name]);
    setPicked((current) => new Set(current).add(name));
    setAnother('');
    setMessage(null);
  };

  const create = async () => {
    setBusy(true);
    setMessage(null);
    const failures: string[] = [];
    let created = 0;
    for (const name of chosen) {
      try {
        await createEnvironment(environmentCreateBody(name, requireContract));
        created += 1;
      } catch (caught) {
        failures.push(`${name}: ${caught instanceof Error ? caught.message : 'not created'}`);
      }
    }
    await onChanged();
    setBusy(false);
    setExtra([]);
    setMessage(
      failures.length
        ? { tone: 'error', text: `${created} created. Not created — ${failures.join(' · ')}` }
        : { tone: 'ok', text: `${created} ${created === 1 ? 'environment' : 'environments'} created.` },
    );
  };

  return (
    <div className="pset-body" data-testid="pset-environments-form">
      <p className="ppx__muted">can-i-deploy needs to know where things run.</p>
      <div className="pset-checks" role="group" aria-label="Environments">
        {offered.map((name) => {
          const inputId = `pset-env-${name}`;
          const exists = has(name);
          return (
            <label key={name} htmlFor={inputId} className="pset-check" data-testid={inputId}>
              <input
                id={inputId}
                type="checkbox"
                checked={exists || picked.has(name)}
                disabled={exists || busy || !state.can_edit}
                onChange={() => toggle(name)}
              />
              <span className="pcx-mono">{name}</span>
              {name === 'production' ? <span className="pset-role" data-role="provider">Production</span> : null}
              {exists ? <span className="ppx__meta">exists</span> : null}
            </label>
          );
        })}
      </div>
      {state.can_edit ? (
        <>
          <div className="pset-inline">
            <label htmlFor="pset-env-another" className="sr-only">
              Another environment
            </label>
            <Input
              id="pset-env-another"
              value={another}
              onChange={(event) => setAnother(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  event.preventDefault();
                  add();
                }
              }}
              placeholder="another-environment"
              disabled={busy}
              data-testid="pset-env-another"
            />
            <Button variant="outline" onClick={add} disabled={busy || !another.trim()} data-testid="pset-env-add">
              Add another
            </Button>
          </div>
          {createsProduction ? (
            <label htmlFor="pset-env-require" className="pset-check" data-testid="pset-env-require-row">
              <input
                id="pset-env-require"
                type="checkbox"
                checked={requireContract}
                disabled={busy}
                onChange={(event) => setRequireContract(event.target.checked)}
              />
              Require a verified contract before anything reaches production
            </label>
          ) : null}
        </>
      ) : null}
      <SectionMessage message={message} testId="pset-environments-message" />
      {state.can_edit ? (
        <div className="ppx__actions">
          <Button onClick={() => void create()} disabled={busy || chosen.length === 0} data-testid="pset-create-environments">
            {busy ? 'Creating…' : `Create ${chosen.length} ${chosen.length === 1 ? 'environment' : 'environments'}`}
          </Button>
        </div>
      ) : (
        <AskAnAdmin />
      )}
      {existing.length > 0 ? (
        <p className="ppx__muted">
          {existing.length} {existing.length === 1 ? 'environment' : 'environments'} so far ·{' '}
          <Link className="ppx__panel-link" href={ENVIRONMENTS_ROUTE}>
            Environments
          </Link>
        </p>
      ) : null}
    </div>
  );
}

export default EnvironmentsSection;
