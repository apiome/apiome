/**
 * The **Board** view of the Environments page — PFX-8.13 (#7310): what is running where.
 *
 * Services down, environments across (non-production first, production last), then **Released to
 * users**. Each cell is the version running there with a dot — verified with everything beside it,
 * unverified, failing — and, where the environment to its left runs a newer version, whether that
 * version **can go** next (can-i-deploy's answer, the deploy simulator's for the same question). A
 * service with nothing anywhere shows dashes and **Record its first deployment**.
 *
 * Pure presentation: the page owns the read and the dialogs. Actions are passed in, so a role that
 * may not record or end anything gets none of them.
 *
 * Authority: `docs/mockups/contracts/environments.html` (`v-board`).
 */

import * as React from 'react';
import Link from 'next/link';
import { ArrowUp, CircleMinus, OctagonX, Rocket } from 'lucide-react';
import { Badge } from '@/app/components/ui/Badge';
import { Button } from '@/app/components/ui';
import { pacticipantRoute, shortVersion } from '@lib/pact-pacticipants';
import { environmentRoute, simulatorRoute, type EnvironmentFacts, type NamedPacticipant } from '@lib/pact-environments';
import {
  DOT_WORDS,
  dotTone,
  nextLabel,
  simulatorEnvironment,
  versionNote,
  type Board,
  type BoardRelease,
  type BoardVerdict,
} from '@lib/pact-environment-board';

/** What the board lets the person do (each left out when the role may not). */
export interface BoardActions {
  /** Open Record a deployment, filled in. */
  deploy?: (environment: string, pacticipant: NamedPacticipant, version?: string) => void;
  /** Open End support for a release. */
  endSupport?: (pacticipant: NamedPacticipant, release: BoardRelease) => void;
  /** The column menu of an environment. */
  menu?: (environment: EnvironmentFacts) => React.ReactNode;
}

/**
 * A verdict's dot, named for screen readers.
 *
 * @param props - The verdict.
 * @returns The dot.
 */
export function VerdictDot({ verdict }: { verdict: BoardVerdict }) {
  const tone = dotTone(verdict);
  return <span className={`penv-dot penv-dot--${tone}`} role="img" aria-label={DOT_WORDS[tone]} />;
}

/**
 * A version with its dot.
 *
 * @param props - The version number and its verdict.
 * @returns The inline version.
 */
function DottedVersion({ number, verdict }: { number: string; verdict: BoardVerdict }) {
  return (
    <span className="penv-board__version">
      <VerdictDot verdict={verdict} />
      <span className="ppx__mono" title={number}>
        {shortVersion(number)}
      </span>
    </span>
  );
}

/** The dash of an empty cell. */
function Dash() {
  return (
    <span className="ppx__muted" aria-label="Nothing here">
      —
    </span>
  );
}

/**
 * The board.
 *
 * @param props - The board and what the person may do.
 * @returns The table, its legend and the simulator link.
 */
export function EnvironmentBoard({ board, actions = {} }: { board: Board; actions?: BoardActions }) {
  const simulated = simulatorEnvironment(board);
  return (
    <section className="ppx__panel penv-board" aria-labelledby="penv-board-title" data-testid="penv-board">
      <h2 id="penv-board-title" className="sr-only">
        What is running where
      </h2>
      <div className="ppx__table-wrap">
        <table className="ppx__table penv-board__table">
          <caption className="sr-only">Services by environment: the version running in each and whether the next can go</caption>
          <thead>
            <tr>
              <th scope="col">Service</th>
              {board.environments.map((environment) => (
                <th scope="col" key={environment.uuid} data-testid={`penv-column-${environment.name}`}>
                  <span className="penv-board__head">
                    <Link className="ppx__link" href={environmentRoute(environment.name)}>
                      {environment.displayName}
                    </Link>
                    {environment.production ? <Badge variant="danger">Production</Badge> : null}
                    {environment.contractRequired ? <Badge variant="accent">Contracts required</Badge> : null}
                    {actions.menu ? actions.menu(environment) : null}
                  </span>
                </th>
              ))}
              <th scope="col">Released to users</th>
            </tr>
          </thead>
          <tbody>
            {board.rows.map((row) => (
              <tr key={row.pacticipant.slug} data-testid={`penv-row-${row.pacticipant.slug}`}>
                <th scope="row">
                  <Link className="ppx__link penv-board__service" href={pacticipantRoute(row.pacticipant.slug)}>
                    {row.pacticipant.name}
                  </Link>
                  {row.idle ? (
                    <div className="penv-board__sub">
                      {actions.deploy && board.environments.length ? (
                        <Button
                          variant="link"
                          size="sm"
                          onClick={() => actions.deploy?.(board.environments[0].name, row.pacticipant)}
                          data-testid={`penv-first-${row.pacticipant.slug}`}
                        >
                          <Rocket aria-hidden />
                          Record its first deployment
                        </Button>
                      ) : (
                        <span className="ppx__muted">Never deployed</span>
                      )}
                    </div>
                  ) : null}
                </th>
                {row.cells.map((cell, index) => {
                  const environment = board.environments[index];
                  const label = cell.next ? nextLabel(cell.next) : null;
                  return (
                    <td key={cell.environment} className="penv-board__cell" data-testid={`penv-cell-${row.pacticipant.slug}-${environment.name}`}>
                      {cell.deployed.length ? (
                        cell.deployed.map((version) => {
                          const note = versionNote(version);
                          return (
                            <div key={version.version}>
                              <DottedVersion number={version.version} verdict={version.verdict} />
                              {note ? <div className="penv-board__sub">{note}</div> : null}
                            </div>
                          );
                        })
                      ) : (
                        <Dash />
                      )}
                      {cell.next && label ? (
                        <div className="penv-board__next" data-testid={`penv-next-${row.pacticipant.slug}-${environment.name}`}>
                          {label.canGo && actions.deploy ? (
                            <Button
                              variant="link"
                              size="sm"
                              onClick={() => actions.deploy?.(environment.name, row.pacticipant, cell.next?.version)}
                            >
                              <ArrowUp aria-hidden />
                              {label.text}
                            </Button>
                          ) : (
                            <Link
                              className={`penv-board__next-link penv-board__next-link--${label.tone}`}
                              href={simulatorRoute(
                                environment.name,
                                new URLSearchParams({ pacticipant: row.pacticipant.slug, version: cell.next.version }),
                              )}
                              title={cell.next.verdict.checked ? cell.next.verdict.reason : cell.next.verdict.notChecked}
                            >
                              {label.tone === 'danger' ? <OctagonX aria-hidden /> : label.tone === 'ok' ? <ArrowUp aria-hidden /> : null}
                              {label.text}
                            </Link>
                          )}
                        </div>
                      ) : null}
                    </td>
                  );
                })}
                <td className="penv-board__cell" data-testid={`penv-cell-${row.pacticipant.slug}-released`}>
                  {row.released.length ? (
                    <>
                      {row.released.map((release) => (
                        <div key={`${release.environment}:${release.version}`} className="penv-board__release">
                          <DottedVersion number={release.version} verdict={release.verdict} />
                          <span className="ppx__muted"> · {release.environment}</span>
                          {actions.endSupport ? (
                            <Button
                              variant="ghost"
                              size="sm"
                              aria-label={`End support for ${row.pacticipant.name} ${release.version} in ${release.environment}`}
                              title="End support"
                              onClick={() => actions.endSupport?.(row.pacticipant, release)}
                              data-testid={`penv-end-${row.pacticipant.slug}-${release.version}`}
                            >
                              <CircleMinus aria-hidden />
                            </Button>
                          ) : null}
                        </div>
                      ))}
                      {row.released.length > 1 ? (
                        <div className="penv-board__sub">{row.released.length} versions supported</div>
                      ) : null}
                    </>
                  ) : (
                    <Dash />
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="penv-board__foot">
        <ul className="penv-board__legend" aria-label="Legend">
          {(['ok', 'warn', 'danger'] as const).map((tone) => (
            <li key={tone}>
              <span className={`penv-dot penv-dot--${tone}`} aria-hidden />
              {DOT_WORDS[tone]}
            </li>
          ))}
        </ul>
        {simulated ? (
          <Link className="ppx__link penv-board__simulator" href={simulatorRoute(simulated)}>
            Open the deploy simulator
          </Link>
        ) : null}
      </div>
    </section>
  );
}
