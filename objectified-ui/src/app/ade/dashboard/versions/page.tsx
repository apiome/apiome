'use client';

import { useSession } from 'next-auth/react';
import { useEffect, useState, useRef } from 'react';
import { Plus, Edit2, Trash2, Package, AlertCircle, Lock, Unlock, CheckCircle, Eye, Copy, MoreVertical } from 'lucide-react';
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
import { Textarea } from '../../../components/ui/Textarea';
import { Badge } from '../../../components/ui/Badge';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../../../components/ui/Select';
import { useDialog } from '../../../components/providers/DialogProvider';
import {
  getProjectsForTenant,
  getVersionsForProject,
  createVersion,
  updateVersion,
  deleteVersion,
  publishVersion,
  unpublishVersion,
  getClassesForVersion,
  getPropertiesForClass,
  getTenantsAdministratedByUser
} from '../../../../../lib/db/helper';
import { generateOpenApiSpec } from '../../../utils/openapi';
import YAML from 'yaml';
import { diffLines, Change } from 'diff';

const Editor = dynamic(() => import('@monaco-editor/react'), {
  ssr: false,
  loading: () => <div className="h-full flex items-center justify-center"><div className="text-gray-500 dark:text-gray-400">Loading editor...</div></div>,
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
}

const Versions = () => {
  const { data: session } = useSession();
  const { confirm: confirmDialog, alert: alertDialog } = useDialog();
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<string>('');
  const [versions, setVersions] = useState<Version[]>([]);
  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [showEditDialog, setShowEditDialog] = useState(false);
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
  const [diffViewMode, setDiffViewMode] = useState<'overlay' | 'side-by-side'>('overlay');

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

  const loadProjects = async () => {
    if (!currentTenantId) return;
    try {
      const result = await getProjectsForTenant(currentTenantId);
      const projectsData = JSON.parse(result);
      setProjects(projectsData);
      if (projectsData.length > 0 && !selectedProjectId) setSelectedProjectId(projectsData[0].id);
    } catch (error) { console.error('Failed to load projects:', error); }
  };

  const loadVersions = async () => {
    if (!selectedProjectId) return;
    try {
      const result = await getVersionsForProject(selectedProjectId);
      setVersions(JSON.parse(result));
    } catch (error) { console.error('Failed to load versions:', error); }
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
        if (response.copiedClasses > 0) await alertDialog({ message: `Version created! Copied ${response.copiedClasses} class(es).`, variant: 'success' });
        else if (response.copyWarning) await alertDialog({ message: `Version created, but: ${response.copyWarning}`, variant: 'warning' });
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

  const handlePublish = async (versionRecordId: string) => {
    const ver = versions.find(v => v.id === versionRecordId);
    if (!ver) { await alertDialog({ message: 'Version not found', variant: 'error' }); return; }
    if (ver.creator_id !== currentUserId && !effectiveIsAdmin) { await alertDialog({ message: 'Only owner or admin can publish', variant: 'warning' }); return; }
    const confirmed = await confirmDialog({ title: 'Publish Version', message: 'Once published, it cannot be edited.', variant: 'info', confirmLabel: 'Publish', cancelLabel: 'Cancel' });
    if (!confirmed) return;
    try {
      const result = await publishVersion(versionRecordId, currentUserId);
      const response = JSON.parse(result);
      if (response.success) await loadVersions();
      else await alertDialog({ message: response.error || 'Failed to publish', variant: 'error' });
    } catch (error: any) { await alertDialog({ message: error.message || 'An error occurred', variant: 'error' }); }
  };

  const handleUnpublish = async (versionRecordId: string) => {
    const ver = versions.find(v => v.id === versionRecordId);
    if (!ver) { await alertDialog({ message: 'Version not found', variant: 'error' }); return; }
    if (ver.creator_id !== currentUserId && !effectiveIsAdmin) { await alertDialog({ message: 'Only owner or admin can unpublish', variant: 'warning' }); return; }
    const confirmed = await confirmDialog({ title: 'Unpublish Version', message: 'Best practice is to keep it published. Are you sure?', variant: 'danger', confirmLabel: 'Unpublish', cancelLabel: 'Cancel' });
    if (!confirmed) return;
    try {
      const result = await unpublishVersion(versionRecordId, currentUserId);
      const response = JSON.parse(result);
      if (response.success) await loadVersions();
      else await alertDialog({ message: response.error || 'Failed to unpublish', variant: 'error' });
    } catch (error: any) { await alertDialog({ message: error.message || 'An error occurred', variant: 'error' }); }
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
    if (!compareVersion1Id || !compareVersion2Id) { await alertDialog({ message: 'Please select two versions', variant: 'warning' }); return; }
    if (compareVersion1Id === compareVersion2Id) { await alertDialog({ message: 'Select two different versions', variant: 'warning' }); return; }
    setIsLoadingComparison(true);
    try {
      const [spec1, spec2] = await Promise.all([loadVersionSpec(compareVersion1Id), loadVersionSpec(compareVersion2Id)]);
      setCompareSpec1(spec1); setCompareSpec2(spec2);
      const content1 = compareFormat === 'json' ? spec1 : YAML.stringify(JSON.parse(spec1));
      const content2 = compareFormat === 'json' ? spec2 : YAML.stringify(JSON.parse(spec2));
      setDiffResult(diffLines(content1, content2));
    } catch (error) { await alertDialog({ message: 'Failed to load specs for comparison', variant: 'error' }); }
    finally { setIsLoadingComparison(false); }
  };

  const handleCompareDialogOpen = () => {
    setShowCompareDialog(true); setCompareVersion1Id(''); setCompareVersion2Id('');
    setCompareSpec1(''); setCompareSpec2(''); setCompareFormat('json');
    setDiffResult([]); setDiffViewMode('overlay');
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

  const formatDate = (dateString: string) => new Date(dateString).toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  const canModify = (version: Version) => version.creator_id === currentUserId || !!effectiveIsAdmin;

  const handleRowAction = async (action: string, version: Version) => {
    const isPublished = !!version.published;
    const canPub = !isPublished && canModify(version);
    const canUnpub = isPublished && canModify(version);
    switch (action) {
      case 'view': await handleViewOpenApi(version); break;
      case 'edit': if (!isPublished) handleEditClick(version); else setErrorMessage('Cannot edit published version'); break;
      case 'publish': if (canPub) await handlePublish(version.id); else await alertDialog({ message: 'Only owner or admin can publish', variant: 'warning' }); break;
      case 'unpublish': if (canUnpub) await handleUnpublish(version.id); else await alertDialog({ message: 'Only owner or admin can unpublish', variant: 'warning' }); break;
      case 'delete': await handleDelete(version.id); break;
    }
  };

  if (!session) return <div className="p-6"><p>Loading...</p></div>;

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
        <div className="relative">
          <div className="absolute -top-10 -left-10 w-40 h-40 bg-gradient-to-br from-indigo-100 to-purple-100 dark:from-indigo-900/20 dark:to-purple-900/20 rounded-full blur-3xl opacity-60" />
          <div className="absolute -bottom-10 -right-10 w-40 h-40 bg-gradient-to-br from-purple-100 to-pink-100 dark:from-purple-900/20 dark:to-pink-900/20 rounded-full blur-3xl opacity-60" />
          <div className="relative bg-white/80 dark:bg-gray-800/80 backdrop-blur-sm border border-gray-200/50 dark:border-gray-700/50 rounded-2xl p-16 text-center shadow-xl">
            <div className="w-20 h-20 mx-auto mb-6 bg-gradient-to-br from-indigo-500 to-purple-600 rounded-2xl flex items-center justify-center shadow-lg shadow-indigo-500/30">
              <Package className="h-10 w-10 text-white" />
            </div>
            <h3 className="text-2xl font-bold text-gray-900 dark:text-white mb-3">No Projects Available</h3>
            <p className="text-gray-500 dark:text-gray-400 max-w-md mx-auto mb-6">Please create a project before managing versions.</p>
            <Button asChild className="bg-gradient-to-r from-indigo-500 to-purple-600 hover:from-indigo-600 hover:to-purple-700">
              <a href="/ade/dashboard/projects">Go to Projects</a>
            </Button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex justify-between items-center mb-8">
        <div className="flex items-center gap-4">
          <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-emerald-500 to-teal-600 flex items-center justify-center shadow-lg shadow-emerald-500/25">
            <Package className="h-7 w-7 text-white" />
          </div>
          <div>
            <h1 className="text-3xl font-bold text-gray-900 dark:text-white tracking-tight">Versions</h1>
            <p className="text-gray-500 dark:text-gray-400 mt-1">Manage versions with semantic versioning</p>
          </div>
        </div>
        <div className="flex gap-3">
          <Select value={selectedProjectId} onValueChange={setSelectedProjectId}>
            <SelectTrigger className="w-56"><SelectValue placeholder="Select Project" /></SelectTrigger>
            <SelectContent>{projects.map((p) => <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>)}</SelectContent>
          </Select>
          <Button variant="secondary" onClick={handleCompareDialogOpen} disabled={!selectedProjectId || versions.length < 2} className="bg-gradient-to-r from-purple-500 to-indigo-500 hover:from-purple-600 hover:to-indigo-600 text-white">
            <Copy className="h-4 w-4" />Compare
          </Button>
          <Button onClick={handleCreateClick} disabled={!selectedProjectId} className="bg-gradient-to-r from-emerald-500 to-teal-500 hover:from-emerald-600 hover:to-teal-600">
            <Plus className="h-4 w-4" />New Version
          </Button>
        </div>
      </div>

      {/* Versions List */}
      {versions.length === 0 ? (
        <div className="relative">
          <div className="absolute -top-10 -left-10 w-40 h-40 bg-gradient-to-br from-emerald-100 to-teal-100 dark:from-emerald-900/20 dark:to-teal-900/20 rounded-full blur-3xl opacity-60" />
          <div className="absolute -bottom-10 -right-10 w-40 h-40 bg-gradient-to-br from-teal-100 to-cyan-100 dark:from-teal-900/20 dark:to-cyan-900/20 rounded-full blur-3xl opacity-60" />
          <div className="relative bg-white/80 dark:bg-gray-800/80 backdrop-blur-sm border border-gray-200/50 dark:border-gray-700/50 rounded-2xl p-16 text-center shadow-xl">
            <div className="w-20 h-20 mx-auto mb-6 bg-gradient-to-br from-emerald-500 to-teal-600 rounded-2xl flex items-center justify-center shadow-lg shadow-emerald-500/30">
              <Package className="h-10 w-10 text-white" />
            </div>
            <h3 className="text-2xl font-bold text-gray-900 dark:text-white mb-3">No Versions Yet</h3>
            <p className="text-gray-500 dark:text-gray-400 max-w-md mx-auto">Get started by creating your first version</p>
          </div>
        </div>
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
                            className="fixed w-48 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-lg shadow-lg z-20"
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

      {/* Create Version Dialog */}
      <Dialog open={showCreateDialog} onOpenChange={(open) => !isLoading && setShowCreateDialog(open)}>
        <DialogContent className="max-w-lg">
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
        <DialogContent>
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

      {/* OpenAPI Viewer Dialog */}
      <Dialog open={showOpenApiDialog} onOpenChange={setShowOpenApiDialog}>
        <DialogContent className="max-w-4xl max-h-[80vh]">
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
              <div className="h-full flex items-center justify-center"><div className="text-gray-500 dark:text-gray-400">Loading specification...</div></div>
            ) : (
              <Editor height="100%" language={openApiFormat} value={openApiFormat === 'json' ? openApiSpec : YAML.stringify(JSON.parse(openApiSpec || '{}'))} theme="vs-dark" options={{ readOnly: true, minimap: { enabled: true }, fontSize: 13 }} />
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowOpenApiDialog(false)}>Close</Button>
            <Button onClick={async () => { await navigator.clipboard.writeText(openApiFormat === 'json' ? openApiSpec : YAML.stringify(JSON.parse(openApiSpec))); await alertDialog({ message: 'Copied to clipboard!', variant: 'success' }); }} disabled={isLoadingSpec}>Copy</Button>
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
        <DialogContent className="max-w-6xl max-h-[90vh]">
          <DialogHeader>
            <DialogTitle className="flex items-center justify-between">
              <div>
                <div>Compare Version Schemas</div>
                <div className="text-sm text-gray-500 dark:text-gray-400 mt-1 font-normal">View differences between two version specifications</div>
              </div>
              {diffResult.length > 0 && (
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
          <div className="h-[70vh] overflow-auto">
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
              <div>
                <div className="flex items-center justify-between mb-2 pb-2 border-b border-gray-200 dark:border-gray-700">
                  <div className="flex gap-4 text-sm">
                    <div className="flex items-center gap-2"><div className="w-4 h-4 bg-red-200 dark:bg-red-900 border border-red-400"></div><span>Removed</span></div>
                    <div className="flex items-center gap-2"><div className="w-4 h-4 bg-green-200 dark:bg-green-900 border border-green-400"></div><span>Added</span></div>
                    <div className="flex items-center gap-2"><div className="w-4 h-4 bg-gray-100 dark:bg-gray-800 border border-gray-300"></div><span>Unchanged</span></div>
                  </div>
                  <div className="text-sm text-gray-600 dark:text-gray-400">v{versions.find(v => v.id === compareVersion1Id)?.version_id} → v{versions.find(v => v.id === compareVersion2Id)?.version_id}</div>
                </div>
                <div className="border border-gray-300 dark:border-gray-600 rounded overflow-auto font-mono text-xs" style={{ maxHeight: 'calc(70vh - 120px)' }}>
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
              </div>
            )}
          </div>
          <DialogFooter>
            {diffResult.length > 0 && <Button variant="outline" onClick={() => { setDiffResult([]); setCompareSpec1(''); setCompareSpec2(''); }}>Compare Different Versions</Button>}
            <Button variant="outline" onClick={() => setShowCompareDialog(false)}>Close</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default Versions;

