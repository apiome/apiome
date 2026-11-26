/**
 * The pieces of the **Environments** pages (PFX-5.7, #6951). Pure presentation — the pages own the
 * reads.
 *
 * Every table is a real `<table>` with a caption and column headers, and every interactive cell is
 * a link or a button, so the tables are read and driven from the keyboard like any other.
 */

import * as React from 'react';
import Link from 'next/link';
import { Badge } from '@/app/components/ui/Badge';
import { formatWhen, pacticipantRoute, shortVersion } from '@lib/pact-pacticipants';
import {
  buildGrid,
  effectLabel,
  environmentRoute,
  placementLabel,
  replacementSentence,
  summaryLine,
  verdictWord,
  type CurrentDeployment,
  type CurrentRelease,
  type HistoryDeployment,
  type Simulation,
  type SimulationVerdict,
  type Topology,
  type TopologyEnvironment,
} from '@lib/pact-environments';

/**
 * A version, cut to 12 characters when it is a commit SHA (the whole number in the title).
 *
 * @param props - The version number.
 * @returns The cell content.
 */
function Version({ number }: { number: string }) {
  return (
    <span className="ppx__mono" title={number}>
      {shortVersion(number)}
    </span>
  );
}

/**
 * The **Production** badge, when the environment is one.
 *
 * @param props - Whether it is.
 * @returns The badge, or nothing.
 */
export function ProductionBadge({ production }: { production: boolean }) {
  return production ? (
    <Badge variant="warn" className="ppx__inline-badge">
      Production
    </Badge>
  ) : null;
}

/**
 * The dashboard grid: each pacticipant (rows) in each environment (columns) — the versions
 * deployed there now (with the instance) and the releases it supports.
 *
 * @param props - The topology.
 * @returns The table.
 */
export function DeployedVersionsGrid({ topology }: { topology: Topology }) {
  const rows = buildGrid(topology);
  if (rows.length === 0) {
    return <p className="ppx__muted">Nothing is deployed or released to any environment yet.</p>;
  }
  return (
    <div className="ppx__table-wrap">
      <table className="ppx__table" data-testid="penv-grid">
        <caption className="sr-only">Deployed versions: pacticipants by environment</caption>
        <thead>
          <tr>
            <th scope="col">Pacticipant</th>
            {topology.environments.map((environment) => (
              <th scope="col" key={environment.uuid}>
                <Link className="ppx__link" href={environmentRoute(environment.name)}>
                  {environment.displayName}
                </Link>
                <ProductionBadge production={environment.production} />
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.pacticipant.slug} data-testid={`penv-row-${row.pacticipant.slug}`}>
              <th scope="row" className="ppx__name-cell">
                <Link className="ppx__link ppx__name" href={pacticipantRoute(row.pacticipant.slug)}>
                  {row.pacticipant.name}
                </Link>
              </th>
              {row.cells.map((cell, index) => (
                <td key={topology.environments[index].uuid}>
                  {cell.deployed.length === 0 && cell.released.length === 0 ? (
                    <span className="ppx__muted">—</span>
                  ) : (
                    <ul className="ppx__plain-list">
                      {cell.deployed.map((deployment) => (
                        <li key={`d-${deployment.version}-${deployment.applicationInstance ?? ''}`}>
                          <Version number={deployment.version} />
                          {deployment.applicationInstance ? (
                            <span className="ppx__muted"> · {deployment.applicationInstance}</span>
                          ) : null}
                        </li>
                      ))}
                      {cell.released.map((release) => (
                        <li key={`r-${release.version}`}>
                          <Version number={release.version} />
                          <span className="ppx__muted"> · released</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * The environments themselves: name, flags and how much is in each.
 *
 * @param props - The environments.
 * @returns The table.
 */
export function EnvironmentList({ environments }: { environments: TopologyEnvironment[] }) {
  return (
    <div className="ppx__table-wrap">
      <table className="ppx__table" data-testid="penv-environments">
        <caption className="sr-only">Environments, by name</caption>
        <thead>
          <tr>
            <th scope="col">Environment</th>
            <th scope="col">Name</th>
            <th scope="col">Deployed</th>
            <th scope="col">Released</th>
            <th scope="col">Contract required</th>
          </tr>
        </thead>
        <tbody>
          {environments.map((environment) => (
            <tr key={environment.uuid} data-testid={`penv-env-${environment.name}`}>
              <th scope="row" className="ppx__name-cell">
                <Link className="ppx__link ppx__name" href={environmentRoute(environment.name)}>
                  {environment.displayName}
                </Link>
                <ProductionBadge production={environment.production} />
              </th>
              <td className="ppx__mono">{environment.name}</td>
              <td>{environment.deployed.length}</td>
              <td>{environment.released.length}</td>
              <td>{environment.contractRequired ? 'Yes' : 'No'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * What is deployed to one environment now.
 *
 * @param props - The deployments.
 * @returns The table.
 */
export function CurrentDeploymentsTable({ deployments }: { deployments: CurrentDeployment[] }) {
  return (
    <div className="ppx__table-wrap">
      <table className="ppx__table" data-testid="penv-deployed">
        <caption className="sr-only">Versions deployed now</caption>
        <thead>
          <tr>
            <th scope="col">Pacticipant</th>
            <th scope="col">Version</th>
            <th scope="col">Instance</th>
            <th scope="col">Deployed</th>
          </tr>
        </thead>
        <tbody>
          {deployments.map((deployment) => (
            <tr key={`${deployment.pacticipant.slug}-${deployment.applicationInstance ?? ''}-${deployment.version}`}>
              <th scope="row">
                <Link className="ppx__link" href={pacticipantRoute(deployment.pacticipant.slug)}>
                  {deployment.pacticipant.name}
                </Link>
              </th>
              <td>
                <Version number={deployment.version} />
              </td>
              <td>{deployment.applicationInstance ?? <span className="ppx__muted">Unnamed</span>}</td>
              <td className="ppx__when">{formatWhen(deployment.deployedAt)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * The releases one environment supports now.
 *
 * @param props - The releases.
 * @returns The table.
 */
export function CurrentReleasesTable({ releases }: { releases: CurrentRelease[] }) {
  return (
    <div className="ppx__table-wrap">
      <table className="ppx__table" data-testid="penv-released">
        <caption className="sr-only">Releases supported now</caption>
        <thead>
          <tr>
            <th scope="col">Pacticipant</th>
            <th scope="col">Version</th>
            <th scope="col">Released</th>
          </tr>
        </thead>
        <tbody>
          {releases.map((release) => (
            <tr key={`${release.pacticipant.slug}-${release.version}`}>
              <th scope="row">
                <Link className="ppx__link" href={pacticipantRoute(release.pacticipant.slug)}>
                  {release.pacticipant.name}
                </Link>
              </th>
              <td>
                <Version number={release.version} />
              </td>
              <td className="ppx__when">{formatWhen(release.releasedAt)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * The deployment history: every deployment, current or replaced, newest first.
 *
 * @param props - The deployments.
 * @returns The table.
 */
export function HistoryTable({ deployments }: { deployments: HistoryDeployment[] }) {
  return (
    <div className="ppx__table-wrap">
      <table className="ppx__table" data-testid="penv-history-table">
        <caption className="sr-only">Deployments, newest first</caption>
        <thead>
          <tr>
            <th scope="col">Deployed</th>
            <th scope="col">Pacticipant</th>
            <th scope="col">Version</th>
            <th scope="col">Instance</th>
            <th scope="col">State</th>
            <th scope="col">Recorded by</th>
          </tr>
        </thead>
        <tbody>
          {deployments.map((deployment) => (
            <tr key={deployment.uuid} data-testid={`penv-history-${deployment.uuid}`}>
              <th scope="row" className="ppx__when">
                {formatWhen(deployment.deployedAt)}
              </th>
              <td>
                <Link className="ppx__link" href={pacticipantRoute(deployment.pacticipant.slug)}>
                  {deployment.pacticipant.name}
                </Link>
              </td>
              <td>
                <Version number={deployment.version} />
              </td>
              <td>{deployment.applicationInstance ?? <span className="ppx__muted">Unnamed</span>}</td>
              <td>
                {deployment.currentlyDeployed ? (
                  <Badge variant="ok">Deployed</Badge>
                ) : (
                  <span className="ppx__chips">
                    <Badge variant="neutral">Replaced</Badge>
                    <span className="ppx__when">{formatWhen(deployment.undeployedAt)}</span>
                  </span>
                )}
              </td>
              <td>{deployment.recordedBy ?? <span className="ppx__muted">—</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * A verdict as a badge, with its reasons behind a disclosure.
 *
 * @param props - The verdict.
 * @returns The cell content.
 */
function VerdictCell({ verdict }: { verdict: SimulationVerdict }) {
  const word = verdictWord(verdict.deployable);
  return (
    <>
      <Badge variant={word.variant}>{word.label}</Badge>
      {verdict.reasons.length > 0 ? (
        <details>
          <summary className="ppx__meta">Why</summary>
          <ul className="ppx__plain-list">
            {verdict.reasons.map((reason) => (
              <li key={`${reason.code}-${reason.text}`} className="ppx__statement">
                {reason.text}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </>
  );
}

/**
 * The simulator's answer: the candidate's verdict, what it replaces, the effects, each checked
 * counterpart version (before → after) and each one not checked with the reason.
 *
 * @param props - The simulation.
 * @returns The panels.
 */
export function SimulationResult({ simulation }: { simulation: Simulation }) {
  const word = verdictWord(simulation.verdict.deployable);
  const environment = simulation.environment.name;
  return (
    <>
      <section
        className="ppx__panel pmx-verdict"
        data-tone={word.variant === 'neutral' ? 'warn' : word.variant}
        aria-labelledby="psim-verdict-title"
        data-testid="psim-verdict"
      >
        <div className="ppx__panel-head">
          <h2 id="psim-verdict-title" className="ppx__title">
            Can {simulation.pacticipant.name} {simulation.version} go to {environment}?
          </h2>
          <span className="ppx__meta">Read at {formatWhen(simulation.evaluatedAt)}</span>
        </div>
        <p className="pmx-verdict__headline" role="status" data-testid="psim-headline">
          {word.label}
        </p>
        {simulation.verdict.reason ? <p className="ppx__statement">{simulation.verdict.reason}</p> : null}
        <p className="ppx__meta" data-testid="psim-replaces">
          {replacementSentence(simulation)}
        </p>
      </section>
      <section className="ppx__panel" aria-labelledby="psim-impacts-title" data-testid="psim-impacts">
        <div className="ppx__panel-head">
          <h2 id="psim-impacts-title" className="ppx__title">
            What else changes
          </h2>
          <span className="ppx__meta" data-testid="psim-summary">
            {summaryLine(simulation.summary)}
          </span>
        </div>
        {simulation.impacts.length === 0 ? (
          <p className="ppx__muted" data-testid="psim-no-impacts">
            {simulation.notChecked.length === 0
              ? `No version of a pacticipant ${simulation.pacticipant.name} has a pact with is deployed or released anywhere, so nothing else is affected.`
              : 'No counterpart version was checked; see below why.'}
          </p>
        ) : (
          <div className="ppx__table-wrap">
            <table className="ppx__table" data-testid="psim-impacts-table">
              <caption className="sr-only">
                The verdict of each counterpart version now and with the deployment
              </caption>
              <thead>
                <tr>
                  <th scope="col">Pacticipant</th>
                  <th scope="col">Version</th>
                  <th scope="col">Where</th>
                  <th scope="col">Side</th>
                  <th scope="col">Now</th>
                  <th scope="col">After</th>
                  <th scope="col">Effect</th>
                </tr>
              </thead>
              <tbody>
                {simulation.impacts.map((impact) => {
                  const effect = effectLabel(impact.effect);
                  return (
                    <tr
                      key={`${impact.pacticipant.slug}-${impact.version}-${impact.placement}`}
                      data-testid={`psim-impact-${impact.pacticipant.slug}-${impact.version}`}
                    >
                      <th scope="row">
                        <Link className="ppx__link" href={pacticipantRoute(impact.pacticipant.slug)}>
                          {impact.pacticipant.name}
                        </Link>
                      </th>
                      <td>
                        <Version number={impact.version} />
                      </td>
                      <td>{placementLabel(impact, environment)}</td>
                      <td>{impact.roles.join(', ') || '—'}</td>
                      <td>
                        <VerdictCell verdict={impact.before} />
                      </td>
                      <td>
                        <VerdictCell verdict={impact.after} />
                      </td>
                      <td>
                        <Badge variant={effect.variant} data-testid="psim-effect">
                          {effect.label}
                        </Badge>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
      {simulation.notChecked.length > 0 ? (
        <section className="ppx__panel" aria-labelledby="psim-unchecked-title" data-testid="psim-not-checked">
          <div className="ppx__panel-head">
            <h2 id="psim-unchecked-title" className="ppx__title">
              Not checked
            </h2>
            <span className="ppx__meta">
              {simulation.notChecked.length} {simulation.notChecked.length === 1 ? 'version' : 'versions'}
            </span>
          </div>
          <div className="ppx__table-wrap">
            <table className="ppx__table">
              <caption className="sr-only">Counterpart versions not checked, and why</caption>
              <thead>
                <tr>
                  <th scope="col">Pacticipant</th>
                  <th scope="col">Version</th>
                  <th scope="col">Where</th>
                  <th scope="col">Why</th>
                </tr>
              </thead>
              <tbody>
                {simulation.notChecked.map((item) => (
                  <tr key={`${item.pacticipant.slug}-${item.version}-${item.placement}`}>
                    <th scope="row">{item.pacticipant.name}</th>
                    <td>
                      <Version number={item.version} />
                    </td>
                    <td>{placementLabel(item, environment)}</td>
                    <td>{item.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}
    </>
  );
}
