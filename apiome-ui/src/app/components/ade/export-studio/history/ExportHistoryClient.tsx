'use client';

/**
 * ExportHistoryClient — Export studio's **History** tab (MFX-46.1, #4379).
 *
 * The workspace's answer to "who exported what, where, with how much loss?": every export run, newest
 * first, from the export run ledger. Each row shows the source and version → target, the share
 * preserved, the validation and lint verdicts, the delivery decision and deliveries, who ran it and
 * when. Filters narrow it by source, target, person, outcome, delivery channel, verdicts and dates.
 *
 * Opening a row shows the run read-only — its deliveries and, per target, the fidelity report, the
 * validation report and the delivery gate exactly as they were stored — with **Re-run in Studio**, which
 * opens Export studio on the same source, version, target and options (`./exportHistoryModel.ts`).
 *
 * The history is scoped to the signed-in workspace by the server; it needs `projects:view`.
 */

import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import Link from 'next/link';
import { History, RotateCcw } from 'lucide-react';
import { Badge } from '@/app/components/ui/Badge';
import { Button } from '@/app/components/ui/Button';
import { EmptyState } from '@/app/components/ui/EmptyState';
import { ErrorState } from '@/app/components/ui/ErrorState';
import {
  DataTable,
  DataTableCellPrimary,
  DataTableCellSub,
  DataTableClearFilters,
  DataTableFoot,
  DataTablePager,
  DataTableToolbar,
  dataTablePageCount,
  dataTableRangeLabel,
  type DataTableColumn,
} from '@/app/components/ui/DataTable';
import { Drawer, DrawerBody, DrawerContent, DrawerHeader, DrawerTitle } from '@/app/components/ui/Drawer';
import { Skeleton } from '@/app/components/ui/Skeleton';
import PageHeader from '@/app/components/shell/PageHeader';
import { Page, PageBody } from '@/app/components/shell/pageChrome';
import { DeliveryGatePanel } from '../../dashboard/export/DeliveryGatePanel';
import { ValidationResultsLens } from '../../dashboard/export/ValidationResultsLens';
import { FidelityReportRow } from '../../dashboard/export/FidelityWarningPanel';
import type { DeliveryGateReport } from '../../dashboard/export/exportJob';
import type { EmittedValidationReport } from '../../dashboard/export/exportVerify';
import type { LossItem } from '../../dashboard/export/exportFidelityPreview';
import { fetchExportRun, fetchExportRunActors, fetchExportRuns } from './exportHistoryApi';
import {
  EMPTY_FILTERS,
  HISTORY_PAGE_SIZE,
  RUN_CHANNELS,
  RUN_DECISIONS,
  RUN_STATES,
  RUN_VALIDATIONS,
  activeFilterCount,
  channelLabel,
  decisionVerdict,
  deliverySummary,
  hasFilters,
  lintVerdict,
  preservedTone,
  rerunHref,
  sourceLabel,
  stateVerdict,
  validationVerdict,
  type ExportRunActor,
  type ExportRunDetail,
  type ExportRunSummary,
  type HistoryFilters,
  type Verdict,
} from './exportHistoryModel';

export interface ExportHistoryClientProps {
  /** The Export studio tab strip, drawn in the header. */
  tabs?: ReactNode;
}

/** A verdict as a badge — its word and its tone, never colour alone. */
function VerdictBadge({ verdict, testId }: { verdict: Verdict | null; testId?: string }) {
  if (!verdict) return <span className="xhis-none">—</span>;
  return (
    <Badge variant={verdict.tone} data-testid={testId}>
      {verdict.label}
    </Badge>
  );
}

/** When a run finished, in the reader's locale. */
function when(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString();
}

/** One filter select: its label, "any", and the allowed values in words. */
function FilterSelect({
  id,
  label,
  value,
  options,
  onChange,
}: {
  id: keyof HistoryFilters;
  label: string;
  value: string;
  options: ReadonlyArray<{ value: string; label: string }>;
  onChange: (value: string) => void;
}) {
  return (
    <select
      className="hive-control xhis-filter"
      aria-label={label}
      data-testid={`export-history-filter-${id}`}
      value={value}
      onChange={(event) => onChange(event.target.value)}
    >
      <option value="">{label}: any</option>
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  );
}

export default function ExportHistoryClient({ tabs }: ExportHistoryClientProps = {}) {
  const [filters, setFilters] = useState<HistoryFilters>(EMPTY_FILTERS);
  const [page, setPage] = useState(0);
  const [runs, setRuns] = useState<ExportRunSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [actors, setActors] = useState<ExportRunActor[]>([]);
  // The sources and targets seen so far — the history is the only list of what has been exported.
  const [seenSources, setSeenSources] = useState<Map<string, string>>(new Map());
  const [seenTargets, setSeenTargets] = useState<Set<string>>(new Set());
  const [openRun, setOpenRun] = useState<ExportRunSummary | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const result = await fetchExportRuns(filters, page);
        if (cancelled) return;
        setRuns(result.runs);
        setTotal(result.total);
        setSeenSources((current) => {
          const next = new Map(current);
          for (const run of result.runs) next.set(run.artifact_id, run.artifact_name || run.artifact_id);
          return next;
        });
        setSeenTargets((current) => {
          const next = new Set(current);
          for (const run of result.runs) for (const target of run.target.split(',')) if (target) next.add(target);
          return next;
        });
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : 'The export history could not be loaded.');
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, [filters, page, attempt]);

  useEffect(() => {
    let cancelled = false;
    fetchExportRunActors()
      .then((list) => {
        if (!cancelled) setActors(list);
      })
      .catch(() => undefined); // The actor filter is a convenience; the history works without it.
    return () => {
      cancelled = true;
    };
  }, []);

  /** Change one filter, back to the first page. */
  const setFilter = useCallback((key: keyof HistoryFilters, value: string) => {
    setFilters((current) => ({ ...current, [key]: value }));
    setPage(0);
  }, []);

  const narrowed = hasFilters(filters);
  const pageCount = dataTablePageCount(total, HISTORY_PAGE_SIZE);

  const columns = useMemo<DataTableColumn<ExportRunSummary>[]>(
    () => [
      {
        id: 'source',
        header: 'Source → target',
        cell: (run) => (
          <>
            <DataTableCellPrimary>{sourceLabel(run)}</DataTableCellPrimary>
            <DataTableCellSub className="mono">
              → {run.target}
              {run.dry_run ? ' · dry run' : ''}
            </DataTableCellSub>
          </>
        ),
      },
      {
        id: 'outcome',
        header: 'Outcome',
        cell: (run) => <VerdictBadge verdict={stateVerdict(run.state)} testId="export-history-state" />,
      },
      {
        id: 'preserved',
        header: 'Preserved',
        align: 'end',
        cell: (run) =>
          run.preserved_percent == null ? (
            <span className="xhis-none">—</span>
          ) : (
            <Badge variant={preservedTone(run.preserved_percent)} data-testid="export-history-preserved">
              {run.preserved_percent}%
            </Badge>
          ),
      },
      {
        id: 'validation',
        header: 'Validation',
        cell: (run) => <VerdictBadge verdict={validationVerdict(run.validation_verdict)} />,
      },
      { id: 'lint', header: 'Lint', cell: (run) => <VerdictBadge verdict={lintVerdict(run.lint_verdict)} /> },
      {
        id: 'delivery',
        header: 'Delivery',
        cell: (run) => (
          <>
            <VerdictBadge verdict={decisionVerdict(run.delivery_decision)} />
            <DataTableCellSub data-testid="export-history-deliveries">
              {deliverySummary(run.deliveries) ?? 'Not delivered'}
            </DataTableCellSub>
          </>
        ),
      },
      {
        id: 'actor',
        header: 'By',
        cell: (run) => (
          <>
            <DataTableCellPrimary>{run.actor_label}</DataTableCellPrimary>
            <DataTableCellSub>{when(run.finished_at)}</DataTableCellSub>
          </>
        ),
      },
    ],
    [],
  );

  return (
    <Page data-testid="export-history">
      <PageHeader
        breadcrumb={[{ label: 'Home', href: '/ade/dashboard' }, { label: 'Ship' }, { label: 'Export studio' }]}
        title="Export studio"
        description="Every export in this workspace: who exported what, where, and with how much loss."
        tabs={tabs}
      />
      <PageBody>
        <DataTable
          caption="Export history"
          columns={columns}
          rows={runs}
          getRowId={(run) => run.job_id}
          getRowLabel={(run) => `${sourceLabel(run)} to ${run.target}`}
          onRowActivate={(run) => setOpenRun(run)}
          loading={loading}
          error={error ?? undefined}
          errorTitle="The export history could not be loaded"
          onRetry={() => setAttempt((count) => count + 1)}
          toolbar={
            <DataTableToolbar className="xhis-toolbar">
              <FilterSelect
                id="artifact"
                label="Source"
                value={filters.artifact}
                options={[...seenSources].map(([value, label]) => ({ value, label }))}
                onChange={(value) => setFilter('artifact', value)}
              />
              <FilterSelect
                id="target"
                label="Target"
                value={filters.target}
                options={[...seenTargets].sort().map((value) => ({ value, label: value }))}
                onChange={(value) => setFilter('target', value)}
              />
              <FilterSelect
                id="actor"
                label="By"
                value={filters.actor}
                options={actors.map((actor) => ({ value: actor.actor_id, label: actor.actor_label }))}
                onChange={(value) => setFilter('actor', value)}
              />
              <FilterSelect
                id="state"
                label="Outcome"
                value={filters.state}
                options={RUN_STATES.map((value) => ({ value, label: stateVerdict(value).label }))}
                onChange={(value) => setFilter('state', value)}
              />
              <FilterSelect
                id="channel"
                label="Delivered to"
                value={filters.channel}
                options={RUN_CHANNELS.map((value) => ({ value, label: channelLabel(value) }))}
                onChange={(value) => setFilter('channel', value)}
              />
              <FilterSelect
                id="validation"
                label="Validation"
                value={filters.validation}
                options={RUN_VALIDATIONS.map((value) => ({ value, label: validationVerdict(value)!.label }))}
                onChange={(value) => setFilter('validation', value)}
              />
              <FilterSelect
                id="decision"
                label="Delivery gate"
                value={filters.decision}
                options={RUN_DECISIONS.map((value) => ({ value, label: decisionVerdict(value)!.label }))}
                onChange={(value) => setFilter('decision', value)}
              />
              <input
                type="date"
                className="hive-control xhis-filter"
                aria-label="From"
                data-testid="export-history-filter-from"
                value={filters.from}
                onChange={(event) => setFilter('from', event.target.value)}
              />
              <input
                type="date"
                className="hive-control xhis-filter"
                aria-label="To"
                data-testid="export-history-filter-to"
                value={filters.to}
                onChange={(event) => setFilter('to', event.target.value)}
              />
              <DataTableClearFilters
                count={activeFilterCount(filters)}
                data-testid="export-history-clear"
                onClick={() => {
                  setFilters(EMPTY_FILTERS);
                  setPage(0);
                }}
              />
            </DataTableToolbar>
          }
          empty={
            <EmptyState
              variant="compact"
              icon={<History aria-hidden />}
              title={narrowed ? 'No exports match these filters' : 'No exports yet'}
              description={
                narrowed
                  ? 'Clear the filters or widen the dates.'
                  : 'Every export run in this workspace appears here once it finishes, for 90 days.'
              }
            />
          }
          footer={
            <DataTableFoot>
              <span data-testid="export-history-range">
                {dataTableRangeLabel(page + 1, HISTORY_PAGE_SIZE, total, 'run')}
              </span>
              <DataTablePager
                page={page + 1}
                pageCount={pageCount}
                onPageChange={(next) => setPage(next - 1)}
                label="Export history pages"
              />
            </DataTableFoot>
          }
        />
      </PageBody>
      <RunDrawer run={openRun} onClose={() => setOpenRun(null)} />
    </Page>
  );
}

/** The read-only detail of one run, with its stored reports. */
function RunDrawer({ run, onClose }: { run: ExportRunSummary | null; onClose: () => void }) {
  // What was loaded, for which run: a different run reads as "loading" until its own answer arrives.
  const [loaded, setLoaded] = useState<{ jobId: string; detail?: ExportRunDetail; error?: string } | null>(null);
  const jobId = run?.job_id ?? null;
  const current = loaded && loaded.jobId === jobId ? loaded : null;
  const detail = current?.detail ?? null;
  const error = current?.error ?? null;
  // MFX-46.5: Retry reads the run again.
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!jobId) return;
    let cancelled = false;
    fetchExportRun(jobId)
      .then((result) => {
        if (!cancelled) setLoaded({ jobId, detail: result });
      })
      .catch((err) => {
        if (!cancelled) {
          setLoaded({ jobId, error: err instanceof Error ? err.message : 'The run could not be loaded.' });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [jobId, attempt]);

  return (
    <Drawer open={run !== null} onOpenChange={(open) => !open && onClose()}>
      <DrawerContent size="lg" data-testid="export-history-detail" aria-describedby={undefined}>
        {run && (
          <>
            <DrawerHeader>
              <DrawerTitle>{sourceLabel(run)}</DrawerTitle>
              <p className="xhis-sub mono">→ {run.target}</p>
            </DrawerHeader>
            <DrawerBody className="xhis-detail">
              <div className="xhis-facts">
                <VerdictBadge verdict={stateVerdict(run.state)} />
                {run.preserved_percent != null && (
                  <Badge variant={preservedTone(run.preserved_percent)}>{run.preserved_percent}% preserved</Badge>
                )}
                <span className="xhis-sub">
                  {run.actor_label} · {when(run.finished_at)}
                </span>
              </div>
              {run.error_message && (
                <p className="xhis-error" data-testid="export-history-error">
                  {run.error_code ? <code className="mono">{run.error_code}</code> : null} {run.error_message}
                </p>
              )}
              <Button asChild variant="outline" size="sm" data-testid="export-history-rerun">
                <Link href={rerunHref(run)}>
                  <RotateCcw aria-hidden />
                  Re-run in Studio
                </Link>
              </Button>

              <section aria-label="Deliveries" className="xhis-section">
                <h3 className="xhis-heading">Deliveries</h3>
                {run.deliveries.length === 0 ? (
                  <p className="xhis-sub">Not delivered to a git repository, webhook or bucket.</p>
                ) : (
                  <ul className="xhis-deliveries" data-testid="export-history-detail-deliveries">
                    {run.deliveries.map((delivery, index) => (
                      <li key={`${delivery.channel}-${index}`} className="xhis-delivery">
                        <Badge
                          variant={
                            delivery.outcome === 'delivered' ? 'ok' : delivery.outcome === 'failed' ? 'danger' : 'warn'
                          }
                        >
                          {channelLabel(delivery.channel)} · {delivery.status.replace(/_/g, ' ')}
                        </Badge>
                        {delivery.destination ? <span className="mono xhis-sub">{delivery.destination}</span> : null}
                        {delivery.error_code ? <code className="mono xhis-sub">{delivery.error_code}</code> : null}
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              {error && (
                <ErrorState
                  variant="compact"
                  title="This run's reports could not be loaded"
                  description={error}
                  data-testid="export-history-detail-error"
                  onRetry={() => {
                    setLoaded(null);
                    setAttempt((count) => count + 1);
                  }}
                />
              )}
              {!detail && !error && <Skeleton className="xhis-skeleton" />}
              {detail?.reports.length === 0 && (
                <p className="xhis-sub" data-testid="export-history-no-reports">
                  This run stopped before any report was made.
                </p>
              )}
              {detail?.reports.map((report, index) => (
                <TargetReports key={`${report.target ?? 'target'}-${index}`} report={report} />
              ))}
            </DrawerBody>
          </>
        )}
      </DrawerContent>
    </Drawer>
  );
}

/** One target's stored reports, read-only: fidelity findings, validation, the delivery gate. */
function TargetReports({ report }: { report: ExportRunDetail['reports'][number] }) {
  const items = ((report.fidelity?.report as { items?: LossItem[] } | undefined)?.items ?? []).filter(
    (item) => item.kind !== 'ok',
  );
  const summary = report.fidelity?.summary as { tier?: string; preserved_percent?: number } | undefined;
  return (
    <section aria-label={`Reports for ${report.target ?? 'the target'}`} className="xhis-section"
      data-testid="export-history-target-report">
      <h3 className="xhis-heading mono">{report.target ?? 'Target'}</h3>
      <h4 className="xhis-subheading">Fidelity</h4>
      {report.fidelity ? (
        <>
          <p className="xhis-sub">
            {summary?.tier ?? 'unknown'} · {summary?.preserved_percent ?? '—'}% preserved ·{' '}
            {items.length} finding{items.length === 1 ? '' : 's'} beyond OK
          </p>
          {items.length > 0 && (
            <ul className="xhis-findings">
              {items.map((item, index) => (
                <FidelityReportRow key={`${item.construct}-${item.kind}-${index}`} item={item} />
              ))}
            </ul>
          )}
        </>
      ) : (
        <p className="xhis-sub">No fidelity report was stored.</p>
      )}
      <h4 className="xhis-subheading">Validation</h4>
      {report.validation ? (
        <ValidationResultsLens validation={report.validation as unknown as EmittedValidationReport} />
      ) : (
        <p className="xhis-sub">Not validated (a dry run, or the run stopped first).</p>
      )}
      <h4 className="xhis-subheading">Delivery gate</h4>
      {report.delivery_gate ? (
        <DeliveryGatePanel delivery={report.delivery_gate as unknown as DeliveryGateReport} />
      ) : (
        <p className="xhis-sub">No delivery gate ran.</p>
      )}
    </section>
  );
}
