'use client';

import { useSession } from 'next-auth/react';
import { useEffect, useState, useRef } from 'react';
import { Plus, Edit2, Trash2, FolderOpen, Lock, Upload, AlertTriangle, MoreVertical, ExternalLink, Bot, FileEdit } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '../../../components/ui/Dialog';
import { Button } from '../../../components/ui/Button';
import { Input } from '../../../components/ui/Input';
import { Label } from '../../../components/ui/Label';
import { Alert } from '../../../components/ui/Alert';
import { Textarea } from '../../../components/ui/Textarea';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../../../components/ui/Select';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '../../../components/ui/Tabs';
import { createProject, updateProject, deleteProject, permanentDeleteProject } from '../../../../../lib/db/helper';
import OpenAPIImportDialog from '../../../components/ade/dashboard/OpenAPIImportDialog';
import ImportDialog from '../../../components/ade/dashboard/ImportDialog';
import { LLMChatPanel } from '../../../components/ade/dashboard/LLMImportDialog';
import { useDialog } from '../../../components/providers/DialogProvider';
import { filterSlugInput } from '../../../utils/slug';
import { SPDX_LICENSES, getLicenseUrl, SPDXLicense } from '../../../utils/spdx-licenses';

interface ProjectMetadata {
  summary?: string;
  termsOfService?: string;
  contact?: { name?: string; url?: string; email?: string };
  license?: { name?: string; identifier?: string; url?: string };
}

interface Project {
  id: string;
  tenant_id: string;
  creator_id: string;
  name: string;
  description: string;
  enabled: boolean;
  deleted_at: string | null;
  created_at: string;
  updated_at: string;
  creator_name: string;
  creator_email: string;
  metadata?: ProjectMetadata;
}

const Projects = () => {
  const { data: session } = useSession();
  const { confirm: confirmDialog, alert: alertDialog } = useDialog();
  const [projects, setProjects] = useState<Project[]>([]);
  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [createDialogTab, setCreateDialogTab] = useState<'manual' | 'ai'>('manual');
  const aiPanelRef = useRef<{ abort: () => void } | null>(null);
  const [showEditDialog, setShowEditDialog] = useState(false);
  const [showImportDialog, setShowImportDialog] = useState(false);
  const [showNewImportDialog, setShowNewImportDialog] = useState(false);
  const [importOpenedFromNewProjectAI, setImportOpenedFromNewProjectAI] = useState(false);
  const [pendingLLMSpec, setPendingLLMSpec] = useState<string | null>(null);
  const [selectedProject, setSelectedProject] = useState<Project | null>(null);
  const [projectName, setProjectName] = useState('');
  const [projectDescription, setProjectDescription] = useState('');
  const [projectSlug, setProjectSlug] = useState('');
  const [projectEnabled, setProjectEnabled] = useState(true);
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');
  // Dropdown state
  const [openProjectDropdown, setOpenProjectDropdown] = useState<string | null>(null);
  const [dropdownPosition, setDropdownPosition] = useState<{ top: number; right: number } | null>(null);

  // Metadata state
  const [metadataSummary, setMetadataSummary] = useState('');
  const [metadataTermsOfService, setMetadataTermsOfService] = useState('');
  const [metadataContactName, setMetadataContactName] = useState('');
  const [metadataContactUrl, setMetadataContactUrl] = useState('');
  const [metadataContactEmail, setMetadataContactEmail] = useState('');
  const [metadataLicenseName, setMetadataLicenseName] = useState('');
  const [metadataLicenseIdentifier, setMetadataLicenseIdentifier] = useState('');
  const [metadataLicenseUrl, setMetadataLicenseUrl] = useState('');

  const currentTenantId = (session?.user as any)?.current_tenant_id;
  const currentUserId = (session?.user as any)?.user_id;

  const generateSlug = (name: string) => {
    return name.toLowerCase().trim().replace(/[^a-z0-9\s-]/g, '').replace(/\s+/g, '-').replace(/-+/g, '-').replace(/^-|-$/g, '');
  };

  useEffect(() => {
    if (currentTenantId) loadProjects();
  }, [currentTenantId]);

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
      } else {
        throw new Error(data.error || 'Failed to load projects');
      }
    } catch (error) {
      console.error('Failed to load projects:', error);
      setProjects([]);
    }
  };

  const handleCreateClick = () => {
    setProjectName('');
    setProjectDescription('');
    setProjectSlug('');
    setProjectEnabled(true);
    setErrorMessage('');
    setCreateDialogTab('manual');
    setMetadataSummary('');
    setMetadataTermsOfService('');
    setMetadataContactName('');
    setMetadataContactUrl('');
    setMetadataContactEmail('');
    setMetadataLicenseName('');
    setMetadataLicenseIdentifier('');
    setMetadataLicenseUrl('');
    setShowCreateDialog(true);
  };

  const handleImportClick = () => setShowImportDialog(true);
  const handleImportSuccess = async () => await loadProjects();

  const handleCreateSubmit = async () => {
    if (!projectName.trim()) { setErrorMessage('Project name is required'); return; }
    if (!projectSlug.trim()) { setErrorMessage('Project slug is required'); return; }
    setIsLoading(true);
    setErrorMessage('');

    try {
      const metadata: ProjectMetadata = {};
      if (metadataSummary.trim()) metadata.summary = metadataSummary.trim();
      if (metadataTermsOfService.trim()) metadata.termsOfService = metadataTermsOfService.trim();
      if (metadataContactName.trim() || metadataContactUrl.trim() || metadataContactEmail.trim()) {
        metadata.contact = {};
        if (metadataContactName.trim()) metadata.contact.name = metadataContactName.trim();
        if (metadataContactUrl.trim()) metadata.contact.url = metadataContactUrl.trim();
        if (metadataContactEmail.trim()) metadata.contact.email = metadataContactEmail.trim();
      }
      if (metadataLicenseName.trim() || metadataLicenseIdentifier.trim() || metadataLicenseUrl.trim()) {
        metadata.license = {};
        if (metadataLicenseName.trim()) metadata.license.name = metadataLicenseName.trim();
        if (metadataLicenseIdentifier.trim()) metadata.license.identifier = metadataLicenseIdentifier.trim();
        if (metadataLicenseUrl.trim()) metadata.license.url = metadataLicenseUrl.trim();
      }

      const result = await createProject(currentTenantId, currentUserId, projectName, projectDescription, projectSlug, metadata);
      const response = JSON.parse(result);
      if (response.success) { setShowCreateDialog(false); await loadProjects(); }
      else setErrorMessage(response.error || 'Failed to create project');
    } catch (error: any) {
      setErrorMessage(error.message || 'An error occurred');
    } finally {
      setIsLoading(false);
    }
  };

  const handleEditClick = (project: Project) => {
    setSelectedProject(project);
    setProjectName(project.name);
    setProjectDescription(project.description || '');
    setProjectSlug((project as any).slug || '');
    setProjectEnabled(project.enabled);
    setErrorMessage('');
    const metadata = project.metadata || {};
    setMetadataSummary(metadata.summary || '');
    setMetadataTermsOfService(metadata.termsOfService || '');
    setMetadataContactName(metadata.contact?.name || '');
    setMetadataContactUrl(metadata.contact?.url || '');
    setMetadataContactEmail(metadata.contact?.email || '');
    setMetadataLicenseName(metadata.license?.name || '');
    setMetadataLicenseIdentifier(metadata.license?.identifier || '');
    setMetadataLicenseUrl(metadata.license?.url || '');
    setShowEditDialog(true);
  };

  const handleEditSubmit = async () => {
    if (!projectName.trim()) { setErrorMessage('Project name is required'); return; }
    if (!projectSlug.trim()) { setErrorMessage('Project slug is required'); return; }
    if (!selectedProject) return;
    setIsLoading(true);
    setErrorMessage('');

    try {
      const metadata: ProjectMetadata = {};
      if (metadataSummary.trim()) metadata.summary = metadataSummary.trim();
      if (metadataTermsOfService.trim()) metadata.termsOfService = metadataTermsOfService.trim();
      if (metadataContactName.trim() || metadataContactUrl.trim() || metadataContactEmail.trim()) {
        metadata.contact = {};
        if (metadataContactName.trim()) metadata.contact.name = metadataContactName.trim();
        if (metadataContactUrl.trim()) metadata.contact.url = metadataContactUrl.trim();
        if (metadataContactEmail.trim()) metadata.contact.email = metadataContactEmail.trim();
      }
      if (metadataLicenseName.trim() || metadataLicenseIdentifier.trim() || metadataLicenseUrl.trim()) {
        metadata.license = {};
        if (metadataLicenseName.trim()) metadata.license.name = metadataLicenseName.trim();
        if (metadataLicenseIdentifier.trim()) metadata.license.identifier = metadataLicenseIdentifier.trim();
        if (metadataLicenseUrl.trim()) metadata.license.url = metadataLicenseUrl.trim();
      }

      const result = await updateProject(selectedProject.id, projectName, projectDescription, projectSlug, projectEnabled, metadata);
      const response = JSON.parse(result);
      if (response.success) { setShowEditDialog(false); await loadProjects(); }
      else setErrorMessage(response.error || 'Failed to update project');
    } catch (error: any) {
      setErrorMessage(error.message || 'An error occurred');
    } finally {
      setIsLoading(false);
    }
  };

  const handleDelete = async (projectId: string) => {
    const confirmed = await confirmDialog({
      title: 'Delete Project',
      message: 'Are you sure you want to delete this project? This action cannot be undone.',
      variant: 'danger',
      confirmLabel: 'Delete',
      cancelLabel: 'Cancel',
    });
    if (!confirmed) return;

    try {
      const result = await deleteProject(projectId);
      const response = JSON.parse(result);
      if (response.success) await loadProjects();
      else await alertDialog({ message: response.error || 'Failed to delete project', variant: 'error' });
    } catch (error: any) {
      await alertDialog({ message: error.message || 'An error occurred', variant: 'error' });
    }
  };

  const handlePermanentDelete = async (project: Project) => {
    const confirmed = await confirmDialog({
      title: 'Permanently Delete Project',
      message: `Are you absolutely sure you want to permanently delete "${project.name}"?\n\nThis will permanently delete:\n• All versions of this project\n• All publications associated with those versions\n• All classes and their properties\n• All properties directly linked to this project\n\nThis action CANNOT be undone and all data will be lost forever.`,
      variant: 'danger',
      confirmLabel: 'Permanently Delete',
      cancelLabel: 'Cancel',
    });
    if (!confirmed) return;

    // Double confirmation for safety
    const doubleConfirmed = await confirmDialog({
      title: 'Final Confirmation',
      message: `Type "DELETE" mentally and confirm: You are about to permanently destroy all data for project "${project.name}". This is your last chance to cancel.`,
      variant: 'danger',
      confirmLabel: 'Yes, Delete Everything',
      cancelLabel: 'Cancel',
    });
    if (!doubleConfirmed) return;

    try {
      const result = await permanentDeleteProject(project.id);
      const response = JSON.parse(result);
      if (response.success) {
        await alertDialog({ message: 'Project and all associated data have been permanently deleted.', variant: 'success' });
        await loadProjects();
      } else {
        await alertDialog({ message: response.error || 'Failed to permanently delete project', variant: 'error' });
      }
    } catch (error: any) {
      await alertDialog({ message: error.message || 'An error occurred', variant: 'error' });
    }
  };

  const formatDateTime = (dateString: string) => {
    const d = new Date(dateString);
    const datePart = d.toLocaleDateString('en-US', { month: '2-digit', day: '2-digit', year: '2-digit' });
    const timePart = d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: true });
    return `${datePart} ${timePart}`;
  };

  const handleLicenseSelect = (identifier: string) => {
    const license = SPDX_LICENSES.find((l: SPDXLicense) => l.identifier === identifier);
    if (license) {
      setMetadataLicenseIdentifier(license.identifier);
      setMetadataLicenseName(license.name);
      const url = getLicenseUrl(license.identifier);
      if (url) setMetadataLicenseUrl(url);
    }
  };

  if (!session) return <div className="p-6"><p>Loading...</p></div>;

  if (!currentTenantId) {
    return (
      <div className="p-6">
        <div className="bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded-lg p-6">
          <div className="flex items-start gap-3">
            <Lock className="h-6 w-6 text-yellow-600 dark:text-yellow-400 flex-shrink-0 mt-1" />
            <div>
              <h2 className="text-lg font-semibold text-yellow-900 dark:text-yellow-100 mb-2">No Tenant Selected</h2>
              <p className="text-yellow-800 dark:text-yellow-200 mb-3">Please select a tenant before managing projects.</p>
              <Button asChild><a href="/ade/dashboard/tenants">Go to Tenants</a></Button>
            </div>
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
          <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-purple-500 to-indigo-600 flex items-center justify-center shadow-lg shadow-purple-500/25">
            <FolderOpen className="h-7 w-7 text-white" />
          </div>
          <div>
            <h1 className="text-3xl font-bold text-gray-900 dark:text-white tracking-tight">Projects</h1>
            <p className="text-gray-500 dark:text-gray-400 mt-1">Manage projects for the current tenant</p>
          </div>
        </div>
        <div className="flex gap-2">
          <Button
            onClick={() => {
              setImportOpenedFromNewProjectAI(false);
              setShowNewImportDialog(true);
            }}
            variant="outline"
            className="border-indigo-200 dark:border-indigo-800 hover:bg-indigo-50 dark:hover:bg-indigo-900/30"
            disabled={!currentTenantId}
            title={!currentTenantId ? 'Please select a tenant first' : 'Import specification'}
          >
            <Upload className="h-5 w-5" />Import
          </Button>
          <Button onClick={handleCreateClick} className="bg-gradient-to-r from-indigo-500 to-purple-600 hover:from-indigo-600 hover:to-purple-700">
            <Plus className="h-5 w-5" />New Project
          </Button>
        </div>
      </div>

      {/* Projects List */}
      {projects.length === 0 ? (
        <div className="relative">
          <div className="absolute -top-10 -left-10 w-40 h-40 bg-gradient-to-br from-indigo-100 to-purple-100 dark:from-indigo-900/20 dark:to-purple-900/20 rounded-full blur-3xl opacity-60" />
          <div className="absolute -bottom-10 -right-10 w-40 h-40 bg-gradient-to-br from-purple-100 to-pink-100 dark:from-purple-900/20 dark:to-pink-900/20 rounded-full blur-3xl opacity-60" />
          <div className="relative bg-white/80 dark:bg-gray-800/80 backdrop-blur-sm border border-gray-200/50 dark:border-gray-700/50 rounded-2xl p-16 text-center shadow-xl">
            <div className="w-20 h-20 mx-auto mb-6 bg-gradient-to-br from-indigo-500 to-purple-600 rounded-2xl flex items-center justify-center shadow-lg shadow-indigo-500/30">
              <FolderOpen className="h-10 w-10 text-white" />
            </div>
            <h3 className="text-2xl font-bold text-gray-900 dark:text-white mb-3">No Projects Yet</h3>
            <p className="text-gray-500 dark:text-gray-400 max-w-md mx-auto">Get started by creating your first project</p>
          </div>
        </div>
      ) : (
        <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-sm border border-gray-100 dark:border-gray-700 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-100 dark:divide-gray-700">
              <thead className="bg-gradient-to-r from-gray-50 to-slate-50 dark:from-gray-900 dark:to-gray-800">
                <tr>
                  <th scope="col" className="px-6 py-4 text-left text-xs font-bold text-gray-500 dark:text-gray-400 uppercase tracking-wider w-64">
                    Project Name
                  </th>
                  <th scope="col" className="px-6 py-4 text-left text-xs font-bold text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                    Description
                  </th>
                  <th scope="col" className="px-6 py-4 text-left text-xs font-bold text-gray-500 dark:text-gray-400 uppercase tracking-wider w-48">
                    Status
                  </th>
                  <th scope="col" className="px-6 py-4 text-left text-xs font-bold text-gray-500 dark:text-gray-400 uppercase tracking-wider w-56">
                    Created By
                  </th>
                  <th scope="col" className="px-6 py-4 text-left text-xs font-bold text-gray-500 dark:text-gray-400 uppercase tracking-wider w-40">
                    Created
                  </th>
                  <th scope="col" className="px-6 py-4 text-left text-xs font-bold text-gray-500 dark:text-gray-400 uppercase tracking-wider w-40">
                    Updated
                  </th>
                  <th scope="col" className="px-6 py-4 text-right text-xs font-bold text-gray-500 dark:text-gray-400 uppercase tracking-wider w-24">

                  </th>
                </tr>
              </thead>
              <tbody className="bg-white dark:bg-gray-800 divide-y divide-gray-100 dark:divide-gray-700">
                {projects.map((project) => (
                  <tr key={project.id} className="hover:bg-indigo-50/50 dark:hover:bg-indigo-900/20 transition-all duration-200">
                    <td className="px-6 py-4">
                      <div className="flex flex-col gap-1">
                        <div className="text-sm font-semibold text-gray-900 dark:text-white truncate max-w-xs" title={project.name}>
                          {project.name}
                        </div>
                        <div className="text-xs text-gray-500 dark:text-gray-400 font-mono truncate" title={(project as any).slug}>
                          {(project as any).slug || '—'}
                        </div>
                      </div>
                    </td>
                    <td className="px-6 py-4">
                      <div className="text-sm text-gray-600 dark:text-gray-400 truncate max-w-md" title={project.description || ''}>
                        {project.description || <span className="text-gray-400 dark:text-gray-600">No description</span>}
                      </div>
                      {project.metadata?.summary && (
                        <div className="text-xs text-gray-500 dark:text-gray-500 truncate max-w-md mt-1" title={project.metadata.summary}>
                          {project.metadata.summary}
                        </div>
                      )}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <div className="flex flex-col gap-2">
                        <div className="flex items-center gap-2">
                          {project.enabled ? (
                            <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400">
                              <span className="w-1.5 h-1.5 rounded-full bg-green-500"></span>
                              Enabled
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-400">
                              <span className="w-1.5 h-1.5 rounded-full bg-gray-400"></span>
                              Disabled
                            </span>
                          )}
                        </div>
                        {project.deleted_at && (
                          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400">
                            <Trash2 className="w-3 h-3" />
                            Deleted
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-6 py-4">
                      <div className="text-sm text-gray-900 dark:text-white truncate" title={project.creator_name}>
                        {project.creator_name}
                      </div>
                      <div className="text-xs text-gray-500 dark:text-gray-400 truncate" title={project.creator_email}>
                        {project.creator_email}
                      </div>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <div className="text-sm text-gray-500 dark:text-gray-400" title={formatDateTime(project.created_at)}>
                        {formatDateTime(project.created_at)}
                      </div>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <div className="text-sm text-gray-500 dark:text-gray-400" title={formatDateTime(project.updated_at)}>
                        {formatDateTime(project.updated_at)}
                      </div>
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
                            setOpenProjectDropdown(openProjectDropdown === project.id ? null : project.id);
                          }}
                          className="p-2 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg transition-colors text-gray-400 hover:text-gray-600 dark:hover:text-white"
                          title="Actions"
                        >
                          <MoreVertical className="h-4 w-4" />
                        </button>

                        {openProjectDropdown === project.id && dropdownPosition && (
                          <>
                            <div
                              className="fixed inset-0 z-10"
                              onClick={(e) => {
                                e.stopPropagation();
                                setOpenProjectDropdown(null);
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
                                    setOpenProjectDropdown(null);
                                    handleEditClick(project);
                                  }}
                                  className="w-full px-4 py-2 text-left text-sm hover:bg-gray-100 dark:hover:bg-gray-800 flex items-center gap-3 text-gray-700 dark:text-gray-300 hover:text-gray-900 dark:hover:text-white transition-colors"
                                >
                                  <Edit2 className="w-4 h-4 text-indigo-500" />
                                  Edit Project
                                </button>
                                <button
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    setOpenProjectDropdown(null);
                                    handleDelete(project.id);
                                  }}
                                  className="w-full px-4 py-2 text-left text-sm hover:bg-gray-100 dark:hover:bg-gray-800 flex items-center gap-3 text-gray-700 dark:text-gray-300 hover:text-gray-900 dark:hover:text-white transition-colors"
                                >
                                  <Trash2 className="w-4 h-4 text-red-500" />
                                  Delete Project
                                </button>
                                <div className="border-t border-gray-200 dark:border-gray-700 my-1" />
                                <button
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    setOpenProjectDropdown(null);
                                    handlePermanentDelete(project);
                                  }}
                                  className="w-full px-4 py-2 text-left text-sm hover:bg-red-50 dark:hover:bg-red-900/20 flex items-center gap-3 text-red-600 dark:text-red-400 hover:text-red-700 dark:hover:text-red-300 transition-colors"
                                >
                                  <AlertTriangle className="w-4 h-4" />
                                  Permanently Delete
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
        </div>
      )}

      {/* Create Project Dialog */}
      <Dialog
        open={showCreateDialog}
        onOpenChange={(open) => {
          if (!open) {
            if (createDialogTab === 'ai') {
              aiPanelRef.current?.abort();
              setCreateDialogTab('manual');
              return;
            }
            aiPanelRef.current?.abort();
          }
          if (!isLoading) setShowCreateDialog(open);
        }}
      >
        <DialogContent className="w-[1280px] max-w-[95vw] h-[90vh] flex flex-col">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <div className="p-1.5 rounded-lg bg-gradient-to-br from-purple-100 to-indigo-100 dark:from-purple-900/30 dark:to-indigo-900/30">
                <FolderOpen className="h-5 w-5 text-purple-600 dark:text-purple-400" />
              </div>
              Create New Project
            </DialogTitle>
          </DialogHeader>
          <Tabs value={createDialogTab} onValueChange={(v) => setCreateDialogTab(v as 'manual' | 'ai')} className="flex-1 flex flex-col min-h-0 mt-0">
            <TabsList className="w-full h-auto p-0 rounded-none bg-transparent border-b border-gray-200 dark:border-gray-700 justify-start gap-0">
              <TabsTrigger
                value="manual"
                className="flex items-center gap-2 rounded-none border-b-2 border-transparent bg-transparent px-4 py-3 text-sm font-medium text-gray-500 dark:text-gray-400 data-[state=active]:border-indigo-600 data-[state=active]:text-indigo-600 dark:data-[state=active]:text-indigo-400 data-[state=active]:bg-transparent data-[state=active]:shadow-none -mb-px"
              >
                <FileEdit className="h-4 w-4" />
                Create manually
              </TabsTrigger>
              <TabsTrigger
                value="ai"
                className="flex items-center gap-2 rounded-none border-b-2 border-transparent bg-transparent px-4 py-3 text-sm font-medium text-gray-500 dark:text-gray-400 data-[state=active]:border-indigo-600 data-[state=active]:text-indigo-600 dark:data-[state=active]:text-indigo-400 data-[state=active]:bg-transparent data-[state=active]:shadow-none -mb-px"
              >
                <Bot className="h-4 w-4" />
                Design with AI
              </TabsTrigger>
            </TabsList>
            <TabsContent value="manual" className="mt-4 flex-1 min-h-0">
          {errorMessage && <Alert variant="error" className="mb-4">{errorMessage}</Alert>}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-0 divide-x divide-gray-200 dark:divide-gray-700">
            {/* Left: Basic Information */}
            <div className="flex flex-col pr-4 lg:pr-6">
              <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100 mb-4">Basic Information</h3>
              <div className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="projectName">Project Name *</Label>
                  <Input id="projectName" value={projectName} onChange={(e) => { setProjectName(e.target.value); if (!projectSlug || projectSlug === generateSlug(projectName)) setProjectSlug(generateSlug(e.target.value)); }} disabled={isLoading} autoFocus />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="projectSlug">Slug *</Label>
                  <Input id="projectSlug" value={projectSlug} onChange={(e) => setProjectSlug(filterSlugInput(e.target.value))} disabled={isLoading} className="font-mono" />
                  <p className="text-xs text-gray-500 dark:text-gray-400">URL-friendly identifier (lowercase letters, numbers, and dashes only)</p>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="projectDescription">Description</Label>
                  <Textarea id="projectDescription" value={projectDescription} onChange={(e) => setProjectDescription(e.target.value)} disabled={isLoading} rows={4} />
                </div>
              </div>
            </div>
            {/* Right: API Metadata */}
            <div className="flex flex-col pl-4 lg:pl-6 pt-4 lg:pt-0">
              <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100 mb-4">API Metadata</h3>
              <div className="space-y-6">
                <div className="space-y-4">
                  <h4 className="text-xs font-medium text-gray-600 dark:text-gray-400 uppercase tracking-wide">OpenAPI</h4>
                  <div className="space-y-2">
                    <Label htmlFor="createSummary">API Summary</Label>
                    <Input id="createSummary" value={metadataSummary} onChange={(e) => setMetadataSummary(e.target.value)} disabled={isLoading} />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="createTermsOfService">Terms of Service URL</Label>
                    <div className="flex gap-2">
                      <Input id="createTermsOfService" type="url" value={metadataTermsOfService} onChange={(e) => setMetadataTermsOfService(e.target.value)} disabled={isLoading} placeholder="https://example.com/terms" className="flex-1 min-w-0" />
                      <Button
                        type="button"
                        variant="outline"
                        size="icon"
                        disabled={isLoading || !metadataTermsOfService.trim() || (!metadataTermsOfService.trim().startsWith('http://') && !metadataTermsOfService.trim().startsWith('https://'))}
                        onClick={() => window.open(metadataTermsOfService.trim(), '_blank', 'noopener,noreferrer')}
                        title="Open URL in new window"
                        className="shrink-0"
                      >
                        <ExternalLink className="h-4 w-4" />
                      </Button>
                    </div>
                  </div>
                </div>
                <div className="space-y-4">
                  <h4 className="text-xs font-medium text-gray-600 dark:text-gray-400 uppercase tracking-wide">Contact</h4>
                  <div className="grid grid-cols-1 gap-3">
                    <div className="space-y-2">
                      <Label htmlFor="createContactName">Name</Label>
                      <Input id="createContactName" value={metadataContactName} onChange={(e) => setMetadataContactName(e.target.value)} disabled={isLoading} />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="createContactUrl">URL</Label>
                      <div className="flex gap-2">
                        <Input id="createContactUrl" type="url" value={metadataContactUrl} onChange={(e) => setMetadataContactUrl(e.target.value)} disabled={isLoading} className="flex-1 min-w-0" />
                        <Button
                          type="button"
                          variant="outline"
                          size="icon"
                          disabled={isLoading || !metadataContactUrl.trim() || (!metadataContactUrl.trim().startsWith('http://') && !metadataContactUrl.trim().startsWith('https://'))}
                          onClick={() => window.open(metadataContactUrl.trim(), '_blank', 'noopener,noreferrer')}
                          title="Open URL in new window"
                          className="shrink-0"
                        >
                          <ExternalLink className="h-4 w-4" />
                        </Button>
                      </div>
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="createContactEmail">Email</Label>
                      <Input id="createContactEmail" type="email" value={metadataContactEmail} onChange={(e) => setMetadataContactEmail(e.target.value)} disabled={isLoading} />
                    </div>
                  </div>
                </div>
                <div className="space-y-4">
                  <h4 className="text-xs font-medium text-gray-600 dark:text-gray-400 uppercase tracking-wide">License</h4>
                  <div className="space-y-2">
                    <Label htmlFor="createLicenseIdentifier">License (SPDX)</Label>
                    <Select value={metadataLicenseIdentifier} onValueChange={handleLicenseSelect}>
                      <SelectTrigger>
                        <SelectValue placeholder="Select a license..." />
                      </SelectTrigger>
                      <SelectContent className="max-h-60">
                        {SPDX_LICENSES.slice(0, 50).map((license: SPDXLicense) => (
                          <SelectItem key={license.identifier} value={license.identifier}>{license.name} ({license.identifier})</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="grid grid-cols-1 gap-3">
                    <div className="space-y-2">
                      <Label htmlFor="createLicenseName">License Name</Label>
                      <Input id="createLicenseName" value={metadataLicenseName} onChange={(e) => setMetadataLicenseName(e.target.value)} disabled={isLoading} />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="createLicenseUrl">License URL</Label>
                      <div className="flex gap-2">
                        <Input id="createLicenseUrl" type="url" value={metadataLicenseUrl} onChange={(e) => setMetadataLicenseUrl(e.target.value)} disabled={isLoading} className="flex-1 min-w-0" />
                        <Button
                          type="button"
                          variant="outline"
                          size="icon"
                          disabled={isLoading || !metadataLicenseUrl.trim() || (!metadataLicenseUrl.trim().startsWith('http://') && !metadataLicenseUrl.trim().startsWith('https://'))}
                          onClick={() => window.open(metadataLicenseUrl.trim(), '_blank', 'noopener,noreferrer')}
                          title="Open URL in new window"
                          className="shrink-0"
                        >
                          <ExternalLink className="h-4 w-4" />
                        </Button>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
          <DialogFooter className="mt-6">
            <Button variant="outline" onClick={() => setShowCreateDialog(false)} disabled={isLoading}>Cancel</Button>
            <Button onClick={handleCreateSubmit} disabled={isLoading} className="bg-gradient-to-r from-purple-500 to-indigo-600">
              {isLoading ? 'Creating...' : 'Create Project'}
            </Button>
          </DialogFooter>
            </TabsContent>
            <TabsContent value="ai" className="mt-4 flex-1 min-h-0 flex flex-col p-0 data-[state=inactive]:hidden">
              {currentTenantId && currentUserId && (
                <LLMChatPanel
                  ref={aiPanelRef}
                  tenantId={currentTenantId}
                  userId={currentUserId}
                  embedded
                  className="flex-1 min-h-0"
                  onImportSpec={(specContent) => {
                    setPendingLLMSpec(specContent);
                    setImportOpenedFromNewProjectAI(true);
                    setShowCreateDialog(false);
                    setShowNewImportDialog(true);
                  }}
                />
              )}
            </TabsContent>
          </Tabs>
        </DialogContent>
      </Dialog>

      {/* New Import Dialog (Step 1 - Source Selection) */}
      {currentTenantId && currentUserId && (
        <ImportDialog
          open={showNewImportDialog}
          onClose={() => setShowNewImportDialog(false)}
          onSuccess={handleImportSuccess}
          tenantId={currentTenantId}
          userId={currentUserId}
          initialLLMSpec={pendingLLMSpec}
          onConsumeInitialLLMSpec={() => setPendingLLMSpec(null)}
          openedFromNewProjectAI={importOpenedFromNewProjectAI}
          onReturnToNewProjectAI={() => {
            setShowNewImportDialog(false);
            setShowCreateDialog(true);
            setCreateDialogTab('ai');
            setImportOpenedFromNewProjectAI(false);
          }}
        />
      )}

      {/* OpenAPI Import Dialog (Legacy - will be replaced by multi-step flow) */}
      {currentTenantId && currentUserId && (
        <OpenAPIImportDialog open={showImportDialog} onClose={() => setShowImportDialog(false)} onSuccess={handleImportSuccess} tenantId={currentTenantId} userId={currentUserId} />
      )}

      {/* Edit Project Dialog */}
      <Dialog open={showEditDialog} onOpenChange={(open) => !isLoading && setShowEditDialog(open)}>
        <DialogContent className="max-w-4xl">
          <DialogHeader>
            <DialogTitle>Edit Project</DialogTitle>
          </DialogHeader>
          {errorMessage && <Alert variant="error" className="mt-4">{errorMessage}</Alert>}
          {selectedProject && (
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mt-4">
              <div className="rounded-lg border border-gray-200 dark:border-gray-600 bg-gray-50 dark:bg-gray-800/50 p-3">
                <div className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-1">Status</div>
                <div className="text-sm font-medium text-gray-900 dark:text-white">
                  {selectedProject.deleted_at ? (
                    <span className="inline-flex items-center gap-1 text-red-600 dark:text-red-400">
                      <Trash2 className="w-4 h-4" /> Deleted
                    </span>
                  ) : selectedProject.enabled ? (
                    <span className="inline-flex items-center gap-1 text-green-600 dark:text-green-400">
                      <span className="w-1.5 h-1.5 rounded-full bg-green-500" /> Enabled
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 text-gray-600 dark:text-gray-400">
                      <span className="w-1.5 h-1.5 rounded-full bg-gray-400" /> Disabled
                    </span>
                  )}
                </div>
              </div>
              <div className="rounded-lg border border-gray-200 dark:border-gray-600 bg-gray-50 dark:bg-gray-800/50 p-3">
                <div className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-1">Created by</div>
                <div className="text-sm font-medium text-gray-900 dark:text-white truncate" title={selectedProject.creator_name}>{selectedProject.creator_name}</div>
                <div className="text-xs text-gray-500 dark:text-gray-400 truncate" title={selectedProject.creator_email}>{selectedProject.creator_email}</div>
              </div>
              <div className="rounded-lg border border-gray-200 dark:border-gray-600 bg-gray-50 dark:bg-gray-800/50 p-3">
                <div className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-1">Created</div>
                <div className="text-sm text-gray-900 dark:text-white">{formatDateTime(selectedProject.created_at)}</div>
              </div>
              <div className="rounded-lg border border-gray-200 dark:border-gray-600 bg-gray-50 dark:bg-gray-800/50 p-3">
                <div className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-1">Updated</div>
                <div className="text-sm text-gray-900 dark:text-white">{formatDateTime(selectedProject.updated_at)}</div>
              </div>
            </div>
          )}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-0 divide-x divide-gray-200 dark:divide-gray-700 mt-4">
            {/* Left: Basic Information */}
            <div className="flex flex-col pr-4 lg:pr-6">
              <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100 mb-4">Basic Information</h3>
              <div className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="editName">Project Name *</Label>
                  <Input id="editName" value={projectName} onChange={(e) => setProjectName(e.target.value)} disabled={isLoading} />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="editSlug">Slug *</Label>
                  <Input id="editSlug" value={projectSlug} onChange={(e) => setProjectSlug(filterSlugInput(e.target.value))} disabled={isLoading} className="font-mono" />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="editDescription">Description</Label>
                  <Textarea id="editDescription" value={projectDescription} onChange={(e) => setProjectDescription(e.target.value)} disabled={isLoading} rows={4} />
                </div>
              </div>
            </div>
            {/* Right: API Metadata */}
            <div className="flex flex-col pl-4 lg:pl-6 pt-4 lg:pt-0">
              <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100 mb-4">API Metadata</h3>
              <div className="space-y-6">
                <div className="space-y-4">
                  <h4 className="text-xs font-medium text-gray-600 dark:text-gray-400 uppercase tracking-wide">OpenAPI</h4>
                  <div className="space-y-2">
                    <Label htmlFor="summary">API Summary</Label>
                    <Input id="summary" value={metadataSummary} onChange={(e) => setMetadataSummary(e.target.value)} disabled={isLoading} />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="termsOfService">Terms of Service URL</Label>
                    <div className="flex gap-2">
                      <Input id="termsOfService" type="url" value={metadataTermsOfService} onChange={(e) => setMetadataTermsOfService(e.target.value)} disabled={isLoading} placeholder="https://example.com/terms" className="flex-1 min-w-0" />
                      <Button
                        type="button"
                        variant="outline"
                        size="icon"
                        disabled={isLoading || !metadataTermsOfService.trim() || (!metadataTermsOfService.trim().startsWith('http://') && !metadataTermsOfService.trim().startsWith('https://'))}
                        onClick={() => window.open(metadataTermsOfService.trim(), '_blank', 'noopener,noreferrer')}
                        title="Open URL in new window"
                        className="shrink-0"
                      >
                        <ExternalLink className="h-4 w-4" />
                      </Button>
                    </div>
                  </div>
                </div>
                <div className="space-y-4">
                  <h4 className="text-xs font-medium text-gray-600 dark:text-gray-400 uppercase tracking-wide">Contact</h4>
                  <div className="grid grid-cols-1 gap-3">
                    <div className="space-y-2">
                      <Label htmlFor="contactName">Name</Label>
                      <Input id="contactName" value={metadataContactName} onChange={(e) => setMetadataContactName(e.target.value)} disabled={isLoading} />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="contactUrl">URL</Label>
                      <div className="flex gap-2">
                        <Input id="contactUrl" type="url" value={metadataContactUrl} onChange={(e) => setMetadataContactUrl(e.target.value)} disabled={isLoading} className="flex-1 min-w-0" />
                        <Button
                          type="button"
                          variant="outline"
                          size="icon"
                          disabled={isLoading || !metadataContactUrl.trim() || (!metadataContactUrl.trim().startsWith('http://') && !metadataContactUrl.trim().startsWith('https://'))}
                          onClick={() => window.open(metadataContactUrl.trim(), '_blank', 'noopener,noreferrer')}
                          title="Open URL in new window"
                          className="shrink-0"
                        >
                          <ExternalLink className="h-4 w-4" />
                        </Button>
                      </div>
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="contactEmail">Email</Label>
                      <Input id="contactEmail" type="email" value={metadataContactEmail} onChange={(e) => setMetadataContactEmail(e.target.value)} disabled={isLoading} />
                    </div>
                  </div>
                </div>
                <div className="space-y-4">
                  <h4 className="text-xs font-medium text-gray-600 dark:text-gray-400 uppercase tracking-wide">License</h4>
                  <div className="space-y-2">
                    <Label htmlFor="licenseIdentifier">License (SPDX)</Label>
                    <Select value={metadataLicenseIdentifier} onValueChange={handleLicenseSelect}>
                      <SelectTrigger>
                        <SelectValue placeholder="Select a license..." />
                      </SelectTrigger>
                      <SelectContent className="max-h-60">
                        {SPDX_LICENSES.slice(0, 50).map((license: SPDXLicense) => (
                          <SelectItem key={license.identifier} value={license.identifier}>{license.name} ({license.identifier})</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="grid grid-cols-1 gap-3">
                    <div className="space-y-2">
                      <Label htmlFor="licenseName">License Name</Label>
                      <Input id="licenseName" value={metadataLicenseName} onChange={(e) => setMetadataLicenseName(e.target.value)} disabled={isLoading} />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="licenseUrl">License URL</Label>
                      <div className="flex gap-2">
                        <Input id="licenseUrl" type="url" value={metadataLicenseUrl} onChange={(e) => setMetadataLicenseUrl(e.target.value)} disabled={isLoading} className="flex-1 min-w-0" />
                        <Button
                          type="button"
                          variant="outline"
                          size="icon"
                          disabled={isLoading || !metadataLicenseUrl.trim() || (!metadataLicenseUrl.trim().startsWith('http://') && !metadataLicenseUrl.trim().startsWith('https://'))}
                          onClick={() => window.open(metadataLicenseUrl.trim(), '_blank', 'noopener,noreferrer')}
                          title="Open URL in new window"
                          className="shrink-0"
                        >
                          <ExternalLink className="h-4 w-4" />
                        </Button>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
          <DialogFooter className="mt-6">
            <Button variant="outline" onClick={() => setShowEditDialog(false)} disabled={isLoading}>Cancel</Button>
            <Button onClick={handleEditSubmit} disabled={isLoading}>{isLoading ? 'Saving...' : 'Save Changes'}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default Projects;

