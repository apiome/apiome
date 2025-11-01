'use client';

import { useSession } from 'next-auth/react';
import { useEffect, useState } from 'react';
import { Plus, Edit2, Trash2, Package, AlertCircle, Lock, Unlock, CheckCircle } from 'lucide-react';
import Dialog from '@mui/material/Dialog';
import DialogTitle from '@mui/material/DialogTitle';
import DialogContent from '@mui/material/DialogContent';
import DialogActions from '@mui/material/DialogActions';
import Button from '@mui/material/Button';
import TextField from '@mui/material/TextField';
import Alert from '@mui/material/Alert';
import Select from '@mui/material/Select';
import MenuItem from '@mui/material/MenuItem';
import FormControl from '@mui/material/FormControl';
import InputLabel from '@mui/material/InputLabel';
import Chip from '@mui/material/Chip';
import {
  getProjectsForTenant,
  getVersionsForProject,
  createVersion,
  updateVersion,
  deleteVersion,
  publishVersion,
  unpublishVersion
} from '../../../../../lib/db/helper';

interface Project {
  id: string;
  name: string;
  slug: string;
}

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
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');

  const currentTenantId = (session?.user as any)?.current_tenant_id;
  const currentUserId = (session?.user as any)?.user_id;

  useEffect(() => {
    if (currentTenantId) {
      loadProjects();
    }
  }, [currentTenantId]);

  useEffect(() => {
    if (selectedProjectId) {
      loadVersions();
    } else {
      setVersions([]);
    }
  }, [selectedProjectId]);

  const loadProjects = async () => {
    if (!currentTenantId) return;

    try {
      const result = await getProjectsForTenant(currentTenantId);
      const projectsData = JSON.parse(result);
      setProjects(projectsData);

      // Auto-select first project if available
      if (projectsData.length > 0 && !selectedProjectId) {
        setSelectedProjectId(projectsData[0].id);
      }
    } catch (error) {
      console.error('Failed to load projects:', error);
    }
  };

  const loadVersions = async () => {
    if (!selectedProjectId) return;

    try {
      const result = await getVersionsForProject(selectedProjectId);
      setVersions(JSON.parse(result));
    } catch (error) {
      console.error('Failed to load versions:', error);
    }
  };

  const calculateNextVersion = (strategy: 'patch' | 'minor' = 'patch'): string => {
    if (versions.length === 0) {
      return '0.1.0';
    }

    // Get the latest version (versions are already sorted by created_at DESC)
    const latestVersion = versions[0].version_id;
    const match = latestVersion.match(/^(\d+)\.(\d+)\.(\d+)$/);

    if (!match) {
      return '0.1.0';
    }

    const major = parseInt(match[1], 10);
    const minor = parseInt(match[2], 10);
    const patch = parseInt(match[3], 10);

    if (strategy === 'minor') {
      return `${major}.${minor + 1}.0`;
    } else {
      return `${major}.${minor}.${patch + 1}`;
    }
  };

  const handleCreateClick = () => {
    setVersionId('');
    setAutoGenerate(true);
    setBumpStrategy('patch');
    setNextAutoVersion(calculateNextVersion('patch'));
    setDescription('');
    setChangeLog('');
    setEnabled(true);
    setErrorMessage('');
    setShowCreateDialog(true);
  };

  const handleCreateSubmit = async () => {
    if (!autoGenerate && !versionId.trim()) {
      setErrorMessage('Version ID is required when not auto-generating');
      return;
    }

    if (!description.trim()) {
      setErrorMessage('Description is required');
      return;
    }

    setIsLoading(true);
    setErrorMessage('');

    try {
      const result = await createVersion(
        selectedProjectId,
        currentUserId,
        autoGenerate ? null : versionId,
        description,
        changeLog
      );
      const response = JSON.parse(result);

      if (response.success) {
        setShowCreateDialog(false);
        await loadVersions();
      } else {
        setErrorMessage(response.error || 'Failed to create version');
      }
    } catch (error: any) {
      setErrorMessage(error.message || 'An error occurred');
    } finally {
      setIsLoading(false);
    }
  };

  const handleEditClick = (version: Version) => {
    if (version.published) {
      setErrorMessage('Cannot edit published version');
      return;
    }

    setSelectedVersion(version);
    setVersionId(version.version_id);
    setDescription(version.description || '');
    setChangeLog(version.change_log || '');
    setEnabled(version.enabled);
    setErrorMessage('');
    setShowEditDialog(true);
  };

  const handleEditSubmit = async () => {
    if (!selectedVersion) return;

    if (!description.trim()) {
      setErrorMessage('Description is required');
      return;
    }

    setIsLoading(true);
    setErrorMessage('');

    try {
      const result = await updateVersion(
        selectedVersion.id,
        description,
        changeLog,
        enabled
      );
      const response = JSON.parse(result);

      if (response.success) {
        setShowEditDialog(false);
        await loadVersions();
      } else {
        setErrorMessage(response.error || 'Failed to update version');
      }
    } catch (error: any) {
      setErrorMessage(error.message || 'An error occurred');
    } finally {
      setIsLoading(false);
    }
  };

  const handlePublish = async (versionRecordId: string) => {
    if (!confirm('Are you sure you want to publish this version? Once published, it cannot be edited (but can be unpublished or deleted).')) {
      return;
    }

    try {
      const result = await publishVersion(versionRecordId);
      const response = JSON.parse(result);

      if (response.success) {
        await loadVersions();
      } else {
        alert(response.error || 'Failed to publish version');
      }
    } catch (error: any) {
      alert(error.message || 'An error occurred');
    }
  };

  const handleUnpublish = async (versionRecordId: string) => {
    if (!confirm('Are you sure you want to unpublish this version? It will become editable again.')) {
      return;
    }

    try {
      const result = await unpublishVersion(versionRecordId);
      const response = JSON.parse(result);

      if (response.success) {
        await loadVersions();
      } else {
        alert(response.error || 'Failed to unpublish version');
      }
    } catch (error: any) {
      alert(error.message || 'An error occurred');
    }
  };

  const handleDelete = async (versionRecordId: string) => {
    if (!confirm('Are you sure you want to delete this version? This action cannot be undone.')) {
      return;
    }

    try {
      const result = await deleteVersion(versionRecordId);
      const response = JSON.parse(result);

      if (response.success) {
        await loadVersions();
      } else {
        alert(response.error || 'Failed to delete version');
      }
    } catch (error: any) {
      alert(error.message || 'An error occurred');
    }
  };

  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  if (!session) {
    return (
      <div className="p-6">
        <p>Loading...</p>
      </div>
    );
  }

  if (!currentTenantId) {
    return (
      <div className="p-6">
        <div className="bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded-lg p-6">
          <div className="flex items-start gap-3">
            <AlertCircle className="h-6 w-6 text-yellow-600 dark:text-yellow-400 flex-shrink-0 mt-1" />
            <div>
              <h2 className="text-lg font-semibold text-yellow-900 dark:text-yellow-100 mb-2">
                No Tenant Selected
              </h2>
              <p className="text-yellow-800 dark:text-yellow-200 mb-3">
                Please select a tenant before managing versions. Versions are associated with projects within a tenant.
              </p>
              <a
                href="/ade/dashboard/tenants"
                className="inline-block px-4 py-2 bg-yellow-600 hover:bg-yellow-700 text-white rounded-lg font-medium transition-colors"
              >
                Go to Tenants
              </a>
            </div>
          </div>
        </div>
      </div>
    );
  }

  if (projects.length === 0) {
    return (
      <div className="p-6">
        <div className="bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded-lg p-6">
          <div className="flex items-start gap-3">
            <AlertCircle className="h-6 w-6 text-yellow-600 dark:text-yellow-400 flex-shrink-0 mt-1" />
            <div>
              <h2 className="text-lg font-semibold text-yellow-900 dark:text-yellow-100 mb-2">
                No Projects Available
              </h2>
              <p className="text-yellow-800 dark:text-yellow-200 mb-3">
                Please create a project before managing versions. Versions belong to specific projects.
              </p>
              <a
                href="/ade/dashboard/projects"
                className="inline-block px-4 py-2 bg-yellow-600 hover:bg-yellow-700 text-white rounded-lg font-medium transition-colors"
              >
                Go to Projects
              </a>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6">
      <div className="flex justify-between items-center mb-6">
        <div>
          <h1 className="text-3xl font-bold mb-2">Versions</h1>
          <p className="text-gray-600 dark:text-gray-400">
            Manage versions with semantic versioning
          </p>
        </div>
        <div className="flex gap-3">
          <FormControl
            sx={{
              minWidth: 250,
              '& .MuiOutlinedInput-root': {
                color: 'var(--foreground)',
                backgroundColor: 'var(--background)',
                '& fieldset': {
                  borderColor: 'rgba(128, 128, 128, 0.5)',
                },
                '&:hover fieldset': {
                  borderColor: 'rgba(128, 128, 128, 0.7)',
                },
                '&.Mui-focused fieldset': {
                  borderColor: '#3b82f6',
                },
              },
              '& .MuiInputLabel-root': {
                color: 'var(--foreground)',
                '&.Mui-focused': {
                  color: '#3b82f6',
                },
              },
              '& .MuiSvgIcon-root': {
                color: 'var(--foreground)',
              },
            }}
          >
            <InputLabel>Select Project</InputLabel>
            <Select
              value={selectedProjectId}
              label="Select Project"
              onChange={(e) => setSelectedProjectId(e.target.value)}
              MenuProps={{
                PaperProps: {
                  sx: {
                    bgcolor: 'var(--background)',
                    color: 'var(--foreground)',
                    '& .MuiMenuItem-root': {
                      '&:hover': {
                        backgroundColor: 'rgba(128, 128, 128, 0.2)',
                      },
                      '&.Mui-selected': {
                        backgroundColor: 'rgba(59, 130, 246, 0.2)',
                        '&:hover': {
                          backgroundColor: 'rgba(59, 130, 246, 0.3)',
                        },
                      },
                    },
                  },
                },
              }}
            >
              {projects.map((project) => (
                <MenuItem key={project.id} value={project.id}>
                  {project.name}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <button
            onClick={handleCreateClick}
            disabled={!selectedProjectId}
            className="flex items-center gap-2 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-400 text-white font-bold py-2 px-4 rounded-lg cursor-pointer transition-colors disabled:cursor-not-allowed"
          >
            <Plus className="h-5 w-5" />
            New Version
          </button>
        </div>
      </div>

      {versions.length === 0 ? (
        <div className="bg-gray-50 dark:bg-gray-800 border-2 border-dashed border-gray-300 dark:border-gray-600 rounded-lg p-12 text-center">
          <Package className="h-16 w-16 text-gray-400 dark:text-gray-500 mx-auto mb-4" />
          <h3 className="text-xl font-semibold text-gray-700 dark:text-gray-300 mb-2">
            No Versions Yet
          </h3>
          <p className="text-gray-600 dark:text-gray-400 mb-4">
            Get started by creating your first version
          </p>
          <button
            onClick={handleCreateClick}
            className="inline-flex items-center gap-2 bg-blue-600 hover:bg-blue-700 text-white font-bold py-2 px-4 rounded-lg cursor-pointer transition-colors"
          >
            <Plus className="h-5 w-5" />
            Create Version
          </button>
        </div>
      ) : (
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow overflow-hidden">
          <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
            <thead className="bg-gray-50 dark:bg-gray-900">
              <tr>
                <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                  Version
                </th>
                <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                  Description
                </th>
                <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                  Status
                </th>
                <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                  Created By
                </th>
                <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                  Created
                </th>
                <th scope="col" className="px-6 py-3 text-right text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className="bg-white dark:bg-gray-800 divide-y divide-gray-200 dark:divide-gray-700">
              {versions.map((version) => (
                <tr key={version.id} className="hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors">
                  <td className="px-6 py-4 whitespace-nowrap">
                    <div className="flex items-center gap-2">
                      <div className="text-sm font-bold text-gray-900 dark:text-white">
                        v{version.version_id}
                      </div>
                      {version.published && (
                        <div title="Published (Frozen)">
                          <Lock className="h-4 w-4 text-blue-600 dark:text-blue-400" />
                        </div>
                      )}
                    </div>
                  </td>
                  <td className="px-6 py-4">
                    <div className="text-sm text-gray-900 dark:text-white max-w-xs truncate">
                      {version.description || '—'}
                    </div>
                    {version.change_log && (
                      <div className="text-xs text-gray-500 dark:text-gray-400 mt-1 max-w-xs truncate">
                        {version.change_log}
                      </div>
                    )}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    <div className="flex gap-2">
                      {version.published ? (
                        <Chip
                          label="Published"
                          color="success"
                          size="small"
                          icon={<CheckCircle style={{ fontSize: 16 }} />}
                        />
                      ) : (
                        <Chip
                          label="Draft"
                          size="small"
                          sx={{
                            backgroundColor: 'rgba(128, 128, 128, 0.2)',
                            color: 'var(--foreground)',
                            borderColor: 'rgba(128, 128, 128, 0.3)',
                            border: '1px solid',
                          }}
                        />
                      )}
                      {!version.enabled && (
                        <Chip
                          label="Disabled"
                          color="error"
                          size="small"
                        />
                      )}
                    </div>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    <div className="text-sm text-gray-900 dark:text-white">
                      {version.creator_name}
                    </div>
                    <div className="text-xs text-gray-500 dark:text-gray-400">
                      {version.creator_email}
                    </div>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">
                    {formatDate(version.created_at)}
                    {version.published_at && (
                      <div className="text-xs text-green-600 dark:text-green-400">
                        Published: {formatDate(version.published_at)}
                      </div>
                    )}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                    <div className="flex justify-end gap-2">
                      {!version.published ? (
                        <>
                          <div title="Edit version">
                            <button
                              onClick={() => handleEditClick(version)}
                              className="p-2 hover:bg-gray-100 dark:hover:bg-gray-600 rounded cursor-pointer transition-colors"
                            >
                              <Edit2 className="h-4 w-4 text-blue-600 dark:text-blue-400" />
                            </button>
                          </div>
                          <div title="Publish version (freeze)">
                            <button
                              onClick={() => handlePublish(version.id)}
                              className="p-2 hover:bg-gray-100 dark:hover:bg-gray-600 rounded cursor-pointer transition-colors"
                            >
                              <Lock className="h-4 w-4 text-green-600 dark:text-green-400" />
                            </button>
                          </div>
                        </>
                      ) : (
                        <div title="Unpublish version">
                          <button
                            onClick={() => handleUnpublish(version.id)}
                            className="p-2 hover:bg-gray-100 dark:hover:bg-gray-600 rounded cursor-pointer transition-colors"
                          >
                            <Unlock className="h-4 w-4 text-orange-600 dark:text-orange-400" />
                          </button>
                        </div>
                      )}
                      <div title="Delete version">
                        <button
                          onClick={() => handleDelete(version.id)}
                          className="p-2 hover:bg-gray-100 dark:hover:bg-gray-600 rounded cursor-pointer transition-colors"
                        >
                          <Trash2 className="h-4 w-4 text-red-600 dark:text-red-400" />
                        </button>
                      </div>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Create Version Dialog */}
      <Dialog
        open={showCreateDialog}
        onClose={() => !isLoading && setShowCreateDialog(false)}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>Create New Version</DialogTitle>
        <DialogContent>
          {errorMessage && (
            <Alert severity="error" sx={{ mb: 2 }}>
              {errorMessage}
            </Alert>
          )}
          <FormControl fullWidth sx={{ mb: 2, mt: 1 }}>
            <InputLabel>Version Strategy</InputLabel>
            <Select
              value={autoGenerate ? 'auto' : 'manual'}
              label="Version Strategy"
              onChange={(e) => {
                const isAuto = e.target.value === 'auto';
                setAutoGenerate(isAuto);
                if (isAuto) {
                  setNextAutoVersion(calculateNextVersion(bumpStrategy));
                }
              }}
              disabled={isLoading}
            >
              <MenuItem value="auto">Auto-generate version</MenuItem>
              <MenuItem value="manual">Manual entry</MenuItem>
            </Select>
          </FormControl>
          {autoGenerate ? (
            <>
              <FormControl fullWidth sx={{ mb: 2 }}>
                <InputLabel>Bump Strategy</InputLabel>
                <Select
                  value={bumpStrategy}
                  label="Bump Strategy"
                  onChange={(e) => {
                    const strategy = e.target.value as 'patch' | 'minor';
                    setBumpStrategy(strategy);
                    setNextAutoVersion(calculateNextVersion(strategy));
                  }}
                  disabled={isLoading}
                >
                  <MenuItem value="patch">
                    Patch version (bug fixes) - {calculateNextVersion('patch')}
                  </MenuItem>
                  <MenuItem value="minor">
                    Minor version (new features) - {calculateNextVersion('minor')}
                  </MenuItem>
                </Select>
              </FormControl>
              <Alert severity="info" sx={{ mb: 2 }}>
                Version <strong>{nextAutoVersion}</strong> will be created
                <div style={{ fontSize: '0.875rem', marginTop: '4px' }}>
                  {bumpStrategy === 'patch'
                    ? 'Patch bump: For bug fixes and small changes'
                    : 'Minor bump: For new features and functionality'}
                </div>
              </Alert>
            </>
          ) : (
            <TextField
              autoFocus={!autoGenerate}
              margin="dense"
              label="Version ID"
              type="text"
              fullWidth
              variant="outlined"
              value={versionId}
              onChange={(e) => setVersionId(e.target.value)}
              disabled={isLoading}
              required
              helperText="Semantic version format (e.g., 1.0.0, 2.1.3)"
              sx={{ mb: 2 }}
            />
          )}
          <TextField
            margin="dense"
            label="Description"
            type="text"
            fullWidth
            variant="outlined"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            disabled={isLoading}
            required
            helperText="Provide a brief description of this version"
            sx={{ mb: 2 }}
          />
          <TextField
            margin="dense"
            label="Change Log"
            type="text"
            fullWidth
            variant="outlined"
            multiline
            rows={4}
            value={changeLog}
            onChange={(e) => setChangeLog(e.target.value)}
            disabled={isLoading}
            helperText="Document what's new or changed in this version"
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setShowCreateDialog(false)} disabled={isLoading}>
            Cancel
          </Button>
          <Button onClick={handleCreateSubmit} variant="contained" disabled={isLoading}>
            {isLoading ? 'Creating...' : 'Create Version'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Edit Version Dialog */}
      <Dialog
        open={showEditDialog}
        onClose={() => !isLoading && setShowEditDialog(false)}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>Edit Version</DialogTitle>
        <DialogContent>
          {errorMessage && (
            <Alert severity="error" sx={{ mb: 2 }}>
              {errorMessage}
            </Alert>
          )}
          <TextField
            margin="dense"
            label="Version ID"
            type="text"
            fullWidth
            variant="outlined"
            value={versionId}
            disabled
            sx={{ mb: 2 }}
          />
          <TextField
            autoFocus
            margin="dense"
            label="Description"
            type="text"
            fullWidth
            variant="outlined"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            disabled={isLoading}
            required
            sx={{ mb: 2 }}
          />
          <TextField
            margin="dense"
            label="Change Log"
            type="text"
            fullWidth
            variant="outlined"
            multiline
            rows={4}
            value={changeLog}
            onChange={(e) => setChangeLog(e.target.value)}
            disabled={isLoading}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setShowEditDialog(false)} disabled={isLoading}>
            Cancel
          </Button>
          <Button onClick={handleEditSubmit} variant="contained" disabled={isLoading}>
            {isLoading ? 'Saving...' : 'Save Changes'}
          </Button>
        </DialogActions>
      </Dialog>
    </div>
  );
}

export default Versions;
