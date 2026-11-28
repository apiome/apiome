'use client';

/**
 * Step 2 of the **Migration wizard** — **Choose** (PFX-8.16, #7313), built to
 * `docs/mockups/contracts/migrate.html`.
 *
 * - **What to copy** — eight tick boxes, each with what a dry run counted at the source. Nothing has
 *   been written yet.
 * - **How much history** — verification results (all, the latest of each pact, none) and versions
 *   (all, or only what the workspace's clean-up rules would keep).
 * - **When something already exists here** — keep Apiome's, or replace it with the source's.
 * - **Before you copy** — everything the source holds that cannot be carried over as it is, as one
 *   status strip rather than stacked banners (`DESIGN.md` §5.4).
 * - **Advanced** — start from scratch, the matrix limit and the batch size (the command's
 *   `--restart`, `--matrix-limit` and `--batch-bytes`).
 *
 * While the dry run is still reading the source, the step shows its progress instead.
 */

import * as React from 'react';
import Link from 'next/link';
import { Button, StatusStrip, type StatusStripItem } from '@/app/components/ui';
import { SECRETS_TAB_ROUTE } from '@lib/pact-contract-settings';
import { CONTRACTS_ROUTE } from '@lib/pact-overview';
import { SETTINGS_ROUTE } from '@lib/pact-retention';
import {
  BATCH_BYTES_RANGE,
  CHOICE_TILES,
  MATRIX_LIMIT_RANGE,
  existingSentence,
  formatCount,
  migrationWarnings,
  tileChecked,
  tileCount,
  toggleTile,
  type MigrationOptions,
  type MigrationRun,
} from '@lib/pact-migration';

/** Props for {@link ChooseStep}. */
export interface ChooseStepProps {
  /** The finished dry run whose counts fill the step, if there is one. */
  dry: MigrationRun | null;
  /** The dry run still reading the source (or that failed), if that is what the wizard follows. */
  counting: MigrationRun | null;
  options: MigrationOptions;
  onOptions: (options: MigrationOptions) => void;
  /** Why **Start copying** cannot be pressed, if it cannot. */
  problem: string | null;
  canMigrate: boolean;
  busy: boolean;
  /** Why starting the copy failed, if it did. */
  error: string | null;
  onBack: () => void;
  onStart: () => void;
  /** Count again (after a dry run that failed). */
  onRecount: () => void;
}

/** One group of chips that picks a single value. */
function Chips<T extends string>({
  label,
  id,
  value,
  choices,
  disabled,
  onChange,
}: {
  label: string;
  id: string;
  value: T;
  choices: ReadonlyArray<{ value: T; label: string; disabled?: boolean }>;
  disabled: boolean;
  onChange: (value: T) => void;
}) {
  return (
    <div>
      <div className="pmg-label" id={`${id}-label`}>
        {label}
      </div>
      <div className="pcx-chips" role="group" aria-labelledby={`${id}-label`}>
        {choices.map((choice) => (
          <button
            key={choice.value}
            type="button"
            className="pcx-chip"
            aria-pressed={value === choice.value}
            disabled={disabled || choice.disabled}
            onClick={() => onChange(choice.value)}
            data-testid={`${id}-${choice.value}`}
          >
            {choice.label}
          </button>
        ))}
      </div>
    </div>
  );
}

/**
 * The **Choose** step.
 *
 * @param props - See {@link ChooseStepProps}.
 * @returns The step's body and footer.
 */
export function ChooseStep({
  dry,
  counting,
  options,
  onOptions,
  problem,
  canMigrate,
  busy,
  error,
  onBack,
  onStart,
  onRecount,
}: ChooseStepProps) {
  const reading = counting !== null && counting.status === 'running';
  const countFailed = counting !== null && counting.status !== 'running' && counting.status !== 'completed';
  const locked = !canMigrate || reading;
  const versionsChosen = options.kinds.includes('version');
  const rulesSet = dry?.facts.cleanup_rules_set === true;
  const wouldSkip = dry?.facts.cleanup_would_skip;
  const notLatest = dry?.facts.results_not_latest;

  const warnings: StatusStripItem[] = migrationWarnings(dry).map((warning) => ({
    id: warning.id,
    tone: warning.tone,
    label: warning.label,
    title: warning.title,
    body: (
      <ul className="pmg-lines">
        {warning.lines.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
    ),
    actions: warning.secrets ? (
      <Button variant="outline" size="sm" asChild>
        <Link href={SECRETS_TAB_ROUTE}>Secrets</Link>
      </Button>
    ) : undefined,
  }));

  return (
    <>
      <div className="pmg-body" data-testid="pmg-choose">
        {reading ? (
          <div className="pmg-counting" role="status" data-testid="pmg-counting">
            <div className="pmg-row">
              <span className="pmg-strong">Counting what is at {counting.host}</span>
              <span className="pmg-subtle">
                {counting.phase === 'reading' ? 'reading the source' : `${counting.percent}% checked`}
              </span>
            </div>
            <progress
              className="pvl-progress pvl-progress--striped"
              max={100}
              value={counting.percent}
              aria-label="Dry run progress"
            >
              {counting.percent}%
            </progress>
            <p className="pmg-subtle">A dry run reads the source and checks every record. Nothing is written.</p>
          </div>
        ) : null}
        {countFailed ? (
          <div className="pcx-callout" role="alert" data-testid="pmg-count-failed">
            <span className="pmg-strong">The source could not be counted.</span>{' '}
            {counting.error ?? 'The dry run did not finish.'}{' '}
            <Button variant="outline" size="sm" onClick={onRecount} disabled={!canMigrate}>
              Count again
            </Button>
          </div>
        ) : null}

        <div className="pmg-row">
          <h3 className="pmg-heading">What to copy</h3>
          <span className="pmg-subtle" data-testid="pmg-count-note">
            {dry ? 'Counted by a dry run · nothing written yet' : 'Counts come from a dry run'}
          </span>
        </div>
        <div className="pmg-tiles">
          {CHOICE_TILES.map((tile) => {
            const count = tileCount(dry, tile);
            return (
              <label key={tile.id} className="pmg-tile" data-testid={`pmg-tile-${tile.id}`}>
                <span className="pmg-row">
                  <span className="pcx-caps">{tile.label}</span>
                  <input
                    type="checkbox"
                    checked={tileChecked(options, tile)}
                    disabled={locked}
                    onChange={(event) => onOptions(toggleTile(options, tile, event.target.checked))}
                    aria-label={`Copy ${tile.label}`}
                  />
                </span>
                <span className="pmg-tile__value">{count === null ? '—' : formatCount(count)}</span>
                {tile.note ? <span className="pmg-subtle">{tile.note}</span> : null}
              </label>
            );
          })}
        </div>

        <div className="pmg-columns">
          <section className="pmg-card" aria-labelledby="pmg-history-title">
            <h3 id="pmg-history-title" className="pmg-heading">
              How much history
            </h3>
            <Chips
              label="Verification results"
              id="pmg-results"
              value={options.results}
              disabled={locked}
              onChange={(results) => onOptions({ ...options, results })}
              choices={[
                { value: 'all', label: 'All' },
                { value: 'latest', label: 'Latest per pact' },
                { value: 'none', label: 'None' },
              ]}
            />
            {options.results === 'latest' && typeof notLatest === 'number' ? (
              <p className="pmg-subtle" data-testid="pmg-results-hint">
                Skips {formatCount(notLatest)} older {notLatest === 1 ? 'result' : 'results'}.
              </p>
            ) : null}
            <Chips
              label="Versions"
              id="pmg-versions"
              value={options.versions}
              disabled={locked}
              onChange={(versions) => onOptions({ ...options, versions })}
              choices={[
                { value: 'all', label: 'All' },
                { value: 'kept', label: 'What clean-up would keep', disabled: !rulesSet || !versionsChosen },
              ]}
            />
            <p className="pmg-subtle" data-testid="pmg-versions-hint">
              {!rulesSet ? (
                <>
                  Save <Link href={SETTINGS_ROUTE}>keep-rules</Link> to copy only what clean-up would keep.
                </>
              ) : typeof wouldSkip === 'number' ? (
                <>
                  {options.versions === 'kept' ? 'Skips' : 'Would skip'} {formatCount(wouldSkip)}{' '}
                  {wouldSkip === 1 ? 'version' : 'versions'} your <Link href={SETTINGS_ROUTE}>keep-rules</Link> would
                  remove anyway, with their pacts and results.
                </>
              ) : (
                <>
                  Leaves behind the versions your <Link href={SETTINGS_ROUTE}>keep-rules</Link> would remove anyway.
                </>
              )}
            </p>
          </section>

          <section className="pmg-card" aria-labelledby="pmg-conflicts-title">
            <h3 id="pmg-conflicts-title" className="pmg-heading">
              When something already exists here
            </h3>
            <div className="pmg-radios" role="radiogroup" aria-labelledby="pmg-conflicts-title">
              {(
                [
                  ['keep', 'Keep Apiome’s, skip the source’s'],
                  ['replace', 'Replace with the source’s'],
                ] as const
              ).map(([value, label]) => (
                <label key={value} className="pmg-radio">
                  <input
                    type="radio"
                    name="pmg-conflicts"
                    value={value}
                    checked={options.conflicts === value}
                    disabled={locked}
                    onChange={() => onOptions({ ...options, conflicts: value })}
                    data-testid={`pmg-conflicts-${value}`}
                  />
                  {label}
                </label>
              ))}
            </div>
            <p className="pmg-subtle" data-testid="pmg-existing">
              {existingSentence(dry)} A pact or a current deployment can be replaced; a verification result never
              is, and is listed if it differs.
            </p>
          </section>
        </div>

        <StatusStrip aria-label="Before you copy" caption="Before you copy" items={warnings} />

        <details className="pmg-advanced" data-testid="pmg-advanced">
          <summary>Advanced</summary>
          <div className="pmg-advanced__body">
            <label className="pmg-radio">
              <input
                type="checkbox"
                checked={options.restart}
                disabled={locked}
                onChange={(event) => onOptions({ ...options, restart: event.target.checked })}
                data-testid="pmg-restart"
              />
              Start from scratch: copy everything again, ignoring what earlier migrations from this source copied
            </label>
            <div className="pmg-pair">
              <label className="pmg-number">
                <span className="pmg-label">Matrix rows read per integration</span>
                <input
                  type="number"
                  className="pmg-number__input"
                  min={MATRIX_LIMIT_RANGE.min}
                  max={MATRIX_LIMIT_RANGE.max}
                  value={Number.isFinite(options.matrix_limit) ? options.matrix_limit : ''}
                  disabled={locked}
                  onChange={(event) => onOptions({ ...options, matrix_limit: event.target.valueAsNumber })}
                  data-testid="pmg-matrix-limit"
                />
              </label>
              <label className="pmg-number">
                <span className="pmg-label">Bytes written at a time</span>
                <input
                  type="number"
                  className="pmg-number__input"
                  min={BATCH_BYTES_RANGE.min}
                  max={BATCH_BYTES_RANGE.max}
                  value={Number.isFinite(options.batch_bytes) ? options.batch_bytes : ''}
                  disabled={locked}
                  onChange={(event) => onOptions({ ...options, batch_bytes: event.target.valueAsNumber })}
                  data-testid="pmg-batch-bytes"
                />
              </label>
            </div>
            <p className="pmg-subtle">
              Raise the matrix limit when the strip says pacts or results may be missing. Changing the limit takes
              effect on the copy; count again from Connect to see it in the numbers above.
            </p>
          </div>
        </details>

        {problem ? (
          <p className="ppub-hint" role="status" data-testid="pmg-choose-problem">
            {problem}
          </p>
        ) : null}
        {error ? (
          <p className="ppub-hint ppub-hint--danger" role="alert" data-testid="pmg-choose-error">
            {error}
          </p>
        ) : null}
      </div>
      <div className="pmg-footer">
        <Button variant="outline" asChild className="pmg-footer__start">
          <Link href={CONTRACTS_ROUTE} data-testid="pmg-save-close">
            Save &amp; close
          </Link>
        </Button>
        <Button variant="ghost" onClick={onBack} data-testid="pmg-back">
          Back
        </Button>
        <Button onClick={onStart} disabled={locked || busy || problem !== null} data-testid="pmg-start">
          {busy ? 'Starting…' : 'Start copying'}
        </Button>
      </div>
    </>
  );
}

export default ChooseStep;
