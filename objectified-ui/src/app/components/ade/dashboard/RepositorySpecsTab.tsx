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
import { toast } from 'sonner';
import { Button } from '@/app/components/ui/Button';
import ConfirmDialog from '@/app/components/dialogs/ConfirmDialog';
import { Input } from '@/app/components/ui/Input';
import { Switch } from '@/app/components/ui/Switch';
import { RepositorySpecDetailDrawer } from './RepositorySpecDetailDrawer';

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

/** REPO-9.7: client-only filters (must match `filteredSpecs` in the list). */
export function matchesListFilter(
  row: Pick<RepositorySpecRecord, 'status' | 'confidence' | 'importEnabled'>,
  filter: SpecFilter,
  minConf: number,
): boolean {
  if (filter === 'importable') {
    return (row.confidence ?? 0) >= minConf;
  }
  if (filter === 'failing') {
    return row.status === 'parse_error' || row.status === 'manifest_error';
  }
  return true;
}

const BULK_MAX = 500;

function mergeBulkResponseIntoList(
  current: RepositorySpecRecord[],
  updated: RepositorySpecRecord[],
): RepositorySpecRecord[] {
  const fromResponse = new Map(updated.map((u) => [u.fileId, u]));
  const had = new Set(current.map((c) => c.fileId));
  const next: RepositorySpecRecord[] = current.map(
    (c) => fromResponse.get(c.fileId) ?? c,
  );
  for (const u of updated) {
    if (!had.has(u.fileId)) {
      next.push(u);
    }
  }
  return next;
}

function applyOptimisticBulk(
  rows: RepositorySpecRecord[],
  ids: Set<string>,
  payload: { importEnabled?: boolean; autoImportEnabled?: boolean },
): RepositorySpecRecord[] {
  return rows.map((row) => {
    if (!ids.has(row.fileId)) return row;
    let { importEnabled, autoImportEnabled } = row;
    if (payload.importEnabled === true) {
      importEnabled = true;
    }
    if (payload.importEnabled === false) {
      importEnabled = false;
      autoImportEnabled = false;
    }
    if (payload.autoImportEnabled === true) {
      autoImportEnabled = true;
    }
    if (payload.autoImportEnabled === false) {
      autoImportEnabled = false;
    }
    return { ...row, importEnabled, autoImportEnabled };
  });
}

function chunkIds(ids: string[], size: number): string[][] {
  if (ids.length === 0) return [];
  const out: string[][] = [];
  for (let i = 0; i < ids.length; i += size) {
    out.push(ids.slice(i, i + size));
  }
  return out;
}

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
  /** When the parent has a `?fileId=` query string, the drawer opens for that
   * spec on mount (deep linking, REPO-9.6). */
  initialFileId?: string | null;
  /** Notifies the parent every time the selected spec changes so it can keep
   * the URL in sync (or null to clear `?fileId=`). */
  onSelectedFileIdChange?: (fileId: string | null) => void;
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
  initialFileId = null,
  onSelectedFileIdChange,
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
  /** REPO-9.7: rows from "Select all matching filter" (and other off-canvas IDs) for import/imported state. */
  const [extraRowById, setExtraRowById] = useState<Record<string, RepositorySpecRecord>>({});
  const [confirmDisableImportOpen, setConfirmDisableImportOpen] = useState(false);
  const [isBulkPending, setIsBulkPending] = useState(false);
  const [isSelectAllMatchingPending, setIsSelectAllMatchingPending] = useState(false);
  const importNowEarlyRefreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const importNowLateRefreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const selectionScopeKeyRef = useRef<string | null>(null);

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
    const k = `${branch}||${filter}||${search}`;
    if (selectionScopeKeyRef.current === null) {
      selectionScopeKeyRef.current = k;
      return;
    }
    if (selectionScopeKeyRef.current !== k) {
      setSelectedIds(new Set());
      setExtraRowById({});
      selectionScopeKeyRef.current = k;
    }
  }, [branch, filter, search]);

  // Sync the parent's `?fileId=` query param when the drawer opens or closes.
  useEffect(() => {
    if (!onSelectedFileIdChange) return;
    onSelectedFileIdChange(selectedSpec?.fileId ?? null);
  }, [selectedSpec, onSelectedFileIdChange]);

  // Deep-link: when the spec list (re)loads and the URL/parent points at a
  // specific fileId, surface that spec in the drawer once it's available.
  useEffect(() => {
    if (!initialFileId) return;
    if (selectedSpec && selectedSpec.fileId === initialFileId) return;
    const candidate = specs.find((row) => row.fileId === initialFileId);
    if (candidate) setSelectedSpec(candidate);
  }, [initialFileId, specs, selectedSpec]);

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

  useEffect(() => {
    if (specs.length === 0) return;
    setExtraRowById((prev) => {
      if (Object.keys(prev).length === 0) return prev;
      const inSpec = new Set(specs.map((r) => r.fileId));
      const n = { ...prev };
      let changed = false;
      for (const k of Object.keys(n)) {
        if (inSpec.has(k)) {
          delete n[k];
          changed = true;
        }
      }
      return changed ? n : prev;
    });
  }, [specs]);

  const rowForSelection = useCallback(
    (fileId: string) => specs.find((r) => r.fileId === fileId) ?? extraRowById[fileId] ?? null,
    [specs, extraRowById],
  );

  const selectedCanSetAutoImport = useMemo(() => {
    if (selectedIds.size === 0) return false;
    for (const id of selectedIds) {
      const row = rowForSelection(id);
      if (!row?.importEnabled) return false;
    }
    return true;
  }, [rowForSelection, selectedIds]);

  const disableImportAffectsImported = useMemo(() => {
    for (const id of selectedIds) {
      const row = rowForSelection(id);
      if (row && (row.status === 'imported' || row.lastImportedVersionId)) {
        return true;
      }
    }
    return false;
  }, [rowForSelection, selectedIds]);

  const fetchFileIdsMatchingCurrentFilter = useCallback(async () => {
    const collected: RepositorySpecRecord[] = [];
    const seen = new Set<string>();
    let cursor: string | null = null;
    for (;;) {
      const params = new URLSearchParams();
      params.set('limit', '200');
      params.set('min_confidence', String(minImportableConfidence));
      if (branch) params.set('branch', branch);
      if (search.trim()) params.set('search', search.trim());
      const serverStatuses = filterToServerStatus[filter];
      if (serverStatuses && serverStatuses.length === 1) {
        params.set('status', serverStatuses[0]);
      }
      if (cursor) params.set('cursor', cursor);
      const response = await fetch(`/api/repositories/${repositoryId}/specs?${params.toString()}`);
      const data = (await response.json()) as SpecsResponse;
      if (!response.ok || !data.success) {
        throw new Error(data.error || 'Failed to list specs for selection');
      }
      const items = Array.isArray(data.items) ? data.items : [];
      for (const row of items) {
        if (!matchesListFilter(row, filter, minImportableConfidence)) continue;
        if (seen.has(row.fileId)) continue;
        seen.add(row.fileId);
        collected.push(row);
        if (collected.length >= BULK_MAX) {
          return { records: collected, hitCap: true };
        }
      }
      const next = data.nextCursor;
      if (!next) {
        return { records: collected, hitCap: false };
      }
      cursor = next;
    }
  }, [branch, filter, repositoryId, search]);

  const handleSelectAllMatchingFilter = useCallback(async () => {
    setIsSelectAllMatchingPending(true);
    setErrorMessage('');
    try {
      const { records, hitCap } = await fetchFileIdsMatchingCurrentFilter();
      setSelectedIds(new Set(records.map((r) => r.fileId)));
      setExtraRowById(Object.fromEntries(records.map((r) => [r.fileId, r])));
      if (records.length === 0) {
        toast.info('No specs match the current filter on this branch.');
        return;
      }
      if (hitCap) {
        toast.info(
          `Selected first ${BULK_MAX} file(s) (bulk update limit). Narrow the filter to target fewer rows.`,
        );
      } else {
        toast.success(`Selected ${records.length} file(s) matching the current filter.`);
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to list specs';
      setErrorMessage(message);
      toast.error(message);
    } finally {
      setIsSelectAllMatchingPending(false);
    }
  }, [fetchFileIdsMatchingCurrentFilter]);

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

  const bulkOptSnapshotRef = useRef<RepositorySpecRecord[] | null>(null);

  const runBulkUpdate = useCallback(
    async (payload: { importEnabled?: boolean; autoImportEnabled?: boolean }) => {
      const allIds = Array.from(selectedIds);
      if (allIds.length === 0) return;
      const idChunks = chunkIds(allIds, BULK_MAX);
      setIsBulkPending(true);
      setErrorMessage('');
      setSuccessMessage('');
      setImportNowJobId(null);
      setSpecs((c) => {
        bulkOptSnapshotRef.current = c.map((r) => ({ ...r }));
        return applyOptimisticBulk(c, selectedIds, payload);
      });
      let succeededChunks = 0;
      try {
        for (const chunk of idChunks) {
          const response = await fetch(`/api/repositories/${repositoryId}/specs/bulk-update`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ fileIds: chunk, ...payload }),
          });
          const data = (await response.json()) as SpecBulkResponse;
          if (!response.ok || !data.success) {
            const d = data.detail as { message?: string; code?: string } | null | string | undefined;
            const fromDetail =
              typeof d === 'object' && d && 'message' in d && typeof d.message === 'string'
                ? d.message
                : null;
            throw new Error(
              (typeof d === 'string' ? d : fromDetail) ||
                (typeof data.error === 'string' ? data.error : null) ||
                'Failed to bulk update specs',
            );
          }
          const updated = Array.isArray(data.items) ? data.items : [];
          setSpecs((c) => mergeBulkResponseIntoList(c, updated));
          succeededChunks++;
        }
        toast.success(`Updated ${allIds.length} spec(s).`);
        setSelectedIds(new Set());
        setExtraRowById({});
        bulkOptSnapshotRef.current = null;
      } catch (error) {
        const message = error instanceof Error ? error.message : 'Failed to bulk update specs';
        if (succeededChunks > 0) {
          // Earlier chunks already applied on the server — refetch to get the
          // true server state instead of rolling back to a stale snapshot.
          bulkOptSnapshotRef.current = null;
          void loadSpecs();
          toast.error(`Partial update: ${succeededChunks} of ${idChunks.length} chunk(s) applied. Error: ${message}`, {
            id: 'spec-bulk-error',
          });
        } else {
          const snap = bulkOptSnapshotRef.current;
          if (snap) {
            setSpecs(snap);
            bulkOptSnapshotRef.current = null;
          }
          toast.error(message, { id: 'spec-bulk-error' });
        }
        setErrorMessage(message);
      } finally {
        setIsBulkPending(false);
      }
    },
    [loadSpecs, repositoryId, selectedIds],
  );

  const requestBulkDisableImport = useCallback(() => {
    if (selectedIds.size === 0) return;
    if (disableImportAffectsImported) {
      setConfirmDisableImportOpen(true);
      return;
    }
    void runBulkUpdate({ importEnabled: false });
  }, [disableImportAffectsImported, runBulkUpdate, selectedIds]);

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
          className="sticky top-0 z-30 mx-3 sm:mx-5 rounded-md border border-indigo-200 dark:border-indigo-700/40 bg-indigo-50/90 dark:bg-indigo-900/30 supports-[backdrop-filter]:backdrop-blur-sm px-3 py-2 text-xs flex flex-wrap items-center gap-2 shadow-sm"
          data-testid="spec-bulk-bar"
        >
          <span className="font-mono">{selectedIds.size} selected</span>
          <span className="text-gray-500">·</span>
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={isBulkPending}
            onClick={() => void runBulkUpdate({ importEnabled: true })}
            data-testid="spec-bulk-enable-import"
          >
            Enable import
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={isBulkPending}
            onClick={requestBulkDisableImport}
            data-testid="spec-bulk-disable-import"
          >
            Disable import
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={isBulkPending || !selectedCanSetAutoImport}
            title={
              !selectedCanSetAutoImport
                ? 'Set auto-import only when import is already enabled for every selected row.'
                : 'Turn on auto-import for the selected file(s) without changing import opt-in state.'
            }
            onClick={() => void runBulkUpdate({ autoImportEnabled: true })}
            data-testid="spec-bulk-set-auto"
          >
            Set auto-import
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={isBulkPending}
            onClick={() => void runBulkUpdate({ autoImportEnabled: false })}
            data-testid="spec-bulk-clear-auto"
          >
            Clear auto-import
          </Button>
          <span className="w-px h-4 bg-gray-300 dark:bg-gray-600 hidden sm:block" aria-hidden />
          <Button
            type="button"
            size="sm"
            variant="secondary"
            disabled={isLoading || isBulkPending || isSelectAllMatchingPending}
            onClick={() => void handleSelectAllMatchingFilter()}
            data-testid="spec-bulk-select-all-matching"
          >
            {isSelectAllMatchingPending ? 'Selecting…' : 'Select all matching filter'}
          </Button>
          <button
            type="button"
            className="ml-auto text-indigo-600 dark:text-indigo-400 hover:text-indigo-700 dark:hover:text-indigo-300 underline"
            onClick={() => {
              setSelectedIds(new Set());
              setExtraRowById({});
            }}
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
        <RepositorySpecDetailDrawer
          spec={selectedSpec}
          repositoryId={repositoryId}
          isPatchPending={pendingPatchIds.has(selectedSpec.fileId)}
          onSelectionToggle={async (fileId, payload) => {
            const target = specs.find((row) => row.fileId === fileId);
            if (!target) return;
            if (payload.importEnabled !== undefined) {
              handleImportToggle(target, payload.importEnabled);
            }
            if (payload.autoImportEnabled !== undefined) {
              handleAutoImportToggle(target, payload.autoImportEnabled);
            }
          }}
          onSpecRefresh={(refreshed) => {
            setSpecs((current) =>
              current.map((row) => (row.fileId === refreshed.fileId ? refreshed : row)),
            );
            setSelectedSpec((prev) =>
              prev && prev.fileId === refreshed.fileId ? refreshed : prev,
            );
          }}
          onClose={() => setSelectedSpec(null)}
        />
      ) : null}

      <ConfirmDialog
        open={confirmDisableImportOpen}
        title="Disable import for selected files?"
        message="This will leave the existing version in place but stop further imports. Proceed?"
        variant="warning"
        confirmLabel="Disable import"
        onCancel={() => {
          setConfirmDisableImportOpen(false);
        }}
        onConfirm={() => {
          setConfirmDisableImportOpen(false);
          void runBulkUpdate({ importEnabled: false });
        }}
      />
    </div>
  );
}

export const _internal = {
  filterToServerStatus,
  minImportableConfidence,
  matchesListFilter,
  BULK_MAX,
  mergeBulkResponseIntoList,
  applyOptimisticBulk,
  chunkIds,
};
