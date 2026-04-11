'use client';

import Link from 'next/link';
import { useSession } from 'next-auth/react';
import { useEffect, useState, useRef, useMemo } from 'react';
import { Plus, Edit2, Trash2, Package, AlertCircle, Lock, Unlock, CheckCircle, Eye, Copy, MoreVertical, Network, Snowflake, GitBranch, GitMerge, Tag, GitFork, Shield, Sun, LayoutGrid, Undo2, ScrollText, ListOrdered } from 'lucide-react';
import dynamic from 'next/dynamic';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogDescription,
} from '../../../components/ui/Dialog';
import { Button } from '../../../components/ui/Button';
import { Input } from '../../../components/ui/Input';
import { Label } from '../../../components/ui/Label';
import { Alert } from '../../../components/ui/Alert';
import { LoadingState } from '../../../components/ui/LoadingState';
import { EmptyState } from '../../../components/ui/EmptyState';
import { Textarea } from '../../../components/ui/Textarea';
import { Badge } from '../../../components/ui/Badge';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../../../components/ui/Select';
import { useDialog } from '../../../components/providers/DialogProvider';
import {
  deleteVersion,
  getClassesForVersion,
  getPropertiesForClass,
  getTenantsAdministratedByUser
} from '../../../../../lib/db/helper';
import { generateOpenApiSpec } from '../../../utils/openapi';
import YAML from 'yaml';
import { diffLines, Change } from 'diff';
import {
  compareSchemas,
  buildClassLevelDiff,
  formatClassDiffStatLines,
  formatPropertyDiffLine,
  getClassChangeDiffs,
  groupSchemaConflictPathsByClass,
  type DiffSummary,
  type ClassDiffRow,
  getPathLabel,
} from '../../../../../lib/schema-diff';
import { compareLayouts, type LayoutDiffSummary, type LayoutState } from '../../../../../lib/layout-diff';
import { loadLayoutStateForVersionCompare } from '../../../../../lib/version-canvas-layout';
import {
  COMMIT_EXTERNAL_REF_MAX_CHARS,
  extractBreakingHintsFromChangelog,
  validateVersionNotesClient,
  VERSION_NOTES_LIMITS,
} from '../../../../../lib/version-notes';
import { generateBreakingChangesMarkdownFromSummary } from '../../../../../lib/breaking-changes-doc';
import { generateMigrationGuideMarkdownFromSummary } from '../../../../../lib/migration-guide-doc';
import { downloadMigrationGuidePdf } from '../../../utils/export-migration-guide-pdf';
import { sanitizeFilenameSegment } from '../../../utils/filename-utils';
import RelationshipGraphDialog from './RelationshipGraphDialog';
import VersionLineageSnippet from './VersionLineageSnippet';
import VersionHistoryGraphPanel from './VersionHistoryGraphPanel';
import { DEFAULT_HISTORY_WINDOW } from './version-history-dag';
import { toast } from 'sonner';
import { localDatetimeLocalToUtcIso, utcIsoToDatetimeLocalValue } from '../../../utils/revision-deprecation';

const Editor = dynamic(() => import('@monaco-editor/react'), {
  ssr: false,
  loading: () => (
    <LoadingState
      className="h-full"
      minHeightClassName="min-h-0"
      spinnerSize="md"
      message="Loading editor..."
    />
  ),
});

const VersionCanvasCompare = dynamic(() => import('./VersionCanvasCompare'), {
  ssr: false,
  loading: () => (
    <LoadingState
      className="min-h-[min(380px,45vh)] w-full"
      minHeightClassName="min-h-[min(380px,45vh)]"
      spinnerSize="md"
      message="Loading canvas compare…"
    />
  ),
});

interface Project { id: string; name: string; slug: string; }

interface Version {
  id: string;
  project_id: string;
  creator_id: string;
  version_id: string;
  shortMessage: string | null;
  changelog: string | null;
  enabled: boolean;
  published: boolean;
  deleted_at: string | null;
  created_at: string;
  updated_at: string;
  published_at: string | null;
  creator_name: string;
  creator_email: string;
  parent_version_id?: string | null;
  merge_parent_version_id?: string | null;
  forkedFromRevisionId?: string | null;
  upstreamProjectId?: string | null;
  forkSourceVersionLabel?: string | null;
  forkSourceProjectName?: string | null;
  upstreamProjectName?: string | null;
  revisionLocked?: boolean;
  /** Governance lifecycle (#739): stable | beta | deprecated | archived */
  lifecycle?: string;
  /** Revision JSON (#507, #748): deprecation, sunsetAt, successorRevisionId, … */
  metadata?: Record<string, unknown>;
}

interface VersionBranchRow {
  id: string;
  name: string;
  tip_version_id: string;
  tip_version_string?: string;
  created_at?: string;
  created_by?: string | null;
  protected?: boolean;
}

interface VersionTagRow {
  id: string;
  name: string;
  version_id: string;
  target_version_string?: string;
  message?: string | null;
  channel?: string | null;
  immutable?: boolean;
  protected?: boolean;
  created_by?: string | null;
}

const Versions = () => {
  const { data: session } = useSession();
  const { confirm: confirmDialog, alert: alertDialog } = useDialog();
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<string>('');
  const [versions, setVersions] = useState<Version[]>([]);
  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [showEditDialog, setShowEditDialog] = useState(false);
  const [showPublishDialog, setShowPublishDialog] = useState(false);
  const [publishVersionId, setPublishVersionId] = useState<string | null>(null);
  const [publishVisibility, setPublishVisibility] = useState<'private' | 'public'>('private');
  const [publishShortMessage, setPublishShortMessage] = useState('');
  const [publishChangelog, setPublishChangelog] = useState('');
  const [selectedVersion, setSelectedVersion] = useState<Version | null>(null);
  const [versionId, setVersionId] = useState('');
  const [autoGenerate, setAutoGenerate] = useState(true);
  const [bumpStrategy, setBumpStrategy] = useState<'patch' | 'minor'>('patch');
  const [nextAutoVersion, setNextAutoVersion] = useState<string>('');
  const [description, setDescription] = useState('');
  const [changeLog, setChangeLog] = useState('');
  /** Optional ticket / issue id (Jira, Linear, …) stored as external_ref on create (#2564). */
  const [commitExternalRef, setCommitExternalRef] = useState('');
  const [enabled, setEnabled] = useState(true);
  const [sourceVersionId, setSourceVersionId] = useState<string>('');
  /** When multiple named branches exist, select by branch id before resolving tip (#505). */
  const [copySourceBranchKey, setCopySourceBranchKey] = useState<string>('blank');
  const [branchListLoading, setBranchListLoading] = useState(false);
  const [branchListError, setBranchListError] = useState<string | null>(null);
  const [branchPermissionDenied, setBranchPermissionDenied] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');

  // Dropdown state
  const [openVersionDropdown, setOpenVersionDropdown] = useState<string | null>(null);
  const [dropdownPosition, setDropdownPosition] = useState<{ top: number; right: number } | null>(null);

  const [showOpenApiDialog, setShowOpenApiDialog] = useState(false);
  const [openApiSpec, setOpenApiSpec] = useState<string>('');
  const [openApiFormat, setOpenApiFormat] = useState<'json' | 'yaml'>('json');
  const [viewingVersion, setViewingVersion] = useState<Version | null>(null);
  const [isLoadingSpec, setIsLoadingSpec] = useState(false);

  const [showCompareDialog, setShowCompareDialog] = useState(false);
  const [compareVersion1Id, setCompareVersion1Id] = useState<string>('');
  const [compareVersion2Id, setCompareVersion2Id] = useState<string>('');
  const [compareSpec1, setCompareSpec1] = useState<string>('');
  const [compareSpec2, setCompareSpec2] = useState<string>('');
  const [compareFormat, setCompareFormat] = useState<'json' | 'yaml'>('json');
  const [isLoadingComparison, setIsLoadingComparison] = useState(false);
  const [diffResult, setDiffResult] = useState<Change[]>([]);
  const [schemaDiffSummary, setSchemaDiffSummary] = useState<DiffSummary | null>(null);
  const [classDiffRows, setClassDiffRows] = useState<ClassDiffRow[] | null>(null);
  const [classDiffSearch, setClassDiffSearch] = useState('');
  const [classDiffShowUnchanged, setClassDiffShowUnchanged] = useState(true);
  const [expandedClassDiffId, setExpandedClassDiffId] = useState<string | null>(null);
  /** When true, show all property drill lines for that class (performance for large schemas / #741). */
  const [propDrillShowAllByClass, setPropDrillShowAllByClass] = useState<Record<string, boolean>>({});
  const [classListScrollTop, setClassListScrollTop] = useState(0);
  const classListScrollRef = useRef<HTMLDivElement | null>(null);
  const [diffViewMode, setDiffViewMode] = useState<'overlay' | 'side-by-side'>('overlay');
  const [diffFilter, setDiffFilter] = useState<{
    showAdded: boolean;
    showRemoved: boolean;
    showModified: boolean;
  }>({ showAdded: true, showRemoved: true, showModified: true });
  const [activeCompareTab, setActiveCompareTab] = useState<
    'diff' | 'summary' | 'breaking' | 'migration' | 'canvas'
  >('diff');
  const [canvasCompareLeft, setCanvasCompareLeft] = useState<LayoutState | null>(null);
  const [canvasCompareRight, setCanvasCompareRight] = useState<LayoutState | null>(null);
  const [canvasCompareDiff, setCanvasCompareDiff] = useState<LayoutDiffSummary | null>(null);
  const [canvasCompareLoading, setCanvasCompareLoading] = useState(false);
  /** When this matches `baseId:compareId`, canvas snapshots for that pair are loaded (lazy). */
  const [canvasComparePairKey, setCanvasComparePairKey] = useState('');
  const [canvasCompareViewMode, setCanvasCompareViewMode] = useState<'split' | 'overlay'>('split');

  const [showRelationshipGraphDialog, setShowRelationshipGraphDialog] = useState(false);
  const [relationshipGraphVersion, setRelationshipGraphVersion] = useState<Version | null>(null);
  const [relationshipGraphClasses, setRelationshipGraphClasses] = useState<Array<{ id: string; name: string; properties?: Array<{ id: string; name: string; data: unknown }> }> | null>(null);
  const [isLoadingRelationshipGraph, setIsLoadingRelationshipGraph] = useState(false);

  const [hasClassSchemaMap, setHasClassSchemaMap] = useState<Record<string, boolean>>({});
  const [freezingSchemaVersionId, setFreezingSchemaVersionId] = useState<string | null>(null);

  const [versionBranches, setVersionBranches] = useState<VersionBranchRow[]>([]);
  const [showBranchDialog, setShowBranchDialog] = useState(false);
  const [branchFromVersionId, setBranchFromVersionId] = useState<string>('');
  const [branchNameInput, setBranchNameInput] = useState('');
  const [branchSaving, setBranchSaving] = useState(false);

  const [showForkDialog, setShowForkDialog] = useState(false);
  const [forkFromVersionId, setForkFromVersionId] = useState('');
  const [forkTargetProjectId, setForkTargetProjectId] = useState('');
  const [forkAutoGenerate, setForkAutoGenerate] = useState(true);
  const [forkVersionId, setForkVersionId] = useState('');
  const [forkBumpStrategy, setForkBumpStrategy] = useState<'patch' | 'minor'>('patch');
  const [forkDescription, setForkDescription] = useState('');
  const [forkChangeLog, setForkChangeLog] = useState('');
  const [forkSaving, setForkSaving] = useState(false);
  const [forkPreviewNext, setForkPreviewNext] = useState<string>('');

  const [versionTags, setVersionTags] = useState<VersionTagRow[]>([]);
  const [showTagDialog, setShowTagDialog] = useState(false);
  const [tagFromVersionId, setTagFromVersionId] = useState<string>('');
  const [tagNameInput, setTagNameInput] = useState('');
  const [tagMessageInput, setTagMessageInput] = useState('');
  const [tagChannelInput, setTagChannelInput] = useState('');
  const [tagImmutable, setTagImmutable] = useState(false);
  const [tagProtected, setTagProtected] = useState(false);
  const [tagSaving, setTagSaving] = useState(false);
  const [historyTagFilter, setHistoryTagFilter] = useState<string>('');
  const [lifecycleFilter, setLifecycleFilter] = useState<string>('');
  const [editLifecycle, setEditLifecycle] = useState<string>('stable');
  const [editDeprecationMessage, setEditDeprecationMessage] = useState('');
  const [editSunsetLocal, setEditSunsetLocal] = useState('');
  const [editSuccessorRevisionId, setEditSuccessorRevisionId] = useState('');
  const [editPublishedMetadataOnly, setEditPublishedMetadataOnly] = useState(false);
  const [compareBaseTagId, setCompareBaseTagId] = useState<string>('');
  const [compareToTagId, setCompareToTagId] = useState<string>('');
  /** #743: newest-first window for history DAG + "Load older" */
  const [historyGraphWindowSize, setHistoryGraphWindowSize] = useState(DEFAULT_HISTORY_WINDOW);

  const [showMergeDialog, setShowMergeDialog] = useState(false);
  const [mergeSourceBranch, setMergeSourceBranch] = useState('');
  const [mergeTargetBranch, setMergeTargetBranch] = useState('');
  const [mergePreviewLoading, setMergePreviewLoading] = useState(false);
  const [mergeApplyLoading, setMergeApplyLoading] = useState(false);
  const [mergePreviewData, setMergePreviewData] = useState<{
    classification?: { canAutoMerge: boolean; conflictPaths: string[]; addedSchemaNames: string[] };
    sourceTipVersionId?: string;
    targetTipVersionId?: string;
    mergeBaseVersionId?: string | null;
  } | null>(null);
  const [mergeCompatLoading, setMergeCompatLoading] = useState(false);
  const [mergeCompat, setMergeCompat] = useState<{
    overall: string;
    findings: Array<{ id?: string; category: string; rule: string; path: string; message: string }>;
    breakingChangeDocumentationIssueUrl?: string | null;
    tenantCompatGateActive?: boolean;
    mergeBlockedByCompatGate?: boolean;
  } | null>(null);

  const [showRollbackDialog, setShowRollbackDialog] = useState(false);
  const [rollbackTargetVersion, setRollbackTargetVersion] = useState<Version | null>(null);
  const [rollbackBranchName, setRollbackBranchName] = useState('');
  const [rollbackPreviewLoading, setRollbackPreviewLoading] = useState(false);
  const [rollbackApplyLoading, setRollbackApplyLoading] = useState(false);
  const [rollbackPreview, setRollbackPreview] = useState<{
    branchTipRevisionId?: string;
    compatOverall?: string;
    findings?: Array<{ id?: string; path: string; message: string; rule?: string }>;
    deprecationWarnings?: unknown[];
    rollbackBlockedByCompatGate?: boolean;
    breakingChangeDocumentationIssueUrl?: string | null;
  } | null>(null);
  const [rollbackSkipCompat, setRollbackSkipCompat] = useState(false);
  const [rollbackShortMessage, setRollbackShortMessage] = useState('');

  const otherProjects = useMemo(
    () => projects.filter((p) => p.id !== selectedProjectId),
    [projects, selectedProjectId]
  );

  const leftPanelRef = useRef<HTMLDivElement>(null);
  const rightPanelRef = useRef<HTMLDivElement>(null);
  const isSyncingScroll = useRef(false);

  const currentTenantId = (session?.user as any)?.current_tenant_id;
  const currentUserId = (session?.user as any)?.user_id;
  const isAdmin = Boolean((session?.user as any)?.is_tenant_admin);
  const [effectiveIsAdmin, setEffectiveIsAdmin] = useState<boolean>(isAdmin);

  useEffect(() => {
    let cancelled = false;
    const resolveAdmin = async () => {
      try {
        if (isAdmin) { if (!cancelled) setEffectiveIsAdmin(true); return; }
        if (!currentUserId || !currentTenantId) { if (!cancelled) setEffectiveIsAdmin(false); return; }
        const res = await getTenantsAdministratedByUser(currentUserId);
        const rows = JSON.parse(res) as Array<{ tenant_id: string }>;
        const isAdminForTenant = rows.some(r => r.tenant_id === currentTenantId);
        if (!cancelled) setEffectiveIsAdmin(isAdminForTenant);
      } catch { if (!cancelled) setEffectiveIsAdmin(false); }
    };
    resolveAdmin();
    return () => { cancelled = true; };
  }, [isAdmin, currentUserId, currentTenantId]);

  /**
   * Canvas snapshots load only when the Canvas tab is opened (#742) — not during OpenAPI compare —
   * to keep the initial compare fast and defer React Flow + layout queries.
   */
  useEffect(() => {
    if (activeCompareTab !== 'canvas' || diffResult.length === 0) return;
    if (!compareVersion1Id || !compareVersion2Id) return;
    const key = `${compareVersion1Id}:${compareVersion2Id}`;
    if (canvasComparePairKey === key) return;

    let cancelled = false;
    setCanvasCompareLoading(true);
    (async () => {
      try {
        const [left, right] = await Promise.all([
          loadLayoutStateForVersionCompare(compareVersion1Id, currentUserId, currentTenantId),
          loadLayoutStateForVersionCompare(compareVersion2Id, currentUserId, currentTenantId),
        ]);
        if (cancelled) return;
        setCanvasCompareLeft(left);
        setCanvasCompareRight(right);
        const l = left ?? { nodes: [], edges: [] };
        const r = right ?? { nodes: [], edges: [] };
        setCanvasCompareDiff(compareLayouts(l, r));
        setCanvasComparePairKey(key);
      } catch (e) {
        console.error('Canvas compare load failed:', e);
        if (!cancelled) {
          setCanvasCompareDiff(null);
          toast.error('Could not load canvas layouts for comparison');
        }
      } finally {
        if (!cancelled) setCanvasCompareLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [
    activeCompareTab,
    diffResult.length,
    compareVersion1Id,
    compareVersion2Id,
    canvasComparePairKey,
    currentUserId,
    currentTenantId,
  ]);

  useEffect(() => { if (currentTenantId) loadProjects(); }, [currentTenantId]);
  useEffect(() => { if (selectedProjectId) loadVersions(); else setVersions([]); }, [selectedProjectId, lifecycleFilter]);

  useEffect(() => {
    if (!forkTargetProjectId || !showForkDialog) {
      setForkPreviewNext('');
      return;
    }
    let cancelled = false;
    fetch(`/api/versions?projectId=${forkTargetProjectId}`)
      .then((r) => r.json())
      .then((data: { success?: boolean; versions?: Array<{ version_id: string }> }) => {
        if (cancelled || !data.success || !Array.isArray(data.versions)) return;
        const list = data.versions;
        if (list.length === 0) {
          setForkPreviewNext('0.1.0');
          return;
        }
        const latest = list[0].version_id;
        const match = latest.match(/^(\d+)\.(\d+)\.(\d+)$/);
        if (!match) {
          setForkPreviewNext('0.1.0');
          return;
        }
        const major = parseInt(match[1], 10);
        const minor = parseInt(match[2], 10);
        const patch = parseInt(match[3], 10);
        const next =
          forkBumpStrategy === 'minor' ? `${major}.${minor + 1}.0` : `${major}.${minor}.${patch + 1}`;
        setForkPreviewNext(next);
      })
      .catch(() => {
        if (!cancelled) setForkPreviewNext('');
      });
    return () => {
      cancelled = true;
    };
  }, [forkTargetProjectId, showForkDialog, forkBumpStrategy]);

  const loadBranches = async () => {
    if (!selectedProjectId) return;
    setBranchListLoading(true);
    setBranchListError(null);
    setBranchPermissionDenied(false);
    setVersionBranches([]);
    try {
      const r = await fetch(`/api/projects/${selectedProjectId}/version-branches`);
      if (r.status === 401 || r.status === 403) {
        setBranchPermissionDenied(true);
        setBranchListError('You do not have permission to view branch metadata for this project.');
        return;
      }
      const d = await r.json();
      if (d.success && Array.isArray(d.branches)) {
        setVersionBranches(d.branches);
      } else {
        setBranchListError(typeof d.error === 'string' ? d.error : 'Could not load branches');
      }
    } catch {
      setBranchListError('Could not load branches');
    } finally {
      setBranchListLoading(false);
    }
  };

  useEffect(() => {
    if (selectedProjectId) loadBranches();
    else setVersionBranches([]);
  }, [selectedProjectId]);

  const loadVersionTags = async () => {
    if (!selectedProjectId) return;
    try {
      const r = await fetch(`/api/projects/${selectedProjectId}/version-tags`);
      const d = await r.json();
      if (d.success && Array.isArray(d.tags)) setVersionTags(d.tags);
      else setVersionTags([]);
    } catch {
      setVersionTags([]);
    }
  };

  useEffect(() => {
    if (!selectedProjectId) {
      setVersionTags([]);
      setHistoryTagFilter('');
      setLifecycleFilter('');
    } else {
      setHistoryTagFilter('');
      setLifecycleFilter('');
    }
  }, [selectedProjectId]);

  useEffect(() => {
    if (!currentTenantId || versions.length === 0) {
      setHasClassSchemaMap({});
      return;
    }
    const versionIds = versions.map((v) => v.id);
    const url = `/api/database/versions/has-class-schema?versionIds=${versionIds.join(',')}`;
    fetch(url)
      .then((r) => r.json())
      .then((data) => {
        if (data.success && data.map) setHasClassSchemaMap(data.map);
        else setHasClassSchemaMap({});
      })
      .catch(() => setHasClassSchemaMap({}));
  }, [currentTenantId, versions]);

  const loadProjects = async () => {
    if (!currentTenantId) return;
    try {
      const response = await fetch('/api/projects');
      if (!response.ok) {
        throw new Error(`Failed to fetch projects: ${response.statusText}`);
      }
      const data = await response.json();
      if (data.success && data.projects) {
        setProjects(data.projects);
        if (data.projects.length > 0 && !selectedProjectId) setSelectedProjectId(data.projects[0].id);
      } else {
        throw new Error(data.error || 'Failed to load projects');
      }
    } catch (error) {
      console.error('Failed to load projects:', error);
      setProjects([]);
    }
  };

  const loadVersions = async () => {
    if (!selectedProjectId) return;
    try {
      const qs = new URLSearchParams({ projectId: selectedProjectId });
      if (lifecycleFilter) qs.set('lifecycle', lifecycleFilter);
      const response = await fetch(`/api/versions?${qs.toString()}`);
      if (!response.ok) {
        throw new Error(`Failed to fetch versions: ${response.statusText}`);
      }
      const data = await response.json();
      if (data.success && data.versions) {
        setVersions(data.versions);
        await loadVersionTags();
      } else {
        throw new Error(data.error || 'Failed to load versions');
      }
    } catch (error) {
      console.error('Failed to load versions:', error);
      setVersions([]);
    }
  };

  const calculateNextVersion = (strategy: 'patch' | 'minor' = 'patch'): string => {
    if (versions.length === 0) return '0.1.0';
    const latestVersion = versions[0].version_id;
    const match = latestVersion.match(/^(\d+)\.(\d+)\.(\d+)$/);
    if (!match) return '0.1.0';
    const major = parseInt(match[1], 10);
    const minor = parseInt(match[2], 10);
    const patch = parseInt(match[3], 10);
    return strategy === 'minor' ? `${major}.${minor + 1}.0` : `${major}.${minor}.${patch + 1}`;
  };

  const handleCreateClick = () => {
    setVersionId(''); setAutoGenerate(true); setBumpStrategy('patch');
    setNextAutoVersion(calculateNextVersion('patch')); setDescription('');
    setChangeLog(''); setCommitExternalRef(''); setEnabled(true); setSourceVersionId('');
    setCopySourceBranchKey('blank');
    setErrorMessage(''); setBranchListError(null);
    void loadBranches();
    setShowCreateDialog(true);
  };

  const createCommitMessageCheck = validateVersionNotesClient(description, '');
  const commitChangelogOverLimit = changeLog.trim().length > VERSION_NOTES_LIMITS.maxChangelogChars;
  const commitExternalRefTrim = commitExternalRef.trim();
  const createCommitFormValid =
    createCommitMessageCheck.ok &&
    !commitChangelogOverLimit &&
    commitExternalRefTrim.length <= COMMIT_EXTERNAL_REF_MAX_CHARS &&
    (autoGenerate || versionId.trim().length > 0);

  const handleCreateSubmit = async () => {
    if (!autoGenerate && !versionId.trim()) { setErrorMessage('Version ID is required when not auto-generating'); return; }
    const notesCheck = validateVersionNotesClient(description, changeLog);
    if (!notesCheck.ok) { setErrorMessage(notesCheck.error); return; }
    if (commitExternalRefTrim.length > COMMIT_EXTERNAL_REF_MAX_CHARS) {
      setErrorMessage(`External reference must be at most ${COMMIT_EXTERNAL_REF_MAX_CHARS} characters`);
      return;
    }

    let baseRevisionId = '';
    let branchName: string | undefined;
    if (versionBranches.length > 1) {
      if (copySourceBranchKey === 'blank') {
        const msg =
          'Select a branch line to push to (choose a branch tip or copy from a branch).';
        setErrorMessage(msg);
        toast.error(msg);
        return;
      }
      if (!copySourceBranchKey.startsWith('branch:')) {
        const msg = 'Select a valid branch for this commit.';
        setErrorMessage(msg);
        toast.error(msg);
        return;
      }
      const bid = copySourceBranchKey.slice('branch:'.length);
      const br = versionBranches.find((b) => b.id === bid);
      if (!br?.tip_version_id) {
        const msg = 'Could not resolve branch tip for push.';
        setErrorMessage(msg);
        toast.error(msg);
        return;
      }
      baseRevisionId = br.tip_version_id;
      branchName = br.name;
    } else if (versionBranches.length === 1) {
      baseRevisionId = versionBranches[0].tip_version_id;
      branchName = versionBranches[0].name;
    } else {
      baseRevisionId = versions[0]?.id ?? '';
    }

    setIsLoading(true); setErrorMessage('');
    try {
      const body: Record<string, unknown> = {
        projectId: selectedProjectId,
        shortMessage: description.trim(),
        changelog: changeLog.trim() || null,
        baseRevisionId,
      };
      if (branchName) body.branchName = branchName;
      if (commitExternalRefTrim) body.externalRef = commitExternalRefTrim;
      if (!autoGenerate) body.version_id = versionId.trim();
      if (autoGenerate) body.bump_strategy = bumpStrategy;
      if (sourceVersionId?.trim()) body.source_version_id = sourceVersionId.trim();

      const res = await fetch('/api/versions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const json = (await res.json()) as {
        success?: boolean;
        error?: string;
        version?: { copied_classes?: number; copy_warning?: string };
      };
      if (!res.ok || !json.success) {
        const err = typeof json.error === 'string' ? json.error : 'Failed to commit revision';
        setErrorMessage(err);
        toast.error(err);
        return;
      }
      setShowCreateDialog(false);
      await loadVersions();
      const v = json.version;
      if (v && typeof v.copied_classes === 'number' && v.copied_classes > 0) {
        toast.success(`Revision committed. Copied ${v.copied_classes} class(es).`);
      } else if (v?.copy_warning) {
        toast.warning(`Revision committed, but: ${v.copy_warning}`);
      } else {
        toast.success('Revision committed.');
      }
    } catch (error: unknown) {
      const msg = error instanceof Error ? error.message : 'An error occurred';
      setErrorMessage(msg);
      toast.error(msg);
    } finally {
      setIsLoading(false);
    }
  };

  const handleEditClick = (version: Version) => {
    if (version.published && !effectiveIsAdmin) {
      setErrorMessage('Cannot edit published version');
      return;
    }
    const lc = version.lifecycle ?? 'stable';
    if (lc === 'archived' && !effectiveIsAdmin) {
      toast.warning('Archived revisions are read-only.');
      return;
    }
    const meta = version.metadata ?? {};
    setEditDeprecationMessage(
      typeof meta.deprecationMessage === 'string' ? meta.deprecationMessage
        : typeof meta.message === 'string' ? meta.message
        : ''
    );
    const sunsetRaw =
      typeof meta.sunsetAt === 'string'
        ? meta.sunsetAt
        : typeof meta.sunsetDate === 'string'
          ? meta.sunsetDate
          : typeof meta.sunset_date === 'string'
            ? meta.sunset_date
            : '';
    setEditSunsetLocal(sunsetRaw ? utcIsoToDatetimeLocalValue(sunsetRaw) : '');
    setEditSuccessorRevisionId(
      typeof meta.successorRevisionId === 'string' ? meta.successorRevisionId
        : typeof meta.successor_revision_id === 'string' ? meta.successor_revision_id
        : ''
    );
    setEditPublishedMetadataOnly(Boolean(version.published && effectiveIsAdmin));
    setSelectedVersion(version); setVersionId(version.version_id);
    setDescription(version.shortMessage || ''); setChangeLog(version.changelog || '');
    setEnabled(version.enabled); setEditLifecycle(lc);
    setErrorMessage(''); setShowEditDialog(true);
  };

  const handleEditSubmit = async () => {
    if (!selectedVersion) return;
    if (!editPublishedMetadataOnly) {
      const notesCheck = validateVersionNotesClient(description, changeLog);
      if (!notesCheck.ok) {
        setErrorMessage(notesCheck.error);
        return;
      }
    }
    const isArchived = (selectedVersion.lifecycle ?? 'stable') === 'archived';
    if (isArchived && !effectiveIsAdmin) return;
    if (editSunsetLocal.trim()) {
      if (editLifecycle !== 'deprecated') {
        setErrorMessage('Set lifecycle to Deprecated when scheduling a sunset.');
        return;
      }
      if (!editSuccessorRevisionId.trim()) {
        setErrorMessage('Successor revision is required when a sunset is set.');
        return;
      }
    }
    setIsLoading(true); setErrorMessage('');
    try {
      const prevMeta = { ...(selectedVersion.metadata ?? {}) };
      const metadata: Record<string, unknown> = { ...prevMeta };
      metadata.lifecycle = editLifecycle;
      if (editDeprecationMessage.trim()) {
        metadata.deprecationMessage = editDeprecationMessage.trim();
      } else {
        delete metadata.deprecationMessage;
      }
      if (editSunsetLocal.trim()) {
        const iso = localDatetimeLocalToUtcIso(editSunsetLocal.trim());
        if (!iso) {
          setErrorMessage('Invalid sunset date/time');
          setIsLoading(false);
          return;
        }
        metadata.sunsetAt = iso;
      } else {
        metadata.sunsetAt = null;
        metadata.sunsetDate = null;
      }
      if (editSuccessorRevisionId.trim()) {
        metadata.successorRevisionId = editSuccessorRevisionId.trim();
      } else {
        metadata.successorRevisionId = null;
      }

      const body: Record<string, unknown> = {
        projectId: selectedProjectId,
      };
      if (editPublishedMetadataOnly) {
        body.metadata = metadata;
      } else {
        body.shortMessage = description.trim();
        body.changelog = changeLog.trim() || null;
        body.enabled = enabled;
        body.metadata = metadata;
      }
      const res = await fetch(`/api/versions/${selectedVersion.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (data.success) {
        setShowEditDialog(false);
        await loadVersions();
      } else {
        setErrorMessage(typeof data.error === 'string' ? data.error : 'Failed to update version');
      }
    } catch (error: unknown) {
      setErrorMessage(error instanceof Error ? error.message : 'An error occurred');
    } finally {
      setIsLoading(false);
    }
  };

  const handlePublishClick = (versionRecordId: string) => {
    const ver = versions.find(v => v.id === versionRecordId);
    if (!ver) return;
    if (ver.creator_id !== currentUserId && !effectiveIsAdmin) return;
    setPublishVersionId(versionRecordId);
    setPublishVisibility('private');
    setPublishShortMessage(ver.shortMessage?.trim() ?? '');
    setPublishChangelog(ver.changelog?.trim() ?? '');
    setShowPublishDialog(true);
  };

  const handlePublishConfirm = async () => {
    if (!publishVersionId) return;
    const version = versions.find((v) => v.id === publishVersionId);
    if (!version) {
      await alertDialog({ message: 'Version not found', variant: 'error' });
      return;
    }
    const notesCheck = validateVersionNotesClient(publishShortMessage, publishChangelog);
    if (!notesCheck.ok) {
      await alertDialog({ message: notesCheck.error, variant: 'error' });
      return;
    }
    try {
      const res = await fetch(`/api/versions/${publishVersionId}/publish`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          projectId: version.project_id,
          visibility: publishVisibility,
          shortMessage: publishShortMessage.trim(),
          changelog: publishChangelog.trim() || null,
        }),
      });
      const response = await res.json();
      if (response.success) {
        setShowPublishDialog(false);
        setPublishVersionId(null);
        await loadVersions();
      } else {
        await alertDialog({ message: response.error || 'Failed to publish', variant: 'error' });
      }
    } catch (error: unknown) {
      await alertDialog({ message: error instanceof Error ? error.message : 'An error occurred', variant: 'error' });
    }
  };

  const handleUnpublish = async (versionRecordId: string) => {
    const ver = versions.find((v) => v.id === versionRecordId);
    if (!ver) { await alertDialog({ message: 'Version not found', variant: 'error' }); return; }
    if (ver.creator_id !== currentUserId && !effectiveIsAdmin) { toast.warning('Only owner or admin can unpublish'); return; }
    const confirmed = await confirmDialog({ title: 'Unpublish Version', message: 'Best practice is to keep it published. Are you sure?', variant: 'danger', confirmLabel: 'Unpublish', cancelLabel: 'Cancel' });
    if (!confirmed) return;
    try {
      const res = await fetch(`/api/versions/${versionRecordId}/unpublish`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ projectId: ver.project_id }),
      });
      const response = await res.json();
      if (response.success) await loadVersions();
      else await alertDialog({ message: response.error || 'Failed to unpublish', variant: 'error' });
    } catch (error: unknown) { await alertDialog({ message: error instanceof Error ? error.message : 'An error occurred', variant: 'error' }); }
  };

  const handleFreezeSchema = async (version: Version) => {
    if (version.creator_id !== currentUserId && !effectiveIsAdmin) {
      toast.warning('Only the version owner or a tenant admin can freeze schema.');
      return;
    }
    if (hasClassSchemaMap[version.id]) {
      toast.info('Schema is already frozen for this version.');
      return;
    }
    const confirmed = await confirmDialog({
      title: 'Freeze schema',
      message: 'This will capture the current class schemas for this version into the database so the version can be used in the Database section. Only versions with no schema captured yet can be frozen. Continue?',
      variant: 'info',
      confirmLabel: 'Freeze schema',
      cancelLabel: 'Cancel',
    });
    if (!confirmed) return;
    setFreezingSchemaVersionId(version.id);
    try {
      const res = await fetch(`/api/versions/${version.id}/freeze-schema`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ projectId: version.project_id }),
      });
      const response = await res.json();
      if (response.success) {
        await loadVersions();
        toast.success('Schema frozen successfully. This version can now be used in the Database section.');
      } else {
        await alertDialog({ message: response.error || 'Failed to freeze schema', variant: 'error' });
      }
    } catch (error: unknown) {
      await alertDialog({ message: error instanceof Error ? error.message : 'An error occurred', variant: 'error' });
    } finally {
      setFreezingSchemaVersionId(null);
    }
  };

  const handleDelete = async (versionRecordId: string) => {
    const confirmed = await confirmDialog({ title: 'Delete Version', message: 'This action cannot be undone.', variant: 'danger', confirmLabel: 'Delete', cancelLabel: 'Cancel' });
    if (!confirmed) return;
    try {
      const result = await deleteVersion(versionRecordId);
      const response = JSON.parse(result) as { success?: boolean; error?: string; code?: string };
      if (response.success) await loadVersions();
      else {
        const msg =
          response.code === 'REVISION_LOCKED'
            ? 'This revision is locked by policy and cannot be deleted (tenant admins may override).'
            : response.error || 'Failed to delete';
        await alertDialog({ message: msg, variant: 'error' });
      }
    } catch (error: any) { await alertDialog({ message: error.message || 'An error occurred', variant: 'error' }); }
  };

  const handleViewOpenApi = async (version: Version) => {
    setViewingVersion(version); setShowOpenApiDialog(true); setIsLoadingSpec(true); setOpenApiFormat('json');
    try {
      const classesResult = await getClassesForVersion(version.id);
      const classesData = JSON.parse(classesResult);
      const classesWithProperties = await Promise.all(classesData.map(async (cls: any) => {
        const propsResult = await getPropertiesForClass(cls.id);
        return { ...cls, properties: JSON.parse(propsResult) };
      }));
      const project = projects.find(p => p.id === version.project_id);
      const spec = await generateOpenApiSpec(classesWithProperties, { projectName: project?.name, version: version.version_id, description: version.shortMessage || undefined });
      setOpenApiSpec(spec);
    } catch (error) { setOpenApiSpec(JSON.stringify({ openapi: '3.1.0', info: { title: 'Error Loading Spec', version: version.version_id }, components: { schemas: {} } }, null, 2)); }
    finally { setIsLoadingSpec(false); }
  };

  const handleShowRelationshipGraph = async (version: Version) => {
    setRelationshipGraphVersion(version);
    setShowRelationshipGraphDialog(true);
    setIsLoadingRelationshipGraph(true);
    setRelationshipGraphClasses(null);
    try {
      const classesResult = await getClassesForVersion(version.id);
      const classesData = JSON.parse(classesResult);
      const classesWithProperties = await Promise.all(classesData.map(async (cls: any) => {
        const propsResult = await getPropertiesForClass(cls.id);
        return { ...cls, properties: JSON.parse(propsResult) };
      }));
      setRelationshipGraphClasses(classesWithProperties);
    } catch {
      setRelationshipGraphClasses([]);
    } finally {
      setIsLoadingRelationshipGraph(false);
    }
  };

  const loadVersionSpec = async (versionId: string): Promise<string> => {
    const version = versions.find(v => v.id === versionId);
    if (!version) throw new Error('Version not found');
    const classesResult = await getClassesForVersion(version.id);
    const classesData = JSON.parse(classesResult);
    const classesWithProperties = await Promise.all(classesData.map(async (cls: any) => {
      const propsResult = await getPropertiesForClass(cls.id);
      return { ...cls, properties: JSON.parse(propsResult) };
    }));
    const project = projects.find(p => p.id === version.project_id);
    return generateOpenApiSpec(classesWithProperties, { projectName: project?.name, version: version.version_id, description: version.shortMessage || undefined });
  };

  const runCompareBetween = async (baseId: string, targetId: string) => {
    if (!baseId || !targetId) {
      toast.warning('Please select two versions');
      return;
    }
    if (baseId === targetId) {
      toast.warning('Select two different versions');
      return;
    }
    setDiffResult([]);
    setSchemaDiffSummary(null);
    setClassDiffRows(null);
    setCanvasCompareLeft(null);
    setCanvasCompareRight(null);
    setCanvasCompareDiff(null);
    setCanvasComparePairKey('');
    setIsLoadingComparison(true);
    try {
      const [spec1, spec2] = await Promise.all([loadVersionSpec(baseId), loadVersionSpec(targetId)]);
      setCompareSpec1(spec1);
      setCompareSpec2(spec2);
      const diffSummary = compareSchemas(spec1, spec2);
      setSchemaDiffSummary(diffSummary);
      setClassDiffRows(buildClassLevelDiff(spec1, spec2));
      const content1 = compareFormat === 'json' ? spec1 : YAML.stringify(JSON.parse(spec1));
      const content2 = compareFormat === 'json' ? spec2 : YAML.stringify(JSON.parse(spec2));
      setDiffResult(diffLines(content1, content2));
    } catch (error) {
      console.error('Comparison error:', error);
      await alertDialog({ message: 'Failed to load specs for comparison', variant: 'error' });
    } finally {
      setIsLoadingComparison(false);
    }
  };

  const handleCompareVersions = async () => {
    await runCompareBetween(compareVersion1Id, compareVersion2Id);
  };

  const handleHistoryGraphCompareToParent = async (revisionId: string) => {
    const v = versions.find((x) => x.id === revisionId);
    if (!v?.parent_version_id?.trim()) {
      toast.info('This revision has no primary parent to compare against.');
      return;
    }
    setCompareVersion1Id(v.parent_version_id);
    setCompareVersion2Id(v.id);
    setShowCompareDialog(true);
    await runCompareBetween(v.parent_version_id, v.id);
  };

  const handleHistoryGraphViewSpec = async (revisionId: string) => {
    const v = versions.find((x) => x.id === revisionId);
    if (!v) return;
    await handleViewOpenApi(v);
  };

  const handleCompareDialogOpen = () => {
    setShowCompareDialog(true); setCompareVersion1Id(''); setCompareVersion2Id('');
    setCompareSpec1(''); setCompareSpec2(''); setCompareFormat('json');
    setDiffResult([]); setSchemaDiffSummary(null); setClassDiffRows(null);
    setClassDiffSearch(''); setClassDiffShowUnchanged(true); setExpandedClassDiffId(null);
    setPropDrillShowAllByClass({});
    setClassListScrollTop(0); setDiffViewMode('overlay');
    setCompareBaseTagId(''); setCompareToTagId('');
    setCanvasCompareLeft(null);
    setCanvasCompareRight(null);
    setCanvasCompareDiff(null);
    setCanvasComparePairKey('');
    setCanvasCompareViewMode('split');
    setActiveCompareTab('diff');
  };

  const tagsByVersionId = useMemo(() => {
    const map = new Map<string, VersionTagRow[]>();
    for (const t of versionTags) {
      const list = map.get(t.version_id) ?? [];
      list.push(t);
      map.set(t.version_id, list);
    }
    return map;
  }, [versionTags]);

  const CLASS_DIFF_ROW_PX = 40;
  const CLASS_DIFF_VIEWPORT_PX = 288;
  const CLASS_PROP_DRILL_LIMIT = 64;

  const mergeConflictGroups = useMemo(() => {
    const paths = mergePreviewData?.classification?.conflictPaths;
    if (!paths?.length) {
      return [];
    }
    return groupSchemaConflictPathsByClass(paths);
  }, [mergePreviewData?.classification?.conflictPaths]);

  const filteredClassDiffRows = useMemo(() => {
    if (!classDiffRows) return [];
    let rows = classDiffRows;
    if (!classDiffShowUnchanged) rows = rows.filter((r) => r.status !== 'unchanged');
    const q = classDiffSearch.trim().toLowerCase();
    if (q) rows = rows.filter((r) => r.stableId.toLowerCase().includes(q));
    return rows;
  }, [classDiffRows, classDiffSearch, classDiffShowUnchanged]);

  useEffect(() => {
    setClassListScrollTop(0);
    if (classListScrollRef.current) {
      classListScrollRef.current.scrollTop = 0;
    }
  }, [classDiffSearch, classDiffShowUnchanged]);

  const classListVirtual = useMemo(() => {
    const overscan = 6;
    const total = filteredClassDiffRows.length;
    const start = Math.max(0, Math.floor(classListScrollTop / CLASS_DIFF_ROW_PX) - overscan);
    const end = Math.min(
      total,
      Math.ceil((classListScrollTop + CLASS_DIFF_VIEWPORT_PX) / CLASS_DIFF_ROW_PX) + overscan
    );
    return {
      visibleRows: filteredClassDiffRows.slice(start, end),
      padTop: start * CLASS_DIFF_ROW_PX,
      padBottom: Math.max(0, (total - end) * CLASS_DIFF_ROW_PX),
      total,
    };
  }, [filteredClassDiffRows, classListScrollTop]);

  const classDiffCounts = useMemo(() => {
    if (!classDiffRows) return null;
    return {
      added: classDiffRows.filter((r) => r.status === 'added').length,
      removed: classDiffRows.filter((r) => r.status === 'removed').length,
      modified: classDiffRows.filter((r) => r.status === 'modified').length,
      unchanged: classDiffRows.filter((r) => r.status === 'unchanged').length,
    };
  }, [classDiffRows]);

  const breakingChangesMarkdown = useMemo(() => {
    if (!schemaDiffSummary) return '';
    const vBase = versions.find((v) => v.id === compareVersion1Id);
    const vTo = versions.find((v) => v.id === compareVersion2Id);
    return generateBreakingChangesMarkdownFromSummary(schemaDiffSummary, {
      baseLabel: vBase ? `v${vBase.version_id} (base)` : 'base',
      targetLabel: vTo ? `v${vTo.version_id} (compare)` : 'target',
    });
  }, [schemaDiffSummary, compareVersion1Id, compareVersion2Id, versions]);

  const migrationGuideMarkdown = useMemo(() => {
    if (!schemaDiffSummary) return '';
    const vBase = versions.find((v) => v.id === compareVersion1Id);
    const vTo = versions.find((v) => v.id === compareVersion2Id);
    const hintSet = new Set<string>();
    for (const h of extractBreakingHintsFromChangelog(vBase?.changelog)) {
      hintSet.add(h);
    }
    for (const h of extractBreakingHintsFromChangelog(vTo?.changelog)) {
      hintSet.add(h);
    }
    return generateMigrationGuideMarkdownFromSummary(schemaDiffSummary, {
      baseLabel: vBase ? `v${vBase.version_id} (base)` : 'base',
      targetLabel: vTo ? `v${vTo.version_id} (compare)` : 'target',
      baseRevisionId: compareVersion1Id,
      targetRevisionId: compareVersion2Id,
      breakingHintsFromChangelog: [...hintSet].sort((a, b) => a.localeCompare(b)),
    });
  }, [schemaDiffSummary, compareVersion1Id, compareVersion2Id, versions]);

  const appendBreakingDocToCompareTargetChangelog = () => {
    const vTo = versions.find((v) => v.id === compareVersion2Id);
    if (!vTo || !breakingChangesMarkdown.trim()) {
      toast.warning('Nothing to append');
      return;
    }
    if (vTo.published) {
      toast.warning('Cannot edit changelog on a published revision.');
      return;
    }
    const lc = vTo.lifecycle ?? 'stable';
    if (lc === 'archived') {
      toast.warning('Archived revisions cannot update changelog here. Copy the generated doc instead.');
      return;
    }
    const md = breakingChangesMarkdown.trim();
    const existing = vTo.changelog?.trim() ?? '';
    const sep = existing ? '\n\n---\n\n' : '';
    const merged = `${existing}${sep}${md}`;
    setSelectedVersion(vTo);
    setVersionId(vTo.version_id);
    setDescription(vTo.shortMessage || '');
    setChangeLog(merged);
    setEnabled(vTo.enabled);
    setEditLifecycle(lc);
    setErrorMessage('');
    setShowCompareDialog(false);
    setShowEditDialog(true);
    toast.success('Review changelog in Edit Version, then save.');
  };

  const appendMigrationGuideToCompareTargetChangelog = () => {
    const vTo = versions.find((v) => v.id === compareVersion2Id);
    if (!vTo || !migrationGuideMarkdown.trim()) {
      toast.warning('Nothing to append');
      return;
    }
    if (vTo.published) {
      toast.warning('Cannot edit changelog on a published revision.');
      return;
    }
    const lc = vTo.lifecycle ?? 'stable';
    if (lc === 'archived') {
      toast.warning('Archived revisions cannot update changelog here. Copy the generated guide instead.');
      return;
    }
    const md = migrationGuideMarkdown.trim();
    const existing = vTo.changelog?.trim() ?? '';
    const sep = existing ? '\n\n---\n\n' : '';
    const merged = `${existing}${sep}${md}`;
    setSelectedVersion(vTo);
    setVersionId(vTo.version_id);
    setDescription(vTo.shortMessage || '');
    setChangeLog(merged);
    setEnabled(vTo.enabled);
    setEditLifecycle(lc);
    setErrorMessage('');
    setShowCompareDialog(false);
    setShowEditDialog(true);
    toast.success('Review changelog in Edit Version, then save.');
  };

  const downloadMigrationGuideMarkdownFile = () => {
    const vBase = versions.find((v) => v.id === compareVersion1Id);
    const vTo = versions.find((v) => v.id === compareVersion2Id);
    const proj = projects.find((p) => p.id === selectedProjectId);
    const name = `migration-guide-${sanitizeFilenameSegment(proj?.name ?? 'project')}-${sanitizeFilenameSegment(vBase?.version_id ?? 'base')}-to-${sanitizeFilenameSegment(vTo?.version_id ?? 'target')}.md`;
    const blob = new Blob([migrationGuideMarkdown], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = name;
    a.click();
    URL.revokeObjectURL(url);
    toast.success('Markdown downloaded');
  };

  const classDiffListRender = useMemo(() => {
    const hasVisibleExpandedClassDiff =
      expandedClassDiffId !== null &&
      filteredClassDiffRows.some((row) => row.stableId === expandedClassDiffId);
    const virtualize =
      !hasVisibleExpandedClassDiff && filteredClassDiffRows.length > 64;
    if (virtualize) {
      return {
        virtualize: true as const,
        rows: classListVirtual.visibleRows,
        padTop: classListVirtual.padTop,
        padBottom: classListVirtual.padBottom,
      };
    }
    return {
      virtualize: false as const,
      rows: filteredClassDiffRows,
      padTop: 0,
      padBottom: 0,
    };
  }, [expandedClassDiffId, filteredClassDiffRows, classListVirtual]);

  const displayVersions = useMemo(() => {
    if (!historyTagFilter) return versions;
    const t = versionTags.find((x) => x.id === historyTagFilter);
    if (!t) return versions;
    return versions.filter((v) => v.id === t.version_id);
  }, [versions, versionTags, historyTagFilter]);

  useEffect(() => {
    setHistoryGraphWindowSize(DEFAULT_HISTORY_WINDOW);
  }, [selectedProjectId, historyTagFilter, lifecycleFilter]);

  const handleCompareFormatChange = (newFormat: 'json' | 'yaml') => {
    setCompareFormat(newFormat);
    if (compareSpec1 && compareSpec2) {
      const content1 = newFormat === 'json' ? compareSpec1 : YAML.stringify(JSON.parse(compareSpec1));
      const content2 = newFormat === 'json' ? compareSpec2 : YAML.stringify(JSON.parse(compareSpec2));
      setDiffResult(diffLines(content1, content2));
    }
  };

  const handleLeftScroll = () => {
    if (isSyncingScroll.current || !leftPanelRef.current || !rightPanelRef.current) return;
    isSyncingScroll.current = true;
    rightPanelRef.current.scrollTop = leftPanelRef.current.scrollTop;
    requestAnimationFrame(() => { isSyncingScroll.current = false; });
  };

  const handleRightScroll = () => {
    if (isSyncingScroll.current || !leftPanelRef.current || !rightPanelRef.current) return;
    isSyncingScroll.current = true;
    leftPanelRef.current.scrollTop = rightPanelRef.current.scrollTop;
    requestAnimationFrame(() => { isSyncingScroll.current = false; });
  };

  const formatDate = (dateString: string) => {
    const d = new Date(dateString);
    const datePart = d.toLocaleDateString('en-US', { month: '2-digit', day: '2-digit', year: '2-digit' });
    const timePart = d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: true });
    return `${datePart} ${timePart}`;
  };

  const revisionLifecycleBadge = (lc: string | undefined) => {
    const v = (lc ?? 'stable').toLowerCase();
    const label =
      v === 'stable' ? 'Stable' : v === 'beta' ? 'Beta' : v === 'deprecated' ? 'Deprecated' : v === 'archived' ? 'Archived' : 'Stable';
    const variant =
      v === 'stable' ? 'success' : v === 'beta' ? 'default' : v === 'deprecated' ? 'warning' : 'secondary';
    return (
      <Badge variant={variant} title="Revision lifecycle (#739)">
        {label}
      </Badge>
    );
  };

  const canModify = (version: Version) => version.creator_id === currentUserId || !!effectiveIsAdmin;

  const handleRowAction = async (action: string, version: Version) => {
    const isPublished = !!version.published;
    const canPub = !isPublished && canModify(version);
    const canUnpub = isPublished && canModify(version);
    switch (action) {
      case 'view': await handleViewOpenApi(version); break;
      case 'relationshipGraph': await handleShowRelationshipGraph(version); break;
      case 'edit': if (!isPublished) handleEditClick(version); else setErrorMessage('Cannot edit published version'); break;
      case 'publish': if (canPub) handlePublishClick(version.id); else toast.warning('Only owner or admin can publish'); break;
      case 'unpublish': if (canUnpub) await handleUnpublish(version.id); else toast.warning('Only owner or admin can unpublish'); break;
      case 'freezeSchema': if (canModify(version)) await handleFreezeSchema(version); else toast.warning('Only owner or admin can freeze schema'); break;
      case 'delete':
        if (version.revisionLocked && !effectiveIsAdmin) {
          toast.warning('This revision is locked by policy; only a tenant admin can delete it.');
          break;
        }
        await handleDelete(version.id);
        break;
      case 'branchFrom':
        setBranchFromVersionId(version.id);
        setBranchNameInput('');
        setShowBranchDialog(true);
        break;
      case 'forkToProject':
        if (otherProjects.length === 0) {
          toast.warning('Create another project in this tenant to fork into — forks are isolated copies in a different project.');
          break;
        }
        setForkFromVersionId(version.id);
        setForkTargetProjectId(otherProjects[0]?.id ?? '');
        setForkAutoGenerate(true);
        setForkVersionId('');
        setForkBumpStrategy('patch');
        setForkDescription(`Fork from v${version.version_id}`);
        setForkChangeLog('');
        setShowForkDialog(true);
        break;
      case 'tagFrom':
        setTagFromVersionId(version.id);
        setTagNameInput('');
        setTagMessageInput('');
        setTagChannelInput('');
        setTagImmutable(false);
        setTagProtected(false);
        setShowTagDialog(true);
        break;
      case 'rollbackBranch':
        if (versionBranches.length === 0) {
          toast.warning('Create a named branch first');
          break;
        }
        setRollbackTargetVersion(version);
        setRollbackBranchName(versionBranches[0]?.name ?? '');
        setRollbackPreview(null);
        setRollbackShortMessage('');
        setRollbackSkipCompat(false);
        setShowRollbackDialog(true);
        break;
    }
  };

  const handleCreateBranchSubmit = async () => {
    const name = branchNameInput.trim();
    if (!name || !branchFromVersionId || !selectedProjectId) {
      toast.warning('Enter a branch name');
      return;
    }
    setBranchSaving(true);
    try {
      const r = await fetch(`/api/projects/${selectedProjectId}/version-branches`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, fromVersionId: branchFromVersionId }),
      });
      const d = await r.json();
      if (d.success) {
        toast.success(`Branch "${name}" created`);
        setShowBranchDialog(false);
        await loadBranches();
      } else {
        toast.error(d.error || 'Could not create branch');
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not create branch');
    } finally {
      setBranchSaving(false);
    }
  };

  const handleForkSubmit = async () => {
    if (!forkFromVersionId || !forkTargetProjectId) {
      toast.warning('Choose a target project');
      return;
    }
    const notesCheck = validateVersionNotesClient(forkDescription, forkChangeLog);
    if (!notesCheck.ok) {
      toast.error(notesCheck.error);
      return;
    }
    if (!forkAutoGenerate && !forkVersionId.trim()) {
      toast.warning('Enter a version ID or enable auto-generate');
      return;
    }
    setForkSaving(true);
    try {
      const body: Record<string, string | undefined | null> = {
        targetProjectId: forkTargetProjectId,
        sourceRevisionId: forkFromVersionId,
        shortMessage: forkDescription.trim(),
        changelog: forkChangeLog.trim() || undefined,
      };
      if (!forkAutoGenerate) {
        body.versionId = forkVersionId.trim();
      } else {
        body.bumpStrategy = forkBumpStrategy;
      }
      const r = await fetch('/api/versions/fork', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const d = await r.json();
      if (d.success) {
        toast.success(`Fork created in ${projects.find((p) => p.id === forkTargetProjectId)?.name ?? 'target project'}`);
        setShowForkDialog(false);
        setSelectedProjectId(forkTargetProjectId);
      } else {
        toast.error(typeof d.error === 'string' ? d.error : 'Could not create fork');
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not create fork');
    } finally {
      setForkSaving(false);
    }
  };

  const handleCreateTagSubmit = async () => {
    const name = tagNameInput.trim();
    if (!name || !tagFromVersionId || !selectedProjectId) {
      toast.warning('Enter a tag name');
      return;
    }
    setTagSaving(true);
    try {
      const r = await fetch(`/api/projects/${selectedProjectId}/version-tags`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name,
          versionId: tagFromVersionId,
          message: tagMessageInput.trim() || undefined,
          channel: tagChannelInput.trim() || undefined,
          immutable: tagImmutable,
          ...(effectiveIsAdmin && tagProtected ? { protected: true } : {}),
        }),
      });
      const d = await r.json();
      if (d.success) {
        toast.success(`Tag "${name}" created`);
        setShowTagDialog(false);
        await loadVersionTags();
      } else {
        toast.error(d.error || 'Could not create tag');
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not create tag');
    } finally {
      setTagSaving(false);
    }
  };

  const handleDeleteTag = async (tagId: string) => {
    if (!selectedProjectId) return;
    const ok = await confirmDialog({
      title: 'Delete tag',
      message: 'Remove this named tag? Version rows are not deleted.',
      variant: 'danger',
      confirmLabel: 'Delete',
      cancelLabel: 'Cancel',
    });
    if (!ok) return;
    try {
      const r = await fetch(`/api/projects/${selectedProjectId}/version-tags/${tagId}`, {
        method: 'DELETE',
      });
      const d = await r.json();
      if (d.success) {
        toast.success('Tag removed');
        if (historyTagFilter === tagId) setHistoryTagFilter('');
        await loadVersionTags();
      } else {
        toast.error(d.error || 'Could not delete tag');
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not delete tag');
    }
  };

  const handleDeleteBranch = async (branchId: string) => {
    if (!selectedProjectId) return;
    const ok = await confirmDialog({
      title: 'Delete branch',
      message: 'Remove this named branch? The version records are not deleted.',
      variant: 'danger',
      confirmLabel: 'Delete',
      cancelLabel: 'Cancel',
    });
    if (!ok) return;
    try {
      const r = await fetch(`/api/projects/${selectedProjectId}/version-branches/${branchId}`, {
        method: 'DELETE',
      });
      const d = await r.json();
      if (d.success) {
        toast.success('Branch removed');
        await loadBranches();
      } else {
        toast.error(d.error || 'Could not delete branch');
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not delete branch');
    }
  };

  const handleToggleBranchProtection = async (branchId: string, nextProtected: boolean) => {
    if (!selectedProjectId || !effectiveIsAdmin) return;
    try {
      const r = await fetch(`/api/projects/${selectedProjectId}/version-branches/${branchId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ protected: nextProtected }),
      });
      const d = await r.json();
      if (d.success) {
        toast.success(nextProtected ? 'Branch is now protected' : 'Branch protection removed');
        await loadBranches();
      } else {
        toast.error(d.error || 'Could not update branch protection');
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not update branch');
    }
  };

  const handleToggleTagProtection = async (tagId: string, nextProtected: boolean) => {
    if (!selectedProjectId || !effectiveIsAdmin) return;
    try {
      const r = await fetch(`/api/projects/${selectedProjectId}/version-tags/${tagId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ protected: nextProtected }),
      });
      const d = await r.json();
      if (d.success) {
        toast.success(nextProtected ? 'Tag is now protected' : 'Tag protection removed');
        await loadVersionTags();
      } else {
        toast.error(d.error || 'Could not update tag protection');
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not update tag');
    }
  };

  const handleToggleRevisionLock = async (version: Version, nextLocked: boolean) => {
    if (!selectedProjectId || !effectiveIsAdmin) return;
    try {
      const r = await fetch(
        `/api/projects/${selectedProjectId}/versions/${version.id}/revision-lock`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ revisionLocked: nextLocked }),
        }
      );
      const d = await r.json();
      if (d.success) {
        toast.success(nextLocked ? 'Revision locked against deletion' : 'Revision lock removed');
        await loadVersions();
      } else {
        toast.error(d.error || 'Could not update revision lock');
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not update lock');
    }
  };

  const runMergePreview = async () => {
    if (!selectedProjectId || !mergeSourceBranch.trim() || !mergeTargetBranch.trim()) {
      toast.warning('Select source and target branch names');
      return;
    }
    if (mergeSourceBranch.trim() === mergeTargetBranch.trim()) {
      toast.warning('Source and target must be different branches');
      return;
    }
    setMergePreviewLoading(true);
    setMergePreviewData(null);
    setMergeCompat(null);
    try {
      const r = await fetch(`/api/projects/${selectedProjectId}/version-branches/merge-preview`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          sourceBranchName: mergeSourceBranch.trim(),
          targetBranchName: mergeTargetBranch.trim(),
        }),
      });
      const d = await r.json();
      if (d.success) {
        setMergePreviewData({
          classification: d.classification,
          sourceTipVersionId: d.sourceTipVersionId,
          targetTipVersionId: d.targetTipVersionId,
          mergeBaseVersionId: d.mergeBaseVersionId ?? null,
        });
        if (!d.classification?.canAutoMerge) {
          toast.info('Merge preview: conflicts detected — apply is blocked until resolved.');
        }
        const targetTip = typeof d.targetTipVersionId === 'string' ? d.targetTipVersionId : '';
        const sourceTip = typeof d.sourceTipVersionId === 'string' ? d.sourceTipVersionId : '';
        if (targetTip && sourceTip) {
          setMergeCompatLoading(true);
          try {
            const cr = await fetch(`/api/projects/${selectedProjectId}/compatibility`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                baseRevisionId: targetTip,
                headRevisionId: sourceTip,
              }),
            });
            const cd = await cr.json();
            if (cr.ok && cd.success === true && typeof cd.overall === 'string') {
              setMergeCompat({
                overall: cd.overall,
                findings: Array.isArray(cd.findings) ? cd.findings : [],
                breakingChangeDocumentationIssueUrl: cd.breakingChangeDocumentationIssueUrl ?? null,
                tenantCompatGateActive: Boolean(cd.tenantCompatGateActive),
                mergeBlockedByCompatGate: Boolean(cd.mergeBlockedByCompatGate),
              });
            } else {
              setMergeCompat(null);
            }
          } catch {
            setMergeCompat(null);
          } finally {
            setMergeCompatLoading(false);
          }
        }
      } else {
        toast.error(d.error || 'Preview failed');
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Preview failed');
    } finally {
      setMergePreviewLoading(false);
    }
  };

  const runMergeApply = async () => {
    if (!selectedProjectId || !mergeSourceBranch.trim() || !mergeTargetBranch.trim()) {
      toast.warning('Select source and target branch names');
      return;
    }
    if (mergeSourceBranch.trim() === mergeTargetBranch.trim()) {
      toast.warning('Source and target must be different branches');
      return;
    }
    const target = versionBranches.find((b) => b.name === mergeTargetBranch.trim());
    if (!target) {
      toast.error('Target branch not found in list — refresh branches');
      return;
    }
    setMergeApplyLoading(true);
    try {
      const r = await fetch(`/api/projects/${selectedProjectId}/version-branches/merge`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          sourceBranchName: mergeSourceBranch.trim(),
          targetBranchName: mergeTargetBranch.trim(),
          baseRevisionId: target.tip_version_id,
        }),
      });
      const d = await r.json();
      if (d.success) {
        toast.success(`Merged into ${mergeTargetBranch.trim()} — new version ${d.version?.version_id ?? ''}`);
        setShowMergeDialog(false);
        setMergePreviewData(null);
        await loadVersions();
        await loadBranches();
      } else {
        const err = typeof d.detail === 'object' && d.detail !== null ? d.detail : d;
        const code = typeof err === 'object' && err && 'code' in err ? (err as { code?: string }).code : undefined;
        const conflictPaths =
          typeof err === 'object' && err && 'conflictPaths' in err
            ? (err as { conflictPaths?: string[] }).conflictPaths
            : undefined;
        if (r.status === 409 && code === 'MERGE_CONFLICT') {
          toast.error('Merge blocked: overlapping changes. Resolve conflicts using a future merge flow.');
          setMergePreviewData((prev) => ({
            ...(prev ?? {}),
            classification: {
              canAutoMerge: false,
              conflictPaths: conflictPaths ?? [],
              addedSchemaNames: prev?.classification?.addedSchemaNames ?? [],
            },
          }));
        } else {
          const msg =
            typeof err === 'object' && err && 'message' in err
              ? String((err as { message?: string }).message)
              : typeof d.error === 'string'
                ? d.error
                : 'Merge failed';
          toast.error(msg);
        }
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Merge failed');
    } finally {
      setMergeApplyLoading(false);
    }
  };

  const runRollbackPreview = async () => {
    if (!selectedProjectId || !rollbackTargetVersion || !rollbackBranchName.trim()) {
      toast.warning('Choose a branch');
      return;
    }
    setRollbackPreviewLoading(true);
    setRollbackPreview(null);
    try {
      const r = await fetch(`/api/projects/${selectedProjectId}/version-branches/rollback-preview`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          branchName: rollbackBranchName.trim(),
          targetRevisionId: rollbackTargetVersion.id,
        }),
      });
      const d = await r.json();
      if (d.success) {
        setRollbackPreview({
          branchTipRevisionId: typeof d.branchTipRevisionId === 'string' ? d.branchTipRevisionId : undefined,
          compatOverall: typeof d.compatOverall === 'string' ? d.compatOverall : undefined,
          findings: Array.isArray(d.findings) ? d.findings : [],
          deprecationWarnings: Array.isArray(d.deprecationWarnings) ? d.deprecationWarnings : [],
          rollbackBlockedByCompatGate: Boolean(d.rollbackBlockedByCompatGate),
          breakingChangeDocumentationIssueUrl:
            typeof d.breakingChangeDocumentationIssueUrl === 'string' ? d.breakingChangeDocumentationIssueUrl : null,
        });
        setRollbackSkipCompat(false);
      } else {
        const msg = (() => {
          if (typeof d.detail === 'string') return d.detail;
          const detail = d.detail as Record<string, unknown> | null | undefined;
          if (detail && typeof detail.message === 'string') return detail.message;
          if (typeof d.error === 'string') return d.error;
          return 'Preview failed';
        })();
        toast.error(msg);
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Preview failed');
    } finally {
      setRollbackPreviewLoading(false);
    }
  };

  const runRollbackApply = async () => {
    if (!selectedProjectId || !rollbackTargetVersion || !rollbackBranchName.trim() || !rollbackPreview?.branchTipRevisionId) {
      toast.warning('Run preview first');
      return;
    }
    const overall = rollbackPreview.compatOverall ?? 'unknown';
    if (rollbackPreview.rollbackBlockedByCompatGate) {
      toast.error('Project policy blocks rollback when compatibility is not safe');
      return;
    }
    if (overall !== 'safe' && !rollbackSkipCompat) {
      toast.warning('Acknowledge compatibility risk using the checkbox below');
      return;
    }
    setRollbackApplyLoading(true);
    try {
      const r = await fetch(`/api/projects/${selectedProjectId}/version-branches/rollback`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          branchName: rollbackBranchName.trim(),
          targetRevisionId: rollbackTargetVersion.id,
          baseRevisionId: rollbackPreview.branchTipRevisionId,
          skipCompatWarning: overall !== 'safe',
          ...(rollbackShortMessage.trim() ? { shortMessage: rollbackShortMessage.trim() } : {}),
        }),
      });
      const d = await r.json();
      if (d.success) {
        toast.success(`Rollback complete — new revision v${d.version?.version_id ?? ''}`);
        setShowRollbackDialog(false);
        setRollbackPreview(null);
        setRollbackTargetVersion(null);
        await loadVersions();
        await loadBranches();
      } else {
        const err = d.detail;
        const msg =
          typeof err === 'object' && err !== null && 'message' in err
            ? String((err as { message?: string }).message)
            : typeof d.error === 'string'
              ? d.error
              : 'Rollback failed';
        toast.error(msg);
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Rollback failed');
    } finally {
      setRollbackApplyLoading(false);
    }
  };

  if (!session) {
    return (
      <div className="p-6">
        <LoadingState minHeightClassName="min-h-[220px]" message="Loading versions..." />
      </div>
    );
  }

  if (!currentTenantId) {
    return (
      <div className="p-6 max-w-5xl mx-auto">
        <div className="relative">
          <div className="absolute -top-10 -left-10 w-40 h-40 bg-gradient-to-br from-amber-100 to-yellow-100 dark:from-amber-900/20 dark:to-yellow-900/20 rounded-full blur-3xl opacity-60" />
          <div className="relative bg-gradient-to-r from-amber-50 to-yellow-50 dark:from-amber-900/20 dark:to-yellow-900/20 border border-amber-200 dark:border-amber-700/50 rounded-2xl p-8">
            <div className="flex items-start gap-4">
              <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-amber-500 to-yellow-500 flex items-center justify-center shadow-lg shadow-amber-500/25 flex-shrink-0">
                <Lock className="h-6 w-6 text-white" />
              </div>
              <div>
                <h2 className="text-xl font-bold text-amber-900 dark:text-amber-100 mb-2">No Tenant Selected</h2>
                <p className="text-amber-800 dark:text-amber-200 mb-4">Please select a tenant before managing versions.</p>
                <Button asChild><a href="/ade/dashboard/tenants">Go to Tenants</a></Button>
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  if (projects.length === 0) {
    return (
      <div className="p-6 max-w-5xl mx-auto">
        <EmptyState
          icon={<Package className="h-10 w-10" />}
          title="No Projects Available"
          description="Please create a project before managing versions."
          iconContainerClassName="from-indigo-500 to-purple-600 shadow-indigo-500/30"
          action={(
            <Button asChild className="bg-gradient-to-r from-indigo-500 to-purple-600 hover:from-indigo-600 hover:to-purple-700">
              <a href="/ade/dashboard/projects">Go to Projects</a>
            </Button>
          )}
        />
      </div>
    );
  }

  return (
    <>
      <header className="border-b border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800">
        <div className="px-6 py-4">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
                <Package className="w-6 h-6 text-indigo-600 dark:text-indigo-400" />
                Versions
              </h2>
              <p className="text-gray-600 dark:text-gray-400 text-sm mt-1">
                Manage versions with semantic versioning
              </p>
              <Link
                href="/ade/dashboard/versions/sunset-timeline"
                className="inline-flex items-center gap-1.5 text-sm text-amber-700 dark:text-amber-300 hover:underline mt-2"
              >
                <Sun className="h-4 w-4" />
                Sunset timeline (EOL schedule)
              </Link>
            </div>
            <div className="flex items-center gap-3">
              <Select value={selectedProjectId} onValueChange={setSelectedProjectId}>
                <SelectTrigger className="w-56"><SelectValue placeholder="Select Project" /></SelectTrigger>
                <SelectContent>{projects.map((p) => <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>)}</SelectContent>
              </Select>
              <Button variant="secondary" onClick={handleCompareDialogOpen} disabled={!selectedProjectId || versions.length < 2}>
                <Copy className="h-4 w-4 mr-2" />
                Compare
              </Button>
              <Button
                variant="secondary"
                onClick={() => {
                  setMergeSourceBranch('');
                  setMergeTargetBranch('');
                  setMergePreviewData(null);
                  setMergeCompat(null);
                  setShowMergeDialog(true);
                }}
                disabled={!selectedProjectId || versionBranches.length < 2}
                title={versionBranches.length < 2 ? 'Create at least two named branches to merge' : undefined}
              >
                <GitMerge className="h-4 w-4 mr-2" />
                Merge branches
              </Button>
              <Button onClick={handleCreateClick} disabled={!selectedProjectId} title="Create a new schema revision (commit)">
                <Plus className="h-4 w-4 mr-2" />
                Commit
              </Button>
            </div>
          </div>
        </div>
      </header>

      <main className="flex-1 overflow-y-auto p-6">
        <div className="max-w-7xl mx-auto space-y-6">
      {selectedProjectId && versionTags.length > 0 && (
        <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-sm border border-gray-100 dark:border-gray-700 p-4">
          <div className="flex items-center gap-2 mb-3">
            <Tag className="h-5 w-5 text-amber-600 dark:text-amber-400" />
            <h3 className="text-sm font-semibold text-gray-900 dark:text-white">Version tags</h3>
          </div>
          <div className="flex flex-wrap gap-2">
            {versionTags.map((tg) => (
              <div
                key={tg.id}
                className="inline-flex items-center gap-2 rounded-lg border border-gray-200 dark:border-gray-600 px-3 py-1.5 text-sm bg-amber-50/80 dark:bg-amber-950/20"
              >
                <span className="font-mono font-medium text-gray-900 dark:text-white">{tg.name}</span>
                <span className="text-gray-500 dark:text-gray-400">→ v{tg.target_version_string ?? '?'}</span>
                {tg.channel && (
                  <span className="text-xs px-1.5 py-0.5 rounded bg-gray-200 dark:bg-gray-700 text-gray-700 dark:text-gray-200">
                    {tg.channel}
                  </span>
                )}
                {tg.immutable && (
                  <span title="Immutable" className="text-xs text-amber-700 dark:text-amber-300">
                    locked
                  </span>
                )}
                {tg.protected && (
                  <span
                    title="Protected: only tenant admins can move or delete"
                    className="inline-flex items-center gap-0.5 text-xs text-indigo-700 dark:text-indigo-300"
                  >
                    <Shield className="h-3 w-3" />
                    protected
                  </span>
                )}
                {effectiveIsAdmin && !tg.immutable && (
                  <button
                    type="button"
                    onClick={() => handleToggleTagProtection(tg.id, !tg.protected)}
                    className="text-indigo-600 dark:text-indigo-400 hover:underline text-xs"
                  >
                    {tg.protected ? 'Unprotect' : 'Protect'}
                  </button>
                )}
                {!tg.immutable && (effectiveIsAdmin || (!tg.protected && tg.created_by === currentUserId)) && (
                  <button
                    type="button"
                    onClick={() => handleDeleteTag(tg.id)}
                    className="text-red-600 dark:text-red-400 hover:underline text-xs"
                  >
                    Remove
                  </button>
                )}
              </div>
            ))}
          </div>
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-2">
            Tags are stable names for a schema revision (like Git tags). Use &quot;Tag this revision&quot; on a version row to add one.
            Immutable tags cannot be moved or deleted; <span className="font-medium">protected</span> tags (tenant admin) add policy so only admins can move or delete.
            Pair with deprecation and sunset planning as last-known-good pointers.
          </p>
        </div>
      )}

      {selectedProjectId && versionBranches.length > 0 && (
        <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-sm border border-gray-100 dark:border-gray-700 p-4">
          <div className="flex items-center gap-2 mb-3">
            <GitBranch className="h-5 w-5 text-indigo-600 dark:text-indigo-400" />
            <h3 className="text-sm font-semibold text-gray-900 dark:text-white">Named branches</h3>
          </div>
          <div className="flex flex-wrap gap-2">
            {versionBranches.map((b) => (
              <div
                key={b.id}
                className="inline-flex items-center gap-2 rounded-lg border border-gray-200 dark:border-gray-600 px-3 py-1.5 text-sm bg-gray-50 dark:bg-gray-900/50"
              >
                <span className="font-mono font-medium text-gray-900 dark:text-white">{b.name}</span>
                <span className="text-gray-500 dark:text-gray-400">→ v{b.tip_version_string ?? '?'}</span>
                {b.protected && (
                  <span
                    title="Protected branch: only tenant admins can delete"
                    className="inline-flex items-center gap-0.5 text-xs text-indigo-700 dark:text-indigo-300"
                  >
                    <Shield className="h-3 w-3" />
                    protected
                  </span>
                )}
                {effectiveIsAdmin && (
                  <button
                    type="button"
                    onClick={() => handleToggleBranchProtection(b.id, !b.protected)}
                    className="text-indigo-600 dark:text-indigo-400 hover:underline text-xs"
                  >
                    {b.protected ? 'Unprotect' : 'Protect'}
                  </button>
                )}
                {(effectiveIsAdmin || (!b.protected && b.created_by === currentUserId)) && (
                  <button
                    type="button"
                    onClick={() => handleDeleteBranch(b.id)}
                    className="text-red-600 dark:text-red-400 hover:underline text-xs"
                  >
                    Remove
                  </button>
                )}
              </div>
            ))}
          </div>
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-2">
            <span className="font-medium text-gray-700 dark:text-gray-300">Branch vs fork:</span> a named branch stays in this project (same version line).
            A <span className="font-medium">fork</span> copies a revision into a <em>different</em> project for isolated experiments; lineage is stored for audit and merge-back.
          </p>
        </div>
      )}

      {/* Versions List */}
      {versions.length === 0 ? (
        <EmptyState
          icon={<Package className="h-10 w-10" />}
          title="No Versions Yet"
          description="Get started by creating your first version"
          iconContainerClassName="from-emerald-500 to-teal-600 shadow-emerald-500/30"
        />
      ) : displayVersions.length === 0 ? (
        <EmptyState
          icon={<Tag className="h-10 w-10" />}
          title="No version matches this tag"
          description="Clear the tag filter above the table or choose a different tag."
          iconContainerClassName="from-amber-500 to-orange-600 shadow-amber-500/30"
        />
      ) : (
        <>
          <div className="mb-6">
            <VersionHistoryGraphPanel
              key={versionBranches.map((b) => b.id).sort().join('|') || 'graph-branches'}
              versions={displayVersions.map((v) => ({
                id: v.id,
                version_id: v.version_id,
                parent_version_id: v.parent_version_id ?? null,
                merge_parent_version_id: v.merge_parent_version_id ?? null,
                created_at: v.created_at,
                shortMessage: v.shortMessage,
              }))}
              branches={versionBranches.map((b) => ({
                id: b.id,
                name: b.name,
                tip_version_id: b.tip_version_id,
              }))}
              windowSize={historyGraphWindowSize}
              onWindowSizeIncrease={setHistoryGraphWindowSize}
              onCompareToPrimaryParent={handleHistoryGraphCompareToParent}
              onViewSpec={handleHistoryGraphViewSpec}
            />
          </div>
        <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-sm border border-gray-100 dark:border-gray-700 overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-100 dark:border-gray-700 flex flex-wrap items-center gap-3 bg-gray-50/80 dark:bg-gray-900/40">
            <span className="text-sm text-gray-600 dark:text-gray-400">Lifecycle filter</span>
            <Select
              value={lifecycleFilter || '__all__'}
              onValueChange={(v) => setLifecycleFilter(v === '__all__' ? '' : v)}
            >
              <SelectTrigger className="w-48">
                <SelectValue placeholder="All lifecycles" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="__all__">All lifecycles</SelectItem>
                <SelectItem value="stable">Stable</SelectItem>
                <SelectItem value="beta">Beta</SelectItem>
                <SelectItem value="deprecated">Deprecated</SelectItem>
                <SelectItem value="archived">Archived</SelectItem>
              </SelectContent>
            </Select>
          </div>
          {versionTags.length > 0 && (
            <div className="px-4 py-3 border-b border-gray-100 dark:border-gray-700 flex flex-wrap items-center gap-3 bg-gray-50/80 dark:bg-gray-900/40">
              <span className="text-sm text-gray-600 dark:text-gray-400">History filter</span>
              <Select
                value={historyTagFilter || '__all__'}
                onValueChange={(v) => setHistoryTagFilter(v === '__all__' ? '' : v)}
              >
                <SelectTrigger className="w-56">
                  <SelectValue placeholder="All revisions" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__all__">All revisions</SelectItem>
                  {versionTags.map((tg) => (
                    <SelectItem key={tg.id} value={tg.id}>
                      Tag {tg.name} → v{tg.target_version_string ?? '?'}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
          <table className="min-w-full divide-y divide-gray-100 dark:divide-gray-700">
            <thead className="bg-gradient-to-r from-gray-50 to-slate-50 dark:from-gray-900 dark:to-gray-800">
              <tr>
                <th className="px-6 py-4 text-left text-xs font-bold text-gray-500 dark:text-gray-400 uppercase tracking-wider">Version</th>
                <th className="px-6 py-4 text-left text-xs font-bold text-gray-500 dark:text-gray-400 uppercase tracking-wider">Revision / changelog</th>
                <th className="px-6 py-4 text-left text-xs font-bold text-gray-500 dark:text-gray-400 uppercase tracking-wider">Status</th>
                <th className="px-6 py-4 text-left text-xs font-bold text-gray-500 dark:text-gray-400 uppercase tracking-wider">Created By</th>
                <th className="px-6 py-4 text-left text-xs font-bold text-gray-500 dark:text-gray-400 uppercase tracking-wider">Created</th>
                <th className="px-6 py-4 text-right text-xs font-bold text-gray-500 dark:text-gray-400 uppercase tracking-wider">Actions</th>
              </tr>
            </thead>
            <tbody className="bg-white dark:bg-gray-800 divide-y divide-gray-100 dark:divide-gray-700">
              {displayVersions.map((version) => (
                <tr key={version.id} className="hover:bg-emerald-50/50 dark:hover:bg-emerald-900/10 transition-all duration-200">
                  <td className="px-6 py-4 whitespace-nowrap">
                    <div className="flex items-center gap-2 flex-wrap">
                      <div className="text-sm font-bold text-gray-900 dark:text-white font-mono">v{version.version_id}</div>
                      {revisionLifecycleBadge(version.lifecycle)}
                      {version.published && <div title="Published" className="p-1 bg-blue-100 dark:bg-blue-900/30 rounded"><Lock className="h-3.5 w-3.5 text-blue-600 dark:text-blue-400" /></div>}
                      {version.revisionLocked && (
                        <div title="Revision locked: non-admins cannot delete" className="p-1 bg-indigo-100 dark:bg-indigo-900/30 rounded">
                          <Shield className="h-3.5 w-3.5 text-indigo-600 dark:text-indigo-400" />
                        </div>
                      )}
                      {(tagsByVersionId.get(version.id) ?? []).map((t) => (
                        <span
                          key={t.id}
                          title={t.message || t.name}
                          className="text-xs font-mono px-1.5 py-0.5 rounded bg-amber-100 dark:bg-amber-900/40 text-amber-900 dark:text-amber-100 border border-amber-200 dark:border-amber-800"
                        >
                          {t.name}
                        </span>
                      ))}
                    </div>
                    {version.forkedFromRevisionId && (
                      <div className="mt-2 rounded-md border border-violet-200 dark:border-violet-800 bg-violet-50/80 dark:bg-violet-950/30 px-2 py-1.5 text-xs text-violet-900 dark:text-violet-100">
                        <span className="font-medium">Fork</span>
                        {' · '}
                        from v{version.forkSourceVersionLabel ?? '?'}
                        {version.forkSourceProjectName != null && version.forkSourceProjectName !== ''
                          ? ` (${version.forkSourceProjectName})`
                          : ''}
                        {version.upstreamProjectName != null &&
                          version.upstreamProjectName !== '' &&
                          version.upstreamProjectName !== version.forkSourceProjectName && (
                            <span className="text-violet-700 dark:text-violet-300"> · Upstream project: {version.upstreamProjectName}</span>
                          )}
                      </div>
                    )}
                  </td>
                  <td className="px-6 py-4">
                    <div className="text-sm text-gray-900 dark:text-white max-w-xs truncate">{version.shortMessage || '—'}</div>
                    {version.changelog && <div className="text-xs text-gray-500 dark:text-gray-400 mt-1 max-w-xs truncate">{version.changelog}</div>}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    <div className="flex gap-2">
                      {version.published ? (
                        <Badge variant="success" className="flex items-center gap-1"><CheckCircle className="h-3 w-3" />Published</Badge>
                      ) : (
                        <Badge variant="secondary" className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-gray-400"></span>Draft</Badge>
                      )}
                      {!version.enabled && <Badge variant="error">Disabled</Badge>}
                    </div>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    <div className="text-sm font-medium text-gray-900 dark:text-white">{version.creator_name}</div>
                    <div className="text-xs text-gray-500 dark:text-gray-400">{version.creator_email}</div>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">
                    {formatDate(version.created_at)}
                    {version.published_at && <div className="text-xs text-emerald-600 dark:text-emerald-400 mt-0.5">Published: {formatDate(version.published_at)}</div>}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-right">
                    <div className="relative">
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
                          setDropdownPosition({
                            top: rect.bottom + 4,
                            right: window.innerWidth - rect.right
                          });
                          setOpenVersionDropdown(openVersionDropdown === version.id ? null : version.id);
                        }}
                        className="p-2 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg transition-colors text-gray-400 hover:text-gray-600 dark:hover:text-white"
                        title="Actions"
                      >
                        <MoreVertical className="h-4 w-4" />
                      </button>

                      {openVersionDropdown === version.id && dropdownPosition && (
                        <>
                          <div
                            className="fixed inset-0 z-10"
                            onClick={(e) => {
                              e.stopPropagation();
                              setOpenVersionDropdown(null);
                            }}
                          />
                          <div
                            className="fixed w-56 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-lg shadow-lg z-20"
                            style={{
                              top: `${dropdownPosition.top}px`,
                              right: `${dropdownPosition.right}px`
                            }}>
                            <div className="py-1">
                              <button
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setOpenVersionDropdown(null);
                                  handleRowAction('view', version);
                                }}
                                className="w-full px-4 py-2 text-left text-sm hover:bg-gray-100 dark:hover:bg-gray-800 flex items-center gap-3 text-gray-700 dark:text-gray-300 hover:text-gray-900 dark:hover:text-white transition-colors"
                              >
                                <Eye className="w-4 h-4 text-purple-500" />
                                View Spec
                              </button>
                              <button
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setOpenVersionDropdown(null);
                                  handleRowAction('relationshipGraph', version);
                                }}
                                className="w-full px-4 py-2 text-left text-sm hover:bg-gray-100 dark:hover:bg-gray-800 flex items-center gap-3 text-gray-700 dark:text-gray-300 hover:text-gray-900 dark:hover:text-white transition-colors"
                              >
                                <Network className="w-4 h-4 text-teal-500" />
                                Relationship graph
                              </button>
                              <button
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setOpenVersionDropdown(null);
                                  handleRowAction('branchFrom', version);
                                }}
                                className="w-full px-4 py-2 text-left text-sm hover:bg-gray-100 dark:hover:bg-gray-800 flex items-center gap-3 text-gray-700 dark:text-gray-300 hover:text-gray-900 dark:hover:text-white transition-colors"
                              >
                                <GitBranch className="w-4 h-4 text-indigo-500" />
                                Branch from here
                              </button>
                              {versionBranches.length > 0 && (
                                <button
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    setOpenVersionDropdown(null);
                                    handleRowAction('rollbackBranch', version);
                                  }}
                                  className="w-full px-4 py-2 text-left text-sm hover:bg-gray-100 dark:hover:bg-gray-800 flex items-center gap-3 text-gray-700 dark:text-gray-300 hover:text-gray-900 dark:hover:text-white transition-colors"
                                >
                                  <Undo2 className="w-4 h-4 text-orange-600 dark:text-orange-400" />
                                  Rollback branch to this revision…
                                </button>
                              )}
                              <button
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setOpenVersionDropdown(null);
                                  handleRowAction('forkToProject', version);
                                }}
                                className="w-full px-4 py-2 text-left text-sm hover:bg-gray-100 dark:hover:bg-gray-800 flex items-center gap-3 text-gray-700 dark:text-gray-300 hover:text-gray-900 dark:hover:text-white transition-colors"
                              >
                                <GitFork className="w-4 h-4 text-violet-500" />
                                Fork to another project…
                              </button>
                              <button
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setOpenVersionDropdown(null);
                                  handleRowAction('tagFrom', version);
                                }}
                                className="w-full px-4 py-2 text-left text-sm hover:bg-gray-100 dark:hover:bg-gray-800 flex items-center gap-3 text-gray-700 dark:text-gray-300 hover:text-gray-900 dark:hover:text-white transition-colors"
                              >
                                <Tag className="w-4 h-4 text-amber-600" />
                                Tag this revision
                              </button>
                              <button
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setOpenVersionDropdown(null);
                                  handleRowAction('edit', version);
                                }}
                                disabled={!!version.published}
                                className="w-full px-4 py-2 text-left text-sm hover:bg-gray-100 dark:hover:bg-gray-800 flex items-center gap-3 text-gray-700 dark:text-gray-300 hover:text-gray-900 dark:hover:text-white transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                              >
                                <Edit2 className="w-4 h-4 text-blue-500" />
                                Edit
                              </button>
                              {!version.published ? (
                                <button
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    setOpenVersionDropdown(null);
                                    handleRowAction('publish', version);
                                  }}
                                  className="w-full px-4 py-2 text-left text-sm hover:bg-gray-100 dark:hover:bg-gray-800 flex items-center gap-3 text-gray-700 dark:text-gray-300 hover:text-gray-900 dark:hover:text-white transition-colors"
                                >
                                  <Lock className="w-4 h-4 text-green-500" />
                                  Publish
                                </button>
                              ) : (
                                <button
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    setOpenVersionDropdown(null);
                                    handleRowAction('unpublish', version);
                                  }}
                                  className="w-full px-4 py-2 text-left text-sm hover:bg-gray-100 dark:hover:bg-gray-800 flex items-center gap-3 text-gray-700 dark:text-gray-300 hover:text-gray-900 dark:hover:text-white transition-colors"
                                >
                                  <Unlock className="w-4 h-4 text-orange-500" />
                                  Unpublish
                                </button>
                              )}
                              {!hasClassSchemaMap[version.id] && (version.creator_id === currentUserId || effectiveIsAdmin) && (
                                <button
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    setOpenVersionDropdown(null);
                                    handleRowAction('freezeSchema', version);
                                  }}
                                  disabled={freezingSchemaVersionId === version.id}
                                  className="w-full px-4 py-2 text-left text-sm hover:bg-gray-100 dark:hover:bg-gray-800 flex items-center gap-3 text-gray-700 dark:text-gray-300 hover:text-gray-900 dark:hover:text-white transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                                  title="Capture class schemas for this version so it can be used in the Database section (only when no schema is frozen yet)"
                                >
                                  <Snowflake className="w-4 h-4 text-cyan-500" />
                                  {freezingSchemaVersionId === version.id ? 'Freezing...' : 'Freeze schema'}
                                </button>
                              )}
                              {effectiveIsAdmin && (
                                <button
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    setOpenVersionDropdown(null);
                                    handleToggleRevisionLock(version, !version.revisionLocked);
                                  }}
                                  className="w-full px-4 py-2 text-left text-sm hover:bg-gray-100 dark:hover:bg-gray-800 flex items-center gap-3 text-gray-700 dark:text-gray-300 hover:text-gray-900 dark:hover:text-white transition-colors"
                                >
                                  <Shield className="w-4 h-4 text-indigo-500" />
                                  {version.revisionLocked ? 'Unlock revision (allow delete)' : 'Lock revision (delete policy)'}
                                </button>
                              )}
                              <div className="border-t border-gray-200 dark:border-gray-700 my-1" />
                              <button
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setOpenVersionDropdown(null);
                                  handleRowAction('delete', version);
                                }}
                                disabled={!!version.revisionLocked && !effectiveIsAdmin}
                                className="w-full px-4 py-2 text-left text-sm hover:bg-red-50 dark:hover:bg-red-900/20 flex items-center gap-3 text-red-600 dark:text-red-400 hover:text-red-700 dark:hover:text-red-300 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                                title={version.revisionLocked && !effectiveIsAdmin ? 'Revision is locked; only a tenant admin can delete' : undefined}
                              >
                                <Trash2 className="w-4 h-4" />
                                Delete
                              </button>
                            </div>
                          </div>
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        </>
      )}
        </div>
      </main>

      {/* Commit new revision (Radix dialog + validation #2564) */}
      <Dialog open={showCreateDialog} onOpenChange={(open) => !isLoading && setShowCreateDialog(open)}>
        <DialogContent className="max-w-xl" aria-describedby="commit-dialog-desc">
          <DialogHeader>
            <DialogTitle>Commit</DialogTitle>
            <DialogDescription id="commit-dialog-desc">
              Create a new schema revision for this project. Message is required; add an external reference when linking to a ticket or issue.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            {errorMessage && <Alert variant="error">{errorMessage}</Alert>}
            {branchListError && (
              <Alert variant="warning" role="status">
                {branchListError} Branch names may be missing; you can still pick a revision below if your role allows.
              </Alert>
            )}
            <div className="space-y-2">
              {versionBranches.length > 1 ? (
                <>
                  <Label>Base copy on branch tip</Label>
                  <p id="create-copy-branch-hint" className="text-xs text-gray-500 dark:text-gray-400">
                    Multiple branches are defined for this project. Choose which branch tip to copy schema from—like picking which line to extend in git.
                  </p>
                  <Select
                    value={copySourceBranchKey}
                    onValueChange={(val) => {
                      setCopySourceBranchKey(val);
                      if (val === 'blank') setSourceVersionId('');
                      else if (val.startsWith('branch:')) {
                        const bid = val.slice(7);
                        const br = versionBranches.find((b) => b.id === bid);
                        setSourceVersionId(br?.tip_version_id ?? '');
                      }
                    }}
                    disabled={branchListLoading}
                  >
                    <SelectTrigger aria-describedby="create-copy-branch-hint">
                      <SelectValue placeholder={branchListLoading ? 'Loading branches…' : 'Choose branch tip or blank'} />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="blank">Create blank version</SelectItem>
                      {versionBranches.map((b) => (
                        <SelectItem key={b.id} value={`branch:${b.id}`}>
                          {b.name} — tip v{b.tip_version_string ?? '?'}
                          {b.protected ? ' (protected)' : ''}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </>
              ) : (
                <>
                  <Label>Copy from version</Label>
                  <Select
                    value={sourceVersionId || '__blank__'}
                    onValueChange={(val) => {
                      setSourceVersionId(val === '__blank__' ? '' : val);
                    }}
                  >
                    <SelectTrigger><SelectValue placeholder={versions.length === 0 ? 'No versions available' : 'Create blank version'} /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="__blank__">Create blank version</SelectItem>
                      {versions.map((v) => (
                        <SelectItem key={v.id} value={v.id}>
                          {v.published ? '🔒 ' : ''}v{v.version_id} - {v.shortMessage || 'No description'}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </>
              )}
            </div>
            {sourceVersionId && (
              <>
                <VersionLineageSnippet
                  sourceVersionId={sourceVersionId}
                  versions={versions.map((v) => ({
                    id: v.id,
                    version_id: v.version_id,
                    parent_version_id: v.parent_version_id ?? null,
                    merge_parent_version_id: v.merge_parent_version_id ?? null,
                  }))}
                  versionBranches={versionBranches}
                  explicitBranchName={
                    versionBranches.length > 1 && copySourceBranchKey.startsWith('branch:')
                      ? versionBranches.find((b) => b.id === copySourceBranchKey.slice(7))?.name ?? null
                      : versionBranches.length === 1 && versionBranches[0].tip_version_id === sourceVersionId
                        ? versionBranches[0].name
                        : null
                  }
                  isLoading={branchListLoading}
                  permissionDenied={branchPermissionDenied}
                />
                <Alert variant="info">Classes and properties will be copied from the selected revision.</Alert>
              </>
            )}
            <div className="space-y-2">
              <Label>Version Strategy</Label>
              <Select value={autoGenerate ? 'auto' : 'manual'} onValueChange={(v) => { const isAuto = v === 'auto'; setAutoGenerate(isAuto); if (isAuto) setNextAutoVersion(calculateNextVersion(bumpStrategy)); }}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="auto">Auto-generate version</SelectItem>
                  <SelectItem value="manual">Manual entry</SelectItem>
                </SelectContent>
              </Select>
            </div>
            {autoGenerate ? (
              <>
                <div className="space-y-2">
                  <Label>Bump Strategy</Label>
                  <Select value={bumpStrategy} onValueChange={(v) => { const s = v as 'patch' | 'minor'; setBumpStrategy(s); setNextAutoVersion(calculateNextVersion(s)); }}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="patch">Patch - {calculateNextVersion('patch')}</SelectItem>
                      <SelectItem value="minor">Minor - {calculateNextVersion('minor')}</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <Alert variant="info">Version <strong>{nextAutoVersion}</strong> will be created</Alert>
              </>
            ) : (
              <div className="space-y-2">
                <Label>Version ID</Label>
                <Input value={versionId} onChange={(e) => setVersionId(e.target.value)} placeholder="e.g., 1.0.0" disabled={isLoading} />
              </div>
            )}
            <div className="space-y-2">
              <Label htmlFor="commit-message">Message *</Label>
              <Textarea
                id="commit-message"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                disabled={isLoading}
                rows={4}
                placeholder="Describe this revision (required)"
                aria-invalid={description.length > 0 && !createCommitMessageCheck.ok}
                className="min-h-[6rem]"
              />
              {!createCommitMessageCheck.ok && description.length > 0 && (
                <p className="text-xs text-red-600 dark:text-red-400" role="alert">
                  {createCommitMessageCheck.error}
                </p>
              )}
            </div>
            <div className="space-y-2">
              <Label htmlFor="commit-external-ref">External reference (optional)</Label>
              <Input
                id="commit-external-ref"
                value={commitExternalRef}
                onChange={(e) => setCommitExternalRef(e.target.value)}
                disabled={isLoading}
                placeholder="e.g. LINEAR-42, JIRA-123"
                aria-invalid={commitExternalRefTrim.length > COMMIT_EXTERNAL_REF_MAX_CHARS}
              />
              {commitExternalRefTrim.length > COMMIT_EXTERNAL_REF_MAX_CHARS && (
                <p className="text-xs text-red-600 dark:text-red-400" role="alert">
                  External reference must be at most {COMMIT_EXTERNAL_REF_MAX_CHARS} characters
                </p>
              )}
            </div>
            <div className="space-y-2">
              <Label>Changelog (markdown, optional)</Label>
              <Textarea value={changeLog} onChange={(e) => setChangeLog(e.target.value)} rows={3} disabled={isLoading} placeholder="Release notes, breaking bullets (- breaking: …)" aria-invalid={commitChangelogOverLimit} />
              {commitChangelogOverLimit && (
                <p className="text-xs text-red-600 dark:text-red-400" role="alert">
                  Changelog exceeds {VERSION_NOTES_LIMITS.maxChangelogChars} characters
                </p>
              )}
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowCreateDialog(false)} disabled={isLoading}>Cancel</Button>
            <Button onClick={handleCreateSubmit} disabled={isLoading || !createCommitFormValid}>
              {isLoading ? 'Committing…' : 'Commit'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Edit Version Dialog */}
      <Dialog open={showEditDialog} onOpenChange={(open) => !isLoading && setShowEditDialog(open)}>
        <DialogContent aria-describedby={undefined}>
          <DialogHeader><DialogTitle>Edit Version</DialogTitle></DialogHeader>
          <div className="space-y-4 py-4">
            {errorMessage && <Alert variant="error">{errorMessage}</Alert>}
            {selectedVersion && (selectedVersion.lifecycle ?? 'stable') === 'archived' && effectiveIsAdmin && !editPublishedMetadataOnly && (
              <p className="text-sm text-gray-600 dark:text-gray-400">
                This revision is archived (read-only). You can change its lifecycle or use revision lock; notes cannot be edited here.
              </p>
            )}
            {editPublishedMetadataOnly && (
              <p className="text-sm text-gray-600 dark:text-gray-400">
                Published revision — notes are frozen. As a tenant admin you can update deprecation and sunset metadata only (#748).
              </p>
            )}
            <div className="space-y-2">
              <Label>Version ID</Label>
              <Input value={versionId} disabled className="font-mono" />
            </div>
            <div className="space-y-2">
              <Label>Lifecycle</Label>
              <Select value={editLifecycle} onValueChange={setEditLifecycle} disabled={isLoading}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="stable">Stable</SelectItem>
                  <SelectItem value="beta">Beta</SelectItem>
                  <SelectItem value="deprecated">Deprecated</SelectItem>
                  <SelectItem value="archived">Archived</SelectItem>
                </SelectContent>
              </Select>
              <p className="text-xs text-gray-500 dark:text-gray-400">
                Semantic governance tag (#739). Setting Deprecated sets revision deprecation (#507) for consumers.
              </p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="deprecation-msg">Deprecation message</Label>
              <Textarea
                id="deprecation-msg"
                value={editDeprecationMessage}
                onChange={(e) => setEditDeprecationMessage(e.target.value)}
                rows={2}
                disabled={isLoading}
                placeholder="Why this revision is deprecated (optional)"
                className="text-sm"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="sunset-local">Sunset (local time → stored as UTC)</Label>
              <Input
                id="sunset-local"
                type="datetime-local"
                value={editSunsetLocal}
                onChange={(e) => setEditSunsetLocal(e.target.value)}
                disabled={isLoading}
              />
              <p className="text-xs text-gray-500 dark:text-gray-400">
                Requires lifecycle Deprecated and a successor revision. Cleared if empty.
              </p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="successor-rev">Successor revision ID</Label>
              <Input
                id="successor-rev"
                value={editSuccessorRevisionId}
                onChange={(e) => setEditSuccessorRevisionId(e.target.value)}
                disabled={isLoading}
                placeholder="UUID of replacement revision in this project"
                className="font-mono text-sm"
              />
            </div>
            <div className="space-y-2">
              <Label>Revision note *</Label>
              <Input
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                disabled={
                  isLoading ||
                  editPublishedMetadataOnly ||
                  ((selectedVersion?.lifecycle ?? 'stable') === 'archived' && effectiveIsAdmin)
                }
                autoFocus={
                  !editPublishedMetadataOnly &&
                  (((selectedVersion?.lifecycle ?? 'stable') !== 'archived') || !effectiveIsAdmin)
                }
                placeholder="Short summary (commit message)"
              />
            </div>
            <div className="space-y-2">
              <Label>Changelog (markdown)</Label>
              <Textarea
                value={changeLog}
                onChange={(e) => setChangeLog(e.target.value)}
                rows={4}
                disabled={
                  isLoading ||
                  editPublishedMetadataOnly ||
                  ((selectedVersion?.lifecycle ?? 'stable') === 'archived' && effectiveIsAdmin)
                }
                placeholder="Release notes, breaking bullets (- breaking: …)"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowEditDialog(false)} disabled={isLoading}>Cancel</Button>
            <Button onClick={handleEditSubmit} disabled={isLoading}>{isLoading ? 'Saving...' : 'Save Changes'}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Publish Version Dialog */}
      <Dialog open={showPublishDialog} onOpenChange={(open) => { setShowPublishDialog(open); if (!open) setPublishVersionId(null); }}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>Publish Version</DialogTitle>
            <DialogDescription>
              Once published, this version will become read-only. To make any additional edits after publishing, either create a new version, or unpublish this version.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label>Visibility</Label>
              <Select value={publishVisibility} onValueChange={(v) => setPublishVisibility(v as 'private' | 'public')}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="private">Private</SelectItem>
                  <SelectItem value="public">Public</SelectItem>
                </SelectContent>
              </Select>
              <p className="text-sm text-gray-500 dark:text-gray-400">
                {publishVisibility === 'private' ? 'Access requires an API Key.' : 'OpenAPI Specification will be public without requiring an API Key.'}
              </p>
            </div>
            <div className="space-y-2">
              <Label>Revision note *</Label>
              <Input
                value={publishShortMessage}
                onChange={(e) => setPublishShortMessage(e.target.value)}
                placeholder="Short summary frozen with this publish"
              />
            </div>
            <div className="space-y-2">
              <Label>Changelog (markdown)</Label>
              <Textarea
                value={publishChangelog}
                onChange={(e) => setPublishChangelog(e.target.value)}
                rows={5}
                placeholder="Release notes; use - breaking: lines for migration docs"
                className="font-mono text-sm"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => { setShowPublishDialog(false); setPublishVersionId(null); }}>Cancel</Button>
            <Button onClick={handlePublishConfirm}>Publish</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* OpenAPI Viewer Dialog */}
      <Dialog open={showOpenApiDialog} onOpenChange={setShowOpenApiDialog}>
        <DialogContent className="max-w-4xl max-h-[80vh]" aria-describedby={undefined}>
          <DialogHeader>
            <DialogTitle className="flex items-center justify-between">
              <div>
                <div>OpenAPI 3.1.0 Specification</div>
                {viewingVersion && <div className="text-sm text-gray-500 dark:text-gray-400 mt-1 font-normal">{projects.find(p => p.id === viewingVersion.project_id)?.name} - v{viewingVersion.version_id}</div>}
              </div>
              <div className="flex gap-1 border border-gray-300 dark:border-gray-600 rounded overflow-hidden">
                <button onClick={() => setOpenApiFormat('json')} className={`px-3 py-1 text-xs font-medium ${openApiFormat === 'json' ? 'bg-blue-600 text-white' : 'bg-white dark:bg-gray-700 text-gray-700 dark:text-gray-300'}`}>JSON</button>
                <button onClick={() => setOpenApiFormat('yaml')} className={`px-3 py-1 text-xs font-medium border-l border-gray-300 dark:border-gray-600 ${openApiFormat === 'yaml' ? 'bg-blue-600 text-white' : 'bg-white dark:bg-gray-700 text-gray-700 dark:text-gray-300'}`}>YAML</button>
              </div>
            </DialogTitle>
          </DialogHeader>
          <div className="h-[60vh]">
            {isLoadingSpec ? (
              <LoadingState
                className="h-full"
                minHeightClassName="min-h-0"
                spinnerSize="md"
                message="Loading specification..."
              />
            ) : (
              <Editor height="100%" language={openApiFormat} value={openApiFormat === 'json' ? openApiSpec : YAML.stringify(JSON.parse(openApiSpec || '{}'))} theme="vs-dark" options={{ readOnly: true, minimap: { enabled: true }, fontSize: 13 }} />
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowOpenApiDialog(false)}>Close</Button>
            <Button onClick={async () => { await navigator.clipboard.writeText(openApiFormat === 'json' ? openApiSpec : YAML.stringify(JSON.parse(openApiSpec))); toast.success('Copied to clipboard!'); }} disabled={isLoadingSpec}>Copy</Button>
            <Button onClick={() => {
              const content = openApiFormat === 'json' ? openApiSpec : YAML.stringify(JSON.parse(openApiSpec));
              const blob = new Blob([content], { type: openApiFormat === 'json' ? 'application/json' : 'text/yaml' });
              const url = URL.createObjectURL(blob);
              const link = document.createElement('a'); link.href = url;
              const project = viewingVersion ? projects.find(p => p.id === viewingVersion.project_id) : null;
              link.download = `${project?.slug || 'api'}-${viewingVersion?.version_id?.replace(/\./g, '-') || '1-0-0'}-openapi.${openApiFormat === 'json' ? 'json' : 'yaml'}`;
              document.body.appendChild(link); link.click(); document.body.removeChild(link); URL.revokeObjectURL(url);
            }} disabled={isLoadingSpec}>Download</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Version Comparison Dialog */}
      <Dialog open={showCompareDialog} onOpenChange={setShowCompareDialog}>
        <DialogContent className="max-w-6xl h-[90vh] min-h-[90vh] flex flex-col" aria-describedby={undefined}>
          <DialogHeader className="flex-shrink-0">
            <DialogTitle className="flex items-center justify-between">
              <div>
                <div>Compare Version Schemas</div>
                <div className="text-sm text-gray-500 dark:text-gray-400 mt-1 font-normal">View differences between two version specifications</div>
              </div>
              {diffResult.length > 0 && activeCompareTab === 'diff' && (
                <div className="flex gap-2">
                  <div className="flex border border-gray-300 dark:border-gray-600 rounded overflow-hidden">
                    <button onClick={() => setDiffViewMode('overlay')} className={`px-2 py-1 text-xs ${diffViewMode === 'overlay' ? 'bg-purple-600 text-white' : 'bg-white dark:bg-gray-700 text-gray-700 dark:text-gray-300'}`}>Overlay</button>
                    <button onClick={() => setDiffViewMode('side-by-side')} className={`px-2 py-1 text-xs border-l border-gray-300 dark:border-gray-600 ${diffViewMode === 'side-by-side' ? 'bg-purple-600 text-white' : 'bg-white dark:bg-gray-700 text-gray-700 dark:text-gray-300'}`}>Side-by-Side</button>
                  </div>
                  <div className="flex border border-gray-300 dark:border-gray-600 rounded overflow-hidden">
                    <button onClick={() => handleCompareFormatChange('json')} className={`px-2 py-1 text-xs ${compareFormat === 'json' ? 'bg-blue-600 text-white' : 'bg-white dark:bg-gray-700 text-gray-700 dark:text-gray-300'}`}>JSON</button>
                    <button onClick={() => handleCompareFormatChange('yaml')} className={`px-2 py-1 text-xs border-l border-gray-300 dark:border-gray-600 ${compareFormat === 'yaml' ? 'bg-blue-600 text-white' : 'bg-white dark:bg-gray-700 text-gray-700 dark:text-gray-300'}`}>YAML</button>
                  </div>
                </div>
              )}
              {diffResult.length > 0 && activeCompareTab === 'canvas' && (
                <div className="flex border border-gray-300 dark:border-gray-600 rounded overflow-hidden">
                  <button
                    type="button"
                    onClick={() => setCanvasCompareViewMode('split')}
                    className={`px-2 py-1 text-xs ${canvasCompareViewMode === 'split' ? 'bg-teal-600 text-white' : 'bg-white dark:bg-gray-700 text-gray-700 dark:text-gray-300'}`}
                  >
                    Split
                  </button>
                  <button
                    type="button"
                    onClick={() => setCanvasCompareViewMode('overlay')}
                    className={`px-2 py-1 text-xs border-l border-gray-300 dark:border-gray-600 ${canvasCompareViewMode === 'overlay' ? 'bg-teal-600 text-white' : 'bg-white dark:bg-gray-700 text-gray-700 dark:text-gray-300'}`}
                  >
                    Overlay
                  </button>
                </div>
              )}
            </DialogTitle>
          </DialogHeader>
          <div className="flex-1 overflow-y-auto overflow-x-hidden">
            {diffResult.length === 0 ? (
              <div className="space-y-4 p-4">
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label>Version 1 (Base)</Label>
                    <Select
                      value={compareVersion1Id}
                      onValueChange={(id) => {
                        setCompareVersion1Id(id);
                        setCompareBaseTagId('');
                      }}
                    >
                      <SelectTrigger><SelectValue placeholder="Select version..." /></SelectTrigger>
                      <SelectContent>{versions.map((v) => <SelectItem key={v.id} value={v.id}>{v.published ? '🔒 ' : ''}v{v.version_id}</SelectItem>)}</SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-2">
                    <Label>Version 2 (Compare To)</Label>
                    <Select
                      value={compareVersion2Id}
                      onValueChange={(id) => {
                        setCompareVersion2Id(id);
                        setCompareToTagId('');
                      }}
                    >
                      <SelectTrigger><SelectValue placeholder="Select version..." /></SelectTrigger>
                      <SelectContent>{versions.map((v) => <SelectItem key={v.id} value={v.id}>{v.published ? '🔒 ' : ''}v{v.version_id}</SelectItem>)}</SelectContent>
                    </Select>
                  </div>
                </div>
                {versionTags.length > 0 && (
                  <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-2">
                      <Label>Set base from tag</Label>
                      <Select
                        value={compareBaseTagId || '__none__'}
                        onValueChange={(id) => {
                          if (id === '__none__') {
                            setCompareBaseTagId('');
                            return;
                          }
                          setCompareBaseTagId(id);
                          const t = versionTags.find((x) => x.id === id);
                          if (t) setCompareVersion1Id(t.version_id);
                        }}
                      >
                        <SelectTrigger><SelectValue placeholder="Optional" /></SelectTrigger>
                        <SelectContent>
                          <SelectItem value="__none__">—</SelectItem>
                          {versionTags.map((tg) => (
                            <SelectItem key={tg.id} value={tg.id}>
                              {tg.name} → v{tg.target_version_string ?? '?'}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-2">
                      <Label>Set compare target from tag</Label>
                      <Select
                        value={compareToTagId || '__none__'}
                        onValueChange={(id) => {
                          if (id === '__none__') {
                            setCompareToTagId('');
                            return;
                          }
                          setCompareToTagId(id);
                          const t = versionTags.find((x) => x.id === id);
                          if (t) setCompareVersion2Id(t.version_id);
                        }}
                      >
                        <SelectTrigger><SelectValue placeholder="Optional" /></SelectTrigger>
                        <SelectContent>
                          <SelectItem value="__none__">—</SelectItem>
                          {versionTags.map((tg) => (
                            <SelectItem key={tg.id} value={tg.id}>
                              {tg.name} → v{tg.target_version_string ?? '?'}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                  </div>
                )}
                <div className="flex justify-center py-8">
                  <Button onClick={handleCompareVersions} disabled={!compareVersion1Id || !compareVersion2Id || isLoadingComparison}>{isLoadingComparison ? 'Loading...' : 'Compare Versions'}</Button>
                </div>
              </div>
            ) : (
              <div className="flex flex-col h-full">
                {(() => {
                  const vBase = versions.find((v) => v.id === compareVersion1Id);
                  const vTo = versions.find((v) => v.id === compareVersion2Id);
                  if (!vBase || !vTo) return null;
                  const breakBase = extractBreakingHintsFromChangelog(vBase.changelog);
                  const breakTo = extractBreakingHintsFromChangelog(vTo.changelog);
                  return (
                    <div className="mb-4 space-y-3 flex-shrink-0">
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                        <div className="rounded-lg border border-gray-200 dark:border-gray-600 bg-gray-50 dark:bg-gray-900/40 p-3 text-sm">
                          <div className="font-semibold text-gray-900 dark:text-gray-100 mb-1">
                            v{vBase.version_id} (base)
                          </div>
                          <div className="text-gray-600 dark:text-gray-400">
                            <span className="text-gray-500 dark:text-gray-500">Revision note:</span>{' '}
                            {vBase.shortMessage?.trim() || '—'}
                          </div>
                          {vBase.changelog?.trim() ? (
                            <pre className="mt-2 whitespace-pre-wrap text-xs text-gray-700 dark:text-gray-300 font-sans max-h-32 overflow-y-auto">
                              {vBase.changelog}
                            </pre>
                          ) : (
                            <p className="mt-2 text-xs text-gray-500 dark:text-gray-400">No changelog</p>
                          )}
                          {breakBase.length > 0 && (
                            <p className="mt-2 text-xs text-amber-700 dark:text-amber-300">
                              Breaking hints: {breakBase.join(' · ')}
                            </p>
                          )}
                        </div>
                        <div className="rounded-lg border border-gray-200 dark:border-gray-600 bg-gray-50 dark:bg-gray-900/40 p-3 text-sm">
                          <div className="font-semibold text-gray-900 dark:text-gray-100 mb-1">
                            v{vTo.version_id} (compare to)
                          </div>
                          <div className="text-gray-600 dark:text-gray-400">
                            <span className="text-gray-500 dark:text-gray-500">Revision note:</span>{' '}
                            {vTo.shortMessage?.trim() || '—'}
                          </div>
                          {vTo.changelog?.trim() ? (
                            <pre className="mt-2 whitespace-pre-wrap text-xs text-gray-700 dark:text-gray-300 font-sans max-h-32 overflow-y-auto">
                              {vTo.changelog}
                            </pre>
                          ) : (
                            <p className="mt-2 text-xs text-gray-500 dark:text-gray-400">No changelog</p>
                          )}
                          {breakTo.length > 0 && (
                            <p className="mt-2 text-xs text-amber-700 dark:text-amber-300">
                              Breaking hints: {breakTo.join(' · ')}
                            </p>
                          )}
                        </div>
                      </div>
                    </div>
                  );
                })()}
                {/* Tab Navigation */}
                <div className="flex border-b border-gray-200 dark:border-gray-700 mb-4">
                  <button
                    onClick={() => setActiveCompareTab('diff')}
                    className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                      activeCompareTab === 'diff'
                        ? 'border-indigo-600 text-indigo-600 dark:text-indigo-400'
                        : 'border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300 hover:border-gray-300 dark:hover:border-gray-600'
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                      </svg>
                      <span>Diff View</span>
                    </div>
                  </button>
                  <button
                    onClick={() => setActiveCompareTab('summary')}
                    className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                      activeCompareTab === 'summary'
                        ? 'border-indigo-600 text-indigo-600 dark:text-indigo-400'
                        : 'border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300 hover:border-gray-300 dark:hover:border-gray-600'
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
                      </svg>
                      <span>Schema Changes</span>
                      {schemaDiffSummary && (
                        <span className="ml-1 px-1.5 py-0.5 text-xs rounded-full bg-indigo-100 dark:bg-indigo-900 text-indigo-700 dark:text-indigo-300">
                          {classDiffRows
                            ? classDiffRows.filter((r) => r.status !== 'unchanged').length
                            : schemaDiffSummary.added.length +
                              schemaDiffSummary.removed.length +
                              schemaDiffSummary.modified.length}
                        </span>
                      )}
                    </div>
                  </button>
                  <button
                    type="button"
                    onClick={() => setActiveCompareTab('breaking')}
                    className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                      activeCompareTab === 'breaking'
                        ? 'border-indigo-600 text-indigo-600 dark:text-indigo-400'
                        : 'border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300 hover:border-gray-300 dark:hover:border-gray-600'
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      <ScrollText className="h-4 w-4" aria-hidden />
                      <span>Breaking doc</span>
                    </div>
                  </button>
                  <button
                    type="button"
                    onClick={() => setActiveCompareTab('migration')}
                    className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                      activeCompareTab === 'migration'
                        ? 'border-indigo-600 text-indigo-600 dark:text-indigo-400'
                        : 'border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300 hover:border-gray-300 dark:hover:border-gray-600'
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      <ListOrdered className="h-4 w-4" aria-hidden />
                      <span>Migration guide</span>
                    </div>
                  </button>
                  <button
                    type="button"
                    onClick={() => setActiveCompareTab('canvas')}
                    className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                      activeCompareTab === 'canvas'
                        ? 'border-indigo-600 text-indigo-600 dark:text-indigo-400'
                        : 'border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300 hover:border-gray-300 dark:hover:border-gray-600'
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      <LayoutGrid className="h-4 w-4" aria-hidden />
                      <span>Canvas</span>
                    </div>
                  </button>
                </div>

                {/* Tab Content */}
                {activeCompareTab === 'diff' ? (
                  // Diff View Tab
                  <div>
                    <div className="flex items-center justify-between mb-2 pb-2 border-b border-gray-200 dark:border-gray-700">
                      <div className="flex gap-4 text-sm">
                        <div className="flex items-center gap-2"><div className="w-4 h-4 bg-red-200 dark:bg-red-900 border border-red-400"></div><span>Removed</span></div>
                        <div className="flex items-center gap-2"><div className="w-4 h-4 bg-green-200 dark:bg-green-900 border border-green-400"></div><span>Added</span></div>
                        <div className="flex items-center gap-2"><div className="w-4 h-4 bg-gray-100 dark:bg-gray-800 border border-gray-300"></div><span>Unchanged</span></div>
                      </div>
                      <div className="text-sm text-gray-600 dark:text-gray-400">v{versions.find(v => v.id === compareVersion1Id)?.version_id} → v{versions.find(v => v.id === compareVersion2Id)?.version_id}</div>
                    </div>
                    <div className="border border-gray-300 dark:border-gray-600 rounded font-mono text-xs h-[calc(90vh-280px)]">
                      {diffViewMode === 'overlay' ? (
                        // Overlay/Unified diff view
                        <div className="h-full overflow-y-auto">
                          {diffResult.map((part, i) => (
                            <div key={i} className={part.added ? 'bg-green-100 dark:bg-green-900/30 text-green-900 dark:text-green-200' : part.removed ? 'bg-red-100 dark:bg-red-900/30 text-red-900 dark:text-red-200' : 'bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-300'}>
                              {part.value.split('\n').filter(Boolean).map((line, j) => (
                                <div key={j} className="px-3 py-0.5" style={{ whiteSpace: 'pre-wrap' }}>
                                  {part.added && '+ '}{part.removed && '- '}{line}
                                </div>
                              ))}
                            </div>
                          ))}
                        </div>
                      ) : (
                        // Side-by-side view
                        <div className="flex h-full">
                          {/* Left panel - Version 1 (Base) */}
                          <div
                            ref={leftPanelRef}
                            onScroll={handleLeftScroll}
                            className="w-1/2 border-r border-gray-300 dark:border-gray-600 h-full overflow-y-auto"
                          >
                            <div className="sticky top-0 bg-gray-100 dark:bg-gray-700 px-3 py-1 text-xs font-semibold border-b border-gray-300 dark:border-gray-600 z-10">
                              v{versions.find(v => v.id === compareVersion1Id)?.version_id} (Base)
                            </div>
                            {(() => {
                              const content1 = compareFormat === 'json' ? compareSpec1 : YAML.stringify(JSON.parse(compareSpec1));
                              return content1.split('\n').map((line, i) => {
                                const isRemoved = diffResult.some(part => part.removed && part.value.includes(line));
                                return (
                                  <div
                                    key={i}
                                    className={`px-3 py-0.5 ${isRemoved ? 'bg-red-100 dark:bg-red-900/30 text-red-900 dark:text-red-200' : 'bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-300'}`}
                                    style={{ whiteSpace: 'pre-wrap' }}
                                  >
                                    <span className="text-gray-400 dark:text-gray-500 select-none mr-2 inline-block w-8 text-right">{i + 1}</span>
                                    {line || ' '}
                                  </div>
                                );
                              });
                            })()}
                          </div>
                          {/* Right panel - Version 2 (Compare To) */}
                          <div
                            ref={rightPanelRef}
                            onScroll={handleRightScroll}
                            className="w-1/2 h-full overflow-y-auto"
                          >
                            <div className="sticky top-0 bg-gray-100 dark:bg-gray-700 px-3 py-1 text-xs font-semibold border-b border-gray-300 dark:border-gray-600 z-10">
                              v{versions.find(v => v.id === compareVersion2Id)?.version_id} (Compare To)
                            </div>
                            {(() => {
                              const content2 = compareFormat === 'json' ? compareSpec2 : YAML.stringify(JSON.parse(compareSpec2));
                              return content2.split('\n').map((line, i) => {
                                const isAdded = diffResult.some(part => part.added && part.value.includes(line));
                                return (
                                  <div
                                    key={i}
                                    className={`px-3 py-0.5 ${isAdded ? 'bg-green-100 dark:bg-green-900/30 text-green-900 dark:text-green-200' : 'bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-300'}`}
                                    style={{ whiteSpace: 'pre-wrap' }}
                                  >
                                    <span className="text-gray-400 dark:text-gray-500 select-none mr-2 inline-block w-8 text-right">{i + 1}</span>
                                    {line || ' '}
                                  </div>
                                );
                              });
                            })()}
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                ) : activeCompareTab === 'summary' ? (
                  // Schema Changes Summary Tab
                  <div className="h-[calc(90vh-280px)] overflow-y-auto">
                    {schemaDiffSummary && (
                  <div className="p-4 bg-gray-50 dark:bg-gray-900 rounded-lg border border-gray-200 dark:border-gray-700">
                    {classDiffRows && classDiffCounts && (
                      <div className="mb-6 pb-6 border-b border-gray-200 dark:border-gray-700">
                        <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between mb-3">
                          <div>
                            <h3 className="text-sm font-semibold text-gray-900 dark:text-white">Classes</h3>
                            <p className="text-xs text-gray-600 dark:text-gray-400 mt-0.5">
                              Structural diff (git-style). Stable ID = OpenAPI schema name.{' '}
                              <span className="text-green-700 dark:text-green-400">+{classDiffCounts.added}</span>
                              {' · '}
                              <span className="text-red-700 dark:text-red-400">−{classDiffCounts.removed}</span>
                              {' · '}
                              <span className="text-yellow-700 dark:text-yellow-400">~{classDiffCounts.modified}</span>
                              {' · '}
                              <span className="text-gray-600 dark:text-gray-500">{classDiffCounts.unchanged} unchanged</span>
                            </p>
                          </div>
                          <div className="flex flex-wrap items-center gap-2">
                            <Button
                              type="button"
                              variant="outline"
                              className="text-xs h-8"
                              onClick={async () => {
                                try {
                                  await navigator.clipboard.writeText(formatClassDiffStatLines(classDiffRows));
                                  toast.success('Class diff copied to clipboard');
                                } catch {
                                  toast.error('Failed to copy class diff to clipboard');
                                }
                              }}
                            >
                              Copy class stat
                            </Button>
                          </div>
                        </div>
                        <div className="flex flex-col sm:flex-row gap-2 mb-2">
                          <Input
                            type="search"
                            placeholder="Search classes…"
                            value={classDiffSearch}
                            onChange={(e) => setClassDiffSearch(e.target.value)}
                            className="text-sm h-9 flex-1 min-w-0"
                            aria-label="Filter classes by name"
                          />
                          <label className="flex items-center gap-2 text-xs text-gray-700 dark:text-gray-300 whitespace-nowrap shrink-0">
                            <input
                              type="checkbox"
                              className="rounded border-gray-300 dark:border-gray-600"
                              checked={classDiffShowUnchanged}
                              onChange={(e) => setClassDiffShowUnchanged(e.target.checked)}
                            />
                            Show unchanged
                          </label>
                        </div>
                        <p className="text-[11px] text-gray-500 dark:text-gray-500 mb-1">
                          Showing {filteredClassDiffRows.length} of {classDiffRows.length} classes
                          {classDiffListRender.virtualize ? ' · Virtualized list' : ''}
                        </p>
                        <div
                          ref={classListScrollRef}
                          className="max-h-72 overflow-y-auto rounded-md border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-950"
                          style={
                            classDiffListRender.virtualize ? { height: CLASS_DIFF_VIEWPORT_PX } : undefined
                          }
                          onScroll={(e) => setClassListScrollTop(e.currentTarget.scrollTop)}
                        >
                          <div style={{ height: classDiffListRender.padTop }} aria-hidden />
                          {classDiffListRender.rows.map((row) => {
                            const sym =
                              row.status === 'added'
                                ? '+'
                                : row.status === 'removed'
                                  ? '−'
                                  : row.status === 'modified'
                                    ? '~'
                                    : ' ';
                            const rowBg =
                              row.status === 'added'
                                ? 'bg-green-50 dark:bg-green-950/30 border-green-200 dark:border-green-900 border-l-green-600'
                                : row.status === 'removed'
                                  ? 'bg-red-50 dark:bg-red-950/30 border-red-200 dark:border-red-900 border-l-red-600'
                                  : row.status === 'modified'
                                    ? 'bg-yellow-50 dark:bg-yellow-950/30 border-yellow-200 dark:border-yellow-900 border-l-yellow-500'
                                    : 'bg-gray-50 dark:bg-gray-900/40 border-gray-200 dark:border-gray-700 border-l-gray-400';
                            const expanded = expandedClassDiffId === row.stableId;
                            const drill = expanded ? getClassChangeDiffs(schemaDiffSummary, row.stableId) : [];
                            const showAllProps = propDrillShowAllByClass[row.stableId] === true;
                            const drillVisible =
                              drill.length <= CLASS_PROP_DRILL_LIMIT || showAllProps
                                ? drill
                                : drill.slice(0, CLASS_PROP_DRILL_LIMIT);
                            return (
                              <div key={row.stableId} className="border-b border-gray-100 dark:border-gray-800 last:border-b-0">
                                <button
                                  type="button"
                                  onClick={() =>
                                    setExpandedClassDiffId((id) => (id === row.stableId ? null : row.stableId))
                                  }
                                  className={`w-full text-left px-3 py-2 flex items-center gap-2 border-l-4 ${rowBg} hover:opacity-95 transition-opacity`}
                                  style={{ minHeight: CLASS_DIFF_ROW_PX }}
                                  aria-expanded={expanded}
                                >
                                  <span
                                    className={`font-mono text-xs w-4 shrink-0 ${
                                      row.status === 'added'
                                        ? 'text-green-700 dark:text-green-400'
                                        : row.status === 'removed'
                                          ? 'text-red-700 dark:text-red-400'
                                          : row.status === 'modified'
                                            ? 'text-yellow-800 dark:text-yellow-300'
                                            : 'text-gray-400 dark:text-gray-500'
                                    }`}
                                  >
                                    {sym}
                                  </span>
                                  <span className="font-mono text-sm font-medium text-gray-900 dark:text-gray-100 truncate flex-1">
                                    {row.stableId}
                                  </span>
                                  {row.status === 'modified' && (
                                    <span className="text-[10px] text-gray-600 dark:text-gray-400 shrink-0 hidden sm:inline">
                                      {row.propertyAdded ? `+${row.propertyAdded} ` : ''}
                                      {row.propertyRemoved ? `−${row.propertyRemoved} ` : ''}
                                      {row.propertyModified ? `~${row.propertyModified} ` : ''}
                                      {row.schemaChanges?.length ? `schema ${row.schemaChanges.join(', ')}` : ''}
                                    </span>
                                  )}
                                  {row.status === 'added' && (
                                    <span className="text-[10px] text-green-800 dark:text-green-300 shrink-0">
                                      +{row.propertyAdded} props
                                    </span>
                                  )}
                                  {row.status === 'removed' && (
                                    <span className="text-[10px] text-red-800 dark:text-red-300 shrink-0">
                                      −{row.propertyRemoved} props
                                    </span>
                                  )}
                                </button>
                                {expanded && drill.length > 0 && (
                                  <div className="px-3 pb-3 pt-0 space-y-1 bg-gray-50/80 dark:bg-gray-900/50 border-t border-dashed border-gray-200 dark:border-gray-700">
                                    <p className="text-[10px] font-medium text-gray-600 dark:text-gray-400 pt-2">
                                      Property-level changes
                                    </p>
                                    {drillVisible.map((d, i) => (
                                      <div
                                        key={`${d.path}-${d.type}-${i}`}
                                        className={`text-xs rounded px-2 py-1 font-mono flex flex-wrap gap-x-2 items-start ${
                                          d.type === 'added'
                                            ? 'bg-green-50 dark:bg-green-950/20 text-green-900 dark:text-green-100'
                                            : d.type === 'removed'
                                              ? 'bg-red-50 dark:bg-red-950/20 text-red-900 dark:text-red-100'
                                              : 'bg-yellow-50 dark:bg-yellow-950/20 text-yellow-900 dark:text-yellow-100'
                                        }`}
                                      >
                                        <span className="shrink-0 pt-px">
                                          {d.type === 'added' ? '+' : d.type === 'removed' ? '−' : '~'}
                                        </span>
                                        <span className="min-w-0 break-words">{formatPropertyDiffLine(d)}</span>
                                      </div>
                                    ))}
                                    {drill.length > CLASS_PROP_DRILL_LIMIT && (
                                      <button
                                        type="button"
                                        className="text-[11px] text-indigo-600 dark:text-indigo-400 hover:underline mt-1"
                                        onClick={(e) => {
                                          e.stopPropagation();
                                          setPropDrillShowAllByClass((prev) => ({
                                            ...prev,
                                            [row.stableId]: !showAllProps,
                                          }));
                                        }}
                                      >
                                        {showAllProps
                                          ? `Show first ${CLASS_PROP_DRILL_LIMIT} only`
                                          : `Show all ${drill.length} changes`}
                                      </button>
                                    )}
                                  </div>
                                )}
                                {expanded && drill.length === 0 && row.status === 'unchanged' && (
                                  <p className="text-[10px] text-gray-500 px-3 pb-2">No property-level changes.</p>
                                )}
                              </div>
                            );
                          })}
                          <div style={{ height: classDiffListRender.padBottom }} aria-hidden />
                        </div>
                      </div>
                    )}
                    <div className="flex items-center justify-between mb-3">
                      <h3 className="text-sm font-semibold text-gray-900 dark:text-white">Schema Changes Summary</h3>

                      {/* Filter Controls */}
                      <div className="flex items-center gap-2">
                        <span className="text-xs text-gray-600 dark:text-gray-400 mr-1">Filter:</span>
                        <button
                          onClick={() => setDiffFilter(prev => ({ ...prev, showAdded: !prev.showAdded }))}
                          className={`px-2 py-1 text-xs rounded border transition-all flex items-center gap-1.5 ${
                            diffFilter.showAdded
                              ? 'bg-green-600 dark:bg-green-700 text-white border-green-700 dark:border-green-600 shadow-sm'
                              : 'bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-500 border-gray-300 dark:border-gray-600 hover:bg-gray-200 dark:hover:bg-gray-700'
                          }`}
                          title={diffFilter.showAdded ? 'Hide additions' : 'Show additions'}
                        >
                          {diffFilter.showAdded && (
                            <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                            </svg>
                          )}
                          <span>+ Added ({schemaDiffSummary.added.length})</span>
                        </button>
                        <button
                          onClick={() => setDiffFilter(prev => ({ ...prev, showRemoved: !prev.showRemoved }))}
                          className={`px-2 py-1 text-xs rounded border transition-all flex items-center gap-1.5 ${
                            diffFilter.showRemoved
                              ? 'bg-red-600 dark:bg-red-700 text-white border-red-700 dark:border-red-600 shadow-sm'
                              : 'bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-500 border-gray-300 dark:border-gray-600 hover:bg-gray-200 dark:hover:bg-gray-700'
                          }`}
                          title={diffFilter.showRemoved ? 'Hide removals' : 'Show removals'}
                        >
                          {diffFilter.showRemoved && (
                            <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                            </svg>
                          )}
                          <span>- Removed ({schemaDiffSummary.removed.length})</span>
                        </button>
                        <button
                          onClick={() => setDiffFilter(prev => ({ ...prev, showModified: !prev.showModified }))}
                          className={`px-2 py-1 text-xs rounded border transition-all flex items-center gap-1.5 ${
                            diffFilter.showModified
                              ? 'bg-yellow-600 dark:bg-yellow-700 text-white border-yellow-700 dark:border-yellow-600 shadow-sm'
                              : 'bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-500 border-gray-300 dark:border-gray-600 hover:bg-gray-200 dark:hover:bg-gray-700'
                          }`}
                          title={diffFilter.showModified ? 'Hide modifications' : 'Show modifications'}
                        >
                          {diffFilter.showModified && (
                            <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                            </svg>
                          )}
                          <span>~ Modified ({schemaDiffSummary.modified.length})</span>
                        </button>
                        {/* Reset filter button */}
                        {(!diffFilter.showAdded || !diffFilter.showRemoved || !diffFilter.showModified) && (
                          <button
                            onClick={() => setDiffFilter({ showAdded: true, showRemoved: true, showModified: true })}
                            className="px-2 py-1 text-xs rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-600 transition-colors"
                            title="Show all changes"
                          >
                            Clear
                          </button>
                        )}
                      </div>
                    </div>

                    <div className="grid grid-cols-3 gap-4 mb-4">
                      <div className="bg-green-50 dark:bg-green-900/20 p-3 rounded-lg border border-green-200 dark:border-green-800">
                        <div className="text-2xl font-bold text-green-600 dark:text-green-400">{schemaDiffSummary.added.length}</div>
                        <div className="text-xs text-green-700 dark:text-green-300">Added</div>
                      </div>
                      <div className="bg-red-50 dark:bg-red-900/20 p-3 rounded-lg border border-red-200 dark:border-red-800">
                        <div className="text-2xl font-bold text-red-600 dark:text-red-400">{schemaDiffSummary.removed.length}</div>
                        <div className="text-xs text-red-700 dark:text-red-300">Removed</div>
                      </div>
                      <div className="bg-yellow-50 dark:bg-yellow-900/20 p-3 rounded-lg border border-yellow-200 dark:border-yellow-800">
                        <div className="text-2xl font-bold text-yellow-600 dark:text-yellow-400">{schemaDiffSummary.modified.length}</div>
                        <div className="text-xs text-yellow-700 dark:text-yellow-300">Modified</div>
                      </div>
                    </div>

                    {/* Detailed changes */}
                    <div className="space-y-4">
                      {/* Empty state when all filters are off or no matching changes */}
                      {(!diffFilter.showAdded && !diffFilter.showRemoved && !diffFilter.showModified) ? (
                        <div className="text-center py-8 text-gray-500 dark:text-gray-400">
                          <div className="text-sm">All change types are filtered out</div>
                          <div className="text-xs mt-1">Enable at least one filter to see changes</div>
                        </div>
                      ) : (
                        (diffFilter.showAdded && schemaDiffSummary.added.length === 0) &&
                        (diffFilter.showRemoved && schemaDiffSummary.removed.length === 0) &&
                        (diffFilter.showModified && schemaDiffSummary.modified.length === 0) &&
                        (!diffFilter.showAdded || schemaDiffSummary.added.length === 0) &&
                        (!diffFilter.showRemoved || schemaDiffSummary.removed.length === 0) &&
                        (!diffFilter.showModified || schemaDiffSummary.modified.length === 0)
                      ) ? (
                        <div className="text-center py-8 text-gray-500 dark:text-gray-400">
                          <div className="text-sm">No changes match the current filter</div>
                        </div>
                      ) : null}

                      {/* Added items */}
                      {diffFilter.showAdded && schemaDiffSummary.added.length > 0 && (
                        <div>
                          <h4 className="text-xs font-semibold text-green-700 dark:text-green-300 mb-2 flex items-center gap-2">
                            <span className="inline-block w-2 h-2 bg-green-500 rounded-full"></span>
                            Added ({schemaDiffSummary.added.length})
                          </h4>
                          <div className="space-y-1">
                            {schemaDiffSummary.added.map((diff, idx) => (
                              <div key={idx} className="flex items-center gap-2 text-sm bg-green-50 dark:bg-green-900/10 px-3 py-1.5 rounded border border-green-200 dark:border-green-800">
                                <span className="text-green-600 dark:text-green-400 font-mono text-xs">+</span>
                                <span className="text-green-900 dark:text-green-100 font-medium">{getPathLabel(diff.path)}</span>
                                <span className="text-green-700 dark:text-green-300 text-xs">({diff.itemType})</span>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Removed items */}
                      {diffFilter.showRemoved && schemaDiffSummary.removed.length > 0 && (
                        <div>
                          <h4 className="text-xs font-semibold text-red-700 dark:text-red-300 mb-2 flex items-center gap-2">
                            <span className="inline-block w-2 h-2 bg-red-500 rounded-full"></span>
                            Removed ({schemaDiffSummary.removed.length})
                          </h4>
                          <div className="space-y-1">
                            {schemaDiffSummary.removed.map((diff, idx) => (
                              <div key={idx} className="flex items-center gap-2 text-sm bg-red-50 dark:bg-red-900/10 px-3 py-1.5 rounded border border-red-200 dark:border-red-800">
                                <span className="text-red-600 dark:text-red-400 font-mono text-xs">-</span>
                                <span className="text-red-900 dark:text-red-100 font-medium">{getPathLabel(diff.path)}</span>
                                <span className="text-red-700 dark:text-red-300 text-xs">({diff.itemType})</span>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Modified items */}
                      {diffFilter.showModified && schemaDiffSummary.modified.length > 0 && (
                        <div>
                          <h4 className="text-xs font-semibold text-yellow-700 dark:text-yellow-300 mb-2 flex items-center gap-2">
                            <span className="inline-block w-2 h-2 bg-yellow-500 rounded-full"></span>
                            Modified ({schemaDiffSummary.modified.length})
                          </h4>
                          <div className="space-y-1">
                            {schemaDiffSummary.modified.map((diff, idx) => (
                              <div key={idx} className="flex items-start gap-2 text-sm bg-yellow-50 dark:bg-yellow-900/10 px-3 py-1.5 rounded border border-yellow-200 dark:border-yellow-800">
                                <span className="text-yellow-600 dark:text-yellow-400 font-mono text-xs mt-0.5">~</span>
                                <div className="flex-1">
                                  <div className="flex items-center gap-2">
                                    <span className="text-yellow-900 dark:text-yellow-100 font-medium">{getPathLabel(diff.path)}</span>
                                    <span className="text-yellow-700 dark:text-yellow-300 text-xs">({diff.itemType})</span>
                                  </div>
                                  {diff.changes && diff.changes.length > 0 && (
                                    <div className="text-xs text-yellow-700 dark:text-yellow-400 mt-1">
                                      Changed: {diff.changes.join(', ')}
                                    </div>
                                  )}
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                    )}
                  </div>
                ) : activeCompareTab === 'breaking' ? (
                  <div className="h-[calc(90vh-280px)] overflow-y-auto flex flex-col gap-3 p-2">
                    <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between shrink-0">
                      <p className="text-xs text-gray-600 dark:text-gray-400 max-w-prose">
                        Generated from the schema diff. Stable identifiers use{' '}
                        <span className="font-mono text-[11px]">components.schemas…</span> paths. The same revision pair always yields the same text (template version is in the header).
                      </p>
                      <div className="flex flex-wrap gap-2 shrink-0">
                        <Button
                          type="button"
                          variant="outline"
                          className="text-xs h-8"
                          onClick={async () => {
                            try {
                              await navigator.clipboard.writeText(breakingChangesMarkdown);
                              toast.success('Breaking-changes doc copied');
                            } catch {
                              toast.error('Copy failed');
                            }
                          }}
                          disabled={!breakingChangesMarkdown}
                        >
                          Copy
                        </Button>
                        <Button
                          type="button"
                          variant="default"
                          className="text-xs h-8"
                          onClick={appendBreakingDocToCompareTargetChangelog}
                          disabled={!breakingChangesMarkdown}
                        >
                          Append to compare-to changelog
                        </Button>
                      </div>
                    </div>
                    <Textarea
                      readOnly
                      className="flex-1 min-h-[min(420px,50vh)] font-mono text-xs"
                      value={breakingChangesMarkdown}
                      placeholder="Compare two versions to generate breaking-changes Markdown."
                      aria-label="Generated breaking changes markdown"
                    />
                  </div>
                ) : activeCompareTab === 'migration' ? (
                  <div className="h-[calc(90vh-280px)] overflow-y-auto flex flex-col gap-3 p-2">
                    <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between shrink-0">
                      <p className="text-xs text-gray-600 dark:text-gray-400 max-w-prose">
                        Ordered steps for <strong className="font-medium text-gray-800 dark:text-gray-200">breaking</strong>{' '}
                        contract changes, tied to this revision pair. Companion to the{' '}
                        <strong className="font-medium text-gray-800 dark:text-gray-200">Breaking doc</strong> tab (#746) and
                        compatibility checks (#506). Template version is in the header; edit the Markdown after export if
                        needed (#502).
                      </p>
                      <div className="flex flex-wrap gap-2 shrink-0">
                        <Button
                          type="button"
                          variant="outline"
                          className="text-xs h-8"
                          onClick={async () => {
                            try {
                              await navigator.clipboard.writeText(migrationGuideMarkdown);
                              toast.success('Migration guide copied');
                            } catch {
                              toast.error('Copy failed');
                            }
                          }}
                          disabled={!migrationGuideMarkdown}
                        >
                          Copy
                        </Button>
                        <Button
                          type="button"
                          variant="default"
                          className="text-xs h-8"
                          onClick={appendMigrationGuideToCompareTargetChangelog}
                          disabled={!migrationGuideMarkdown}
                        >
                          Append to compare-to changelog
                        </Button>
                        <Button
                          type="button"
                          variant="outline"
                          className="text-xs h-8"
                          onClick={downloadMigrationGuideMarkdownFile}
                          disabled={!migrationGuideMarkdown}
                        >
                          Download Markdown
                        </Button>
                        <Button
                          type="button"
                          variant="outline"
                          className="text-xs h-8"
                          onClick={() => {
                            const vBase = versions.find((v) => v.id === compareVersion1Id);
                            const vTo = versions.find((v) => v.id === compareVersion2Id);
                            const proj = projects.find((p) => p.id === selectedProjectId);
                            downloadMigrationGuidePdf({
                              body: migrationGuideMarkdown,
                              projectName: proj?.name ?? 'Project',
                              baseVersionLabel: vBase ? `v${vBase.version_id}` : 'base',
                              targetVersionLabel: vTo ? `v${vTo.version_id}` : 'target',
                            });
                            toast.success('PDF downloaded');
                          }}
                          disabled={!migrationGuideMarkdown}
                        >
                          Download PDF
                        </Button>
                      </div>
                    </div>
                    <Textarea
                      readOnly
                      className="flex-1 min-h-[min(420px,50vh)] font-mono text-xs"
                      value={migrationGuideMarkdown}
                      placeholder="Compare two versions to generate a migration guide."
                      aria-label="Generated migration guide markdown"
                    />
                  </div>
                ) : (
                  <div className="h-[calc(90vh-280px)] overflow-y-auto px-1 pt-1">
                    {canvasCompareLoading ? (
                      <LoadingState
                        className="min-h-[min(380px,45vh)] w-full py-8"
                        minHeightClassName="min-h-[min(380px,45vh)]"
                        spinnerSize="md"
                        message="Loading canvas layouts…"
                      />
                    ) : (
                      <VersionCanvasCompare
                        left={canvasCompareLeft}
                        right={canvasCompareRight}
                        leftLabel={`v${versions.find((v) => v.id === compareVersion1Id)?.version_id ?? '?'} (base)`}
                        rightLabel={`v${versions.find((v) => v.id === compareVersion2Id)?.version_id ?? '?'} (compare)`}
                        mode={canvasCompareViewMode}
                        diff={canvasCompareDiff}
                      />
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
          <DialogFooter className="flex-shrink-0">
            {diffResult.length > 0 && (
              <Button
                variant="outline"
                onClick={() => {
                  setDiffResult([]);
                  setCompareSpec1('');
                  setCompareSpec2('');
                  setSchemaDiffSummary(null);
                  setClassDiffRows(null);
                  setClassDiffSearch('');
                  setExpandedClassDiffId(null);
                  setPropDrillShowAllByClass({});
                  setCanvasCompareLeft(null);
                  setCanvasCompareRight(null);
                  setCanvasCompareDiff(null);
                  setCanvasComparePairKey('');
                  setActiveCompareTab('diff');
                }}
              >
                Compare Different Versions
              </Button>
            )}
            <Button variant="outline" onClick={() => setShowCompareDialog(false)}>Close</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={showForkDialog} onOpenChange={(open) => !forkSaving && setShowForkDialog(open)}>
        <DialogContent className="max-w-lg" aria-describedby={undefined}>
          <DialogHeader>
            <DialogTitle>Fork to another project</DialogTitle>
            <DialogDescription>
              Create an isolated copy of this revision in a different project. Edits stay separate from the upstream line until you merge or publish intentionally.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3 py-2">
            <div className="space-y-1">
              <Label htmlFor="fork-target-project">Target project</Label>
              <Select value={forkTargetProjectId} onValueChange={setForkTargetProjectId}>
                <SelectTrigger id="fork-target-project">
                  <SelectValue placeholder="Select project" />
                </SelectTrigger>
                <SelectContent>
                  {otherProjects.map((p) => (
                    <SelectItem key={p.id} value={p.id}>
                      {p.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Version ID</Label>
              <Select
                value={forkAutoGenerate ? 'auto' : 'manual'}
                onValueChange={(v) => {
                  const isAuto = v === 'auto';
                  setForkAutoGenerate(isAuto);
                }}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="auto">Auto-generate in target project</SelectItem>
                  <SelectItem value="manual">Manual entry</SelectItem>
                </SelectContent>
              </Select>
            </div>
            {forkAutoGenerate ? (
              <div className="space-y-1">
                <Label>Bump strategy</Label>
                <Select value={forkBumpStrategy} onValueChange={(v) => setForkBumpStrategy(v as 'patch' | 'minor')}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="patch">Patch — next {forkPreviewNext || '…'}</SelectItem>
                    <SelectItem value="minor">Minor — next minor in target</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            ) : (
              <div className="space-y-1">
                <Label htmlFor="fork-version-id">Version ID (semantic)</Label>
                <Input
                  id="fork-version-id"
                  value={forkVersionId}
                  onChange={(e) => setForkVersionId(e.target.value)}
                  placeholder="e.g. 1.0.0"
                  autoComplete="off"
                />
              </div>
            )}
            <div className="space-y-1">
              <Label htmlFor="fork-short">Revision note</Label>
              <Input
                id="fork-short"
                value={forkDescription}
                onChange={(e) => setForkDescription(e.target.value)}
                placeholder="Short message"
                autoComplete="off"
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="fork-changelog">Changelog (optional)</Label>
              <Textarea
                id="fork-changelog"
                value={forkChangeLog}
                onChange={(e) => setForkChangeLog(e.target.value)}
                placeholder="Markdown release notes"
                rows={3}
                className="resize-y min-h-[72px]"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowForkDialog(false)} disabled={forkSaving}>
              Cancel
            </Button>
            <Button onClick={handleForkSubmit} disabled={forkSaving || !forkTargetProjectId}>
              {forkSaving ? 'Creating…' : 'Create fork'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={showBranchDialog} onOpenChange={(open) => !branchSaving && setShowBranchDialog(open)}>
        <DialogContent className="max-w-md" aria-describedby={undefined}>
          <DialogHeader>
            <DialogTitle>Create named branch</DialogTitle>
            <DialogDescription>
              Point a new branch name at this version snapshot in this project. Further work can advance the tip via merge workflows.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3 py-2">
            <div className="space-y-1">
              <Label htmlFor="branch-name">Branch name</Label>
              <Input
                id="branch-name"
                value={branchNameInput}
                onChange={(e) => setBranchNameInput(e.target.value)}
                placeholder="e.g. feature/payments"
                autoComplete="off"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowBranchDialog(false)} disabled={branchSaving}>
              Cancel
            </Button>
            <Button onClick={handleCreateBranchSubmit} disabled={branchSaving || !branchNameInput.trim()}>
              {branchSaving ? 'Saving…' : 'Create branch'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={showTagDialog} onOpenChange={(open) => !tagSaving && setShowTagDialog(open)}>
        <DialogContent className="max-w-md" aria-describedby={undefined}>
          <DialogHeader>
            <DialogTitle>Create version tag</DialogTitle>
            <DialogDescription>
              Attach a stable name to this schema revision (like <span className="font-mono">v1.0</span> or{' '}
              <span className="font-mono">stable</span>). Immutable tags cannot be moved or deleted afterward.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3 py-2">
            <div className="space-y-1">
              <Label htmlFor="tag-name">Tag name</Label>
              <Input
                id="tag-name"
                value={tagNameInput}
                onChange={(e) => setTagNameInput(e.target.value)}
                placeholder="e.g. v1.0.0 or stable"
                autoComplete="off"
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="tag-msg">Message (optional)</Label>
              <Input
                id="tag-msg"
                value={tagMessageInput}
                onChange={(e) => setTagMessageInput(e.target.value)}
                placeholder="Release notes or annotation"
                autoComplete="off"
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="tag-channel">Channel (optional)</Label>
              <Input
                id="tag-channel"
                value={tagChannelInput}
                onChange={(e) => setTagChannelInput(e.target.value)}
                placeholder="e.g. stable, beta"
                autoComplete="off"
              />
            </div>
            <label className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300 cursor-pointer">
              <input
                type="checkbox"
                checked={tagImmutable}
                onChange={(e) => setTagImmutable(e.target.checked)}
                className="rounded border-gray-300 dark:border-gray-600"
              />
              Lock tag (immutable — cannot move or delete)
            </label>
            {effectiveIsAdmin && (
              <label className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300 cursor-pointer">
                <input
                  type="checkbox"
                  checked={tagProtected}
                  onChange={(e) => setTagProtected(e.target.checked)}
                  className="rounded border-gray-300 dark:border-gray-600"
                />
                Protected (only tenant admins can move or delete)
              </label>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowTagDialog(false)} disabled={tagSaving}>
              Cancel
            </Button>
            <Button onClick={handleCreateTagSubmit} disabled={tagSaving || !tagNameInput.trim()}>
              {tagSaving ? 'Saving…' : 'Create tag'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={showMergeDialog}
        onOpenChange={(open) => {
          if (!open) setMergeCompat(null);
          if (!mergePreviewLoading && !mergeApplyLoading) setShowMergeDialog(open);
        }}
      >
        <DialogContent className="max-w-2xl" aria-describedby={undefined}>
          <DialogHeader>
            <DialogTitle>Merge branches</DialogTitle>
            <DialogDescription>
              Preview uses a three-way merge of OpenAPI components against the merge-base (LCA) revision. Apply creates a merge revision with two parents when the merge engine reports no conflicts.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3 py-2">
            <div className="space-y-1">
              <Label>Source branch</Label>
              <Select value={mergeSourceBranch || '__pick__'} onValueChange={(v) => setMergeSourceBranch(v === '__pick__' ? '' : v)}>
                <SelectTrigger><SelectValue placeholder="Choose branch" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="__pick__">Choose branch</SelectItem>
                  {versionBranches.map((b) => (
                    <SelectItem key={b.id} value={b.name}>{b.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label>Target branch</Label>
              <Select value={mergeTargetBranch || '__pick__'} onValueChange={(v) => setMergeTargetBranch(v === '__pick__' ? '' : v)}>
                <SelectTrigger><SelectValue placeholder="Choose branch" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="__pick__">Choose branch</SelectItem>
                  {versionBranches.map((b) => (
                    <SelectItem key={`t-${b.id}`} value={b.name}>{b.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            {mergePreviewData?.classification && (
              <Alert variant={mergePreviewData.classification.canAutoMerge ? 'success' : 'error'}>
                {mergePreviewData.classification.canAutoMerge
                  ? 'No overlapping modified or removed paths — apply is allowed if the target tip has not moved.'
                  : `Conflicts: ${mergePreviewData.classification.conflictPaths.length} path(s). Apply is blocked.`}
              </Alert>
            )}
            {mergePreviewData?.classification &&
              !mergePreviewData.classification.canAutoMerge &&
              mergeConflictGroups.length > 0 && (
                <div className="rounded-md border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/40 p-3 max-h-56 overflow-y-auto">
                  <p className="text-xs font-semibold text-gray-800 dark:text-gray-200 mb-2">
                    Conflict paths (grouped by class, same IDs as Schema Changes)
                  </p>
                  <ul className="space-y-2 text-xs">
                    {mergeConflictGroups.map((g) => (
                      <li key={g.className}>
                        <span className="font-mono font-medium text-gray-900 dark:text-gray-100">{g.className}</span>
                        <ul className="mt-1 ml-2 space-y-0.5 pl-2 border-l border-gray-300 dark:border-gray-600">
                          {g.paths.map((p) => (
                            <li key={p} className="font-mono text-[11px] text-gray-700 dark:text-gray-300 break-all">
                              {p}
                            </li>
                          ))}
                        </ul>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            {mergePreviewData?.mergeBaseVersionId != null && mergePreviewData?.classification && (
              <p className="text-xs text-gray-500 dark:text-gray-400">
                Merge-base revision: <span className="font-mono">{mergePreviewData.mergeBaseVersionId}</span>
              </p>
            )}
            {mergeCompatLoading && (
              <p className="text-xs text-gray-500 dark:text-gray-400">Checking backward compatibility (target tip → source tip)…</p>
            )}
            {mergeCompat && !mergeCompatLoading && (
              <Alert
                variant={
                  mergeCompat.overall === 'safe'
                    ? 'success'
                    : mergeCompat.overall === 'unknown'
                      ? 'default'
                      : 'error'
                }
              >
                <span className="font-medium text-sm">Backward compatibility: {mergeCompat.overall}</span>
                <p className="text-xs text-gray-600 dark:text-gray-400 mt-1">
                  Compares generated OpenAPI for <strong>target tip</strong> (base) vs <strong>source tip</strong> (head). Merge execution uses the three-way engine plus optional project compat gate on the merged result.
                </p>
                {mergeCompat.findings.length > 0 && (
                  <ul className="mt-2 text-xs list-disc pl-4 max-h-36 overflow-y-auto space-y-0.5">
                    {mergeCompat.findings.slice(0, 14).map((f) => (
                      <li key={f.id ?? `${f.path}-${f.rule}-${f.message}`}>
                        <span className="font-mono text-[11px]">{f.path}</span>
                        {' — '}
                        {f.message}
                      </li>
                    ))}
                  </ul>
                )}
                {mergeCompat.breakingChangeDocumentationIssueUrl && (
                  <a
                    href={mergeCompat.breakingChangeDocumentationIssueUrl}
                    target="_blank"
                    rel="noreferrer"
                    className="text-xs underline mt-2 inline-block text-blue-600 dark:text-blue-400"
                  >
                    Breaking changes documentation (#746)
                  </a>
                )}
                {mergeCompat.mergeBlockedByCompatGate && (
                  <p className="text-xs mt-2 text-amber-800 dark:text-amber-200">
                    Project metadata enables compat gating — merge is blocked until compatibility is safe or policy is updated.
                  </p>
                )}
              </Alert>
            )}
          </div>
          <DialogFooter className="gap-2 flex-wrap">
            <Button variant="outline" onClick={() => setShowMergeDialog(false)} disabled={mergePreviewLoading || mergeApplyLoading}>
              Close
            </Button>
            <Button variant="secondary" onClick={runMergePreview} disabled={mergePreviewLoading || mergeApplyLoading || !mergeSourceBranch || !mergeTargetBranch}>
              {mergePreviewLoading ? 'Previewing…' : 'Preview merge'}
            </Button>
            <Button
              onClick={runMergeApply}
              disabled={
                mergeApplyLoading ||
                mergePreviewLoading ||
                mergeCompatLoading ||
                !mergeSourceBranch ||
                !mergeTargetBranch ||
                mergePreviewData?.classification?.canAutoMerge === false ||
                mergeCompat?.mergeBlockedByCompatGate === true
              }
            >
              {mergeApplyLoading ? 'Merging…' : 'Apply merge'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={showRollbackDialog}
        onOpenChange={(open) => {
          if (!rollbackPreviewLoading && !rollbackApplyLoading) {
            setShowRollbackDialog(open);
            if (!open) setRollbackPreview(null);
          }
        }}
      >
        <DialogContent className="max-w-2xl" aria-describedby={undefined}>
          <DialogHeader>
            <DialogTitle>Rollback branch (revert-style)</DialogTitle>
            <DialogDescription>
              Creates a <strong>new</strong> revision whose schema matches the selected row; the branch tip moves forward
              with <span className="font-mono">parent</span> pointing at the prior head. History is not rewritten.
              {rollbackTargetVersion ? (
                <span className="block mt-2 text-gray-700 dark:text-gray-300">
                  Restore snapshot from <span className="font-mono">v{rollbackTargetVersion.version_id}</span>
                </span>
              ) : null}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3 py-2">
            <div className="space-y-1">
              <Label>Branch to update</Label>
              <Select
                value={rollbackBranchName || '__pick__'}
                onValueChange={(v) => setRollbackBranchName(v === '__pick__' ? '' : v)}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Choose branch" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__pick__">Choose branch</SelectItem>
                  {versionBranches.map((b) => (
                    <SelectItem key={`rb-${b.id}`} value={b.name}>
                      {b.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label htmlFor="rollback-msg">Revision note (optional)</Label>
              <Input
                id="rollback-msg"
                value={rollbackShortMessage}
                onChange={(e) => setRollbackShortMessage(e.target.value)}
                placeholder="Defaults to a rollback summary"
                autoComplete="off"
              />
            </div>
            {rollbackPreview && (
              <>
                <Alert
                  variant={
                    rollbackPreview.compatOverall === 'safe'
                      ? 'success'
                      : rollbackPreview.compatOverall === 'unknown'
                        ? 'default'
                        : 'error'
                  }
                >
                  <span className="font-medium text-sm">
                    Schema impact (current tip → restored content): {rollbackPreview.compatOverall ?? '—'}
                  </span>
                  <p className="text-xs text-gray-600 dark:text-gray-400 mt-1">
                    Same compatibility rules as elsewhere (#506): rolling back can remove paths or fields consumers rely on.
                  </p>
                  {(rollbackPreview.findings ?? []).length > 0 && (
                    <ul className="mt-2 text-xs list-disc pl-4 max-h-36 overflow-y-auto space-y-0.5">
                      {(rollbackPreview.findings ?? []).slice(0, 14).map((f) => (
                        <li key={f.id ?? `${f.path}-${f.message}`}>
                          <span className="font-mono text-[11px]">{f.path}</span>
                          {' — '}
                          {f.message}
                        </li>
                      ))}
                    </ul>
                  )}
                  {rollbackPreview.breakingChangeDocumentationIssueUrl ? (
                    <a
                      href={rollbackPreview.breakingChangeDocumentationIssueUrl}
                      target="_blank"
                      rel="noreferrer"
                      className="text-xs underline mt-2 inline-block text-blue-600 dark:text-blue-400"
                    >
                      Breaking changes documentation (#746)
                    </a>
                  ) : null}
                </Alert>
                {rollbackPreview.rollbackBlockedByCompatGate ? (
                  <p className="text-xs text-amber-800 dark:text-amber-200">
                    Project metadata sets <span className="font-mono">compatGateOnRollback</span> — apply is blocked until the
                    rollback pair is safe or policy is updated.
                  </p>
                ) : null}
                {(rollbackPreview.deprecationWarnings ?? []).length > 0 ? (
                  <p className="text-xs text-gray-600 dark:text-gray-400">
                    Deprecation warnings: {(rollbackPreview.deprecationWarnings ?? []).length} (see compatibility API / sunset
                    timeline)
                  </p>
                ) : null}
                {rollbackPreview.compatOverall && rollbackPreview.compatOverall !== 'safe' ? (
                  <label className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={rollbackSkipCompat}
                      onChange={(e) => setRollbackSkipCompat(e.target.checked)}
                      className="rounded border-gray-300 dark:border-gray-600"
                    />
                    I understand this rollback may break existing consumers; proceed anyway
                  </label>
                ) : null}
              </>
            )}
          </div>
          <DialogFooter className="gap-2 flex-wrap">
            <Button
              variant="outline"
              onClick={() => setShowRollbackDialog(false)}
              disabled={rollbackPreviewLoading || rollbackApplyLoading}
            >
              Close
            </Button>
            <Button
              variant="secondary"
              onClick={() => void runRollbackPreview()}
              disabled={rollbackPreviewLoading || rollbackApplyLoading || !rollbackBranchName || !rollbackTargetVersion}
            >
              {rollbackPreviewLoading ? 'Previewing…' : 'Preview impact'}
            </Button>
            <Button
              onClick={() => void runRollbackApply()}
              disabled={
                rollbackApplyLoading ||
                rollbackPreviewLoading ||
                !rollbackPreview?.branchTipRevisionId ||
                rollbackPreview.rollbackBlockedByCompatGate === true ||
                (Boolean(rollbackPreview.compatOverall) &&
                  rollbackPreview.compatOverall !== 'safe' &&
                  !rollbackSkipCompat)
              }
            >
              {rollbackApplyLoading ? 'Applying…' : 'Apply rollback'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Relationship graph (#322) */}
      <RelationshipGraphDialog
        open={showRelationshipGraphDialog}
        onOpenChange={setShowRelationshipGraphDialog}
        version={relationshipGraphVersion}
        projectName={projects.find(p => p.id === relationshipGraphVersion?.project_id)?.name ?? ''}
        classesWithProperties={relationshipGraphClasses}
        isLoading={isLoadingRelationshipGraph}
      />
    </>
  );
};

export default Versions;

