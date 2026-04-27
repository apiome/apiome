'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertCircle,
  CheckCircle2,
  ChevronRight,
  CircleDashed,
  CircleDot,
  Download,
  ExternalLink,
  FileSearch,
  Loader2,
  MoreHorizontal,
  X,
} from 'lucide-react';
import { Button } from '@/app/components/ui/Button';
import { Input } from '@/app/components/ui/Input';
import { Switch } from '@/app/components/ui/Switch';

export type RepositorySpecStatus =
  | 'importing'
  | 'imported'
  | 'parse_error'
  | 'manifest_error'
  | 'not_imported'
  | 'unchanged_checksum';

export interface RepositorySpecRecord {
  fileId: string;
  repositoryId: string;
  scanId: string;
  branch: string;
  path: string;
  format: string | null;
  confidence: number | null;
  discriminator: string | null;
  status: RepositorySpecStatus;
  importEnabled: boolean;
  autoImportEnabled: boolean;
  lastImportedVersionId: string | null;
  lastImportedAt: string | null;
  createdAt: string;
}

interface SpecsResponse {
  success: boolean;
  items?: RepositorySpecRecord[];
  limit?: number;
  nextCursor?: string | null;
  error?: string;
}

interface SpecPatchResponse {
  success: boolean;
  spec?: RepositorySpecRecord;
  error?: string;
  detail?: { code?: string; message?: string } | null;
}

interface SpecBulkResponse {
  success: boolean;
  updatedCount?: number;
  items?: RepositorySpecRecord[];
  error?: string;
  detail?: { code?: string; message?: string } | null;
}

const filterStatusValues = [
  'all',
  'importable',
  'imported',
  'failing',
  'awaiting_selection',
] as const;
type SpecFilter = (typeof filterStatusValues)[number];

const filterLabel: Record<SpecFilter, string> = {
  all: 'All',
  importable: 'Importable',
  imported: 'Imported',
  failing: 'Failing',
  awaiting_selection: 'Awaiting selection',
};

/**
 * Maps the chip the user clicks into the `status=` query string the REST
 * endpoint understands. `failing` collapses parse_error + manifest_error
 * into two requests on the client side; the rest are 1:1.
 */
const filterToServerStatus: Record<SpecFilter, RepositorySpecStatus[] | null> = {
  all: null,
  importable: null,
  imported: ['imported'],
  failing: ['parse_error', 'manifest_error'],
  awaiting_selection: ['not_imported'],
};

const formatPillClass: Record<string, string> = {
  openapi_3_0: 'bg-indigo-100 text-indigo-700 dark:bg-indigo-900/40 dark:text-indigo-300',
  openapi_3_1: 'bg-indigo-100 text-indigo-700 dark:bg-indigo-900/40 dark:text-indigo-300',
  swagger_2_0: 'bg-violet-100 text-violet-700 dark:bg-violet-900/40 dark:text-violet-300',
  json_schema: 'bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300',
  json_schema_2020_12: 'bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300',
  asyncapi_2_6: 'bg-sky-100 text-sky-700 dark:bg-sky-900/40 dark:text-sky-300',
  graphql: 'bg-fuchsia-100 text-fuchsia-700 dark:bg-fuchsia-900/40 dark:text-fuchsia-300',
};

function getFormatPillClass(format: string | null | undefined): string {
  const key = (format || 'unknown').toLowerCase();
  return formatPillClass[key] ?? 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300';
}

const statusPillClass: Record<RepositorySpecStatus, string> = {
  importing: 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200',
  imported: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300',
  parse_error: 'bg-rose-100 text-rose-700 dark:bg-rose-900/40 dark:text-rose-300',
  manifest_error: 'bg-rose-100 text-rose-700 dark:bg-rose-900/40 dark:text-rose-300',
  not_imported: 'bg-slate-200 text-slate-700 dark:bg-slate-700 dark:text-slate-200',
  unchanged_checksum: 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300',
};

const statusLabel: Record<RepositorySpecStatus, string> = {
  importing: 'Importing',
  imported: 'Imported',
  parse_error: 'Parse error',
  manifest_error: 'Manifest error',
  not_imported: 'Not imported',
  unchanged_checksum: 'Unchanged',
};

function StatusPill({ status }: { status: RepositorySpecStatus }) {
  const Icon = status === 'imported'
    ? CheckCircle2
    : status === 'importing'
      ? Loader2
    : status === 'parse_error' || status === 'manifest_error'
      ? AlertCircle
      : status === 'unchanged_checksum'
        ? CircleDot
        : CircleDashed;
  return (
    <span
      className={`inline-flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wider px-1.5 py-0.5 rounded ${statusPillClass[status]}`}
      data-testid={`spec-status-${status}`}
    >
      <Icon className={status === 'importing' ? 'w-3 h-3 animate-spin' : 'w-3 h-3'} />
      {statusLabel[status]}
    </span>
  );
}

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return '—';
  const ts = Date.parse(value);
  if (!Number.isFinite(ts)) return '—';
  return new Date(ts).toLocaleString();
}

interface RepositorySpecsTabProps {
  repositoryId: string;
  branches: string[];
  initialBranch?: string;
  initialFilter?: SpecFilter;
  initialSearch?: string;
  onFilterChange?: (filter: SpecFilter) => void;
  onBranchChange?: (branch: string) => void;
}

const minImportableConfidence = 0.5;

export function RepositorySpecsTab({
  repositoryId,
  branches,
  initialBranch,
  initialFilter = 'all',
  initialSearch = '',
  onFilterChange,
  onBranchChange,
}: RepositorySpecsTabProps) {
  const [filter, setFilter] = useState<SpecFilter>(initialFilter);
  const [branch, setBranch] = useState<string>(initialBranch || branches[0] || '');
  const [search, setSearch] = useState(initialSearch);
  const [specs, setSpecs] = useState<RepositorySpecRecord[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');
  const [successMessage, setSuccessMessage] = useState('');
  const [importNowJobId, setImportNowJobId] = useState<string | null>(null);
  const [openMenuFileId, setOpenMenuFileId] = useState<string | null>(null);
  const [selectedSpec, setSelectedSpec] = useState<RepositorySpecRecord | null>(null);
  const [pendingPatchIds, setPendingPatchIds] = useState<Set<string>>(new Set());
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [isBulkPending, setIsBulkPending] = useState(false);
  const drawerRef = useRef<HTMLElement | null>(null);
  const importNowEarlyRefreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const importNowLateRefreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (initialBranch && initialBranch !== branch) {
      setBranch(initialBranch);
    }
  }, [initialBranch]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (initialFilter !== filter) {
      setFilter(initialFilter);
    }
  }, [initialFilter]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (selectedSpec) {
      drawerRef.current?.focus();
    }
  }, [selectedSpec]);

  useEffect(() => {
    return () => {
      if (importNowEarlyRefreshTimerRef.current !== null) clearTimeout(importNowEarlyRefreshTimerRef.current);
      if (importNowLateRefreshTimerRef.current !== null) clearTimeout(importNowLateRefreshTimerRef.current);
    };
  }, []);

  const loadSpecs = useCallback(async () => {
    if (!repositoryId) return;
    setIsLoading(true);
    setErrorMessage('');
    try {
      const params = new URLSearchParams();
      params.set('limit', '200');
      params.set('min_confidence', String(minImportableConfidence));
      if (branch) params.set('branch', branch);
      if (search.trim()) params.set('search', search.trim());
      const serverStatuses = filterToServerStatus[filter];
      if (serverStatuses && serverStatuses.length === 1) {
        params.set('status', serverStatuses[0]);
      }
      const response = await fetch(`/api/repositories/${repositoryId}/specs?${params.toString()}`);
      const data = (await response.json()) as SpecsResponse;
      if (!response.ok || !data.success) {
        throw new Error(data.error || 'Failed to load specs');
      }
      let rows = Array.isArray(data.items) ? data.items : [];
      if (filter === 'failing') {
        rows = rows.filter((row) => row.status === 'parse_error' || row.status === 'manifest_error');
      }
      setSpecs(rows);
      setSelectedIds((prev) => {
        const validIds = new Set(rows.map((row) => row.fileId));
        const next = new Set<string>();
        prev.forEach((id) => {
          if (validIds.has(id)) next.add(id);
        });
        return next;
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to load specs';
      setErrorMessage(message);
    } finally {
      setIsLoading(false);
    }
  }, [branch, filter, repositoryId, search]);

  useEffect(() => {
    void loadSpecs();
  }, [loadSpecs]);

  /**
   * Optimistically PATCH a single spec selection. Rolls back on REST 4xx by
   * restoring the previous record. The atomic auto-import cleanup happens on
   * the server, so we trust the response payload as the new source of truth.
   */
  const patchSpec = useCallback(
    async (
      fileId: string,
      payload: { importEnabled?: boolean; autoImportEnabled?: boolean },
      mutator: (prev: RepositorySpecRecord) => RepositorySpecRecord,
    ) => {
      const previous = specs.find((row) => row.fileId === fileId);
      if (!previous) return;
      setSpecs((current) => current.map((row) => (row.fileId === fileId ? mutator(row) : row)));
      setPendingPatchIds((prev) => {
        const next = new Set(prev);
        next.add(fileId);
        return next;
      });
      try {
        const response = await fetch(`/api/repositories/${repositoryId}/specs/${fileId}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        const data = (await response.json()) as SpecPatchResponse;
        if (!response.ok || !data.success || !data.spec) {
          throw new Error(data.error || data.detail?.message || 'Failed to update spec');
        }
        const next = data.spec;
        setSpecs((current) => current.map((row) => (row.fileId === fileId ? next : row)));
      } catch (error) {
        setSpecs((current) => current.map((row) => (row.fileId === fileId ? previous : row)));
        const message = error instanceof Error ? error.message : 'Failed to update spec';
        setErrorMessage(message);
      } finally {
        setPendingPatchIds((prev) => {
          const next = new Set(prev);
          next.delete(fileId);
          return next;
        });
      }
    },
    [repositoryId, specs],
  );

  const handleImportToggle = useCallback(
    (spec: RepositorySpecRecord, nextChecked: boolean) => {
      void patchSpec(
        spec.fileId,
        { importEnabled: nextChecked },
        (prev) => ({
          ...prev,
          importEnabled: nextChecked,
          autoImportEnabled: nextChecked ? prev.autoImportEnabled : false,
        }),
      );
    },
    [patchSpec],
  );

  const handleAutoImportToggle = useCallback(
    (spec: RepositorySpecRecord, nextChecked: boolean) => {
      if (!spec.importEnabled && nextChecked) return;
      void patchSpec(
        spec.fileId,
        { autoImportEnabled: nextChecked },
        (prev) => ({ ...prev, autoImportEnabled: nextChecked }),
      );
    },
    [patchSpec],
  );

  const handleBulkUpdate = useCallback(
    async (payload: { importEnabled?: boolean; autoImportEnabled?: boolean }) => {
      const ids = Array.from(selectedIds);
      if (ids.length === 0) return;
      setIsBulkPending(true);
      setErrorMessage('');
      setSuccessMessage('');
      setImportNowJobId(null);
      try {
        const response = await fetch(`/api/repositories/${repositoryId}/specs/bulk-update`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ fileIds: ids, ...payload }),
        });
        const data = (await response.json()) as SpecBulkResponse;
        if (!response.ok || !data.success) {
          throw new Error(data.error || data.detail?.message || 'Failed to bulk update specs');
        }
        const updated = Array.isArray(data.items) ? data.items : [];
        const updatedById = new Map(updated.map((row) => [row.fileId, row]));
        setSpecs((current) => current.map((row) => updatedById.get(row.fileId) ?? row));
        setSuccessMessage(`Updated ${data.updatedCount ?? updated.length} spec(s).`);
      } catch (error) {
        const message = error instanceof Error ? error.message : 'Failed to bulk update specs';
        setErrorMessage(message);
      } finally {
        setIsBulkPending(false);
      }
    },
    [repositoryId, selectedIds],
  );

  const handleImportNow = useCallback(
    async (spec: RepositorySpecRecord) => {
      setOpenMenuFileId(null);
      setErrorMessage('');
      setSuccessMessage('');
      setImportNowJobId(null);
      try {
        const response = await fetch(
          `/api/repositories/${repositoryId}/specs/${spec.fileId}/import-now`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ branch: spec.branch, force: false }),
          },
        );
        const data = (await response.json()) as { success?: boolean; importJobId?: string; error?: string; detail?: unknown };
        if (!response.ok || !data.success) {
          const d = data.detail as { message?: string } | undefined;
          const msg = (typeof d === 'object' && d?.message) || data.error || 'Import Now failed';
          throw new Error(msg);
        }
        const jobId = data.importJobId ?? '';
        setSpecs((current) =>
          current.map((row) => (row.fileId === spec.fileId ? { ...row, status: 'importing' } : row)),
        );
        setSelectedSpec((prev) =>
          prev && prev.fileId === spec.fileId ? { ...prev, status: 'importing' } : prev,
        );
        setImportNowJobId(jobId);
        setSuccessMessage(
          `Import started (job ${jobId ? `${jobId.slice(0, 8)}…` : 'queued'}).`,
        );
        if (importNowEarlyRefreshTimerRef.current !== null) clearTimeout(importNowEarlyRefreshTimerRef.current);
        if (importNowLateRefreshTimerRef.current !== null) clearTimeout(importNowLateRefreshTimerRef.current);
        importNowEarlyRefreshTimerRef.current = setTimeout(() => { void loadSpecs(); }, 1500);
        importNowLateRefreshTimerRef.current = setTimeout(() => { void loadSpecs(); }, 5000);
      } catch (error) {
        const message = error instanceof Error ? error.message : 'Import Now failed';
        setSuccessMessage('');
        setImportNowJobId(null);
        setErrorMessage(message);
      }
    },
    [loadSpecs, repositoryId],
  );

  const filteredSpecs = useMemo(() => {
    if (filter !== 'importable') return specs;
    return specs.filter((row) => (row.confidence ?? 0) >= minImportableConfidence);
  }, [filter, specs]);

  const allVisibleSelected = filteredSpecs.length > 0
    && filteredSpecs.every((row) => selectedIds.has(row.fileId));

  const toggleSelectAll = () => {
    setSelectedIds((prev) => {
      if (allVisibleSelected) {
        const next = new Set(prev);
        filteredSpecs.forEach((row) => next.delete(row.fileId));
        return next;
      }
      const next = new Set(prev);
      filteredSpecs.forEach((row) => next.add(row.fileId));
      return next;
    });
  };

  return (
    <div className="space-y-4" data-testid="specs-tab-root">
      <div className="px-5 py-3 flex flex-wrap items-center gap-2 border-b border-gray-200 dark:border-gray-700">
        {filterStatusValues.map((value) => (
          <Button
            key={value}
            type="button"
            size="sm"
            variant={filter === value ? 'secondary' : 'outline'}
            onClick={() => {
              setFilter(value);
              onFilterChange?.(value);
            }}
            data-testid={`spec-filter-${value}`}
          >
            {filterLabel[value]}
          </Button>
        ))}
        <div className="ml-auto flex items-center gap-2">
          {branches.length > 0 ? (
            <select
              className="h-8 rounded-md border border-gray-200 bg-white px-2 text-xs dark:border-gray-700 dark:bg-gray-900"
              value={branch}
              onChange={(event) => {
                setBranch(event.target.value);
                onBranchChange?.(event.target.value);
              }}
              aria-label="Branch"
              data-testid="spec-branch-select"
            >
              {branches.map((entry) => (
                <option key={entry} value={entry}>{entry}</option>
              ))}
            </select>
          ) : null}
          <div className="w-56">
            <Input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search by path..."
              className="h-8 text-xs font-mono"
              aria-label="Search specs"
              data-testid="spec-search"
            />
          </div>
        </div>
      </div>

      {errorMessage ? (
        <div
          role="alert"
          className="mx-5 rounded-md border border-rose-200 dark:border-rose-700/40 bg-rose-50 dark:bg-rose-900/20 px-3 py-2 text-xs text-rose-700 dark:text-rose-300 flex items-center justify-between gap-3"
          data-testid="spec-error"
        >
          <span>{errorMessage}</span>
          <button
            type="button"
            aria-label="Dismiss error"
            onClick={() => setErrorMessage('')}
            className="text-rose-500 hover:text-rose-700"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      ) : null}
      {successMessage ? (
        <div
          role="status"
          className="mx-5 rounded-md border border-emerald-200 dark:border-emerald-700/40 bg-emerald-50 dark:bg-emerald-900/20 px-3 py-2 text-xs text-emerald-700 dark:text-emerald-300 flex items-center justify-between gap-3"
          data-testid="spec-success"
        >
          <span>
            {successMessage}
            {importNowJobId ? (
              <a
                className="ml-2 text-indigo-600 hover:text-indigo-700 font-medium"
                href={`/ade/dashboard/repositories/${repositoryId}?tab=sync&importJobId=${encodeURIComponent(importNowJobId)}`}
              >
                View in Sync history
              </a>
            ) : null}
          </span>
          <button
            type="button"
            aria-label="Dismiss success"
            onClick={() => {
              setSuccessMessage('');
              setImportNowJobId(null);
            }}
            className="text-emerald-600 hover:text-emerald-800"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      ) : null}

      {selectedIds.size > 0 ? (
        <div
          className="mx-5 rounded-md border border-indigo-200 dark:border-indigo-700/40 bg-indigo-50/70 dark:bg-indigo-900/20 px-3 py-2 text-xs flex flex-wrap items-center gap-2"
          data-testid="spec-bulk-bar"
        >
          <span className="font-mono">{selectedIds.size} selected</span>
          <span className="text-gray-500">·</span>
          <Button
            size="sm"
            variant="outline"
            disabled={isBulkPending}
            onClick={() => void handleBulkUpdate({ importEnabled: true })}
            data-testid="spec-bulk-enable-import"
          >
            Enable import
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={isBulkPending}
            onClick={() => void handleBulkUpdate({ importEnabled: false })}
            data-testid="spec-bulk-disable-import"
          >
            Disable import
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={isBulkPending}
            onClick={() => void handleBulkUpdate({ importEnabled: true, autoImportEnabled: true })}
            data-testid="spec-bulk-enable-auto"
          >
            Enable auto-import
          </Button>
          <button
            type="button"
            className="ml-auto text-indigo-600 hover:text-indigo-700 underline"
            onClick={() => setSelectedIds(new Set())}
          >
            Clear selection
          </button>
        </div>
      ) : null}

      {isLoading ? (
        <div className="px-5 py-6 text-sm text-gray-500 flex items-center gap-2" data-testid="spec-loading">
          <Loader2 className="w-4 h-4 animate-spin" />
          Loading specs...
        </div>
      ) : filteredSpecs.length === 0 ? (
        <div className="px-5 py-6 text-sm text-gray-500" data-testid="spec-empty">
          No specs match the current filter. Try changing the filter or running another scan.
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm" data-testid="spec-table">
            <thead className="text-[10px] uppercase tracking-wider text-gray-500 dark:text-gray-400 bg-gray-50/60 dark:bg-gray-900/40 border-b border-gray-200 dark:border-gray-700">
              <tr>
                <th className="text-left px-5 py-2 font-semibold w-8">
                  <input
                    type="checkbox"
                    aria-label="Select all visible specs"
                    data-testid="spec-select-all"
                    checked={allVisibleSelected}
                    onChange={toggleSelectAll}
                  />
                </th>
                <th className="text-left px-3 py-2 font-semibold">Path</th>
                <th className="text-left px-3 py-2 font-semibold">Format</th>
                <th className="text-left px-3 py-2 font-semibold">Status</th>
                <th className="text-left px-3 py-2 font-semibold">Last version</th>
                <th className="text-left px-3 py-2 font-semibold">Last imported</th>
                <th className="text-left px-3 py-2 font-semibold">Import</th>
                <th className="text-left px-3 py-2 font-semibold">Auto-Import</th>
                <th className="text-right px-5 py-2 font-semibold w-16">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-700/60">
              {filteredSpecs.map((spec) => {
                const isPending = pendingPatchIds.has(spec.fileId);
                const isSelected = selectedIds.has(spec.fileId);
                const confidencePercent = spec.confidence != null
                  ? `${Math.round(spec.confidence * 100)}%`
                  : '—';
                const confidenceTitle = spec.discriminator
                  ? `Confidence ${confidencePercent} · discriminator: ${spec.discriminator}`
                  : `Confidence ${confidencePercent}`;
                return (
                  <tr
                    key={spec.fileId}
                    className="hover:bg-gray-50/60 dark:hover:bg-gray-900/30"
                    data-testid={`spec-row-${spec.path}`}
                  >
                    <td className="px-5 py-2.5 align-middle">
                      <input
                        type="checkbox"
                        aria-label={`Select ${spec.path}`}
                        data-testid={`spec-row-select-${spec.path}`}
                        checked={isSelected}
                        onChange={(event) => {
                          setSelectedIds((prev) => {
                            const next = new Set(prev);
                            if (event.target.checked) next.add(spec.fileId);
                            else next.delete(spec.fileId);
                            return next;
                          });
                        }}
                      />
                    </td>
                    <td className="px-3 py-2.5 align-middle max-w-[320px]">
                      <button
                        type="button"
                        className="flex items-center gap-1.5 font-mono text-xs truncate hover:text-indigo-600 hover:underline"
                        title={spec.path}
                        onClick={() => setSelectedSpec(spec)}
                        data-testid={`spec-row-path-${spec.path}`}
                      >
                        <ChevronRight className="w-3 h-3 text-gray-400 flex-shrink-0" />
                        <span className="truncate">{spec.path}</span>
                      </button>
                    </td>
                    <td className="px-3 py-2.5 align-middle">
                      <span
                        className={`text-[10px] font-semibold uppercase tracking-wider px-1.5 py-0.5 rounded ${getFormatPillClass(spec.format)}`}
                        title={confidenceTitle}
                      >
                        {spec.format || 'unknown'}
                      </span>
                      <span className="ml-2 text-[10px] font-mono text-gray-400" title={confidenceTitle}>
                        {confidencePercent}
                      </span>
                    </td>
                    <td className="px-3 py-2.5 align-middle">
                      <StatusPill status={spec.status} />
                    </td>
                    <td className="px-3 py-2.5 align-middle">
                      {spec.lastImportedVersionId ? (
                        <a
                          href={`/ade/dashboard/versions/${spec.lastImportedVersionId}`}
                          className="font-mono text-xs text-indigo-600 hover:text-indigo-700 inline-flex items-center gap-1"
                        >
                          {spec.lastImportedVersionId.slice(0, 8)}
                          <ExternalLink className="w-3 h-3" />
                        </a>
                      ) : (
                        <span className="font-mono text-xs text-gray-400">—</span>
                      )}
                    </td>
                    <td className="px-3 py-2.5 align-middle font-mono text-[11px] text-gray-500">
                      {formatTimestamp(spec.lastImportedAt)}
                    </td>
                    <td className="px-3 py-2.5 align-middle">
                      <Switch
                        checked={spec.importEnabled}
                        onCheckedChange={(checked) => handleImportToggle(spec, checked)}
                        disabled={isPending}
                        aria-label={`Toggle import for ${spec.path}`}
                        data-testid={`spec-import-toggle-${spec.path}`}
                      />
                    </td>
                    <td className="px-3 py-2.5 align-middle">
                      <Switch
                        checked={spec.autoImportEnabled}
                        onCheckedChange={(checked) => handleAutoImportToggle(spec, checked)}
                        disabled={isPending || !spec.importEnabled}
                        aria-label={`Toggle auto-import for ${spec.path}`}
                        data-testid={`spec-auto-toggle-${spec.path}`}
                      />
                    </td>
                    <td className="px-5 py-2.5 align-middle text-right relative">
                      <button
                        type="button"
                        className="p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-700"
                        aria-label={`Actions for ${spec.path}`}
                        onClick={() =>
                          setOpenMenuFileId((current) => (current === spec.fileId ? null : spec.fileId))
                        }
                        data-testid={`spec-overflow-${spec.path}`}
                      >
                        <MoreHorizontal className="w-4 h-4 text-gray-500" />
                      </button>
                      {openMenuFileId === spec.fileId ? (
                        <div
                          role="menu"
                          className="absolute right-4 z-20 mt-1 w-56 rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 shadow-lg text-left text-xs"
                          data-testid={`spec-overflow-menu-${spec.path}`}
                        >
                          <button
                            type="button"
                            role="menuitem"
                            className="w-full px-3 py-2 hover:bg-gray-100 dark:hover:bg-gray-800 flex items-center gap-2"
                            onClick={() => { void handleImportNow(spec); }}
                            data-testid={`spec-import-now-${spec.path}`}
                          >
                            <Download className="w-3.5 h-3.5" />
                            Import Now
                          </button>
                          <button
                            type="button"
                            role="menuitem"
                            className="w-full px-3 py-2 hover:bg-gray-100 dark:hover:bg-gray-800 flex items-center gap-2"
                            onClick={() => {
                              setOpenMenuFileId(null);
                              setSelectedSpec(spec);
                            }}
                          >
                            <FileSearch className="w-3.5 h-3.5" />
                            Open spec detail
                          </button>
                          <a
                            role="menuitem"
                            href={`/api/repositories/${repositoryId}/scans/${spec.scanId}`}
                            target="_blank"
                            rel="noreferrer"
                            className="w-full px-3 py-2 hover:bg-gray-100 dark:hover:bg-gray-800 flex items-center gap-2"
                            onClick={() => setOpenMenuFileId(null)}
                          >
                            <ExternalLink className="w-3.5 h-3.5" />
                            Open scan record
                          </a>
                        </div>
                      ) : null}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <div className="px-5 py-2.5 border-t border-gray-100 dark:border-gray-700/60 text-[11px] text-gray-500 font-mono flex items-center justify-between">
        <span>
          Showing {filteredSpecs.length} importable spec{filteredSpecs.length === 1 ? '' : 's'} (confidence ≥ 50%)
        </span>
        <span>click a row to open the spec detail drawer</span>
      </div>

      {selectedSpec ? (
        <div
          className="fixed top-12 right-0 bottom-0 left-0 z-40 bg-black/30"
          role="presentation"
          onClick={() => setSelectedSpec(null)}
          data-testid="spec-drawer-overlay"
        >
          <aside
            ref={drawerRef}
            className="absolute right-0 top-0 h-full w-full max-w-xl bg-white dark:bg-gray-900 shadow-xl overflow-auto"
            role="dialog"
            aria-modal="true"
            aria-label="Spec detail drawer"
            tabIndex={-1}
            onClick={(event) => event.stopPropagation()}
            onKeyDown={(event) => { if (event.key === 'Escape') setSelectedSpec(null); }}
            data-testid="spec-drawer"
          >
            <div className="px-5 py-4 border-b border-gray-200 dark:border-gray-700 flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="text-[10px] uppercase tracking-wider text-gray-500 dark:text-gray-400 font-semibold">
                  Spec detail
                </p>
                <p className="text-sm font-medium font-mono mt-1 truncate" title={selectedSpec.path}>
                  {selectedSpec.path}
                </p>
              </div>
              <button
                type="button"
                aria-label="Close spec drawer"
                className="p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-700"
                onClick={() => setSelectedSpec(null)}
              >
                <X className="w-4 h-4 text-gray-500" />
              </button>
            </div>
            <div className="p-5 space-y-3 text-xs">
              <div className="rounded-md border border-gray-200 dark:border-gray-700 divide-y divide-gray-100 dark:divide-gray-700/60">
                <DrawerRow label="Format">
                  <span className="font-mono">{selectedSpec.format || 'unknown'}</span>
                </DrawerRow>
                <DrawerRow label="Confidence">
                  <span className="font-mono">
                    {selectedSpec.confidence != null
                      ? `${Math.round(selectedSpec.confidence * 100)}%`
                      : '—'}
                  </span>
                </DrawerRow>
                <DrawerRow label="Discriminator">
                  <span className="font-mono truncate max-w-[260px]" title={selectedSpec.discriminator || 'n/a'}>
                    {selectedSpec.discriminator || 'n/a'}
                  </span>
                </DrawerRow>
                <DrawerRow label="Status">
                  <StatusPill status={selectedSpec.status} />
                </DrawerRow>
                <DrawerRow label="Branch">
                  <span className="font-mono">{selectedSpec.branch}</span>
                </DrawerRow>
                <DrawerRow label="Import">
                  <span className="font-mono">{selectedSpec.importEnabled ? 'enabled' : 'disabled'}</span>
                </DrawerRow>
                <DrawerRow label="Auto-Import">
                  <span className="font-mono">{selectedSpec.autoImportEnabled ? 'enabled' : 'disabled'}</span>
                </DrawerRow>
                <DrawerRow label="Last imported">
                  <span className="font-mono">{formatTimestamp(selectedSpec.lastImportedAt)}</span>
                </DrawerRow>
                <DrawerRow label="Last version">
                  {selectedSpec.lastImportedVersionId ? (
                    <a
                      href={`/ade/dashboard/versions/${selectedSpec.lastImportedVersionId}`}
                      className="font-mono text-indigo-600 hover:text-indigo-700"
                    >
                      {selectedSpec.lastImportedVersionId.slice(0, 8)}
                    </a>
                  ) : (
                    <span className="font-mono text-gray-400">—</span>
                  )}
                </DrawerRow>
              </div>
              <div className="pt-1">
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  onClick={() => { void handleImportNow(selectedSpec); }}
                  data-testid="spec-drawer-import-now"
                >
                  <Download className="w-3.5 h-3.5 mr-1.5" />
                  Import now
                </Button>
              </div>
              <p className="text-[11px] text-gray-500">
                Full spec detail UI ships with REPO-9.6. The drawer above shows the values
                already available from the scan record.
              </p>
            </div>
          </aside>
        </div>
      ) : null}
    </div>
  );
}

function DrawerRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="px-3 py-2 flex justify-between gap-3 items-center">
      <span className="text-gray-500">{label}</span>
      <div>{children}</div>
    </div>
  );
}

export const _internal = { filterToServerStatus, minImportableConfidence };
