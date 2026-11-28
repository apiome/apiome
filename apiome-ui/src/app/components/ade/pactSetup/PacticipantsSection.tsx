'use client';

/**
 * **Who talks to whom** — section 1 of **Set up contracts** (PFX-8.20, #7317).
 *
 * The pacticipants REST proposes from projects (providers) and from registered repositories no
 * project is read from (consumers), with where each was found, its role and its owner team. Ticked
 * ones are created through `POST /api/pact/pacticipants`, one at a time, so a refusal names its
 * service and the others still go through. One that already exists is listed as such and cannot be
 * created twice. With nothing detected the section offers **Add one by hand** and a link to import
 * a project.
 */

import * as React from 'react';
import Link from 'next/link';
import { Button } from '@/app/components/ui';
import { PACTICIPANTS_ROUTE, pacticipantRoute } from '@lib/pact-pacticipants';
import { candidateCreateBody, newCandidates, type SetupState } from '@lib/pact-setup';
import { createPacticipant } from '../pactPacticipants/pacticipantsApi';
import { AskAnAdmin, SectionMessage } from './SetupSection';

/** Where a project is imported from. */
export const IMPORT_ROUTE = '/ade/dashboard/import';

/** Props shared by every section body. */
export interface SectionBodyProps {
  state: SetupState;
  /** Read the set-up again after a change. */
  onChanged: () => Promise<void>;
}

/**
 * The section's body.
 *
 * @param props - The set-up and what to do after a change.
 * @returns The body.
 */
export function PacticipantsSection({ state, onChanged }: SectionBodyProps) {
  const fresh = newCandidates(state);
  const [picked, setPicked] = React.useState<Set<string>>(() => new Set(fresh.map((candidate) => candidate.slug)));
  const [busy, setBusy] = React.useState(false);
  const [message, setMessage] = React.useState<{ tone: 'ok' | 'error'; text: string } | null>(null);
  const chosen = fresh.filter((candidate) => picked.has(candidate.slug));

  const toggle = (slug: string) =>
    setPicked((current) => {
      const next = new Set(current);
      if (!next.delete(slug)) next.add(slug);
      return next;
    });

  const create = async () => {
    setBusy(true);
    setMessage(null);
    const failures: string[] = [];
    let created = 0;
    for (const candidate of chosen) {
      const answer = await createPacticipant(candidateCreateBody(candidate));
      if ('error' in answer) failures.push(`${candidate.name}: ${answer.error}`);
      else created += 1;
    }
    await onChanged();
    setBusy(false);
    setMessage(
      failures.length
        ? { tone: 'error', text: `${created} created. Not created — ${failures.join(' · ')}` }
        : { tone: 'ok', text: `${created} ${created === 1 ? 'pacticipant' : 'pacticipants'} created.` },
    );
  };

  return (
    <div className="pset-body" data-testid="pset-pacticipants-form">
      {state.candidates.length === 0 ? (
        <p className="ppx__muted" data-testid="pset-nothing-detected">
          Apiome found no projects or repositories to propose. Add a pacticipant by hand, or{' '}
          <Link className="ppx__panel-link" href={IMPORT_ROUTE}>
            import a project
          </Link>{' '}
          and come back.
        </p>
      ) : (
        <>
          <p className="ppx__muted">
            Apiome found services in your projects and registered repositories. Tick the ones that talk to each other;
            each becomes a pacticipant.
          </p>
          <div className="pset-table-wrap">
            <table className="pset-table">
              <thead>
                <tr>
                  <th scope="col">
                    <span className="sr-only">Create</span>
                  </th>
                  <th scope="col">Service</th>
                  <th scope="col">From</th>
                  <th scope="col">Role</th>
                  <th scope="col">Owner</th>
                </tr>
              </thead>
              <tbody>
                {state.candidates.map((candidate) => {
                  const inputId = `pset-candidate-${candidate.slug}`;
                  const exists = candidate.pacticipant !== null;
                  return (
                    <tr key={`${candidate.source}-${candidate.slug}`} data-testid={inputId}>
                      <td>
                        <input
                          id={inputId}
                          type="checkbox"
                          checked={exists || picked.has(candidate.slug)}
                          disabled={exists || busy || !state.can_edit}
                          onChange={() => toggle(candidate.slug)}
                          aria-label={exists ? `${candidate.name} is already a pacticipant` : `Create ${candidate.name}`}
                        />
                      </td>
                      <td>
                        <label htmlFor={inputId} className="pset-table__name">
                          {candidate.name}
                        </label>
                        {exists ? (
                          <Link className="ppx__panel-link pset-table__exists" href={pacticipantRoute(candidate.pacticipant as string)}>
                            Already a pacticipant
                          </Link>
                        ) : null}
                      </td>
                      <td className="ppx__muted">{candidate.source_label}</td>
                      <td>
                        <span className="pset-role" data-role={candidate.role}>
                          {candidate.role === 'provider' ? 'Provider' : 'Consumer'}
                        </span>
                      </td>
                      <td className="ppx__muted">{candidate.owner ?? 'No owner'}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {state.candidates_omitted > 0 ? (
            <p className="ppx__muted" data-testid="pset-candidates-omitted">
              {state.candidates_omitted} more {state.candidates_omitted === 1 ? 'project or repository is' : 'projects and repositories are'}{' '}
              not listed here; add those on Pacticipants.
            </p>
          ) : null}
        </>
      )}
      <SectionMessage message={message} testId="pset-pacticipants-message" />
      {state.can_edit ? (
        <div className="ppx__actions">
          {fresh.length > 0 ? (
            <Button onClick={() => void create()} disabled={busy || chosen.length === 0} data-testid="pset-create-pacticipants">
              {busy ? 'Creating…' : `Create ${chosen.length} ${chosen.length === 1 ? 'pacticipant' : 'pacticipants'}`}
            </Button>
          ) : null}
          <Button variant="outline" asChild>
            <Link href={PACTICIPANTS_ROUTE} data-testid="pset-add-by-hand">
              Add one by hand
            </Link>
          </Button>
        </div>
      ) : (
        <AskAnAdmin />
      )}
      {state.facts.pacticipants > 0 ? (
        <p className="ppx__muted">
          {state.facts.pacticipants} {state.facts.pacticipants === 1 ? 'pacticipant' : 'pacticipants'} so far · editable any time in{' '}
          <Link className="ppx__panel-link" href={PACTICIPANTS_ROUTE}>
            Pacticipants
          </Link>
        </p>
      ) : null}
    </div>
  );
}

export default PacticipantsSection;
