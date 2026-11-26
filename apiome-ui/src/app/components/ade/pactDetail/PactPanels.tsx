/**
 * The pieces of the **Pact** page and of a pacticipant's **Pacts** section (PFX-5.2, #6946).
 * Pure presentation — the pages own the reads.
 *
 * Tables are real `<table>`s with captions and column headers; each interaction is a native
 * `<details>` disclosure, so the page is read and driven from the keyboard like any other.
 */

import * as React from 'react';
import Link from 'next/link';
import { Badge } from '@/app/components/ui/Badge';
import { formatWhen, pacticipantRoute, shortVersion } from '@lib/pact-pacticipants';
import {
  KIND_LABELS,
  VERDICT_BADGES,
  VERDICT_LABELS,
  formatValue,
  httpRequest,
  httpResponse,
  interactionCounts,
  interactionSummary,
  latestVerification,
  messageParts,
  pactRoute,
  shortSha,
  verificationVerdict,
  type ChangedInteraction,
  type HttpPart,
  type InteractionStatus,
  type MessagePart,
  type PacticipantPact,
  type PactDiff,
  type PactHistoryEntry,
  type PactInteraction,
  type PactView,
  type ValueChange,
  type VerificationRow,
} from '@lib/pact-detail';

/**
 * A verification verdict as a badge.
 *
 * @param props - The newest result, or `null`.
 * @returns The badge.
 */
export function VerdictBadge({ latest }: { latest: VerificationRow | null }) {
  const verdict = verificationVerdict(latest);
  return (
    <Badge variant={VERDICT_BADGES[verdict]} data-testid="ppd-verdict">
      {VERDICT_LABELS[verdict]}
    </Badge>
  );
}

/**
 * The facts at the top of a pact.
 *
 * @param props - The pact and the handles of its pacticipants.
 * @returns The facts.
 */
export function PactFacts({
  pact,
  consumer,
  provider,
}: {
  pact: PactView;
  consumer: string;
  provider: string;
}) {
  return (
    <dl className="ppx__facts" data-testid="ppd-facts">
      <div className="ppx__fact">
        <dt>Consumer</dt>
        <dd>
          <Link className="ppx__link" href={pacticipantRoute(consumer)}>
            {pact.consumerName || consumer}
          </Link>
        </dd>
      </div>
      <div className="ppx__fact">
        <dt>Provider</dt>
        <dd>
          <Link className="ppx__link" href={pacticipantRoute(provider)}>
            {pact.providerName || provider}
          </Link>
        </dd>
      </div>
      <div className="ppx__fact">
        <dt>Consumer version</dt>
        <dd className="ppx__mono" title={pact.consumerVersion ?? undefined}>
          {pact.consumerVersion ? shortVersion(pact.consumerVersion) : '—'}
        </dd>
      </div>
      <div className="ppx__fact">
        <dt>Pact version</dt>
        <dd className="ppx__mono" title={pact.sha ?? undefined}>
          {shortSha(pact.sha)}
        </dd>
      </div>
      <div className="ppx__fact">
        <dt>Specification</dt>
        <dd>
          {pact.specification ? (
            `Pact ${pact.specification}`
          ) : (
            <span className="ppx__muted">Not stated</span>
          )}
        </dd>
      </div>
      <div className="ppx__fact">
        <dt>Published</dt>
        <dd className="ppx__when">{formatWhen(pact.publishedAt)}</dd>
      </div>
      <div className="ppx__fact">
        <dt>Interactions</dt>
        <dd>{interactionCounts(pact.interactions)}</dd>
      </div>
    </dl>
  );
}

/**
 * The verification results of one consumer version's pact, newest provider version first.
 *
 * @param props - The results.
 * @returns The table.
 */
export function VerificationTable({ verifications }: { verifications: VerificationRow[] }) {
  return (
    <div className="ppx__table-wrap">
      <table className="ppx__table" data-testid="ppd-verifications-table">
        <caption className="sr-only">Verification results, newest provider version first</caption>
        <thead>
          <tr>
            <th scope="col">Provider version</th>
            <th scope="col">Branch</th>
            <th scope="col">Result</th>
            <th scope="col">How</th>
            <th scope="col">Verified</th>
          </tr>
        </thead>
        <tbody>
          {verifications.map((row, index) => (
            <tr key={`${row.providerVersion ?? ''}-${row.verifiedAt ?? index}`}>
              <th scope="row" className="ppx__mono" title={row.providerVersion ?? undefined}>
                {row.providerVersion ? shortVersion(row.providerVersion) : '—'}
              </th>
              <td>
                {row.providerBranch ? (
                  <span className="ppx__mono">{row.providerBranch}</span>
                ) : (
                  <span className="ppx__muted">—</span>
                )}
              </td>
              <td>
                <span className="ppx__chips">
                  <Badge variant={row.success ? 'success' : row.pending ? 'warn' : 'danger'}>
                    {row.success ? 'Passed' : 'Failed'}
                  </Badge>
                  {row.pending ? <Badge variant="neutral">Pending</Badge> : null}
                  {row.wip ? <Badge variant="neutral">Work in progress</Badge> : null}
                </span>
              </td>
              <td>
                {row.kind === 'bidirectional' ? 'Bi-directional comparison' : 'Pact verifier'}
              </td>
              <td className="ppx__when">{formatWhen(row.verifiedAt)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * An integration's consumer versions, newest first; the open one is marked and each other one
 * opens on its button.
 *
 * @param props - The versions, the open one, and what to do when another is chosen.
 * @returns The table.
 */
export function HistoryTable({
  entries,
  openVersion,
  onOpen,
}: {
  entries: PactHistoryEntry[];
  openVersion: string | null;
  onOpen: (version: string) => void;
}) {
  return (
    <div className="ppx__table-wrap">
      <table className="ppx__table" data-testid="ppd-history-table">
        <caption className="sr-only">Consumer versions with a pact, newest first</caption>
        <thead>
          <tr>
            <th scope="col">Consumer version</th>
            <th scope="col">Branch</th>
            <th scope="col">Published</th>
            <th scope="col">Verification</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((entry) => {
            const open = entry.consumerVersion === openVersion;
            return (
              <tr
                key={entry.consumerVersion}
                className={open ? 'ppd__row--open' : undefined}
                aria-current={open ? 'true' : undefined}
                data-testid={`ppd-history-${entry.consumerVersion}`}
              >
                <th scope="row">
                  {open ? (
                    <span className="ppx__mono" title={entry.consumerVersion}>
                      {shortVersion(entry.consumerVersion)}{' '}
                      <span className="ppx__muted">(open)</span>
                    </span>
                  ) : (
                    <button
                      type="button"
                      className="ppx__chip-button ppx__mono"
                      onClick={() => onOpen(entry.consumerVersion)}
                      aria-label={`Open the pact of version ${entry.consumerVersion}`}
                      title={entry.consumerVersion}
                    >
                      {shortVersion(entry.consumerVersion)}
                    </button>
                  )}
                </th>
                <td>
                  {entry.branch ? (
                    <span className="ppx__mono">{entry.branch}</span>
                  ) : (
                    <span className="ppx__muted">—</span>
                  )}
                </td>
                <td className="ppx__when">{formatWhen(entry.publishedAt)}</td>
                <td>
                  <VerdictBadge latest={latestVerification(entry.verifications)} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/**
 * A JSON value (or a string as it is) in a code block.
 *
 * @param props - The value and the block's accessible name.
 * @returns The block.
 */
function ValueBlock({ value, label }: { value: unknown; label: string }) {
  return (
    <pre className="ppd__code" aria-label={label}>
      <code>{formatValue(value)}</code>
    </pre>
  );
}

/**
 * The headers and body of one HTTP request or response.
 *
 * @param props - The part and whether it is the request.
 * @returns The part.
 */
function HttpPartView({ part, title }: { part: HttpPart; title: string }) {
  return (
    <div className="ppd__part">
      <h3 className="ppd__part-title">
        {title} <span className="ppx__mono">{part.line}</span>
      </h3>
      {part.headers ? <ValueBlock value={part.headers} label={`${title} headers`} /> : null}
      {part.hasBody ? (
        <ValueBlock value={part.body} label={`${title} body`} />
      ) : (
        <p className="ppx__muted">No body</p>
      )}
    </div>
  );
}

/**
 * The contents and metadata of one message.
 *
 * @param props - The message and its heading.
 * @returns The message.
 */
function MessagePartView({ part, title }: { part: MessagePart; title: string }) {
  return (
    <div className="ppd__part">
      <h3 className="ppd__part-title">{title}</h3>
      {part.metadata ? <ValueBlock value={part.metadata} label={`${title} metadata`} /> : null}
      {part.contents !== null ? (
        <ValueBlock value={part.contents} label={`${title} contents`} />
      ) : (
        <p className="ppx__muted">No contents</p>
      )}
    </div>
  );
}

/**
 * What an interaction asks for and expects, by kind; an unknown kind is its JSON as published.
 *
 * @param props - The interaction.
 * @returns The body of its disclosure.
 */
function InteractionBody({ interaction }: { interaction: PactInteraction }) {
  if (interaction.kind === 'http') {
    return (
      <div className="ppd__parts">
        <HttpPartView part={httpRequest(interaction.raw)} title="Request" />
        <HttpPartView part={httpResponse(interaction.raw)} title="Response" />
      </div>
    );
  }
  if (interaction.kind === 'message' || interaction.kind === 'sync-message') {
    const { request, responses } = messageParts(interaction);
    return (
      <div className="ppd__parts">
        <MessagePartView
          part={request}
          title={interaction.kind === 'message' ? 'Message' : 'Request'}
        />
        {responses.map((response, index) => (
          <MessagePartView
            key={index}
            part={response}
            title={responses.length === 1 ? 'Response' : `Response ${index + 1}`}
          />
        ))}
      </div>
    );
  }
  return (
    <div className="ppd__parts">
      <p className="ppx__statement" role="note">
        {interaction.typeLabel}.
      </p>
      <ValueBlock value={interaction.raw} label="The interaction as published" />
    </div>
  );
}

/**
 * The provider states an interaction needs, with their parameters.
 *
 * @param props - The interaction.
 * @returns The list, or a note that it needs none.
 */
function StatesList({ interaction }: { interaction: PactInteraction }) {
  if (interaction.states.length === 0) return <p className="ppx__muted">No provider state</p>;
  return (
    <ul className="ppx__plain-list" aria-label="Provider states">
      {interaction.states.map((state, index) => (
        <li key={`${state.name}-${index}`} className="ppd__state">
          <span className="ppd__state-name">Given {state.name}</span>
          {state.params ? (
            <span className="ppx__mono ppx__muted"> {JSON.stringify(state.params)}</span>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

/**
 * Every interaction of a pact, each a disclosure with its provider states, request and response
 * (or message). Interactions new or changed since the previous pact carry a badge.
 *
 * @param props - The interactions and their statuses.
 * @returns The list.
 */
export function InteractionList({
  interactions,
  statuses,
}: {
  interactions: PactInteraction[];
  statuses: Map<string, InteractionStatus>;
}) {
  return (
    <ol className="ppd__interactions" data-testid="ppd-interaction-list">
      {interactions.map((interaction) => {
        const status = statuses.get(interaction.key);
        return (
          <li key={interaction.key} className="ppd__interaction">
            <details>
              <summary className="ppd__summary">
                <span className="ppd__summary-main">
                  <span className="ppx__name">{interaction.description}</span>
                  <span className="ppx__mono ppx__muted">{interactionSummary(interaction)}</span>
                </span>
                <span className="ppx__chips">
                  <Badge variant={interaction.kind === 'unknown' ? 'warn' : 'neutral'}>
                    {KIND_LABELS[interaction.kind]}
                  </Badge>
                  {interaction.pending ? <Badge variant="neutral">Pending</Badge> : null}
                  {status === 'added' ? <Badge variant="accent">New</Badge> : null}
                  {status === 'changed' ? <Badge variant="warn">Changed</Badge> : null}
                </span>
              </summary>
              <div className="ppd__detail">
                <StatesList interaction={interaction} />
                <InteractionBody interaction={interaction} />
              </div>
            </details>
          </li>
        );
      })}
    </ol>
  );
}

/** One changed value: `path: before → after`. */
function ChangeLine({ change }: { change: ValueChange }) {
  const show = (value: unknown) => JSON.stringify(value) ?? 'undefined';
  return (
    <li className="ppd__change">
      <span className="ppx__mono ppd__change-path">{change.path}</span>
      {!('before' in change) ? (
        <span className="ppd__change-added">added {show(change.after)}</span>
      ) : !('after' in change) ? (
        <span className="ppd__change-removed">removed {show(change.before)}</span>
      ) : (
        <span>
          <span className="ppd__change-removed">{show(change.before)}</span>
          {' → '}
          <span className="ppd__change-added">{show(change.after)}</span>
        </span>
      )}
    </li>
  );
}

/** A changed interaction and its changed values. */
function ChangedItem({ change }: { change: ChangedInteraction }) {
  return (
    <li className="ppd__diff-item">
      <span className="ppd__diff-head">
        <Badge variant="warn">Changed</Badge>
        <span className="ppx__name">{change.current.description}</span>
      </span>
      <ul
        className="ppx__plain-list ppd__changes"
        aria-label={`What changed in ${change.current.description}`}
      >
        {change.changes.map((value) => (
          <ChangeLine key={value.path} change={value} />
        ))}
      </ul>
      {change.truncated ? (
        <p className="ppx__muted">More values changed; open both versions to compare the rest.</p>
      ) : null}
    </li>
  );
}

/**
 * What changed since the previous different pact: added, changed (with the values) and removed
 * interactions.
 *
 * @param props - The diff.
 * @returns The list, or a statement that the interactions are the same.
 */
export function ChangesList({ diff }: { diff: PactDiff }) {
  if (diff.added.length + diff.changed.length + diff.removed.length === 0) {
    return (
      <p className="ppx__statement">
        The interactions are the same; only the pact&apos;s other content (such as its metadata)
        differs.
      </p>
    );
  }
  return (
    <ul className="ppd__diff" data-testid="ppd-diff-list">
      {diff.added.map((interaction) => (
        <li key={`added-${interaction.key}`} className="ppd__diff-item">
          <span className="ppd__diff-head">
            <Badge variant="accent">Added</Badge>
            <span className="ppx__name">{interaction.description}</span>
            <span className="ppx__mono ppx__muted">{interactionSummary(interaction)}</span>
          </span>
        </li>
      ))}
      {diff.changed.map((change) => (
        <ChangedItem key={`changed-${change.current.key}`} change={change} />
      ))}
      {diff.removed.map((interaction) => (
        <li key={`removed-${interaction.key}`} className="ppd__diff-item">
          <span className="ppd__diff-head">
            <Badge variant="danger">Removed</Badge>
            <span className="ppx__name">{interaction.description}</span>
            <span className="ppx__mono ppx__muted">{interactionSummary(interaction)}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}

/**
 * The integrations a pacticipant is in, each linking to its newest pact.
 *
 * @param props - The integrations and the pacticipant's handle (to say which side it is on).
 * @returns The table.
 */
export function PacticipantPactsTable({ pacts, slug }: { pacts: PacticipantPact[]; slug: string }) {
  return (
    <div className="ppx__table-wrap">
      <table className="ppx__table" data-testid="ppx-pacts-table">
        <caption className="sr-only">Pacts this pacticipant publishes or verifies</caption>
        <thead>
          <tr>
            <th scope="col">Pact</th>
            <th scope="col">Role</th>
            <th scope="col">Latest consumer version</th>
            <th scope="col">Published</th>
            <th scope="col">Verification</th>
          </tr>
        </thead>
        <tbody>
          {pacts.map((pact) => (
            <tr key={`${pact.consumer.slug}-${pact.provider.slug}`}>
              <th scope="row">
                <Link
                  className="ppx__link ppx__name"
                  href={pactRoute(pact.consumer.slug, pact.provider.slug)}
                  data-testid={`ppx-pact-${pact.consumer.slug}-${pact.provider.slug}`}
                >
                  {pact.consumer.name} → {pact.provider.name}
                </Link>
              </th>
              <td>{pact.consumer.slug === slug ? 'Consumer' : 'Provider'}</td>
              <td className="ppx__mono" title={pact.latestVersion}>
                {shortVersion(pact.latestVersion)}
              </td>
              <td className="ppx__when">{formatWhen(pact.publishedAt)}</td>
              <td>
                <VerdictBadge latest={pact.latestVerification} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
