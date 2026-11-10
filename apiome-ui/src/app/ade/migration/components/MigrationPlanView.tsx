'use client';

import * as React from 'react';
import dynamic from 'next/dynamic';
import { useMigration } from '../MigrationContext';
import {
  ClipboardList,
  Search,
  FileJson,
  ChevronLeft,
  ChevronRight,
  List,
  Play,
  BarChart3,
  ShieldCheck,
  Database,
} from 'lucide-react';

const MonacoEditor = dynamic(() => import('@monaco-editor/react'), { ssr: false });
import { Switch } from '../../../components/ui/Switch';
import { CODE_EDITOR_FONT_SIZE } from '@/app/components/ui/code/editorTypography';
import { EmptyState } from '@/app/components/ui/EmptyState';
import { LoadingState } from '@/app/components/ui/LoadingState';
import { SkeletonText } from '@/app/components/ui/Skeleton';

const PAGE_SIZE = 20;

type SnapshotRow = {
  record_id: string;
  data: Record<string, unknown>;
  updated_at: string;
  created_at?: string;
  record_sequence?: number;
  last_action?: string;
};

function formatDateTime(iso: string | undefined): string {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    return d.toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'short' });
  } catch {
    return iso;
  }
}

/** Plan-level data quality confidence (1–100%) from rules coverage. */
function getPlanConfidencePercent(rulesAppliedCount: number, totalProperties: number): number {
  if (rulesAppliedCount === 0) return 1;
  if (totalProperties === 0) return rulesAppliedCount >= 1 ? 100 : 1;
  const coverage = rulesAppliedCount / totalProperties;
  const raw = Math.round(coverage * 100);
  return Math.max(1, Math.min(100, raw));
}

/** Record-level confidence (1–100%) from transformed data vs target schema: completeness of required + optional fields. */
function getRecordConfidencePercent(
  transformedData: Record<string, unknown>,
  targetSchema: Record<string, unknown> | null | undefined
): number {
  if (!targetSchema || typeof targetSchema !== 'object') return 100;
  const props = targetSchema.properties as Record<string, unknown> | undefined;
  const required = targetSchema.required as string[] | undefined;
  const expectedKeys = props && typeof props === 'object' ? Object.keys(props) : [];
  if (expectedKeys.length === 0) return 100;
  let filled = 0;
  for (const key of expectedKeys) {
    const v = transformedData[key];
    if (v !== undefined && v !== null && v !== '') filled++;
  }
  const raw = Math.round((filled / expectedKeys.length) * 100);
  return Math.max(1, Math.min(100, raw));
}

/** Result of applying rules to the current record (cleared when selection changes). */
type TransformResult = {
  data: Record<string, unknown>;
  transformedAt: string;
  rulesAppliedCount: number;
};

export default function MigrationPlanView() {
  const { selectedClassName, fromTables, toTables, migrationRules } = useMigration();
  const [rows, setRows] = React.useState<SnapshotRow[]>([]);
  const [total, setTotal] = React.useState(0);
  const [page, setPage] = React.useState(1);
  const [loading, setLoading] = React.useState(false);
  const [searchQ, setSearchQ] = React.useState('');
  const [viewMode, setViewMode] = React.useState<'none' | 'viewAll' | 'search'>('none');
  const [selectedRecord, setSelectedRecord] = React.useState<SnapshotRow | null>(null);
  const [transformResult, setTransformResult] = React.useState<TransformResult | null>(null);
  const [evaluateLoading, setEvaluateLoading] = React.useState(false);
  const [evaluateError, setEvaluateError] = React.useState<string | null>(null);
  const [autoApply, setAutoApply] = React.useState(false);

  const fromRow = selectedClassName
    ? fromTables.find((r) => r.class_name === selectedClassName)
    : null;
  const toRow = selectedClassName
    ? toTables.find((r) => r.class_name === selectedClassName)
    : null;
  const classSchemaId = fromRow?.class_schema_id ?? null;
  const transformedData = transformResult?.data ?? null;

  const runQuery = React.useCallback(
    (pageNum: number, searchQuery?: string) => {
      if (!classSchemaId) return;
      setLoading(true);
      const params = new URLSearchParams({
        classSchemaId,
        page: String(pageNum),
        pageSize: String(PAGE_SIZE),
        orderBy: 'updated_at',
        orderDir: 'desc',
      });
      const url = searchQuery
        ? `/api/database/snapshot/search?${params.toString()}&q=${encodeURIComponent(searchQuery)}`
        : `/api/database/snapshot?${params.toString()}`;
      fetch(url)
        .then((r) => r.json())
        .then((data) => {
          if (data.success && data.rows) {
            setRows(data.rows);
            setTotal(data.total ?? 0);
            setPage(data.page ?? pageNum);
          }
        })
        .finally(() => setLoading(false));
    },
    [classSchemaId]
  );

  React.useEffect(() => {
    if (!classSchemaId) {
      setRows([]);
      setTotal(0);
      setPage(1);
      setViewMode('none');
      setSelectedRecord(null);
      setTransformResult(null);
      setEvaluateError(null);
      return;
    }
    setViewMode('viewAll');
    setSelectedRecord(null);
    setTransformResult(null);
    setEvaluateError(null);
    runQuery(1, undefined);
  }, [classSchemaId]); // eslint-disable-line react-hooks/exhaustive-deps -- only reset when class changes

  const handleViewAll = () => {
    setViewMode('viewAll');
    if (classSchemaId) runQuery(1, undefined);
  };

  const handleSearch = () => {
    setViewMode('search');
    if (classSchemaId) runQuery(1, searchQ);
  };

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const currentIndex = selectedRecord ? rows.findIndex((r) => r.record_id === selectedRecord.record_id) : -1;
  const hasPrev = currentIndex > 0;
  const hasNext = currentIndex >= 0 && currentIndex < rows.length - 1;

  const goPrev = () => {
    if (!hasPrev || currentIndex <= 0) return;
    const prev = rows[currentIndex - 1];
    setSelectedRecord(prev);
    setTransformResult(null);
    setEvaluateError(null);
  };

  const goNext = () => {
    if (!hasNext || currentIndex >= rows.length - 1) return;
    const next = rows[currentIndex + 1];
    setSelectedRecord(next);
    setTransformResult(null);
    setEvaluateError(null);
  };

  const handlePageChange = (newPage: number) => {
    if (!classSchemaId) return;
    if (viewMode === 'search') runQuery(newPage, searchQ);
    else runQuery(newPage, undefined);
    setSelectedRecord(null);
    setTransformResult(null);
    setEvaluateError(null);
  };

  const runEvaluate = React.useCallback(
    (record: SnapshotRow) => {
      if (!migrationRules) return;
      setEvaluateLoading(true);
      setEvaluateError(null);
      fetch('/api/migration-plans/evaluate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ recordData: record.data, rules: migrationRules }),
      })
        .then((r) => r.json())
        .then((data) => {
          if (data.success && data.transformedData !== undefined) {
            setTransformResult({
              data: data.transformedData as Record<string, unknown>,
              transformedAt: new Date().toISOString(),
              rulesAppliedCount: typeof data.rulesAppliedCount === 'number' ? data.rulesAppliedCount : 0,
            });
          } else {
            setEvaluateError(data.error ?? 'Evaluate failed');
          }
        })
        .catch(() => setEvaluateError('Request failed'))
        .finally(() => setEvaluateLoading(false));
    },
    [migrationRules]
  );

  const handleEvaluate = React.useCallback(() => {
    if (!selectedRecord || !migrationRules) return;
    runEvaluate(selectedRecord);
  }, [selectedRecord, migrationRules, runEvaluate]);

  React.useEffect(() => {
    if (!autoApply || !selectedRecord || !migrationRules) return;
    runEvaluate(selectedRecord);
  }, [autoApply, selectedRecord?.record_id, migrationRules]); // eslint-disable-line react-hooks/exhaustive-deps -- only run when record or autoApply changes

  const rulesAppliedCount = React.useMemo(() => {
    if (!migrationRules || typeof migrationRules !== 'object') return 0;
    return Object.values(migrationRules).filter(
      (r) => r && typeof r === 'object' && (r.ruleContent?.trim?.()?.length ?? 0) > 0
    ).length;
  }, [migrationRules]);

  const totalProperties = React.useMemo(() => {
    const fromSchema = fromRow?.schema;
    if (!fromSchema || typeof fromSchema !== 'object') return 0;
    const props = (fromSchema as { properties?: Record<string, unknown> }).properties;
    return props && typeof props === 'object' ? Object.keys(props).length : 0;
  }, [fromRow]);

  /** Before: source record vs source (from) schema. */
  const beforeConfidencePercent = React.useMemo(() => {
    if (!selectedRecord?.data || !fromRow?.schema) return null;
    return getRecordConfidencePercent(selectedRecord.data, fromRow.schema);
  }, [selectedRecord?.data, fromRow?.schema]);
  /** After: transformed record vs target (to) schema; null until rules are applied. */
  const afterConfidencePercent = React.useMemo(() => {
    if (!transformResult?.data || !toRow?.schema) return null;
    return getRecordConfidencePercent(transformResult.data, toRow.schema);
  }, [transformResult?.data, toRow?.schema]);

  if (!selectedClassName) {
    return (
      <div className="h-full flex flex-col min-h-0 p-6">
        <div className="flex items-center gap-3 mb-4">
          <div className="p-2 rounded-lg bg-accent-soft text-accent-fg">
            <ClipboardList className="h-5 w-5" />
          </div>
          <div>
            <h2 className="text-lg font-semibold text-fg">Explorer</h2>
            <p className="text-sm text-fg-muted">
              Explore datasets and preview before/after transformation for the selected schema.
            </p>
          </div>
        </div>
        <div className="flex-1 rounded-xl border border-border bg-subtle/50 flex items-center justify-center p-6">
          <p className="text-fg-muted text-sm text-center">
            Select a class in the sidebar to explore records and see before/after data with rules applied.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col min-h-0 overflow-hidden">
      {/* Top 30%: Stats when a record is selected, otherwise placeholder */}
      <div className="flex-[0_0_30%] min-h-0 flex flex-col overflow-hidden border-b border-border">
        <div className="px-6 py-4 bg-subtle/50 h-full flex items-center justify-center">
          {!selectedRecord ? (
            <p className="text-sm text-fg-muted text-center">
              Select a record to evaluate the currently defined ruleset.
            </p>
          ) : (
            <div className="grid grid-cols-3 gap-4 w-full max-w-4xl">
              <div className="flex items-center gap-3 rounded-lg border border-border bg-surface px-4 py-3">
                <div className="p-2 rounded-md bg-warn-soft text-warn-fg">
                  <BarChart3 className="h-5 w-5" />
                </div>
                <div>
                  <p className="text-xs font-medium text-fg-muted uppercase tracking-wide">Rules applied</p>
                  <p className="text-xl font-semibold text-fg">{rulesAppliedCount}</p>
                </div>
              </div>
              {[
                { label: 'Before', percent: beforeConfidencePercent },
                { label: 'After', percent: afterConfidencePercent },
              ].map(({ label, percent }) => {
                const pct = percent ?? 0;
                const colorClass =
                  percent == null
                    ? 'bg-inset text-fg-muted'
                    : pct >= 70
                      ? 'bg-ok-soft text-ok-fg'
                      : pct >= 40
                        ? 'bg-warn-soft text-warn-fg'
                        : 'bg-inset text-fg-muted';
                const barClass =
                  percent == null
                    ? 'bg-inset'
                    : pct >= 70
                      ? 'bg-ok'
                      : pct >= 40
                        ? 'bg-warn'
                        : 'bg-fg-subtle';
                return (
                  <div key={label} className="flex flex-col gap-2 rounded-lg border border-border bg-surface px-4 py-3">
                    <div className="flex items-center gap-3">
                      <div className={`p-2 rounded-md shrink-0 ${colorClass}`}>
                        <ShieldCheck className="h-5 w-5" />
                      </div>
                      <div className="min-w-0">
                        <p className="text-xs font-medium text-fg-muted uppercase tracking-wide">
                          Data quality ({label})
                        </p>
                        <p className="text-xl font-semibold text-fg tabular-nums">
                          {percent != null ? `${percent}%` : '—'}
                        </p>
                      </div>
                    </div>
                    <div
                      className="w-full h-2 rounded-full bg-inset overflow-hidden"
                      role="progressbar"
                      aria-valuenow={percent ?? 0}
                      aria-valuemin={0}
                      aria-valuemax={100}
                      aria-label={`Data quality confidence ${label.toLowerCase()}`}
                    >
                      <div
                        className={`h-full rounded-full transition-all duration-[var(--dur-slow)] ease-out ${barClass}`}
                        style={{ width: percent != null ? `${percent}%` : '0%' }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* Bottom 70%: search/paging, record list, before/after transform */}
      <div className="flex-[0_0_70%] min-h-0 flex flex-col overflow-hidden">
      {/* Record search and paging with next/prev */}
      <div className="shrink-0 flex flex-wrap items-center gap-3 px-6 py-3 border-b border-border bg-surface">
        <div className="flex items-center gap-2 min-w-0 flex-1">
          <input
            type="text"
            placeholder="Search records..."
            value={searchQ}
            onChange={(e) => setSearchQ(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
            className="flex-1 min-w-0 max-w-xs px-3 py-2 rounded-md border border-border bg-surface text-sm text-fg placeholder:text-fg-subtle focus:outline-none focus:ring-2 focus:ring-accent"
          />
          <button
            type="button"
            onClick={handleSearch}
            className="shrink-0 p-2 rounded-md border border-border bg-surface text-fg-muted hover:bg-subtle"
            title="Search"
          >
            <Search className="w-4 h-4" />
          </button>
          <button
            type="button"
            onClick={handleViewAll}
            className="shrink-0 inline-flex items-center gap-1.5 px-3 py-2 rounded-md border border-border bg-surface text-sm text-fg-muted hover:bg-subtle"
          >
            <List className="w-4 h-4" />
            View all
          </button>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => handlePageChange(page - 1)}
            disabled={page <= 1}
            className="px-2.5 py-1.5 text-sm rounded-md border border-border disabled:opacity-50 text-fg-muted hover:bg-subtle disabled:hover:bg-transparent"
          >
            Page prev
          </button>
          <span className="text-sm text-fg-muted tabular-nums">
            Page {page} / {totalPages}
          </span>
          <button
            type="button"
            onClick={() => handlePageChange(page + 1)}
            disabled={page >= totalPages}
            className="px-2.5 py-1.5 text-sm rounded-md border border-border disabled:opacity-50 text-fg-muted hover:bg-subtle disabled:hover:bg-transparent"
          >
            Page next
          </button>
        </div>
        <div className="flex items-center gap-1 border-l border-border pl-3">
          <button
            type="button"
            onClick={goPrev}
            disabled={!hasPrev}
            className="p-2 rounded-md border border-border disabled:opacity-50 text-fg-muted hover:bg-subtle disabled:hover:bg-transparent"
            title="Previous record"
          >
            <ChevronLeft className="w-5 h-5" />
          </button>
          <span className="text-sm text-fg-muted min-w-[6rem] text-center">
            {selectedRecord ? `Record ${currentIndex + 1} of ${rows.length}` : 'Select a record'}
          </span>
          <button
            type="button"
            onClick={goNext}
            disabled={!hasNext}
            className="p-2 rounded-md border border-border disabled:opacity-50 text-fg-muted hover:bg-subtle disabled:hover:bg-transparent"
            title="Next record"
          >
            <ChevronRight className="w-5 h-5" />
          </button>
        </div>
      </div>

      {/* Record list (compact) for selection + metadata + panels */}
      <div className="flex-1 min-h-0 flex overflow-hidden">
        {/* Left: record list (narrow) */}
        <div className="shrink-0 flex flex-col border-r border-border bg-subtle/50 w-52 min-w-0">
          <div className="p-2 border-b border-border text-xs font-medium text-fg-muted">
            Records
          </div>
          <div className="flex-1 min-h-0 overflow-auto">
            {viewMode === 'none' ? (
              <div className="p-3 text-sm text-fg-muted">View all or search to load.</div>
            ) : loading ? (
              <LoadingState message="Loading records…" skeleton={<SkeletonText className="p-3" />} />
            ) : rows.length === 0 ? (
              <EmptyState
                variant="inline"
                icon={<Database />}
                titleAs="p"
                title="No matching records"
                description="Try a different search, or view all records."
              />
            ) : (
              <ul className="p-1 space-y-0.5">
                {rows.map((row, idx) => {
                  const isSelected = selectedRecord?.record_id === row.record_id;
                  return (
                    <li key={row.record_id}>
                      <button
                        type="button"
                        onClick={() => {
                          setSelectedRecord(row);
                          setTransformResult(null);
                          setEvaluateError(null);
                        }}
                        className={`w-full text-left px-2.5 py-2 rounded-lg text-sm transition-colors border ${
                          isSelected
                            ? 'bg-accent-soft border-accent/30 text-accent-fg'
                            : 'border-transparent text-fg-muted hover:bg-inset'
                        }`}
                      >
                        <span className="font-mono text-xs text-fg-muted block truncate">
                          {row.record_id}
                        </span>
                        <span className="text-xs text-fg-subtle">{idx + 1}</span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </div>

        {/* Center + Right: metadata and Old | New */}
        <div className="flex-1 min-h-0 flex flex-col overflow-hidden">
          {/* Metadata: transformed record when rules applied, otherwise original record */}
          <div className="shrink-0 px-4 py-2 border-b border-border bg-surface flex flex-wrap items-center gap-x-6 gap-y-1 text-sm">
            {transformResult ? (
              <>
                <span className="text-fg-muted">
                  <strong className="text-fg-muted">Record (after transform):</strong>{' '}
                  <code className="text-xs bg-subtle px-1.5 py-0.5 rounded-xs">{selectedRecord?.record_id ?? '—'}</code>
                </span>
                <span className="text-fg-muted">
                  <strong className="text-fg-muted">Transformed at:</strong> {formatDateTime(transformResult.transformedAt)}
                </span>
                <span className="text-fg-muted">
                  <strong className="text-fg-muted">Fields:</strong> {Object.keys(transformResult.data).length}
                </span>
              </>
            ) : selectedRecord ? (
              <>
                <span className="text-fg-muted">
                  <strong className="text-fg-muted">Record (original):</strong>{' '}
                  <code className="text-xs bg-subtle px-1.5 py-0.5 rounded-xs">{selectedRecord.record_id}</code>
                </span>
                <span className="text-fg-muted">
                  <strong className="text-fg-muted">Updated:</strong> {formatDateTime(selectedRecord.updated_at)}
                </span>
                {selectedRecord.created_at != null && (
                  <span className="text-fg-muted">
                    <strong className="text-fg-muted">Created:</strong> {formatDateTime(selectedRecord.created_at)}
                  </span>
                )}
                {selectedRecord.record_sequence != null && (
                  <span className="text-fg-muted">
                    <strong className="text-fg-muted">Sequence:</strong> {selectedRecord.record_sequence}
                  </span>
                )}
                {selectedRecord.last_action && (
                  <span className="text-fg-muted">
                    <strong className="text-fg-muted">Last action:</strong> {selectedRecord.last_action}
                  </span>
                )}
                <span className="text-fg-subtle italic">Apply rules to see transformed record metadata and confidence.</span>
              </>
            ) : (
              <span className="text-fg-muted">Select a record to see metadata.</span>
            )}
          </div>

          {/* Old Record | New Record */}
          <div className="flex-1 min-h-0 flex overflow-hidden">
            {/* Old (left) */}
            <div className="flex-1 min-w-0 flex flex-col border-r border-border bg-surface">
              <div className="h-11 flex items-center justify-between gap-2 px-3 border-b border-border bg-subtle/50 shrink-0">
                <div className="flex items-center gap-2 min-w-0">
                  <FileJson className="w-4 h-4 shrink-0 text-fg-muted" />
                  <span className="text-sm font-medium text-fg-muted truncate">Original record</span>
                </div>
                <div className="min-w-[7.5rem] shrink-0" aria-hidden />
              </div>
              <div className="flex-1 min-h-0 overflow-hidden">
                {selectedRecord ? (
                  <MonacoEditor
                    height="100%"
                    language="json"
                    theme="vs-dark"
                    value={JSON.stringify(selectedRecord.data, null, 2)}
                    options={{
                      readOnly: true,
                      minimap: { enabled: false },
                      scrollBeyondLastLine: false,
                      fontSize: CODE_EDITOR_FONT_SIZE,
                      wordWrap: 'on',
                    }}
                  />
                ) : (
                  <div className="h-full flex flex-col items-center justify-center gap-2 text-fg-subtle p-4">
                    <FileJson className="w-10 h-10" />
                    <p className="text-sm text-center">Select a record to see original data.</p>
                  </div>
                )}
              </div>
            </div>

            {/* New (right) */}
            <div className="flex-1 min-w-0 flex flex-col bg-surface">
              <div className="h-11 flex items-center justify-between gap-2 px-3 border-b border-border bg-subtle/50 shrink-0">
                <div className="flex items-center gap-2 min-w-0">
                  <FileJson className="w-4 h-4 shrink-0 text-fg-muted" />
                  <span className="text-sm font-medium text-fg-muted truncate">After transform</span>
                </div>
                <div className="flex items-center gap-3 shrink-0">
                  <label className="flex items-center gap-2 cursor-pointer text-sm text-fg-muted">
                    <Switch
                      checked={autoApply}
                      onCheckedChange={setAutoApply}
                      disabled={!selectedRecord}
                    />
                    <span>Auto-Apply</span>
                  </label>
                  <button
                    type="button"
                    onClick={handleEvaluate}
                    disabled={!selectedRecord || evaluateLoading || autoApply}
                    className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-md border border-accent/30 bg-accent-soft text-accent-fg hover:bg-accent-soft disabled:opacity-50 disabled:pointer-events-none text-sm font-medium"
                  >
                    <Play className="w-4 h-4" />
                    {evaluateLoading ? 'Applying…' : 'Apply rules'}
                  </button>
                </div>
              </div>
              <div className="flex-1 min-h-0 overflow-hidden">
                {!selectedRecord ? (
                  <div className="h-full flex flex-col items-center justify-center gap-2 text-fg-subtle p-4">
                    <FileJson className="w-10 h-10" />
                    <p className="text-sm text-center">Select a record, then click Apply rules to see transformed data.</p>
                  </div>
                ) : evaluateError ? (
                  <div className="h-full flex flex-col items-center justify-center gap-2 text-warn-fg p-4">
                    <p className="text-sm text-center">{evaluateError}</p>
                    <button
                      type="button"
                      onClick={handleEvaluate}
                      className="text-sm underline hover:no-underline"
                    >
                      Retry
                    </button>
                  </div>
                ) : transformedData !== null ? (
                  <MonacoEditor
                    height="100%"
                    language="json"
                    theme="vs-dark"
                    value={JSON.stringify(transformedData, null, 2)}
                    options={{
                      readOnly: true,
                      minimap: { enabled: false },
                      scrollBeyondLastLine: false,
                      fontSize: CODE_EDITOR_FONT_SIZE,
                      wordWrap: 'on',
                    }}
                  />
                ) : (
                  <div className="h-full flex flex-col items-center justify-center gap-2 text-fg-subtle p-4">
                    <Play className="w-10 h-10" />
                    <p className="text-sm text-center">
                      Click <strong>Apply rules</strong> to run the migration plan on this record and see the result.
                    </p>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
      </div>
    </div>
  );
}
