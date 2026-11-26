/**
 * The pieces of the **Matrix** and **Can I deploy** pages (PFX-5.4, #6948). Pure presentation —
 * the pages own the reads.
 *
 * * {@link VerdictPanel} — the verdict, the broker's sentence, the counts, and every notice
 *   grouped (blocking, warnings, passing) with what to do about it.
 * * {@link MatrixGridTable} — consumer versions down, provider versions across; each cell the
 *   newest result of the pair with its mark, opening the pact.
 * * {@link MatrixRowsTable} — every row the answer holds.
 *
 * Both tables are real `<table>`s with captions and row / column headers, and every cell that
 * does something is a link, so they read and drive from the keyboard.
 */

import * as React from 'react';
import Link from 'next/link';
import { RefreshCw } from 'lucide-react';
import { Badge } from '@/app/components/ui/Badge';
import { Button } from '@/app/components/ui';
import { formatWhen, pacticipantRoute, shortVersion } from '@lib/pact-pacticipants';
import { pactRoute } from '@lib/pact-detail';
import {
  NOTICE_HINTS,
  buildMatrixGrid,
  cellLabel,
  countsLine,
  explainVerdict,
  gridCellKey,
  reasonLook,
  rowsMayBeTruncated,
  verdictHeadline,
  type GridAxisEntry,
  type MatrixAnswer,
  type MatrixNotice,
  type MatrixRow,
  type MatrixSide,
  type ReasonLook,
} from '@lib/pact-matrix';

/** The badge variant of each reason tone. */
const TONE_BADGES: Record<ReasonLook['tone'], 'success' | 'danger' | 'warn' | 'neutral'> = {
  ok: 'success',
  danger: 'danger',
  warn: 'warn',
  muted: 'neutral',
};

/**
 * One group of notices, with a hint under each that has one.
 *
 * @param props - The heading, the notices and the badge they carry.
 * @returns The group, or nothing when it is empty.
 */
function NoticeGroup({
  title,
  notices,
  badge,
  variant,
  testId,
}: {
  title: string;
  notices: MatrixNotice[];
  /** The badge every notice of the group carries; `null` shows each notice's own type. */
  badge: string | null;
  variant: 'success' | 'danger' | 'warn' | 'neutral';
  testId: string;
}) {
  if (notices.length === 0) return null;
  return (
    <div className="pmx-notices" data-testid={testId}>
      <h3 className="pmx-notices__title">{title}</h3>
      <ul className="ppx__plain-list">
        {notices.map((notice, index) => {
          const hint = notice.code ? NOTICE_HINTS[notice.code] : undefined;
          return (
            <li key={`${notice.code ?? notice.type}-${index}`} className="pmx-notice">
              <span className="pmx-notice__line">
                <Badge variant={variant}>{badge ?? notice.type}</Badge>
                <span>{notice.text}</span>
              </span>
              {hint ? <span className="ppx__muted pmx-notice__hint">{hint}</span> : null}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/**
 * The verdict and why.
 *
 * @param props - The answer; the row limit it was asked with (REST's default of 100 for
 *   can-i-deploy); what **Check again** does and whether it is running.
 * @returns The panel.
 */
export function VerdictPanel({
  answer,
  limit,
  onRecheck,
  rechecking,
}: {
  answer: MatrixAnswer;
  limit: number;
  onRecheck: () => void;
  rechecking: boolean;
}) {
  const headline = verdictHeadline(answer.summary.deployable);
  const explanation = explainVerdict(answer);
  const truncated = rowsMayBeTruncated(answer, limit);
  return (
    <section
      className="ppx__panel pmx-verdict"
      data-tone={headline.tone}
      aria-labelledby="pmx-verdict-title"
      data-testid="pmx-verdict-panel"
    >
      <div className="ppx__panel-head">
        <h2 id="pmx-verdict-title" className="ppx__title">
          Verdict
        </h2>
        <span className="ppx__meta" data-testid="pmx-counts">
          {countsLine(answer.summary)}
        </span>
      </div>
      <p className="pmx-verdict__headline" role="status" data-testid="pmx-verdict">
        {headline.label}
      </p>
      {answer.summary.reason ? <p className="ppx__statement">{answer.summary.reason}</p> : null}
      <p className="ppx__meta" data-testid="pmx-row-counts">
        {explanation.considered} {explanation.considered === 1 ? 'row counts' : 'rows count'}{' '}
        towards the verdict
        {explanation.ignored > 0 ? ` · ${explanation.ignored} ignored` : ''}
      </p>
      {answer.summary.deployable === null ? (
        <div className="ppx__actions" data-testid="pmx-retry">
          <span className="ppx__statement">
            A verification result is still missing.
            {answer.retryAfterSeconds
              ? ` Ask again in about ${answer.retryAfterSeconds} seconds`
              : ' Ask again once the provider has verified'}{' '}
            — <code className="ppx__mono">can-i-deploy --retry-while-unknown</code> waits the same
            way.
          </span>
          <Button variant="soft" onClick={onRecheck} disabled={rechecking}>
            <RefreshCw aria-hidden />
            {rechecking ? 'Checking…' : 'Check again'}
          </Button>
        </div>
      ) : null}
      {truncated ? (
        <p className="ppx__error" role="note" data-testid="pmx-truncated">
          The answer holds {answer.rows.length} rows, the most asked for, so some rows may be
          missing. Raise the row limit or narrow the selectors.
        </p>
      ) : null}
      <NoticeGroup
        title="Blocking"
        notices={explanation.blocking}
        badge="Blocks"
        variant="danger"
        testId="pmx-blocking"
      />
      <NoticeGroup
        title="Warnings"
        notices={explanation.warnings}
        badge="Warning"
        variant="warn"
        testId="pmx-warnings"
      />
      <NoticeGroup
        title="Passing"
        notices={explanation.passing}
        badge="Passes"
        variant="success"
        testId="pmx-passing"
      />
      <NoticeGroup
        title="Other notices"
        notices={explanation.other}
        badge={null}
        variant="neutral"
        testId="pmx-other"
      />
    </section>
  );
}

/**
 * A pacticipant's name as a link to its page, or as text when the row carried no handle.
 *
 * @param props - The side of the row.
 * @returns The name.
 */
function SideName({ side }: { side: Pick<MatrixSide, 'name' | 'slug'> }) {
  const name = side.name || side.slug || '—';
  return side.slug ? (
    <Link className="ppx__link" href={pacticipantRoute(side.slug)}>
      {name}
    </Link>
  ) : (
    <span>{name}</span>
  );
}

/**
 * A version number, cut for the table, the whole number in its title.
 *
 * @param props - The number, or `null` (then `empty` is shown).
 * @returns The version.
 */
function VersionText({ version, empty = '—' }: { version: string | null; empty?: string }) {
  if (!version) return <span className="ppx__muted">{empty}</span>;
  return (
    <span className="ppx__mono" title={version}>
      {shortVersion(version)}
    </span>
  );
}

/** The route of a row's pact, or `null` when the row carried no handles. */
function rowPactRoute(row: MatrixRow): string | null {
  return row.consumer.slug && row.provider.slug
    ? pactRoute(row.consumer.slug, row.provider.slug, row.consumer.version)
    : null;
}

/**
 * The header of one axis entry: the pacticipant and its version.
 *
 * @param props - The entry.
 * @returns The header content.
 */
function AxisHeader({ entry }: { entry: GridAxisEntry }) {
  return (
    <span className="ppx__name-cell">
      <SideName side={entry} />
      <VersionText version={entry.version} empty="no result" />
    </span>
  );
}

/**
 * The grid: consumer versions down, provider versions across.
 *
 * @param props - The rows.
 * @returns The grid, with a note when some versions are past its size.
 */
export function MatrixGridTable({ rows }: { rows: MatrixRow[] }) {
  const grid = React.useMemo(() => buildMatrixGrid(rows), [rows]);
  return (
    <div className="pmx-grid-wrap">
      {grid.hiddenConsumers > 0 || grid.hiddenProviders > 0 ? (
        <p className="ppx__meta" role="note" data-testid="pmx-grid-hidden">
          The grid draws the first {grid.consumers.length} consumer versions and{' '}
          {grid.providers.length} provider versions; {grid.hiddenConsumers} more consumer versions
          and {grid.hiddenProviders} more provider versions are only in the rows table below.
        </p>
      ) : null}
      <div className="ppx__table-wrap">
        <table className="ppx__table pmx-grid" data-testid="pmx-grid">
          <caption className="sr-only">
            The matrix: consumer versions in rows, provider versions in columns. Each cell is the
            newest result of the pair.
          </caption>
          <thead>
            <tr>
              <th scope="col">Consumer ↓ · Provider →</th>
              {grid.providers.map((provider) => (
                <th key={provider.key} scope="col">
                  <AxisHeader entry={provider} />
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {grid.consumers.map((consumer) => (
              <tr key={consumer.key}>
                <th scope="row">
                  <AxisHeader entry={consumer} />
                </th>
                {grid.providers.map((provider) => {
                  const cell = grid.cells.get(gridCellKey(consumer, provider));
                  if (!cell) {
                    return (
                      <td key={provider.key} className="pmx-grid__cell">
                        <span className="pmx-cell pmx-cell--empty" aria-hidden>
                          ·
                        </span>
                        <span className="sr-only">No row</span>
                      </td>
                    );
                  }
                  const look = reasonLook(cell.row.reason.code);
                  const href = rowPactRoute(cell.row);
                  const content = (
                    <>
                      <span aria-hidden>{look.mark}</span>
                      {cell.count > 1 ? (
                        <span className="pmx-cell__count" aria-hidden>
                          {cell.count}
                        </span>
                      ) : null}
                    </>
                  );
                  return (
                    <td key={provider.key} className="pmx-grid__cell">
                      {href ? (
                        <Link
                          className="pmx-cell"
                          data-tone={look.tone}
                          data-ignored={cell.row.ignored || undefined}
                          href={href}
                          aria-label={cellLabel(cell)}
                          title={cell.row.reason.text}
                          data-testid={`pmx-cell-${gridCellKey(consumer, provider)}`}
                        >
                          {content}
                        </Link>
                      ) : (
                        <span
                          className="pmx-cell"
                          data-tone={look.tone}
                          data-ignored={cell.row.ignored || undefined}
                          role="img"
                          aria-label={cellLabel(cell).replace(' Open the pact.', '')}
                          title={cell.row.reason.text}
                        >
                          {content}
                        </span>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ul className="pmx-key" aria-label="Key">
        {(
          ['verified', 'verification-failed', 'pact-pending', 'no-verification-result'] as const
        ).map((code) => {
          const look = reasonLook(code);
          return (
            <li key={code} className="pmx-key__item">
              <span className="pmx-cell pmx-cell--key" data-tone={look.tone} aria-hidden>
                {look.mark}
              </span>
              {look.label}
            </li>
          );
        })}
        <li className="pmx-key__item">
          <span className="pmx-cell pmx-cell--key" data-tone="muted" data-ignored aria-hidden>
            ✓
          </span>
          Ignored (does not count)
        </li>
      </ul>
    </div>
  );
}

/**
 * Every row of an answer.
 *
 * @param props - The rows and the table's caption.
 * @returns The table.
 */
export function MatrixRowsTable({ rows, caption }: { rows: MatrixRow[]; caption: string }) {
  return (
    <div className="ppx__table-wrap">
      <table className="ppx__table" data-testid="pmx-rows">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr>
            <th scope="col">Consumer</th>
            <th scope="col">Consumer version</th>
            <th scope="col">Provider</th>
            <th scope="col">Provider version</th>
            <th scope="col">Result</th>
            <th scope="col">Verified</th>
            <th scope="col">Pact</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => {
            const look = reasonLook(row.reason.code);
            const href = rowPactRoute(row);
            const verification = row.verification;
            return (
              <tr key={index} data-ignored={row.ignored || undefined}>
                <th scope="row">
                  <SideName side={row.consumer} />
                </th>
                <td>
                  <span className="ppx__name-cell">
                    <VersionText version={row.consumer.version} />
                    {row.consumer.branch ? (
                      <span className="ppx__muted">{row.consumer.branch}</span>
                    ) : null}
                  </span>
                </td>
                <td>
                  <SideName side={row.provider} />
                </td>
                <td>
                  <span className="ppx__name-cell">
                    <VersionText version={row.provider.version} />
                    {row.provider.branch ? (
                      <span className="ppx__muted">{row.provider.branch}</span>
                    ) : null}
                  </span>
                </td>
                <td>
                  <span className="ppx__chips">
                    <Badge variant={TONE_BADGES[look.tone]}>{look.label}</Badge>
                    {verification?.kind === 'bidirectional' ? (
                      <Badge variant="neutral">Bi-directional</Badge>
                    ) : null}
                    {verification?.pending ? <Badge variant="neutral">Pending</Badge> : null}
                    {verification?.wip ? <Badge variant="neutral">WIP</Badge> : null}
                    {row.ignored ? <Badge variant="neutral">Ignored</Badge> : null}
                  </span>
                  <span className="ppx__muted pmx-row-reason">{row.reason.text}</span>
                </td>
                <td>
                  <span className="ppx__when">{formatWhen(verification?.verifiedAt)}</span>
                </td>
                <td>
                  {href ? (
                    <Link className="ppx__link" href={href}>
                      Open pact
                    </Link>
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
