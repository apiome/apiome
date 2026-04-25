'use client';

import dynamic from 'next/dynamic';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useParams, useRouter, useSearchParams } from 'next/navigation';
import { ArrowLeft, FileCode2, GitBranchPlus, History, Loader2, ScanSearch, Settings2 } from 'lucide-react';
import { Button } from '@/app/components/ui/Button';
import { Alert } from '@/app/components/ui/Alert';
import { Input } from '@/app/components/ui/Input';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/app/components/ui/Tabs';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/app/components/ui/Dialog';
import { dashboardContentStackClass, dashboardMainClass, dashboardPanelClass } from '@/app/components/ade/dashboard/dashboardScreenClasses';
import { repositoryManifestSchema } from '@/lib/repositoryManifestSchema';
import { getRepositoriesI18nBundle } from '../i18n';

const MonacoEditor = dynamic(() => import('@monaco-editor/react'), { ssr: false });

const rowHeightPx = 88;
const fileViewportHeightPx = 420;
const repo63IssueUrl = 'https://github.com/KenSuenobu/objectified-commercial/issues/2796';

type RepositoryTab = 'branches' | 'files' | 'scans' | 'sync' | 'manifest' | 'settings';
const repositoryTabs: RepositoryTab[] = ['branches', 'files', 'scans', 'sync', 'manifest', 'settings'];

interface RepositoryTimelineItem {
  id: string;
  type: string;
  status: string;
  message: string;
  createdAt: string;
}

interface RepositoryDetail {
  id: string;
  linkedAccountId: string;
  provider: string;
  owner: string;
  name: string;
  fullName: string;
  status: string;
  manifest?: string | null;
  archivedAt?: string | null;
  branches: Array<{ branch: string; subpathGlob?: string; pollIntervalSec?: number }>;
  timeline: RepositoryTimelineItem[];
}

interface BranchRow {
  branch: string;
  subpathGlob: string;
  pollIntervalSec?: number;
}

interface ScanRecord {
  id: string;
  branch: string;
  commitSha: string;
  trigger: string;
  status: string;
  startedAt: string;
  finishedAt: string | null;
  filesSeen: number;
  filesClassified: number;
  filesUnknown: number;
  filesFailed: number;
  diffSummary: {
    added?: number;
    modified?: number;
    removed?: number;
    unchanged?: number;
  };
  eventLog?: unknown;
  event_log?: unknown;
  errorDetail?: unknown;
  error_detail?: unknown;
}

interface ScanFileRecord {
  id: string;
  scanId: string;
  path: string;
  blobSha: string | null;
  format: string | null;
  confidence: number | null;
  discriminator: string | null;
  tracked: boolean;
  projectSlug: string | null;
  versionStrategy: string | null;
  status: string;
  qualityScore: number | null;
  promote: 'auto' | 'manual' | null;
  settingsJson: Record<string, unknown> | null;
}

interface SyncHistoryRecord {
  id: string;
  state: string;
  operation: string;
  branch: string;
  sourceUri: string;
  repositoryFileId: string;
  conflictRecords: Array<{ schemaName?: string; kinds?: string[]; message?: string }>;
  createdAt: string;
}

function formatRepositoryStatus(status: string): string {
  if (status === 'archived') return 'Disabled';
  if (status === 'scan_in_progress') return 'Scan in progress';
  return status.replace(/_/g, ' ');
}

function buildRawDiffPreview(file: ScanFileRecord): string {
  if (file.status === 'new') {
    return `+ Added file ${file.path}\n+ blob: ${file.blobSha || 'unknown'}\n+ format: ${file.format || 'unknown'}`;
  }
  if (file.status === 'removed') {
    return `- Removed file ${file.path}\n- previous blob: ${file.blobSha || 'unknown'}`;
  }
  if (file.status === 'modified') {
    return `~ Modified ${file.path}\n- old blob: (previous scan)\n+ new blob: ${file.blobSha || 'unknown'}`;
  }
  return `No textual diff available for ${file.path}\nStatus: ${file.status}`;
}

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return 'n/a';
  return new Date(value).toLocaleString();
}

function formatDuration(startedAt: string, finishedAt: string | null): string {
  if (!startedAt || !finishedAt) return 'n/a';
  const started = Date.parse(startedAt);
  const finished = Date.parse(finishedAt);
  if (!Number.isFinite(started) || !Number.isFinite(finished) || finished < started) return 'n/a';
  const elapsedSec = Math.floor((finished - started) / 1000);
  if (elapsedSec < 60) return `${elapsedSec}s`;
  const minutes = Math.floor(elapsedSec / 60);
  const seconds = elapsedSec % 60;
  if (minutes < 60) return `${minutes}m ${seconds}s`;
  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  return `${hours}h ${remainingMinutes}m ${seconds}s`;
}

function toErrorDetailText(value: unknown): string {
  if (!value) return '';
  if (typeof value === 'string') return value;
  if (Array.isArray(value)) return value.map((entry) => String(entry)).join('\n');
  if (typeof value === 'object') {
    const detail = value as { detail?: unknown; message?: unknown };
    if (typeof detail.detail === 'string') return detail.detail;
    if (typeof detail.message === 'string') return detail.message;
    return JSON.stringify(value, null, 2);
  }
  return String(value);
}

function toEventLogLines(value: unknown): string[] {
  if (!value) return [];
  if (Array.isArray(value)) {
    return value.flatMap((entry) => {
      if (typeof entry === 'string') return [entry];
      if (entry && typeof entry === 'object') {
        const item = entry as {
          timestamp?: string;
          level?: string;
          message?: string;
          error?: string;
          stack?: string;
          detail?: string;
        };
        const prefixBits = [item.timestamp, item.level].filter(Boolean).join(' ');
        const body = item.message || item.error || item.detail || '';
        const line = [prefixBits, body].filter(Boolean).join(' ').trim();
        if (item.stack && line) return [line, item.stack];
        if (item.stack) return [item.stack];
        if (line) return [line];
        return [JSON.stringify(entry, null, 2)];
      }
      return [String(entry)];
    });
  }
  if (typeof value === 'string') return [value];
  if (typeof value === 'object') return [JSON.stringify(value, null, 2)];
  return [String(value)];
}

function extractScanErrorConsole(scan: ScanRecord): string {
  const eventLogValue = scan.eventLog ?? scan.event_log;
  const detailValue = scan.errorDetail ?? scan.error_detail;
  const sections: string[] = [];
  const eventLines = toEventLogLines(eventLogValue);
  if (eventLines.length > 0) {
    sections.push(eventLines.join('\n'));
  }
  const detailText = toErrorDetailText(detailValue);
  if (detailText) {
    sections.push(detailText);
  }
  if (sections.length === 0) {
    return 'No event log or error detail available for this failed scan.';
  }
  return sections.join('\n\n');
}

export default function RepositoryDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const searchParams = useSearchParams();
  const copy = getRepositoriesI18nBundle('en');
  const repositoryId = params?.id || '';

  const activeTab = useMemo<RepositoryTab>(() => {
    const queryTab = searchParams.get('tab');
    if (queryTab && repositoryTabs.includes(queryTab as RepositoryTab)) {
      return queryTab as RepositoryTab;
    }
    return 'branches';
  }, [searchParams]);

  const [repository, setRepository] = useState<RepositoryDetail | null>(null);
  const [branchRows, setBranchRows] = useState<BranchRow[]>([]);
  const [availableBranches, setAvailableBranches] = useState<string[]>([]);
  const [customBranchPattern, setCustomBranchPattern] = useState('');
  const [manifestDraft, setManifestDraft] = useState('');
  const [ownerInput, setOwnerInput] = useState('');
  const [nameInput, setNameInput] = useState('');
  const [scans, setScans] = useState<ScanRecord[]>([]);
  const [scanFiles, setScanFiles] = useState<ScanFileRecord[]>([]);
  const [syncHistory, setSyncHistory] = useState<SyncHistoryRecord[]>([]);
  const [selectedScanId, setSelectedScanId] = useState<string>('');
  const [selectedFile, setSelectedFile] = useState<ScanFileRecord | null>(null);
  const [fileScrollTop, setFileScrollTop] = useState(0);
  const [formatFilter, setFormatFilter] = useState('all');
  const [fileStatusFilter, setFileStatusFilter] = useState('all');
  const [isLoadingRepository, setIsLoadingRepository] = useState(true);
  const [isLoadingScans, setIsLoadingScans] = useState(false);
  const [isLoadingFiles, setIsLoadingFiles] = useState(false);
  const [isLoadingSync, setIsLoadingSync] = useState(false);
  const [isSavingBranches, setIsSavingBranches] = useState(false);
  const [isSavingSettings, setIsSavingSettings] = useState(false);
  const [isSavingManifest, setIsSavingManifest] = useState(false);
  const [isMutatingLifecycle, setIsMutatingLifecycle] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [deleteConfirmation, setDeleteConfirmation] = useState('');
  const [errorMessage, setErrorMessage] = useState('');
  const [successMessage, setSuccessMessage] = useState('');
  const fileViewportRef = useRef<HTMLDivElement | null>(null);
  const fileDrawerRef = useRef<HTMLElement | null>(null);

  const [manifestValidation, setManifestValidation] = useState<{ valid: boolean; errors: string[] }>({ valid: true, errors: [] });
  const [scanTriggerFilter, setScanTriggerFilter] = useState('all');
  const [scanStatusFilter, setScanStatusFilter] = useState('all');
  const [scanBranchFilter, setScanBranchFilter] = useState('all');
  const [expandedScanErrorId, setExpandedScanErrorId] = useState('');

  useEffect(() => {
    const source = manifestDraft.trim();
    if (!source) {
      setManifestValidation({ valid: true, errors: [] });
      return;
    }
    let cancelled = false;
    Promise.all([
      import('ajv/dist/2020'),
      import('yaml'),
    ]).then(([{ default: Ajv2020 }, { parse: parseYaml }]) => {
      if (cancelled) return;
      const ajv = new Ajv2020({ allErrors: true, strict: false });
      const validate = ajv.compile(repositoryManifestSchema);
      try {
        const parsed = parseYaml(source);
        const valid = validate(parsed);
        if (cancelled) return;
        if (valid) {
          setManifestValidation({ valid: true, errors: [] });
        } else {
          const errors = (validate.errors ?? []).map((e) => `${e.instancePath || '/'}: ${e.message ?? 'Invalid'}`);
          setManifestValidation({ valid: false, errors });
        }
      } catch (e) {
        if (cancelled) return;
        setManifestValidation({ valid: false, errors: [e instanceof Error ? e.message : 'Invalid YAML'] });
      }
    }).catch((e) => {
      if (cancelled) return;
      setManifestValidation({ valid: false, errors: [e instanceof Error ? e.message : 'Invalid YAML'] });
    });
    return () => { cancelled = true; };
  }, [manifestDraft]);

  const setTab = useCallback((nextTab: RepositoryTab) => {
    const nextQuery = new URLSearchParams(searchParams.toString());
    nextQuery.set('tab', nextTab);
    router.replace(`/ade/dashboard/repositories/${repositoryId}?${nextQuery.toString()}`);
  }, [repositoryId, router, searchParams]);

  const loadRepository = useCallback(async () => {
    if (!repositoryId) return;
    setIsLoadingRepository(true);
    setErrorMessage('');
    try {
      const response = await fetch(`/api/repositories/${repositoryId}`);
      const data = await response.json();
      if (!response.ok || !data.success) {
        throw new Error(data.error || 'Failed to load repository');
      }
      const loadedRepository = data.repository as RepositoryDetail;
      setRepository(loadedRepository);
      setOwnerInput(loadedRepository.owner);
      setNameInput(loadedRepository.name);
      setManifestDraft(loadedRepository.manifest || '');
      setBranchRows(
        (loadedRepository.branches || []).map((branch) => ({
          branch: branch.branch,
          subpathGlob: branch.subpathGlob || '**/*',
          pollIntervalSec: branch.pollIntervalSec,
        }))
      );
      if (loadedRepository.linkedAccountId && loadedRepository.fullName) {
        const branchesResponse = await fetch(
          `/api/sso/github/branches?accountId=${encodeURIComponent(loadedRepository.linkedAccountId)}&repo=${encodeURIComponent(loadedRepository.fullName)}`
        );
        const branchesData = await branchesResponse.json();
        if (branchesResponse.ok && Array.isArray(branchesData.branches)) {
          setAvailableBranches(branchesData.branches);
        } else {
          setAvailableBranches([]);
        }
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to load repository';
      setErrorMessage(message);
    } finally {
      setIsLoadingRepository(false);
    }
  }, [repositoryId]);

  const loadScans = useCallback(async () => {
    if (!repositoryId) return;
    setIsLoadingScans(true);
    try {
      const response = await fetch(`/api/repositories/${repositoryId}/scans?limit=100`);
      const data = await response.json();
      if (!response.ok || !data.success) {
        throw new Error(data.error || 'Failed to load scan history');
      }
      const scanRows = Array.isArray(data.items) ? (data.items as ScanRecord[]) : [];
      setScans(scanRows);
      const queryScanId = searchParams.get('scanId');
      const defaultScanId = queryScanId && scanRows.some((scan) => scan.id === queryScanId)
        ? queryScanId
        : (scanRows[0]?.id || '');
      setSelectedScanId(defaultScanId);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to load scan history';
      setErrorMessage(message);
    } finally {
      setIsLoadingScans(false);
    }
  }, [repositoryId, searchParams]);

  const loadScanFiles = useCallback(async () => {
    if (!repositoryId || !selectedScanId) return;
    setIsLoadingFiles(true);
    try {
      const response = await fetch(`/api/repositories/${repositoryId}/scans/${selectedScanId}/files?limit=2000`);
      const data = await response.json();
      if (!response.ok || !data.success) {
        throw new Error(data.error || 'Failed to load scan files');
      }
      const rows = Array.isArray(data.items) ? (data.items as ScanFileRecord[]) : [];
      setScanFiles(rows);
      setSelectedFile(null);
      setFileScrollTop(0);
      if (fileViewportRef.current) {
        fileViewportRef.current.scrollTop = 0;
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to load scan files';
      setErrorMessage(message);
    } finally {
      setIsLoadingFiles(false);
    }
  }, [repositoryId, selectedScanId]);

  const loadSyncHistory = useCallback(async () => {
    if (!repositoryId) return;
    setIsLoadingSync(true);
    try {
      const response = await fetch(`/api/repositories/${repositoryId}/sync-history?limit=100`);
      const data = await response.json();
      if (!response.ok || !data.success) {
        throw new Error(data.error || 'Failed to load sync history');
      }
      setSyncHistory(Array.isArray(data.items) ? (data.items as SyncHistoryRecord[]) : []);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to load sync history';
      setErrorMessage(message);
    } finally {
      setIsLoadingSync(false);
    }
  }, [repositoryId]);

  useEffect(() => {
    void loadRepository();
  }, [loadRepository]);

  useEffect(() => {
    if (activeTab === 'scans' || activeTab === 'files') {
      void loadScans();
    }
    if (activeTab === 'sync') {
      void loadSyncHistory();
    }
  }, [activeTab, loadScans, loadSyncHistory]);

  useEffect(() => {
    if (activeTab === 'files' && selectedScanId) {
      void loadScanFiles();
    }
  }, [activeTab, loadScanFiles, selectedScanId]);

  useEffect(() => {
    if (selectedFile && fileDrawerRef.current) {
      const firstFocusable = fileDrawerRef.current.querySelector<HTMLElement>(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
      );
      firstFocusable?.focus();
    }
  }, [selectedFile]);

  const filteredFiles = useMemo(() => {
    return scanFiles.filter((file) => {
      if (formatFilter !== 'all' && (file.format || 'unknown') !== formatFilter) return false;
      if (fileStatusFilter !== 'all' && file.status !== fileStatusFilter) return false;
      return true;
    });
  }, [fileStatusFilter, formatFilter, scanFiles]);

  const visibleRange = useMemo(() => {
    const start = Math.max(0, Math.floor(fileScrollTop / rowHeightPx) - 6);
    const end = Math.min(filteredFiles.length, Math.ceil((fileScrollTop + fileViewportHeightPx) / rowHeightPx) + 6);
    return { start, end };
  }, [fileScrollTop, filteredFiles.length]);

  const visibleFiles = useMemo(
    () => filteredFiles.slice(visibleRange.start, visibleRange.end),
    [filteredFiles, visibleRange.end, visibleRange.start]
  );

  const normalizeScanFilterValue = useCallback((value?: string | null) => value || 'unknown', []);

  const scanTriggerOptions = useMemo(
    () => Array.from(new Set(scans.map((scan) => normalizeScanFilterValue(scan.trigger)))),
    [normalizeScanFilterValue, scans]
  );

  const scanStatusOptions = useMemo(
    () => Array.from(new Set(scans.map((scan) => normalizeScanFilterValue(scan.status)))),
    [normalizeScanFilterValue, scans]
  );

  const scanBranchOptions = useMemo(
    () => Array.from(new Set(scans.map((scan) => normalizeScanFilterValue(scan.branch)))),
    [normalizeScanFilterValue, scans]
  );

  const filteredScans = useMemo(() => {
    return scans.filter((scan) => {
      if (scanTriggerFilter !== 'all' && normalizeScanFilterValue(scan.trigger) !== scanTriggerFilter) return false;
      if (scanStatusFilter !== 'all' && normalizeScanFilterValue(scan.status) !== scanStatusFilter) return false;
      if (scanBranchFilter !== 'all' && normalizeScanFilterValue(scan.branch) !== scanBranchFilter) return false;
      return true;
    });
  }, [normalizeScanFilterValue, scanBranchFilter, scanStatusFilter, scanTriggerFilter, scans]);

  const saveBranches = async () => {
    if (!repository || branchRows.length === 0) {
      setErrorMessage(copy.branchesRequired);
      return;
    }
    setIsSavingBranches(true);
    setErrorMessage('');
    setSuccessMessage('');
    try {
      const response = await fetch(`/api/repositories/${repository.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          branches: branchRows.map((row) => ({
            branch: row.branch.trim(),
            subpathGlob: row.subpathGlob.trim() || undefined,
            pollIntervalSec: row.pollIntervalSec,
          })),
        }),
      });
      const data = await response.json();
      if (!response.ok || !data.success) {
        throw new Error(data.error || 'Failed to update branches');
      }
      const updatedRepository = data.repository as RepositoryDetail;
      setRepository(updatedRepository);
      setBranchRows(
        updatedRepository.branches.map((branch) => ({
          branch: branch.branch,
          subpathGlob: branch.subpathGlob ?? '',
          pollIntervalSec: branch.pollIntervalSec ?? undefined,
        })),
      );
      setSuccessMessage(copy.branchesUpdatedMessage);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to update branches';
      setErrorMessage(message);
    } finally {
      setIsSavingBranches(false);
    }
  };

  const saveSettings = async () => {
    if (!repository) return;
    const owner = ownerInput.trim();
    const name = nameInput.trim();
    if (!owner || !name) {
      setErrorMessage(copy.ownerNameRequired);
      return;
    }
    setIsSavingSettings(true);
    setErrorMessage('');
    setSuccessMessage('');
    try {
      const response = await fetch(`/api/repositories/${repository.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ owner, name }),
      });
      const data = await response.json();
      if (!response.ok || !data.success) {
        throw new Error(data.error || 'Failed to update repository settings');
      }
      const updatedRepository = data.repository as RepositoryDetail;
      setRepository(updatedRepository);
      setOwnerInput(updatedRepository.owner);
      setNameInput(updatedRepository.name);
      setSuccessMessage(copy.settingsUpdatedMessage);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to update repository settings';
      setErrorMessage(message);
    } finally {
      setIsSavingSettings(false);
    }
  };

  const saveManifest = async () => {
    if (!repository) return;
    if (!manifestValidation.valid) {
      setErrorMessage('Fix manifest validation errors before saving.');
      return;
    }
    setIsSavingManifest(true);
    setErrorMessage('');
    setSuccessMessage('');
    try {
      const response = await fetch(`/api/repositories/${repository.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ manifest: manifestDraft }),
      });
      const data = await response.json();
      if (!response.ok || !data.success) {
        throw new Error(data.error || 'Failed to update repository manifest');
      }
      setRepository(data.repository as RepositoryDetail);
      setSuccessMessage('Repository manifest saved.');
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to update repository manifest';
      setErrorMessage(message);
    } finally {
      setIsSavingManifest(false);
    }
  };

  const triggerScanNow = async () => {
    if (!repository) return;
    const branch = branchRows[0]?.branch || repository.branches[0]?.branch || 'main';
    setErrorMessage('');
    setSuccessMessage('');
    try {
      const response = await fetch(`/api/repositories/${repository.id}/scans`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ branch, force: true }),
      });
      const data = await response.json();
      if (!response.ok || !data.success) {
        throw new Error(data.error || 'Failed to queue scan');
      }
      setSuccessMessage(copy.scanQueuedMessage);
      await loadScans();
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to queue scan';
      setErrorMessage(message);
    }
  };

  const updateLifecycle = async (action: 'archive' | 'unarchive') => {
    if (!repository) return;
    setIsMutatingLifecycle(true);
    setErrorMessage('');
    setSuccessMessage('');
    try {
      const response = await fetch(`/api/repositories/${repository.id}/${action}`, { method: 'POST' });
      const data = await response.json();
      if (!response.ok || !data.success) {
        throw new Error(data.error || 'Failed to update repository lifecycle');
      }
      setRepository(data.repository as RepositoryDetail);
      setSuccessMessage(action === 'archive' ? copy.repositoryDisabledMessage : copy.repositoryEnabledMessage);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to update repository lifecycle';
      setErrorMessage(message);
    } finally {
      setIsMutatingLifecycle(false);
    }
  };

  const deleteRepository = async () => {
    if (!repository) return;
    setIsDeleting(true);
    try {
      const response = await fetch(`/api/repositories/${repository.id}`, {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ confirmFullName: deleteConfirmation }),
      });
      if (response.status !== 204) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || 'Failed to delete repository');
      }
      router.push('/ade/dashboard/repositories');
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to delete repository';
      setErrorMessage(message);
      setIsDeleting(false);
    }
  };

  return (
    <>
      <header className="border-b border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800">
        <div className="px-6 py-4">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h2 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
                <GitBranchPlus className="w-6 h-6 text-indigo-600 dark:text-indigo-400" />
                {repository?.fullName || copy.pageTitle}
              </h2>
              <p className="text-gray-600 dark:text-gray-400 text-sm mt-1">
                Provider {repository?.provider || 'github'} · Status {repository ? formatRepositoryStatus(repository.status) : 'Loading'}
              </p>
            </div>
            <Button variant="outline" onClick={() => router.push('/ade/dashboard/repositories')}>
              <ArrowLeft className="w-4 h-4 mr-2" />
              {copy.backButton}
            </Button>
          </div>
        </div>
      </header>

      <main className={dashboardMainClass}>
        <div className={dashboardContentStackClass}>
          {errorMessage ? <Alert variant="error" onClose={() => setErrorMessage('')}>{errorMessage}</Alert> : null}
          {successMessage ? <Alert variant="success" onClose={() => setSuccessMessage('')}>{successMessage}</Alert> : null}

          {isLoadingRepository ? (
            <div className="flex items-center justify-center py-10 text-sm text-gray-500 dark:text-gray-400">
              <Loader2 className="h-5 w-5 animate-spin mr-2" />
              {copy.loadingRepository}
            </div>
          ) : null}

          {repository ? (
            <Tabs value={activeTab} onValueChange={(value) => setTab(value as RepositoryTab)} className="space-y-3">
              <TabsList className="w-full justify-start overflow-x-auto">
                <TabsTrigger value="branches">Branches</TabsTrigger>
                <TabsTrigger value="files">Files</TabsTrigger>
                <TabsTrigger value="scans">Scans</TabsTrigger>
                <TabsTrigger value="sync">Sync history</TabsTrigger>
                <TabsTrigger value="manifest">Manifest</TabsTrigger>
                <TabsTrigger value="settings">Settings</TabsTrigger>
              </TabsList>

              <TabsContent value="branches" className={`${dashboardPanelClass} p-5 space-y-3`}>
                <h3 className="font-semibold">Tracked branches</h3>
                <div className="flex flex-wrap gap-2">
                  {availableBranches.map((branchName) => (
                    <Button
                      key={branchName}
                      type="button"
                      size="sm"
                      variant={branchRows.some((row) => row.branch === branchName) ? 'secondary' : 'outline'}
                      onClick={() => {
                        setBranchRows((prev) =>
                          prev.some((row) => row.branch === branchName)
                            ? prev.filter((row) => row.branch !== branchName)
                            : [...prev, { branch: branchName, subpathGlob: '**/*' }]
                        );
                      }}
                    >
                      {branchName}
                    </Button>
                  ))}
                </div>
                <div className="flex items-center gap-2">
                  <Input
                    value={customBranchPattern}
                    onChange={(event) => setCustomBranchPattern(event.target.value)}
                    placeholder={copy.branchPatternPlaceholder}
                  />
                  <Button
                    variant="outline"
                    onClick={() => {
                      const next = customBranchPattern.trim();
                      if (!next || branchRows.some((row) => row.branch === next)) return;
                      setBranchRows((prev) => [...prev, { branch: next, subpathGlob: '**/*' }]);
                      setCustomBranchPattern('');
                    }}
                  >
                    {copy.addPatternButton}
                  </Button>
                </div>
                <div className="space-y-2">
                  {branchRows.map((branch) => (
                    <div key={branch.branch} className="rounded-lg border border-gray-200 dark:border-gray-700 p-3 space-y-2">
                      <div className="flex items-center justify-between">
                        <span className="font-medium">{branch.branch}</span>
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          onClick={() => setBranchRows((prev) => prev.filter((row) => row.branch !== branch.branch))}
                        >
                          {copy.removeButton}
                        </Button>
                      </div>
                      <Input
                        value={branch.subpathGlob}
                        placeholder={copy.branchSubpathPlaceholder}
                        onChange={(event) =>
                          setBranchRows((prev) =>
                            prev.map((row) =>
                              row.branch === branch.branch
                                ? { ...row, subpathGlob: event.target.value }
                                : row
                            )
                          )
                        }
                      />
                      <Input
                        type="number"
                        min={15}
                        max={86400}
                        value={branch.pollIntervalSec ?? ''}
                        placeholder={copy.pollIntervalPlaceholder}
                        onChange={(event) => {
                          const next = Number.parseInt(event.target.value, 10);
                          setBranchRows((prev) =>
                            prev.map((row) =>
                              row.branch === branch.branch
                                ? { ...row, pollIntervalSec: Number.isFinite(next) ? next : undefined }
                                : row
                            )
                          );
                        }}
                      />
                    </div>
                  ))}
                </div>
                <div className="flex justify-end">
                  <Button onClick={() => void saveBranches()} disabled={isSavingBranches || branchRows.length === 0}>
                    {isSavingBranches ? copy.savingButton : copy.saveBranchesButton}
                  </Button>
                </div>
              </TabsContent>

              <TabsContent value="files" className={`${dashboardPanelClass} p-5 space-y-3`}>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h3 className="font-semibold">Repository files</h3>
                  <div className="flex items-center gap-2">
                    <select
                      className="h-9 rounded-md border border-gray-200 bg-white px-2 text-sm dark:border-gray-700 dark:bg-gray-900"
                      value={selectedScanId}
                      onChange={(event) => setSelectedScanId(event.target.value)}
                      aria-label="Scan"
                    >
                      {scans.map((scan) => (
                        <option key={scan.id} value={scan.id}>{scan.branch} · {scan.status} · {formatTimestamp(scan.startedAt)}</option>
                      ))}
                    </select>
                    <select
                      className="h-9 rounded-md border border-gray-200 bg-white px-2 text-sm dark:border-gray-700 dark:bg-gray-900"
                      value={formatFilter}
                      onChange={(event) => setFormatFilter(event.target.value)}
                      aria-label="Format"
                    >
                      <option value="all">Format: All</option>
                      {Array.from(new Set(scanFiles.map((file) => file.format || 'unknown'))).map((format) => (
                        <option key={format} value={format}>{format}</option>
                      ))}
                    </select>
                    <select
                      className="h-9 rounded-md border border-gray-200 bg-white px-2 text-sm dark:border-gray-700 dark:bg-gray-900"
                      value={fileStatusFilter}
                      onChange={(event) => setFileStatusFilter(event.target.value)}
                      aria-label="File status"
                    >
                      <option value="all">Status: All</option>
                      {Array.from(new Set(scanFiles.map((file) => file.status))).map((status) => (
                        <option key={status} value={status}>{status}</option>
                      ))}
                    </select>
                  </div>
                </div>
                {isLoadingFiles ? (
                  <div className="text-sm text-gray-500">Loading files...</div>
                ) : (
                  <div
                    ref={fileViewportRef}
                    className="rounded-lg border border-gray-200 dark:border-gray-700 overflow-auto"
                    style={{ height: fileViewportHeightPx }}
                    onScroll={(event) => setFileScrollTop(event.currentTarget.scrollTop)}
                  >
                    <div style={{ height: filteredFiles.length * rowHeightPx, position: 'relative' }}>
                      {visibleFiles.map((file, offset) => {
                        const index = visibleRange.start + offset;
                        return (
                          <button
                            key={file.id}
                            type="button"
                            className="absolute left-0 right-0 border-b border-gray-200 dark:border-gray-700 px-4 py-3 text-left hover:bg-gray-50 dark:hover:bg-gray-900"
                            style={{ top: index * rowHeightPx, height: rowHeightPx }}
                            onClick={() => setSelectedFile(file)}
                          >
                            <div className="flex items-center justify-between gap-4 text-sm">
                              <div className="font-medium truncate">{file.path}</div>
                              <span className="text-xs px-2 py-1 rounded-full bg-slate-100 dark:bg-slate-800">{file.status}</span>
                            </div>
                            <div className="text-xs text-gray-500 mt-1">
                              {(file.format || 'unknown').toUpperCase()} · {file.tracked ? 'tracked' : 'untracked'} · quality {file.qualityScore ?? 'n/a'}
                            </div>
                          </button>
                        );
                      })}
                    </div>
                  </div>
                )}
              </TabsContent>

              <TabsContent value="scans" className={`${dashboardPanelClass} p-5 space-y-3`}>
                <div className="flex items-center justify-between">
                  <h3 className="font-semibold">Scan timeline</h3>
                  <div className="flex items-center gap-2">
                    <Button variant="outline" onClick={() => void triggerScanNow()}>
                      <ScanSearch className="h-4 w-4 mr-2" />
                      {copy.scanNowButton}
                    </Button>
                    <a href={repo63IssueUrl} target="_blank" rel="noreferrer" className="text-sm text-indigo-600 hover:text-indigo-500">
                      Continue in REPO-6.3
                    </a>
                  </div>
                </div>
                {isLoadingScans ? <div className="text-sm text-gray-500">Loading scans...</div> : null}
                <div className="space-y-2">
                  <div className="text-xs font-semibold uppercase tracking-wide text-gray-500">Filter by trigger</div>
                  <div className="flex flex-wrap gap-2">
                    <Button
                      size="sm"
                      variant={scanTriggerFilter === 'all' ? 'secondary' : 'outline'}
                      onClick={() => setScanTriggerFilter('all')}
                    >
                      Trigger: All
                    </Button>
                    {scanTriggerOptions.map((trigger) => (
                      <Button
                        key={trigger}
                        size="sm"
                        variant={scanTriggerFilter === trigger ? 'secondary' : 'outline'}
                        onClick={() => setScanTriggerFilter(trigger)}
                      >
                        Trigger: {trigger}
                      </Button>
                    ))}
                  </div>
                  <div className="text-xs font-semibold uppercase tracking-wide text-gray-500">Filter by status</div>
                  <div className="flex flex-wrap gap-2">
                    <Button
                      size="sm"
                      variant={scanStatusFilter === 'all' ? 'secondary' : 'outline'}
                      onClick={() => setScanStatusFilter('all')}
                    >
                      Status: All
                    </Button>
                    {scanStatusOptions.map((status) => (
                      <Button
                        key={status}
                        size="sm"
                        variant={scanStatusFilter === status ? 'secondary' : 'outline'}
                        onClick={() => setScanStatusFilter(status)}
                      >
                        Status: {status}
                      </Button>
                    ))}
                  </div>
                  <div className="text-xs font-semibold uppercase tracking-wide text-gray-500">Filter by branch</div>
                  <div className="flex flex-wrap gap-2">
                    <Button
                      size="sm"
                      variant={scanBranchFilter === 'all' ? 'secondary' : 'outline'}
                      onClick={() => setScanBranchFilter('all')}
                    >
                      Branch: All
                    </Button>
                    {scanBranchOptions.map((branch) => (
                      <Button
                        key={branch}
                        size="sm"
                        variant={scanBranchFilter === branch ? 'secondary' : 'outline'}
                        onClick={() => setScanBranchFilter(branch)}
                      >
                        Branch: {branch}
                      </Button>
                    ))}
                  </div>
                </div>
                <ul className="space-y-2">
                  {filteredScans.map((scan) => (
                    <li key={scan.id} className="rounded-lg border border-gray-200 dark:border-gray-700 px-3 py-2">
                      <div className="flex flex-wrap items-start justify-between gap-2">
                        <div>
                          <div className="font-medium">{scan.branch} · {scan.status}</div>
                          <div className="text-xs text-gray-500">{formatTimestamp(scan.startedAt)} · commit {scan.commitSha}</div>
                          <div className="text-xs text-gray-500">Trigger {scan.trigger} · Duration {formatDuration(scan.startedAt, scan.finishedAt)}</div>
                          <div className="text-xs text-gray-500">
                            Files seen {scan.filesSeen} · classified {scan.filesClassified} · unknown {scan.filesUnknown} · failed {scan.filesFailed}
                          </div>
                          <div className="text-xs text-gray-500">
                            +{scan.diffSummary.added ?? 0} / ~{scan.diffSummary.modified ?? 0} / -{scan.diffSummary.removed ?? 0}
                          </div>
                        </div>
                        <div className="flex flex-col items-end gap-2">
                          <a
                            className="text-xs text-indigo-600 hover:text-indigo-500"
                            href={`/api/repositories/${repository.id}/scans/${scan.id}`}
                            target="_blank"
                            rel="noreferrer"
                          >
                            View repository_scan
                          </a>
                          {scan.status === 'failed' ? (
                            <Button
                              type="button"
                              size="sm"
                              variant="outline"
                              onClick={() => setExpandedScanErrorId((current) => (current === scan.id ? '' : scan.id))}
                            >
                              {expandedScanErrorId === scan.id ? 'Hide errors' : 'Show errors'}
                            </Button>
                          ) : null}
                        </div>
                      </div>
                      {scan.status === 'failed' && expandedScanErrorId === scan.id ? (
                        <pre className="mt-3 max-h-72 overflow-auto rounded-lg bg-gray-100 p-3 text-xs text-gray-700 dark:bg-gray-900 dark:text-gray-200">
                          {extractScanErrorConsole(scan)}
                        </pre>
                      ) : null}
                    </li>
                  ))}
                </ul>
              </TabsContent>

              <TabsContent value="sync" className={`${dashboardPanelClass} p-5 space-y-3`}>
                <h3 className="font-semibold">Sync history</h3>
                {isLoadingSync ? <div className="text-sm text-gray-500">Loading sync history...</div> : null}
                <ul className="space-y-2">
                  {syncHistory.map((entry) => (
                    <li key={entry.id} className="rounded-lg border border-gray-200 dark:border-gray-700 px-3 py-2">
                      <div className="flex items-center justify-between gap-3">
                        <div>
                          <div className="font-medium">{entry.operation} · {entry.state}</div>
                          <div className="text-xs text-gray-500">{entry.sourceUri}</div>
                          {entry.conflictRecords.length > 0 ? (
                            <div className="text-xs text-amber-600 mt-1">{entry.conflictRecords.length} conflict(s) pending</div>
                          ) : null}
                        </div>
                        <History className="h-4 w-4 text-gray-400" />
                      </div>
                    </li>
                  ))}
                </ul>
              </TabsContent>

              <TabsContent value="manifest" className={`${dashboardPanelClass} p-5 space-y-3`}>
                <div className="flex items-center justify-between">
                  <h3 className="font-semibold">Manifest</h3>
                  <Button onClick={() => void saveManifest()} disabled={isSavingManifest || !manifestValidation.valid}>
                    {isSavingManifest ? copy.savingButton : 'Save manifest'}
                  </Button>
                </div>
                <p className="text-xs text-gray-500">
                  Schema validation uses the published REPO-2.4 schema (`repo-manifest.v1.json`).
                </p>
                <div className="rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden">
                  <MonacoEditor
                    height="320px"
                    language="yaml"
                    value={manifestDraft}
                    onChange={(value) => setManifestDraft(value ?? '')}
                    options={{ minimap: { enabled: false }, fontSize: 13 }}
                  />
                </div>
                {manifestValidation.valid ? (
                  <div className="text-xs text-emerald-600">Manifest schema is valid.</div>
                ) : (
                  <ul className="text-xs text-red-600 space-y-1">
                    {manifestValidation.errors.map((error) => <li key={error}>{error}</li>)}
                  </ul>
                )}
              </TabsContent>

              <TabsContent value="settings" className={`${dashboardPanelClass} p-5 space-y-3`}>
                <h3 className="font-semibold flex items-center gap-2"><Settings2 className="h-4 w-4" />Repository settings</h3>
                <Input value={ownerInput} onChange={(event) => setOwnerInput(event.target.value)} placeholder={copy.ownerPlaceholder} />
                <Input value={nameInput} onChange={(event) => setNameInput(event.target.value)} placeholder={copy.namePlaceholder} />
                <div className="flex flex-wrap items-center gap-2">
                  <Button onClick={() => void saveSettings()} disabled={isSavingSettings}>
                    {isSavingSettings ? copy.savingButton : copy.saveSettingsButton}
                  </Button>
                  {repository.status === 'archived' ? (
                    <Button variant="outline" onClick={() => void updateLifecycle('unarchive')} disabled={isMutatingLifecycle}>
                      {copy.enableButton}
                    </Button>
                  ) : (
                    <Button variant="outline" onClick={() => void updateLifecycle('archive')} disabled={isMutatingLifecycle}>
                      {copy.disableButton}
                    </Button>
                  )}
                  <Button variant="destructive" onClick={() => setDeleteDialogOpen(true)} disabled={isDeleting}>
                    {copy.deleteButton}
                  </Button>
                </div>
              </TabsContent>
            </Tabs>
          ) : null}
        </div>
      </main>

      <Dialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{copy.deleteDialogTitle}</DialogTitle>
            <DialogDescription>
              {copy.deleteDialogDescriptionPrefix}{' '}
              <span className="font-semibold">{repository?.fullName}</span>{' '}
              {copy.deleteDialogDescriptionSuffix}
            </DialogDescription>
          </DialogHeader>
          <Input
            value={deleteConfirmation}
            onChange={(event) => setDeleteConfirmation(event.target.value)}
            placeholder={repository?.fullName || copy.ownerNameFallbackPlaceholder}
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteDialogOpen(false)} disabled={isDeleting}>
              {copy.cancelButton}
            </Button>
            <Button
              variant="destructive"
              onClick={() => void deleteRepository()}
              disabled={isDeleting || !repository || deleteConfirmation.trim() !== repository.fullName}
            >
              {isDeleting ? copy.savingButton : copy.deleteRepositoryButton}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {selectedFile ? (
        <div className="fixed inset-0 z-50 bg-black/30" role="presentation" onClick={() => setSelectedFile(null)}>
          <aside
            ref={fileDrawerRef}
            className="absolute right-0 top-0 h-full w-full max-w-xl bg-white dark:bg-gray-900 shadow-xl p-5 overflow-auto"
            role="dialog"
            aria-modal="true"
            aria-label="File detail drawer"
            onClick={(event) => event.stopPropagation()}
            onKeyDown={(event) => { if (event.key === 'Escape') setSelectedFile(null); }}
          >
            <div className="flex items-center justify-between">
              <h3 className="font-semibold flex items-center gap-2"><FileCode2 className="h-4 w-4" />{selectedFile.path}</h3>
              <Button variant="outline" size="sm" onClick={() => setSelectedFile(null)}>Close</Button>
            </div>
            <div className="mt-4 space-y-4">
              <section className="space-y-2">
                <h4 className="text-sm font-medium">Raw diff</h4>
                <pre className="text-xs rounded-lg bg-gray-100 dark:bg-gray-800 p-3 overflow-auto">{buildRawDiffPreview(selectedFile)}</pre>
              </section>
              <section className="space-y-1 text-sm">
                <h4 className="font-medium">Classification details</h4>
                <div>Status: {selectedFile.status}</div>
                <div>Format: {selectedFile.format || 'unknown'}</div>
                <div>Tracked: {selectedFile.tracked ? 'yes' : 'no'}</div>
                <div>Confidence: {selectedFile.confidence ?? 'n/a'}</div>
                <div>Discriminator: {selectedFile.discriminator || 'n/a'}</div>
                <div>Project: {selectedFile.projectSlug || 'n/a'}</div>
                <div>Version strategy: {selectedFile.versionStrategy || 'n/a'}</div>
                <div>Quality score: {selectedFile.qualityScore ?? 'n/a'}</div>
              </section>
              {selectedFile.tracked && selectedFile.promote === 'manual' && (selectedFile.status === 'new' || selectedFile.status === 'modified') ? (
                <Button
                  onClick={() => {
                    setSuccessMessage(`Promotion UI coming soon for ${selectedFile.path}.`);
                    setSelectedFile(null);
                  }}
                >
                  Promotion UI coming soon
                </Button>
              ) : null}
            </div>
          </aside>
        </div>
      ) : null}
    </>
  );
}
