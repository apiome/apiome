/**
 * The pieces of the **Pacticipants** pages (PFX-5.1, #6945). Pure presentation — the pages own
 * the reads.
 *
 * Every table is a real `<table>` with a caption and column headers, and every interactive cell is
 * a link or a button, so the tables are read and driven from the keyboard like any other.
 */

import * as React from 'react';
import Link from 'next/link';
import { Badge } from '@/app/components/ui/Badge';
import {
  formatWhen,
  pacticipantRoute,
  recordDeploymentSnippet,
  safeHttpUrl,
  shortVersion,
  type Pacticipant,
  type PacticipantBranch,
  type PacticipantEnvironment,
  type PacticipantVersion,
} from '@lib/pact-pacticipants';

/**
 * A CLI command, as an empty state shows it.
 *
 * @param props - The command and what it is for (the snippet's accessible name).
 * @returns The snippet.
 */
export function CliSnippet({ command, label }: { command: string; label: string }) {
  return (
    <pre className="ppx__snippet" aria-label={label}>
      <code>{command}</code>
    </pre>
  );
}

/**
 * A pacticipant's labels as badges, or a muted dash.
 *
 * @param props - The labels.
 * @returns The badges.
 */
export function LabelBadges({ labels }: { labels: string[] }) {
  if (labels.length === 0) return <span className="ppx__muted">—</span>;
  return (
    <span className="ppx__chips">
      {labels.map((label) => (
        <Badge key={label} variant="neutral">
          {label}
        </Badge>
      ))}
    </span>
  );
}

/**
 * The repository URL as a link when it is http(s), as text otherwise, or a dash.
 *
 * @param props - The stored URL.
 * @returns The cell content.
 */
export function RepositoryLink({ url }: { url?: string | null }) {
  const safe = safeHttpUrl(url);
  if (safe) {
    return (
      <a className="ppx__link" href={safe} target="_blank" rel="noreferrer noopener">
        {url}
      </a>
    );
  }
  return url ? <span className="ppx__mono">{url}</span> : <span className="ppx__muted">—</span>;
}

/**
 * The workspace's pacticipants.
 *
 * @param props - The rows.
 * @returns The table.
 */
export function PacticipantsTable({ pacticipants }: { pacticipants: Pacticipant[] }) {
  return (
    <div className="ppx__table-wrap">
      <table className="ppx__table" data-testid="ppx-pacticipants-table">
        <caption className="sr-only">Pacticipants, by handle</caption>
        <thead>
          <tr>
            <th scope="col">Pacticipant</th>
            <th scope="col">Main branch</th>
            <th scope="col">Labels</th>
            <th scope="col">Repository</th>
            <th scope="col">Updated</th>
          </tr>
        </thead>
        <tbody>
          {pacticipants.map((pacticipant) => (
            <tr key={pacticipant.id} data-testid={`ppx-row-${pacticipant.slug}`}>
              <th scope="row" className="ppx__name-cell">
                <Link className="ppx__link ppx__name" href={pacticipantRoute(pacticipant.slug)}>
                  {pacticipant.name}
                </Link>
                <span className="ppx__mono ppx__muted">{pacticipant.slug}</span>
              </th>
              <td>
                {pacticipant.main_branch ? (
                  <span className="ppx__mono">{pacticipant.main_branch}</span>
                ) : (
                  <span className="ppx__muted">—</span>
                )}
              </td>
              <td>
                <LabelBadges labels={pacticipant.labels} />
              </td>
              <td>
                <RepositoryLink url={pacticipant.repository_url} />
              </td>
              <td className="ppx__when">{formatWhen(pacticipant.updated_at ?? pacticipant.created_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * The facts at the top of a pacticipant's page.
 *
 * @param props - The pacticipant.
 * @returns The facts.
 */
export function PacticipantFacts({ pacticipant }: { pacticipant: Pacticipant }) {
  const bindings = [pacticipant.project_id ? 'Project' : null, pacticipant.consumer_id ? 'Consumer' : null].filter(
    Boolean,
  );
  return (
    <dl className="ppx__facts" data-testid="ppx-facts">
      <div className="ppx__fact">
        <dt>Handle</dt>
        <dd className="ppx__mono">{pacticipant.slug}</dd>
      </div>
      <div className="ppx__fact">
        <dt>Main branch</dt>
        <dd>
          {pacticipant.main_branch ? (
            <span className="ppx__mono">{pacticipant.main_branch}</span>
          ) : (
            <span className="ppx__muted">Not set</span>
          )}
        </dd>
      </div>
      <div className="ppx__fact">
        <dt>Repository</dt>
        <dd>
          <RepositoryLink url={pacticipant.repository_url} />
        </dd>
      </div>
      <div className="ppx__fact">
        <dt>Labels</dt>
        <dd>
          <LabelBadges labels={pacticipant.labels} />
        </dd>
      </div>
      <div className="ppx__fact">
        <dt>Bound to</dt>
        <dd>{bindings.length > 0 ? bindings.join(' and ') : <span className="ppx__muted">Nothing</span>}</dd>
      </div>
      <div className="ppx__fact">
        <dt>Registered</dt>
        <dd className="ppx__when">{formatWhen(pacticipant.created_at)}</dd>
      </div>
    </dl>
  );
}

/**
 * A pacticipant's branches, each with its head version. Choosing a branch narrows the versions.
 *
 * @param props - The branches and what to do when one is chosen.
 * @returns The table.
 */
export function BranchesTable({
  branches,
  onPickBranch,
}: {
  branches: PacticipantBranch[];
  onPickBranch: (branch: string) => void;
}) {
  return (
    <div className="ppx__table-wrap">
      <table className="ppx__table" data-testid="ppx-branches-table">
        <caption className="sr-only">Branches, by name</caption>
        <thead>
          <tr>
            <th scope="col">Branch</th>
            <th scope="col">Head version</th>
            <th scope="col">Updated</th>
          </tr>
        </thead>
        <tbody>
          {branches.map((branch) => (
            <tr key={branch.id}>
              <th scope="row">
                <button
                  type="button"
                  className="ppx__chip-button ppx__mono"
                  onClick={() => onPickBranch(branch.name)}
                  aria-label={`Show the versions on ${branch.name}`}
                >
                  {branch.name}
                </button>
                {branch.is_main ? (
                  <Badge variant="accent" className="ppx__inline-badge">
                    Main
                  </Badge>
                ) : null}
              </th>
              <td className="ppx__mono" title={branch.head_version}>
                {shortVersion(branch.head_version)}
              </td>
              <td className="ppx__when">{formatWhen(branch.updated_at ?? branch.created_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * Every environment, with the versions of the pacticipant deployed and released there.
 *
 * @param props - The environments and the pacticipant's display name (for the empty-state command).
 * @returns The table, or what to run when the workspace has no environment.
 */
export function EnvironmentsTable({
  environments,
  pacticipantName,
}: {
  environments: PacticipantEnvironment[];
  pacticipantName: string;
}) {
  if (environments.length === 0) {
    return (
      <div className="ppx__empty-note" data-testid="ppx-environments-empty">
        <p className="ppx__statement">
          This workspace has no environments yet. Create one, then record where each version runs:
        </p>
        <CliSnippet
          label="Record a deployment"
          command={`apiome pact create-environment --name production --production\n${recordDeploymentSnippet(pacticipantName)}`}
        />
      </div>
    );
  }
  return (
    <div className="ppx__table-wrap">
      <table className="ppx__table" data-testid="ppx-environments-table">
        <caption className="sr-only">Environments, by name</caption>
        <thead>
          <tr>
            <th scope="col">Environment</th>
            <th scope="col">Deployed now</th>
            <th scope="col">Released and supported</th>
          </tr>
        </thead>
        <tbody>
          {environments.map((environment) => (
            <tr key={environment.uuid} data-testid={`ppx-env-${environment.name}`}>
              <th scope="row">
                <span className="ppx__name">{environment.displayName}</span>
                {environment.production ? (
                  <Badge variant="warn" className="ppx__inline-badge">
                    Production
                  </Badge>
                ) : null}
              </th>
              {environment.error ? (
                <td colSpan={2}>
                  <span className="ppx__error" role="status">
                    Could not be read. {environment.error}
                  </span>
                </td>
              ) : (
                <>
                  <td>
                    {environment.deployed.length === 0 ? (
                      <span className="ppx__muted">Nothing deployed</span>
                    ) : (
                      <ul className="ppx__plain-list">
                        {environment.deployed.map((deployment) => (
                          <li key={`${deployment.version}-${deployment.applicationInstance ?? ''}`}>
                            <span className="ppx__mono" title={deployment.version}>
                              {shortVersion(deployment.version)}
                            </span>
                            {deployment.applicationInstance ? (
                              <span className="ppx__muted"> · {deployment.applicationInstance}</span>
                            ) : null}
                            <span className="ppx__muted"> · {formatWhen(deployment.deployedAt)}</span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </td>
                  <td>
                    {environment.released.length === 0 ? (
                      <span className="ppx__muted">No release</span>
                    ) : (
                      <ul className="ppx__plain-list">
                        {environment.released.map((release) => (
                          <li key={release.version}>
                            <span className="ppx__mono" title={release.version}>
                              {shortVersion(release.version)}
                            </span>
                            <span className="ppx__muted"> · {formatWhen(release.releasedAt)}</span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </td>
                </>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * A pacticipant's versions, latest recorded first, with their branches and tags. Choosing a
 * branch or a tag narrows the list to it.
 *
 * @param props - The versions and what to do when a branch or a tag is chosen.
 * @returns The table.
 */
export function VersionsTable({
  versions,
  onPickBranch,
  onPickTag,
}: {
  versions: PacticipantVersion[];
  onPickBranch: (branch: string) => void;
  onPickTag: (tag: string) => void;
}) {
  return (
    <div className="ppx__table-wrap">
      <table className="ppx__table" data-testid="ppx-versions-table">
        <caption className="sr-only">Versions, latest recorded first</caption>
        <thead>
          <tr>
            <th scope="col">Version</th>
            <th scope="col">Branches</th>
            <th scope="col">Tags</th>
            <th scope="col">Recorded</th>
            <th scope="col">Build</th>
          </tr>
        </thead>
        <tbody>
          {versions.map((version) => {
            const build = safeHttpUrl(version.build_url);
            return (
              <tr key={version.id}>
                <th scope="row" className="ppx__mono" title={version.number}>
                  {shortVersion(version.number)}
                </th>
                <td>
                  {version.branches.length === 0 ? (
                    <span className="ppx__muted">—</span>
                  ) : (
                    <span className="ppx__chips">
                      {version.branches.map((branch) => (
                        <button
                          key={branch}
                          type="button"
                          className="ppx__chip-button ppx__mono"
                          onClick={() => onPickBranch(branch)}
                          aria-label={`Show the versions on ${branch}`}
                        >
                          {branch}
                        </button>
                      ))}
                    </span>
                  )}
                </td>
                <td>
                  {version.tags.length === 0 ? (
                    <span className="ppx__muted">—</span>
                  ) : (
                    <span className="ppx__chips">
                      {version.tags.map((tag) => (
                        <button
                          key={tag}
                          type="button"
                          className="ppx__chip-button"
                          onClick={() => onPickTag(tag)}
                          aria-label={`Show the versions tagged ${tag}`}
                        >
                          {tag}
                        </button>
                      ))}
                    </span>
                  )}
                </td>
                <td className="ppx__when">
                  {formatWhen(version.created_at)}
                  {version.actor_label ? <span className="ppx__muted"> · {version.actor_label}</span> : null}
                </td>
                <td>
                  {build ? (
                    <a className="ppx__link" href={build} target="_blank" rel="noreferrer noopener">
                      Build
                    </a>
                  ) : (
                    <span className="ppx__muted">—</span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
