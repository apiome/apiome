'use client';

/**
 * The Import wizard's **Changes** step (IXH-3.7, #6321).
 *
 * Reached only when the import lands as a new version of an existing Project. It compares the
 * incoming spec with that project's latest version before anything is written:
 *
 *  - a **summary bar** — added / changed / removed / breaking, each a symbol + word + number,
 *    never colour alone — and a warning callout (not a block) when anything is breaking;
 *  - a **Summary** tab with the ranked change list (breaking first), a kind filter and a text
 *    filter, mounted a page at a time so a large delta stays responsive;
 *  - a **Side-by-side spec** tab: `JsonDiffViewer` (Monaco diff, sides labelled for screen
 *    readers), latest version on the left and the incoming spec on the right. Radix unmounts an
 *    inactive tab, and the viewer loads Monaco on demand, so the editor costs nothing until the
 *    tab is opened;
 *  - a "No changes from v…" state, a loading state, and an `ErrorState` with retry — the footer's
 *    **Continue to import** stays available in every one of them;
 *  - a **Merge strategy** choice (#591): **Replace with this import** (the default) or **Additive
 *    merge**, which keeps everything in the latest version and adds what the spec newly defines.
 *
 * A view only: the dialog owns the request and the {@link ProjectDeltaState}.
 */

import { useMemo, useState } from 'react';
import { GitCompareArrows } from 'lucide-react';
import { Alert } from '../../ui/Alert';
import { Badge } from '../../ui/Badge';
import { Button } from '../../ui/Button';
import { EmptyState } from '../../ui/EmptyState';
import { ErrorState } from '../../ui/ErrorState';
import { Input } from '../../ui/Input';
import { RadioGroup, RadioGroupItem } from '../../ui/RadioGroup';
import { LoadingState } from '../../ui/LoadingState';
import { Tabs, TabsContent, TabsCount, TabsList, TabsTrigger } from '../../ui/Tabs';
import { JsonDiffViewer } from '../../ui/code/JsonDiffViewer';
import {
  PROJECT_DELTA_FILTERS,
  PROJECT_DELTA_KIND_LABEL,
  PROJECT_DELTA_KIND_SYMBOL,
  PROJECT_DELTA_PAGE_SIZE,
  describeDeltaValues,
  filterProjectDeltaChanges,
  prettyDeltaDocument,
  type ProjectDelta,
  type ProjectDeltaChangeKind,
  type ProjectDeltaFilter,
  type ProjectDeltaSeverity,
  type ProjectDeltaState,
} from '../../../utils/import-project-delta';
import type { ImportVersionPlan } from '../../../utils/import-version-label';
import { IMPORT_WIZARD_COPY, noChangesTitle, type ImportMergeChoice } from './importWizardModel';

/** Badge tone for each grade; an ungraded change shows no badge. */
const SEVERITY_VARIANT: Readonly<Record<ProjectDeltaSeverity, 'danger' | 'warn' | 'ok'>> = {
  breaking: 'danger',
  unknown: 'warn',
  safe: 'ok',
};

export interface ImportChangesPanelProps {
  /** Where the comparison stands. */
  state: ProjectDeltaState;
  /** Ask again after an error. */
  onRetry: () => void;
  /** Page size override; tests pass a small value. */
  pageSize?: number;
  /** The version label the import will create (#590); says so when the requested one is taken. */
  versionPlan?: ImportVersionPlan | null;
  /** The chosen merge strategy (#591); the choice is shown only when a change handler is given. */
  mergeChoice?: ImportMergeChoice;
  /** Called when the reader picks a merge strategy (#591). */
  onMergeChoiceChange?: (choice: ImportMergeChoice) => void;
}

/**
 * The merge-strategy choice (#591): replace (default) or additive merge, each with a one-line hint.
 *
 * @param props.value The chosen strategy.
 * @param props.onChange Called with the new strategy.
 * @returns A fieldset with one radio per strategy.
 */
function MergeChoice({ value, onChange }: { value: ImportMergeChoice; onChange: (choice: ImportMergeChoice) => void }) {
  const options: Array<{ value: ImportMergeChoice; label: string; hint: string }> = [
    { value: 'replace', label: IMPORT_WIZARD_COPY.changesMergeReplace, hint: IMPORT_WIZARD_COPY.changesMergeReplaceHint },
    { value: 'additive', label: IMPORT_WIZARD_COPY.changesMergeAdditive, hint: IMPORT_WIZARD_COPY.changesMergeAdditiveHint },
  ];
  return (
    <fieldset className="imp-changes__merge" data-testid="import-changes-merge">
      <legend className="imp-changes__merge-legend">{IMPORT_WIZARD_COPY.changesMergeLegend}</legend>
      <RadioGroup value={value} onValueChange={(v) => onChange(v as ImportMergeChoice)}>
        {options.map((o) => (
          <RadioGroupItem
            key={o.value}
            value={o.value}
            name="import-merge-strategy"
            data-testid={`import-changes-merge-${o.value}`}
            label={
              <span>
                {o.label}
                <span className="imp-changes__merge-hint">{o.hint}</span>
              </span>
            }
          />
        ))}
      </RadioGroup>
    </fieldset>
  );
}

/** One summary-bar count: symbol, number, word. */
function SummaryCount({ kind, count }: { kind: ProjectDeltaChangeKind; count: number }) {
  return (
    <span className="imp-changes__count" data-kind={kind} data-testid={`import-changes-count-${kind}`}>
      <span aria-hidden>{PROJECT_DELTA_KIND_SYMBOL[kind]}</span>
      <span className="imp-changes__count-num">{count}</span> {kind}
    </span>
  );
}

/** The delta itself: header, summary bar, tabs. */
function ChangesView({
  delta,
  pageSize,
  versionPlan,
  mergeChoice = 'replace',
  onMergeChoiceChange,
}: {
  delta: ProjectDelta;
  pageSize: number;
  versionPlan?: ImportVersionPlan | null;
  mergeChoice?: ImportMergeChoice;
  onMergeChoiceChange?: (choice: ImportMergeChoice) => void;
}) {
  const [tab, setTab] = useState('summary');
  const [filter, setFilter] = useState<ProjectDeltaFilter>('all');
  const [query, setQuery] = useState('');
  const [shown, setShown] = useState(pageSize);

  const rows = useMemo(
    () => filterProjectDeltaChanges(delta.changes, filter, query),
    [delta.changes, filter, query],
  );
  const visible = rows.slice(0, shown);
  const { counts } = delta;
  const versionLabel = delta.base_version_label ? `v${delta.base_version_label}` : '';

  return (
    <section className="imp-changes" data-testid="import-changes" aria-labelledby="import-changes-heading">
      <h2 id="import-changes-heading" className="imp-heading">
        <GitCompareArrows aria-hidden />
        {IMPORT_WIZARD_COPY.changesHeadingPrefix} {delta.project_name} {versionLabel}
        <Badge variant="neutral">{IMPORT_WIZARD_COPY.changesLatestBadge}</Badge>
      </h2>

      <div className="imp-changes__summary" data-testid="import-changes-summary">
        <SummaryCount kind="added" count={counts.added} />
        <SummaryCount kind="changed" count={counts.changed} />
        <SummaryCount kind="removed" count={counts.removed} />
        {counts.breaking > 0 ? (
          <span className="imp-changes__count" data-kind="breaking" data-testid="import-changes-count-breaking">
            <span aria-hidden>⚠</span>
            <span className="imp-changes__count-num">{counts.breaking}</span> breaking
          </span>
        ) : null}
      </div>

      {versionPlan?.taken ? (
        // #590: the requested label exists, so the import adds a sub-version instead of failing.
        <Alert variant="info" data-testid="import-changes-version-taken">
          <span className="font-semibold">{IMPORT_WIZARD_COPY.changesVersionTakenTitle}</span> — {delta.project_name}{' '}
          already has version <code className="mono">{versionPlan.requested}</code>, so this import is added as{' '}
          <code className="mono">{versionPlan.label}</code>, a new sub-version. Nothing existing changes. To use a
          different number, go <span className="font-semibold">Back</span> and change <span className="font-semibold">Version</span> on Preview.
        </Alert>
      ) : null}

      {onMergeChoiceChange ? <MergeChoice value={mergeChoice} onChange={onMergeChoiceChange} /> : null}

      {mergeChoice === 'additive' && counts.removed > 0 ? (
        // #591: an additive merge keeps what the latest version has, so "removed" rows stay.
        <Alert variant="info" data-testid="import-changes-merge-kept">
          <span className="font-semibold">{IMPORT_WIZARD_COPY.changesMergeRemovedKept}</span> — the {counts.removed}{' '}
          {counts.removed === 1 ? 'item' : 'items'} listed as <span className="font-semibold">Removed</span>{' '}
          {counts.removed === 1 ? 'stays' : 'stay'} in the new version {versionLabel ? `as they are in ${versionLabel}` : 'as they are'}.
        </Alert>
      ) : null}

      {counts.breaking > 0 ? (
        <Alert variant="warn" data-testid="import-changes-breaking">
          <span className="font-semibold">{IMPORT_WIZARD_COPY.changesBreakingTitle}</span> —{' '}
          {IMPORT_WIZARD_COPY.changesBreakingBody}
        </Alert>
      ) : null}

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList aria-label="Changes view">
          <TabsTrigger value="summary">
            {IMPORT_WIZARD_COPY.changesSummaryTab}
            <TabsCount>{counts.total}</TabsCount>
          </TabsTrigger>
          <TabsTrigger value="side-by-side">{IMPORT_WIZARD_COPY.changesSideBySideTab}</TabsTrigger>
        </TabsList>

        <TabsContent value="summary">
          {counts.total === 0 ? (
            <EmptyState
              variant="compact"
              title={noChangesTitle(delta.base_version_label)}
              description="Paths, operations and schemas match the latest version. Importing still adds a version."
              data-testid="import-changes-none"
            />
          ) : (
            <div className="imp-changes__list-wrap">
              <div className="imp-changes__filters">
                <label className="imp-changes__filter">
                  <span>{IMPORT_WIZARD_COPY.changesFilterLabel}</span>
                  <select
                    className="imp-select"
                    value={filter}
                    onChange={(e) => {
                      setFilter(e.target.value as ProjectDeltaFilter);
                      setShown(pageSize);
                    }}
                    data-testid="import-changes-filter"
                  >
                    {PROJECT_DELTA_FILTERS.map((f) => (
                      <option key={f.value} value={f.value}>
                        {f.label}
                      </option>
                    ))}
                  </select>
                </label>
                <Input
                  type="search"
                  aria-label={IMPORT_WIZARD_COPY.changesSearchLabel}
                  placeholder={IMPORT_WIZARD_COPY.changesSearchLabel}
                  value={query}
                  onChange={(e) => {
                    setQuery(e.target.value);
                    setShown(pageSize);
                  }}
                />
              </div>

              <ul className="imp-changes__list" aria-label="Changes" data-testid="import-changes-list">
                {visible.map((change, index) => {
                  const values = describeDeltaValues(change);
                  return (
                    <li
                      key={change.pointer}
                      className="imp-changes__row"
                      data-kind={change.kind}
                      data-severity={change.severity ?? 'ungraded'}
                      aria-setsize={rows.length}
                      aria-posinset={index + 1}
                    >
                      <span className="imp-changes__kind">
                        <span aria-hidden>{PROJECT_DELTA_KIND_SYMBOL[change.kind]}</span>{' '}
                        {PROJECT_DELTA_KIND_LABEL[change.kind]}
                      </span>
                      <span className="imp-changes__label" title={change.pointer}>
                        {change.label}
                        {values ? <span className="imp-changes__values"> {values}</span> : null}
                      </span>
                      {change.severity ? (
                        <Badge variant={SEVERITY_VARIANT[change.severity]} title={change.message ?? undefined}>
                          {change.severity}
                        </Badge>
                      ) : null}
                    </li>
                  );
                })}
              </ul>
              {rows.length === 0 ? <p className="imp-changes__note">No changes match this filter.</p> : null}
              {rows.length > visible.length ? (
                <Button variant="outline" size="sm" onClick={() => setShown((n) => n + pageSize)}>
                  {IMPORT_WIZARD_COPY.changesShowMore} ({rows.length - visible.length})
                </Button>
              ) : null}
              {delta.truncated ? <p className="imp-changes__note">{IMPORT_WIZARD_COPY.changesTruncated}</p> : null}
            </div>
          )}
        </TabsContent>

        <TabsContent value="side-by-side">
          <JsonDiffViewer
            original={prettyDeltaDocument(delta.base_document)}
            modified={prettyDeltaDocument(delta.incoming_document)}
            originalAriaLabel={`${IMPORT_WIZARD_COPY.changesBeforeLabel} ${versionLabel}`.trim()}
            modifiedAriaLabel={IMPORT_WIZARD_COPY.changesAfterLabel}
            maxLines={24}
          />
        </TabsContent>
      </Tabs>
    </section>
  );
}

/**
 * The Changes step for a {@link ProjectDeltaState}.
 *
 * @param props See {@link ImportChangesPanelProps}.
 * @returns The loading, error or delta view; nothing for `idle` / `skip` (the step is not shown).
 */
export function ImportChangesPanel({
  state,
  onRetry,
  pageSize = PROJECT_DELTA_PAGE_SIZE,
  versionPlan,
  mergeChoice,
  onMergeChoiceChange,
}: ImportChangesPanelProps) {
  if (state.status === 'checking') {
    return <LoadingState message="Comparing with the latest version…" />;
  }
  if (state.status === 'error') {
    return (
      <div className="imp-changes">
        <ErrorState
          title={IMPORT_WIZARD_COPY.changesErrorTitle}
          description={`${state.message} You can still continue to import.`}
          onRetry={onRetry}
          data-testid="import-changes-error"
        />
        {onMergeChoiceChange ? <MergeChoice value={mergeChoice ?? 'replace'} onChange={onMergeChoiceChange} /> : null}
      </div>
    );
  }
  if (state.status === 'ready') {
    return (
      <ChangesView
        delta={state.delta}
        pageSize={pageSize}
        versionPlan={versionPlan}
        mergeChoice={mergeChoice}
        onMergeChoiceChange={onMergeChoiceChange}
      />
    );
  }
  return null;
}
