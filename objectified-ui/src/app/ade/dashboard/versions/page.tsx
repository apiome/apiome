'use client';

import { useSession } from 'next-auth/react';
import { useEffect, useState, useRef } from 'react';
import { Plus, Edit2, Trash2, Package, AlertCircle, Lock, Unlock, CheckCircle, Eye, Copy, MoreVertical, Network, Snowflake, GitBranch, GitMerge } from 'lucide-react';
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
  createVersion,
  updateVersion,
  deleteVersion,
  getClassesForVersion,
  getPropertiesForClass,
  getTenantsAdministratedByUser
} from '../../../../../lib/db/helper';
import { generateOpenApiSpec } from '../../../utils/openapi';
import YAML from 'yaml';
import { diffLines, Change } from 'diff';
import { compareSchemas, type DiffSummary, getPathLabel } from '../../../../../lib/schema-diff';
import RelationshipGraphDialog from './RelationshipGraphDialog';
import { toast } from 'sonner';

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

interface Project { id: string; name: string; slug: string; }

interface Version {
  id: string;
  project_id: string;
  creator_id: string;
  version_id: string;
  description: string | null;
  change_log: string | null;
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
}

interface VersionBranchRow {
  id: string;
  name: string;
  tip_version_id: string;
  tip_version_string?: string;
  created_at?: string;
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
  const [selectedVersion, setSelectedVersion] = useState<Version | null>(null);
  const [versionId, setVersionId] = useState('');
  const [autoGenerate, setAutoGenerate] = useState(true);
  const [bumpStrategy, setBumpStrategy] = useState<'patch' | 'minor'>('patch');
  const [nextAutoVersion, setNextAutoVersion] = useState<string>('');
  const [description, setDescription] = useState('');
  const [changeLog, setChangeLog] = useState('');
  const [enabled, setEnabled] = useState(true);
  const [sourceVersionId, setSourceVersionId] = useState<string>('');
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
  const [diffViewMode, setDiffViewMode] = useState<'overlay' | 'side-by-side'>('overlay');
  const [diffFilter, setDiffFilter] = useState<{
    showAdded: boolean;
    showRemoved: boolean;
    showModified: boolean;
  }>({ showAdded: true, showRemoved: true, showModified: true });
  const [activeCompareTab, setActiveCompareTab] = useState<'diff' | 'summary'>('diff');

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

  useEffect(() => { if (currentTenantId) loadProjects(); }, [currentTenantId]);
  useEffect(() => { if (selectedProjectId) loadVersions(); else setVersions([]); }, [selectedProjectId]);

  const loadBranches = async () => {
    if (!selectedProjectId) return;
    try {
      const r = await fetch(`/api/projects/${selectedProjectId}/version-branches`);
      const d = await r.json();
      if (d.success && Array.isArray(d.branches)) setVersionBranches(d.branches);
      else setVersionBranches([]);
    } catch {
      setVersionBranches([]);
    }
  };

  useEffect(() => {
    if (selectedProjectId) loadBranches();
    else setVersionBranches([]);
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
      const response = await fetch(`/api/versions?projectId=${selectedProjectId}`);
      if (!response.ok) {
        throw new Error(`Failed to fetch versions: ${response.statusText}`);
      }
      const data = await response.json();
      if (data.success && data.versions) {
        setVersions(data.versions);
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
    setChangeLog(''); setEnabled(true); setSourceVersionId('');
    setErrorMessage(''); setShowCreateDialog(true);
  };

  const handleCreateSubmit = async () => {
    if (!autoGenerate && !versionId.trim()) { setErrorMessage('Version ID is required when not auto-generating'); return; }
    if (!description.trim()) { setErrorMessage('Description is required'); return; }
    setIsLoading(true); setErrorMessage('');
    try {
      const result = await createVersion(selectedProjectId, currentUserId, autoGenerate ? null : versionId, description, changeLog, sourceVersionId || null, autoGenerate ? bumpStrategy : undefined);
      const response = JSON.parse(result);
      if (response.success) {
        setShowCreateDialog(false);
        await loadVersions();
        if (response.copiedClasses > 0) toast.success(`Version created! Copied ${response.copiedClasses} class(es).`);
        else if (response.copyWarning) toast.warning(`Version created, but: ${response.copyWarning}`);
      } else setErrorMessage(response.error || 'Failed to create version');
    } catch (error: any) { setErrorMessage(error.message || 'An error occurred'); }
    finally { setIsLoading(false); }
  };

  const handleEditClick = (version: Version) => {
    if (version.published) { setErrorMessage('Cannot edit published version'); return; }
    setSelectedVersion(version); setVersionId(version.version_id);
    setDescription(version.description || ''); setChangeLog(version.change_log || '');
    setEnabled(version.enabled); setErrorMessage(''); setShowEditDialog(true);
  };

  const handleEditSubmit = async () => {
    if (!selectedVersion) return;
    if (!description.trim()) { setErrorMessage('Description is required'); return; }
    setIsLoading(true); setErrorMessage('');
    try {
      const result = await updateVersion(selectedVersion.id, description, changeLog, enabled);
      const response = JSON.parse(result);
      if (response.success) { setShowEditDialog(false); await loadVersions(); }
      else setErrorMessage(response.error || 'Failed to update version');
    } catch (error: any) { setErrorMessage(error.message || 'An error occurred'); }
    finally { setIsLoading(false); }
  };

  const handlePublishClick = (versionRecordId: string) => {
    const ver = versions.find(v => v.id === versionRecordId);
    if (!ver) return;
    if (ver.creator_id !== currentUserId && !effectiveIsAdmin) return;
    setPublishVersionId(versionRecordId);
    setPublishVisibility('private');
    setShowPublishDialog(true);
  };

  const handlePublishConfirm = async () => {
    if (!publishVersionId) return;
    const version = versions.find((v) => v.id === publishVersionId);
    if (!version) {
      await alertDialog({ message: 'Version not found', variant: 'error' });
      return;
    }
    try {
      const res = await fetch(`/api/versions/${publishVersionId}/publish`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ projectId: version.project_id, visibility: publishVisibility }),
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
      const response = JSON.parse(result);
      if (response.success) await loadVersions();
      else await alertDialog({ message: response.error || 'Failed to delete', variant: 'error' });
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
      const spec = await generateOpenApiSpec(classesWithProperties, { projectName: project?.name, version: version.version_id, description: version.description || undefined });
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
    return generateOpenApiSpec(classesWithProperties, { projectName: project?.name, version: version.version_id, description: version.description || undefined });
  };

  const handleCompareVersions = async () => {
    if (!compareVersion1Id || !compareVersion2Id) { toast.warning('Please select two versions'); return; }
    if (compareVersion1Id === compareVersion2Id) { toast.warning('Select two different versions'); return; }
    setIsLoadingComparison(true);
    try {
      const [spec1, spec2] = await Promise.all([loadVersionSpec(compareVersion1Id), loadVersionSpec(compareVersion2Id)]);
      setCompareSpec1(spec1); setCompareSpec2(spec2);

      // Perform schema-aware diff
      const diffSummary = compareSchemas(spec1, spec2);
      setSchemaDiffSummary(diffSummary);

      // Also keep line-based diff for fallback
      const content1 = compareFormat === 'json' ? spec1 : YAML.stringify(JSON.parse(spec1));
      const content2 = compareFormat === 'json' ? spec2 : YAML.stringify(JSON.parse(spec2));
      setDiffResult(diffLines(content1, content2));
    } catch (error) {
      console.error('Comparison error:', error);
      await alertDialog({ message: 'Failed to load specs for comparison', variant: 'error' });
    }
    finally { setIsLoadingComparison(false); }
  };

  const handleCompareDialogOpen = () => {
    setShowCompareDialog(true); setCompareVersion1Id(''); setCompareVersion2Id('');
    setCompareSpec1(''); setCompareSpec2(''); setCompareFormat('json');
    setDiffResult([]); setSchemaDiffSummary(null); setDiffViewMode('overlay');
  };

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
      case 'delete': await handleDelete(version.id); break;
      case 'branchFrom':
        setBranchFromVersionId(version.id);
        setBranchNameInput('');
        setShowBranchDialog(true);
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
        if (r.status === 409 && d.code === 'MERGE_CONFLICT') {
          toast.error('Merge blocked: overlapping changes. Resolve conflicts using a future merge flow.');
          setMergePreviewData((prev) => ({
            ...prev,
            classification: {
              canAutoMerge: false,
              conflictPaths: d.conflictPaths ?? [],
              addedSchemaNames: prev?.classification?.addedSchemaNames ?? [],
            },
          }));
        } else {
          toast.error(typeof d.error === 'string' ? d.error : 'Merge failed');
        }
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Merge failed');
    } finally {
      setMergeApplyLoading(false);
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
                  setShowMergeDialog(true);
                }}
                disabled={!selectedProjectId || versionBranches.length < 2}
                title={versionBranches.length < 2 ? 'Create at least two named branches to merge' : undefined}
              >
                <GitMerge className="h-4 w-4 mr-2" />
                Merge branches
              </Button>
              <Button onClick={handleCreateClick} disabled={!selectedProjectId}>
                <Plus className="h-4 w-4 mr-2" />
                Add Version
              </Button>
            </div>
          </div>
        </div>
      </header>

      <main className="flex-1 overflow-y-auto p-6">
        <div className="max-w-7xl mx-auto space-y-6">
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
                {(effectiveIsAdmin || b.created_by === currentUserId) && (
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
            Use &quot;Branch from here&quot; on a version row to create a pointer. Merge uses optimistic concurrency on the target tip (
            <code className="text-xs">baseRevisionId</code>).
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
      ) : (
        <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-sm border border-gray-100 dark:border-gray-700 overflow-hidden">
          <table className="min-w-full divide-y divide-gray-100 dark:divide-gray-700">
            <thead className="bg-gradient-to-r from-gray-50 to-slate-50 dark:from-gray-900 dark:to-gray-800">
              <tr>
                <th className="px-6 py-4 text-left text-xs font-bold text-gray-500 dark:text-gray-400 uppercase tracking-wider">Version</th>
                <th className="px-6 py-4 text-left text-xs font-bold text-gray-500 dark:text-gray-400 uppercase tracking-wider">Description</th>
                <th className="px-6 py-4 text-left text-xs font-bold text-gray-500 dark:text-gray-400 uppercase tracking-wider">Status</th>
                <th className="px-6 py-4 text-left text-xs font-bold text-gray-500 dark:text-gray-400 uppercase tracking-wider">Created By</th>
                <th className="px-6 py-4 text-left text-xs font-bold text-gray-500 dark:text-gray-400 uppercase tracking-wider">Created</th>
                <th className="px-6 py-4 text-right text-xs font-bold text-gray-500 dark:text-gray-400 uppercase tracking-wider">Actions</th>
              </tr>
            </thead>
            <tbody className="bg-white dark:bg-gray-800 divide-y divide-gray-100 dark:divide-gray-700">
              {versions.map((version) => (
                <tr key={version.id} className="hover:bg-emerald-50/50 dark:hover:bg-emerald-900/10 transition-all duration-200">
                  <td className="px-6 py-4 whitespace-nowrap">
                    <div className="flex items-center gap-2">
                      <div className="text-sm font-bold text-gray-900 dark:text-white font-mono">v{version.version_id}</div>
                      {version.published && <div title="Published" className="p-1 bg-blue-100 dark:bg-blue-900/30 rounded"><Lock className="h-3.5 w-3.5 text-blue-600 dark:text-blue-400" /></div>}
                    </div>
                  </td>
                  <td className="px-6 py-4">
                    <div className="text-sm text-gray-900 dark:text-white max-w-xs truncate">{version.description || '—'}</div>
                    {version.change_log && <div className="text-xs text-gray-500 dark:text-gray-400 mt-1 max-w-xs truncate">{version.change_log}</div>}
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
                              <div className="border-t border-gray-200 dark:border-gray-700 my-1" />
                              <button
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setOpenVersionDropdown(null);
                                  handleRowAction('delete', version);
                                }}
                                className="w-full px-4 py-2 text-left text-sm hover:bg-red-50 dark:hover:bg-red-900/20 flex items-center gap-3 text-red-600 dark:text-red-400 hover:text-red-700 dark:hover:text-red-300 transition-colors"
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
      )}
        </div>
      </main>

      {/* Create Version Dialog */}
      <Dialog open={showCreateDialog} onOpenChange={(open) => !isLoading && setShowCreateDialog(open)}>
        <DialogContent className="max-w-lg" aria-describedby={undefined}>
          <DialogHeader><DialogTitle>Create New Version</DialogTitle></DialogHeader>
          <div className="space-y-4 py-4">
            {errorMessage && <Alert variant="error">{errorMessage}</Alert>}
            <div className="space-y-2">
              <Label>Copy From Version</Label>
              <Select
                value={sourceVersionId || '__blank__'}
                onValueChange={(val) => setSourceVersionId(val === '__blank__' ? '' : val)}
              >
                <SelectTrigger><SelectValue placeholder={versions.length === 0 ? 'No versions available' : 'Create blank version'} /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="__blank__">Create blank version</SelectItem>
                  {versions.map((v) => <SelectItem key={v.id} value={v.id}>{v.published ? '🔒 ' : ''}v{v.version_id} - {v.description || 'No description'}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            {sourceVersionId && <Alert variant="info">Classes and properties will be copied from the selected version.</Alert>}
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
              <Label>Description *</Label>
              <Input value={description} onChange={(e) => setDescription(e.target.value)} disabled={isLoading} />
            </div>
            <div className="space-y-2">
              <Label>Change Log</Label>
              <Textarea value={changeLog} onChange={(e) => setChangeLog(e.target.value)} rows={3} disabled={isLoading} />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowCreateDialog(false)} disabled={isLoading}>Cancel</Button>
            <Button onClick={handleCreateSubmit} disabled={isLoading}>{isLoading ? 'Creating...' : 'Create Version'}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Edit Version Dialog */}
      <Dialog open={showEditDialog} onOpenChange={(open) => !isLoading && setShowEditDialog(open)}>
        <DialogContent aria-describedby={undefined}>
          <DialogHeader><DialogTitle>Edit Version</DialogTitle></DialogHeader>
          <div className="space-y-4 py-4">
            {errorMessage && <Alert variant="error">{errorMessage}</Alert>}
            <div className="space-y-2">
              <Label>Version ID</Label>
              <Input value={versionId} disabled className="font-mono" />
            </div>
            <div className="space-y-2">
              <Label>Description *</Label>
              <Input value={description} onChange={(e) => setDescription(e.target.value)} disabled={isLoading} autoFocus />
            </div>
            <div className="space-y-2">
              <Label>Change Log</Label>
              <Textarea value={changeLog} onChange={(e) => setChangeLog(e.target.value)} rows={4} disabled={isLoading} />
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
            </DialogTitle>
          </DialogHeader>
          <div className="flex-1 overflow-y-auto overflow-x-hidden">
            {diffResult.length === 0 ? (
              <div className="space-y-4 p-4">
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label>Version 1 (Base)</Label>
                    <Select value={compareVersion1Id} onValueChange={setCompareVersion1Id}>
                      <SelectTrigger><SelectValue placeholder="Select version..." /></SelectTrigger>
                      <SelectContent>{versions.map((v) => <SelectItem key={v.id} value={v.id}>{v.published ? '🔒 ' : ''}v{v.version_id}</SelectItem>)}</SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-2">
                    <Label>Version 2 (Compare To)</Label>
                    <Select value={compareVersion2Id} onValueChange={setCompareVersion2Id}>
                      <SelectTrigger><SelectValue placeholder="Select version..." /></SelectTrigger>
                      <SelectContent>{versions.map((v) => <SelectItem key={v.id} value={v.id}>{v.published ? '🔒 ' : ''}v{v.version_id}</SelectItem>)}</SelectContent>
                    </Select>
                  </div>
                </div>
                <div className="flex justify-center py-8">
                  <Button onClick={handleCompareVersions} disabled={!compareVersion1Id || !compareVersion2Id || isLoadingComparison}>{isLoadingComparison ? 'Loading...' : 'Compare Versions'}</Button>
                </div>
              </div>
            ) : (
              <div className="flex flex-col h-full">
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
                          {schemaDiffSummary.added.length + schemaDiffSummary.removed.length + schemaDiffSummary.modified.length}
                        </span>
                      )}
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
                ) : (
                  // Schema Changes Summary Tab
                  <div className="h-[calc(90vh-280px)] overflow-y-auto">
                    {schemaDiffSummary && (
                  <div className="p-4 bg-gray-50 dark:bg-gray-900 rounded-lg border border-gray-200 dark:border-gray-700">
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
                )}
              </div>
            )}
          </div>
          <DialogFooter className="flex-shrink-0">
            {diffResult.length > 0 && <Button variant="outline" onClick={() => { setDiffResult([]); setCompareSpec1(''); setCompareSpec2(''); }}>Compare Different Versions</Button>}
            <Button variant="outline" onClick={() => setShowCompareDialog(false)}>Close</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={showBranchDialog} onOpenChange={(open) => !branchSaving && setShowBranchDialog(open)}>
        <DialogContent className="max-w-md" aria-describedby={undefined}>
          <DialogHeader>
            <DialogTitle>Create named branch</DialogTitle>
            <DialogDescription>
              Point a new branch name at this version snapshot. Further work can advance the tip via merge workflows.
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

      <Dialog open={showMergeDialog} onOpenChange={(open) => !mergePreviewLoading && !mergeApplyLoading && setShowMergeDialog(open)}>
        <DialogContent className="max-w-lg" aria-describedby={undefined}>
          <DialogHeader>
            <DialogTitle>Merge branches</DialogTitle>
            <DialogDescription>
              Preview compares branch tips (merge-base from #2593 not yet applied). Apply creates a merge revision with two parents when there are no overlapping schema conflicts.
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
            {mergePreviewData?.mergeBaseVersionId === null && mergePreviewData?.classification && (
              <p className="text-xs text-gray-500 dark:text-gray-400">Merge-base (LCA) is not computed yet (#2593); preview uses two-way diff between tips.</p>
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
                !mergeSourceBranch ||
                !mergeTargetBranch ||
                mergePreviewData?.classification?.canAutoMerge === false
              }
            >
              {mergeApplyLoading ? 'Merging…' : 'Apply merge'}
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

