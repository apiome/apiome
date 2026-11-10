'use client';

import { useState, useEffect, useRef } from 'react';
import {
  Building2,
  Users,
  UserPlus,
  Shield,
  Trash2,
  RefreshCw,
  CheckCircle,
  AlertCircle,
  Plus,
  X,
  UserX,
  ShieldCheck,
  ShieldX,
  MoreVertical,
  Edit,
  Power,
} from 'lucide-react';
import {
  getTenantStats,
  getTenantUsers,
  createTenant,
  updateTenant,
  deleteTenant,
  addUserToTenant,
  removeUserFromTenant,
  addTenantAdministrator,
  removeTenantAdministrator,
  getUsersNotInTenant,
  getAllUsers,
  provisionSampleProject,
} from '../../../../../lib/db/admin-actions';
import { useDialog } from '@/app/components/providers/DialogProvider';
import { destructiveConfirm } from '@/app/components/dialogs/destructiveConfirm';
import { EmptyState } from '@/app/components/ui/EmptyState';
import { LoadingState } from '@/app/components/ui/LoadingState';
import { SkeletonText } from '@/app/components/ui/Skeleton';
import { Button } from '@/app/components/ui/Button';
import { Input } from '@/app/components/ui/Input';
import { Textarea } from '@/app/components/ui/Textarea';
import { ModalFrame } from '@/app/components/ui/ModalFrame';

interface Tenant {
  id: string;
  name: string;
  description: string;
  slug: string;
  enabled: boolean;
  created_at: string;
  updated_at: string;
  user_count?: number;
  admin_count?: number;
  project_count?: number;
}

interface TenantUser {
  id: string;
  name: string;
  email: string;
  verified: boolean;
  enabled: boolean;
  added_at: string;
  is_admin: boolean;
}

interface User {
  id: string;
  name: string;
  email: string;
  verified: boolean;
  enabled: boolean;
}

export default function TenantManagementClient() {
  const { confirm } = useDialog();
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [selectedTenant, setSelectedTenant] = useState<Tenant | null>(null);
  const [tenantUsers, setTenantUsers] = useState<TenantUser[]>([]);
  const [availableUsers, setAvailableUsers] = useState<User[]>([]);
  const [allUsers, setAllUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [showAddUserDialog, setShowAddUserDialog] = useState(false);
  const [showRenameDialog, setShowRenameDialog] = useState(false);
  const [openTenantDropdown, setOpenTenantDropdown] = useState<string | null>(null);
  const [openUserDropdown, setOpenUserDropdown] = useState<string | null>(null);
  const [dropdownPosition, setDropdownPosition] = useState<{ top: number; right: number } | null>(null);
  const [renamingTenant, setRenamingTenant] = useState<Tenant | null>(null);
  const [renameData, setRenameData] = useState({ name: '', description: '', slug: '' });
  const [newTenant, setNewTenant] = useState({
    name: '',
    description: '',
    slug: '',
    initialUserId: '',
    makeAdmin: false
  });

  useEffect(() => {
    loadTenants();
    loadAllUsers();
  }, []);

  const loadTenants = async () => {
    setLoading(true);
    try {
      const result = await getTenantStats();
      const data = JSON.parse(result);
      if (data.success) {
        // Convert string counts to numbers (PostgreSQL COUNT returns BigInt which serializes as string)
        const tenantsWithNumbers = data.tenants.map((t: any) => ({
          ...t,
          user_count: Number(t.user_count) || 0,
          admin_count: Number(t.admin_count) || 0,
          project_count: Number(t.project_count) || 0,
        }));
        setTenants(tenantsWithNumbers);
      }
    } catch (error) {
      console.error('Error loading tenants:', error);
      showMessage('error', 'Failed to load tenants');
    } finally {
      setLoading(false);
    }
  };

  const loadAllUsers = async () => {
    try {
      const result = await getAllUsers();
      const data = JSON.parse(result);
      if (data.success) {
        setAllUsers(data.users);
      }
    } catch (error) {
      console.error('Error loading users:', error);
    }
  };

  const loadTenantUsers = async (tenantId: string) => {
    try {
      const [usersResult, availableResult] = await Promise.all([
        getTenantUsers(tenantId),
        getUsersNotInTenant(tenantId),
      ]);

      const usersData = JSON.parse(usersResult);
      const availableData = JSON.parse(availableResult);

      if (usersData.success) {
        setTenantUsers(usersData.users);
      }
      if (availableData.success) {
        setAvailableUsers(availableData.users);
      }
    } catch (error) {
      console.error('Error loading tenant users:', error);
    }
  };

  const handleSelectTenant = async (tenant: Tenant) => {
    setSelectedTenant(tenant);
    await loadTenantUsers(tenant.id);
  };

  const showMessage = (type: 'success' | 'error', text: string) => {
    setMessage({ type, text });
    setTimeout(() => setMessage(null), 5000);
  };

  const handleCreateTenant = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const result = await createTenant(
        newTenant.name,
        newTenant.description,
        newTenant.slug,
        true
      );
      const data = JSON.parse(result);

      if (data.success) {
        const tenantId = data.tenant.id;

        // Add initial user if selected
        if (newTenant.initialUserId) {
          try {
            await addUserToTenant(tenantId, newTenant.initialUserId);

            // Make admin if requested
            if (newTenant.makeAdmin) {
              await addTenantAdministrator(tenantId, newTenant.initialUserId);
            }

            // Best-effort: seed the curated sample project so the tenant isn't empty (needs a
            // creator, which we have here). Never fail tenant creation if this errors.
            await provisionSampleProject(tenantId, newTenant.initialUserId);

            showMessage('success', `Tenant created successfully${newTenant.makeAdmin ? ' with admin user' : ' with user'}`);
          } catch (userError) {
            console.error('Error adding user to tenant:', userError);
            showMessage('success', 'Tenant created but failed to add user');
          }
        } else {
          showMessage('success', 'Tenant created successfully');
        }

        setShowCreateDialog(false);
        setNewTenant({ name: '', description: '', slug: '', initialUserId: '', makeAdmin: false });
        await loadTenants();
      } else {
        showMessage('error', data.error || 'Failed to create tenant');
      }
    } catch (error) {
      console.error('Error creating tenant:', error);
      showMessage('error', 'Failed to create tenant');
    }
  };

  const handleToggleTenantEnabled = async (tenant: Tenant) => {
    try {
      const result = await updateTenant(tenant.id, { enabled: !tenant.enabled });
      const data = JSON.parse(result);

      if (data.success) {
        showMessage('success', `Tenant ${tenant.enabled ? 'disabled' : 'enabled'} successfully`);
        await loadTenants();
        if (selectedTenant?.id === tenant.id) {
          setSelectedTenant({ ...selectedTenant, enabled: !tenant.enabled });
        }
      } else {
        showMessage('error', data.error || 'Failed to update tenant');
      }
    } catch (error) {
      console.error('Error updating tenant:', error);
      showMessage('error', 'Failed to update tenant');
    }
  };

  const handleOpenRenameDialog = (tenant: Tenant) => {
    setRenamingTenant(tenant);
    setRenameData({
      name: tenant.name,
      description: tenant.description || '',
      slug: tenant.slug
    });
    setShowRenameDialog(true);
  };

  const handleRenameTenant = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!renamingTenant) return;

    try {
      const result = await updateTenant(renamingTenant.id, {
        name: renameData.name,
        description: renameData.description,
        slug: renameData.slug
      });
      const data = JSON.parse(result);

      if (data.success) {
        showMessage('success', 'Tenant renamed successfully');
        setShowRenameDialog(false);
        setRenamingTenant(null);
        setRenameData({ name: '', description: '', slug: '' });
        await loadTenants();
        if (selectedTenant?.id === renamingTenant.id) {
          setSelectedTenant({
            ...selectedTenant,
            name: renameData.name,
            description: renameData.description,
            slug: renameData.slug
          });
        }
      } else {
        showMessage('error', data.error || 'Failed to rename tenant');
      }
    } catch (error) {
      console.error('Error renaming tenant:', error);
      showMessage('error', 'Failed to rename tenant');
    }
  };

  const handleDeleteTenant = async (tenant: Tenant) => {
    // DESIGN.md §8 names tenants as a type-to-confirm case outright: this is the largest
    // blast radius in the admin console, and the row it sits in looks like any other.
    const confirmed = await confirm(
      destructiveConfirm({
        action: 'Delete',
        noun: 'tenant',
        name: tenant.name,
        consequence:
          'Every member loses access, and the projects, versions and API keys belonging to this tenant go with it.',
        typeToConfirm: true,
        confirmLabel: 'Delete tenant',
      })
    );
    if (!confirmed) return;

    try {
      const result = await deleteTenant(tenant.id);
      const data = JSON.parse(result);

      if (data.success) {
        showMessage('success', 'Tenant deleted successfully');
        await loadTenants();
        if (selectedTenant?.id === tenant.id) {
          setSelectedTenant(null);
          setTenantUsers([]);
        }
      } else {
        showMessage('error', data.error || 'Failed to delete tenant');
      }
    } catch (error) {
      console.error('Error deleting tenant:', error);
      showMessage('error', 'Failed to delete tenant');
    }
  };

  const handleAddUser = async (userId: string) => {
    if (!selectedTenant) return;

    try {
      const result = await addUserToTenant(selectedTenant.id, userId);
      const data = JSON.parse(result);

      if (data.success) {
        showMessage('success', 'User added to tenant successfully');
        setShowAddUserDialog(false);
        await loadTenantUsers(selectedTenant.id);
        await loadTenants();
      } else {
        showMessage('error', data.error || 'Failed to add user');
      }
    } catch (error) {
      console.error('Error adding user:', error);
      showMessage('error', 'Failed to add user');
    }
  };

  const handleRemoveUser = async (user: TenantUser) => {
    if (!selectedTenant) return;

    const confirmed = await confirm(
      destructiveConfirm({
        action: 'Remove',
        name: user.name,
        consequence: `They lose access to "${selectedTenant.name}" immediately. Their account and any other tenant they belong to are untouched.`,
        confirmLabel: 'Remove from tenant',
      })
    );
    if (!confirmed) return;

    try {
      const result = await removeUserFromTenant(selectedTenant.id, user.id);
      const data = JSON.parse(result);

      if (data.success) {
        showMessage('success', 'User removed successfully');
        await loadTenantUsers(selectedTenant.id);
        await loadTenants();
      } else {
        showMessage('error', data.error || 'Failed to remove user');
      }
    } catch (error) {
      console.error('Error removing user:', error);
      showMessage('error', 'Failed to remove user');
    }
  };

  const handleToggleAdmin = async (user: TenantUser) => {
    if (!selectedTenant) return;

    try {
      const result = user.is_admin
        ? await removeTenantAdministrator(selectedTenant.id, user.id)
        : await addTenantAdministrator(selectedTenant.id, user.id);
      const data = JSON.parse(result);

      if (data.success) {
        showMessage('success', `Admin status updated successfully`);
        await loadTenantUsers(selectedTenant.id);
        await loadTenants();
      } else {
        showMessage('error', data.error || 'Failed to update admin status');
      }
    } catch (error) {
      console.error('Error updating admin status:', error);
      showMessage('error', 'Failed to update admin status');
    }
  };

  const generateSlug = (name: string) => {
    return name
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-|-$/g, '');
  };

  return (
    <>
      {/* Header */}
      <header className="shrink-0 border-b border-border bg-surface">
        <div className="px-6 py-4">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-2xl font-bold text-fg">Tenants</h2>
              <p className="text-fg-muted text-sm mt-1">Manage tenants and assign users</p>
            </div>
            <Button
              onClick={() => setShowCreateDialog(true)}
              variant="primary"
            >
              <Plus className="w-4 h-4" />
              Create Tenant
            </Button>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="min-h-0 flex-1 overflow-y-auto bg-subtle p-6">
        <div className="space-y-6">
          {/* Message Banner */}
          {message && (
            <div
              className={`p-4 rounded-lg border flex items-start gap-3 ${
                message.type === 'success'
                  ? 'bg-ok/20 border-ok text-ok-fg'
                  : 'bg-danger/20 border-danger text-danger-fg'
              }`}
            >
              {message.type === 'success' ? (
                <CheckCircle className="w-5 h-5 flex-shrink-0 mt-0.5" />
              ) : (
                <AlertCircle className="w-5 h-5 flex-shrink-0 mt-0.5" />
              )}
              <p className="text-sm">{message.text}</p>
            </div>
          )}

          {/* Stats Grid */}
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            <div className="bg-surface border border-border rounded-lg p-4">
              <div className="flex items-center gap-3 mb-2">
                <div className="p-2 bg-violet/20 rounded-lg">
                  <Building2 className="w-5 h-5 text-violet-fg" />
                </div>
                <div>
                  <p className="text-fg-muted text-xs">Total Tenants</p>
                  <p className="text-fg text-xl font-bold">{tenants.length}</p>
                </div>
              </div>
            </div>

            <div className="bg-surface border border-border rounded-lg p-4">
              <div className="flex items-center gap-3 mb-2">
                <div className="p-2 bg-accent/20 rounded-lg">
                  <Users className="w-5 h-5 text-accent-fg" />
                </div>
                <div>
                  <p className="text-fg-muted text-xs">Total Users</p>
                  <p className="text-fg text-xl font-bold">
                    {tenants.reduce((sum, t) => sum + (t.user_count || 0), 0)}
                  </p>
                </div>
              </div>
            </div>

            <div className="bg-surface border border-border rounded-lg p-4">
              <div className="flex items-center gap-3 mb-2">
                <div className="p-2 bg-orange/20 rounded-lg">
                  <Shield className="w-5 h-5 text-orange-fg" />
                </div>
                <div>
                  <p className="text-fg-muted text-xs">Total Admins</p>
                  <p className="text-fg text-xl font-bold">
                    {tenants.reduce((sum, t) => sum + (t.admin_count || 0), 0)}
                  </p>
                </div>
              </div>
            </div>

            <div className="bg-surface border border-border rounded-lg p-4">
              <div className="flex items-center gap-3 mb-2">
                <div className="p-2 bg-ok/20 rounded-lg">
                  <CheckCircle className="w-5 h-5 text-ok-fg" />
                </div>
                <div>
                  <p className="text-fg-muted text-xs">Active Tenants</p>
                  <p className="text-fg text-xl font-bold">
                    {tenants.filter((t) => t.enabled).length}
                  </p>
                </div>
              </div>
            </div>
          </div>

          {/* Refresh Button */}
          <div className="flex justify-end">
            <button
              onClick={loadTenants}
              disabled={loading}
              className="flex items-center gap-2 px-4 py-2 bg-inset hover:bg-inset text-fg-muted rounded-lg transition-colors disabled:opacity-50"
            >
              <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
              Refresh
            </button>
          </div>

          {/* Main Content Grid */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Tenants List */}
            <div className="bg-surface border border-border rounded-lg">
              <div className="p-4 border-b border-border">
                <h3 className="text-lg font-semibold text-fg">Tenants</h3>
              </div>
              <div className="max-h-[600px] divide-y divide-border overflow-y-auto">
                {loading ? (
                  <LoadingState message="Loading tenants…" skeleton={<SkeletonText lines={6} className="p-4" />} />
                ) : tenants.length === 0 ? (
                  <EmptyState
                    variant="compact"
                    surface={false}
                    icon={<Building2 />}
                    title="No tenants yet"
                    description="Create a tenant to group users and their projects."
                  />
                ) : (
                  tenants.map((tenant) => (
                    <div
                      key={tenant.id}
                      className={`cursor-pointer p-4 transition-colors hover:bg-subtle ${
                        selectedTenant?.id === tenant.id
                          ? 'border-l-4 border-danger bg-danger-soft'
                          : ''
                      }`}
                      onClick={() => handleSelectTenant(tenant)}
                    >
                      <div className="flex items-start justify-between mb-2">
                        <div className="flex-1">
                          <h4 className="text-fg font-medium">{tenant.name}</h4>
                          <p className="text-fg-muted text-sm mt-1">{tenant.slug}</p>
                        </div>
                        <div className="relative">
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
                              setDropdownPosition({
                                top: rect.bottom + 4,
                                right: window.innerWidth - rect.right
                              });
                              setOpenTenantDropdown(openTenantDropdown === tenant.id ? null : tenant.id);
                            }}
                            className="p-1 hover:bg-subtle rounded-xs transition-colors text-fg-subtle hover:text-fg-muted"
                            title="Actions"
                          >
                            <MoreVertical className="w-4 h-4" />
                          </button>

                          {openTenantDropdown === tenant.id && dropdownPosition && (
                            <>
                              <div
                                className="fixed inset-0 z-10"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setOpenTenantDropdown(null);
                                }}
                              />
                              <div
                                className="fixed w-48 min-w-0 overflow-x-hidden bg-surface border border-border rounded-lg shadow-lg z-20"
                                style={{
                                  top: `${dropdownPosition.top}px`,
                                  right: `${dropdownPosition.right}px`
                                }}>
                                <div className="py-1">
                                  <button
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      setOpenTenantDropdown(null);
                                      handleOpenRenameDialog(tenant);
                                    }}
                                    className="w-full px-4 py-2 text-left text-sm hover:bg-subtle flex items-center gap-3 text-fg-muted hover:text-fg transition-colors"
                                  >
                                    <Edit className="w-4 h-4 text-accent-fg" />
                                    Edit Tenant
                                  </button>
                                  <button
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      setOpenTenantDropdown(null);
                                      handleToggleTenantEnabled(tenant);
                                    }}
                                    className="w-full px-4 py-2 text-left text-sm hover:bg-subtle flex items-center gap-3 text-fg-muted hover:text-fg transition-colors"
                                  >
                                    <Power className={`w-4 h-4 ${tenant.enabled ? 'text-orange-fg' : 'text-ok-fg'}`} />
                                    {tenant.enabled ? 'Disable Tenant' : 'Enable Tenant'}
                                  </button>
                                  <button
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      setOpenTenantDropdown(null);
                                      handleDeleteTenant(tenant);
                                    }}
                                    className="w-full px-4 py-2 text-left text-sm hover:bg-subtle flex items-center gap-3 text-danger-fg hover:text-danger-fg transition-colors"
                                  >
                                    <Trash2 className="w-4 h-4" />
                                    Delete Tenant
                                  </button>
                                </div>
                              </div>
                            </>
                          )}
                        </div>
                      </div>
                      <div className="flex items-center gap-4 text-xs text-fg-muted">
                        <span className="flex items-center gap-1">
                          <Users className="w-3 h-3" />
                          {tenant.user_count || 0} users
                        </span>
                        <span className="flex items-center gap-1">
                          <Shield className="w-3 h-3" />
                          {tenant.admin_count || 0} admins
                        </span>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>

            {/* Tenant Users */}
            <div className="bg-surface border border-border rounded-lg">
              <div className="p-4 border-b border-border flex items-center justify-between">
                <h3 className="text-lg font-semibold text-fg">
                  {selectedTenant ? `Users in ${selectedTenant.name}` : 'Select a Tenant'}
                </h3>
                {selectedTenant && (
                  <Button
                    onClick={() => setShowAddUserDialog(true)}
                    variant="accent" size="sm"
                  >
                    <UserPlus className="w-4 h-4" />
                    Add User
                  </Button>
                )}
              </div>
              <div className="max-h-[600px] divide-y divide-border overflow-y-auto">
                {!selectedTenant ? (
                  <div className="p-12 text-center">
                    <Building2 className="w-12 h-12 text-fg-muted mx-auto mb-4" />
                    <p className="text-fg-subtle text-sm">Select a tenant to view users</p>
                  </div>
                ) : tenantUsers.length === 0 ? (
                  <EmptyState
                    variant="compact"
                    surface={false}
                    icon={<Users />}
                    title="No users in this tenant"
                    description="Add users to give them access to its projects."
                  />
                ) : (
                  tenantUsers.map((user) => (
                    <div key={user.id} className="p-4 hover:bg-subtle">
                      <div className="flex items-start justify-between">
                        <div className="flex items-start gap-3 flex-1">
                          <div className="w-8 h-8 bg-accent/20 rounded-full flex items-center justify-center flex-shrink-0">
                            <span className="text-accent-fg text-sm font-medium">
                              {user.name.charAt(0).toUpperCase()}
                            </span>
                          </div>
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 mb-1">
                              <h4 className="text-fg font-medium truncate">{user.name}</h4>
                              {user.is_admin && (
                                <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-orange/20 text-orange-fg text-xs rounded-xs">
                                  <Shield className="w-3 h-3" />
                                  Admin
                                </span>
                              )}
                            </div>
                            <p className="text-fg-muted text-sm truncate">{user.email}</p>
                          </div>
                        </div>
                        <div className="relative flex-shrink-0">
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
                              setDropdownPosition({
                                top: rect.bottom + 4,
                                right: window.innerWidth - rect.right
                              });
                              setOpenUserDropdown(openUserDropdown === user.id ? null : user.id);
                            }}
                            className="p-1 hover:bg-subtle rounded-xs transition-colors text-fg-subtle hover:text-fg-muted"
                            title="Actions"
                          >
                            <MoreVertical className="w-4 h-4" />
                          </button>

                          {openUserDropdown === user.id && dropdownPosition && (
                            <>
                              <div
                                className="fixed inset-0 z-10"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setOpenUserDropdown(null);
                                }}
                              />
                              <div
                                className="fixed w-52 min-w-0 overflow-x-hidden bg-surface border border-border rounded-lg shadow-lg z-20"
                                style={{
                                  top: `${dropdownPosition.top}px`,
                                  right: `${dropdownPosition.right}px`
                                }}>
                                <div className="py-1">
                                  <button
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      setOpenUserDropdown(null);
                                      handleToggleAdmin(user);
                                    }}
                                    className="w-full px-4 py-2 text-left text-sm hover:bg-subtle flex items-center gap-3 text-fg-muted hover:text-fg transition-colors"
                                  >
                                    {user.is_admin ? (
                                      <>
                                        <ShieldX className="w-4 h-4 text-orange-fg" />
                                        Remove Admin Rights
                                      </>
                                    ) : (
                                      <>
                                        <ShieldCheck className="w-4 h-4 text-ok-fg" />
                                        Make Administrator
                                      </>
                                    )}
                                  </button>
                                  <button
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      setOpenUserDropdown(null);
                                      handleRemoveUser(user);
                                    }}
                                    className="w-full px-4 py-2 text-left text-sm hover:bg-subtle flex items-center gap-3 text-danger-fg hover:text-danger-fg transition-colors"
                                  >
                                    <UserX className="w-4 h-4" />
                                    Remove from Tenant
                                  </button>
                                </div>
                              </div>
                            </>
                          )}
                        </div>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>
        </div>
      </main>

      {/* Create Tenant Dialog */}
      {showCreateDialog && (
        <ModalFrame
          open
          onClose={() => setShowCreateDialog(false)}
          label="Create New Tenant"
          overlayClassName="fixed inset-0 z-[200] flex items-center justify-center bg-overlay p-4 backdrop-blur-sm"
          className="bg-surface border border-border rounded-xl max-w-md w-full shadow-lg"
        >
            <div className="p-4 border-b border-border flex items-center justify-between">
              <h3 className="text-lg font-semibold text-fg">Create New Tenant</h3>
              <button
                onClick={() => setShowCreateDialog(false)}
                className="text-fg-subtle hover:text-fg transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <form onSubmit={handleCreateTenant} className="p-4 space-y-4">
              <div>
                <label className="block text-sm font-medium text-fg mb-[var(--space-field)]">
                  Tenant Name *
                </label>
                <Input
                  type="text"
                  value={newTenant.name}
                  onChange={(e) => {
                    setNewTenant({
                      ...newTenant,
                      name: e.target.value,
                      slug: newTenant.slug || generateSlug(e.target.value),
                    });
                  }}
                  placeholder="Acme Corporation"
                  required
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-fg mb-[var(--space-field)]">
                  Slug *
                </label>
                <Input
                  type="text"
                  value={newTenant.slug}
                  onChange={(e) => setNewTenant({ ...newTenant, slug: e.target.value })}
                  placeholder="acme-corporation"
                  required
                  pattern="[a-z0-9-]+"
                  title="Only lowercase letters, numbers, and hyphens"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-fg mb-[var(--space-field)]">
                  Description
                </label>
                <Textarea
                  value={newTenant.description}
                  onChange={(e) => setNewTenant({ ...newTenant, description: e.target.value })}
                  className="min-h-[80px]"
                  placeholder="Description of the tenant..."
                />
              </div>

              {/* Initial User Selection */}
              <div className="border-t border-border pt-4">
                <label className="block text-sm font-medium text-fg mb-[var(--space-field)]">
                  Initial User (Optional)
                </label>
                <select
                  value={newTenant.initialUserId}
                  onChange={(e) => setNewTenant({ ...newTenant, initialUserId: e.target.value })}
                  className="hive-control h-[var(--control-h)] w-full rounded-md bg-surface px-3 text-sm text-fg focus-visible:outline-none"
                >
                  <option value="">-- No initial user --</option>
                  {allUsers.map((user) => (
                    <option key={user.id} value={user.id}>
                      {user.name} ({user.email})
                    </option>
                  ))}
                </select>
                <p className="text-fg-muted text-xs mt-1">
                  Add a user to this tenant immediately upon creation
                </p>
              </div>

              {/* Make Admin Checkbox */}
              {newTenant.initialUserId && (
                <div className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    id="makeAdmin"
                    checked={newTenant.makeAdmin}
                    onChange={(e) => setNewTenant({ ...newTenant, makeAdmin: e.target.checked })}
                    className="w-4 h-4 rounded-xs border-border-strong bg-surface text-danger-fg focus:ring-2 focus:ring-danger focus:ring-offset-0"
                  />
                  <label htmlFor="makeAdmin" className="text-sm text-fg-muted flex items-center gap-2">
                    <Shield className="w-4 h-4 text-orange-fg" />
                    Make this user a tenant administrator
                  </label>
                </div>
              )}

              <div className="flex items-center justify-end gap-2 pt-2">
                <Button
                  type="button"
                  onClick={() => setShowCreateDialog(false)}
                  variant="ghost"
                >
                  Cancel
                </Button>
                <Button
                  type="submit"
                  variant="primary"
                >
                  Create Tenant
                </Button>
              </div>
            </form>
        </ModalFrame>
      )}

      {/* Rename Tenant Dialog */}
      {showRenameDialog && renamingTenant && (
        <ModalFrame
          open
          onClose={() => {
            setShowRenameDialog(false);
            setRenamingTenant(null);
          }}
          label="Edit Tenant"
          overlayClassName="fixed inset-0 z-[200] flex items-center justify-center bg-overlay p-4 backdrop-blur-sm"
          className="bg-surface border border-border rounded-xl max-w-md w-full shadow-lg"
        >
            <div className="p-4 border-b border-border flex items-center justify-between">
              <h3 className="text-lg font-semibold text-fg">Edit Tenant</h3>
              <button
                onClick={() => {
                  setShowRenameDialog(false);
                  setRenamingTenant(null);
                }}
                className="text-fg-subtle hover:text-fg transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <form onSubmit={handleRenameTenant} className="p-4 space-y-4">
              <div>
                <label className="block text-sm font-medium text-fg mb-[var(--space-field)]">
                  Tenant Name *
                </label>
                <Input
                  type="text"
                  value={renameData.name}
                  onChange={(e) => {
                    setRenameData({
                      ...renameData,
                      name: e.target.value,
                      slug: renameData.slug || generateSlug(e.target.value),
                    });
                  }}
                  placeholder="Acme Corporation"
                  required
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-fg mb-[var(--space-field)]">
                  Slug *
                </label>
                <Input
                  type="text"
                  value={renameData.slug}
                  onChange={(e) => setRenameData({ ...renameData, slug: e.target.value })}
                  placeholder="acme-corporation"
                  required
                  pattern="[a-z0-9-]+"
                  title="Only lowercase letters, numbers, and hyphens"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-fg mb-[var(--space-field)]">
                  Description
                </label>
                <Textarea
                  value={renameData.description}
                  onChange={(e) => setRenameData({ ...renameData, description: e.target.value })}
                  className="min-h-[80px]"
                  placeholder="Description of the tenant..."
                />
              </div>
              <div className="flex items-center justify-end gap-2 pt-2">
                <Button
                  type="button"
                  onClick={() => {
                    setShowRenameDialog(false);
                    setRenamingTenant(null);
                  }}
                  variant="ghost"
                >
                  Cancel
                </Button>
                <Button
                  type="submit"
                  variant="accent"
                >
                  Save Changes
                </Button>
              </div>
            </form>
        </ModalFrame>
      )}

      {/* Add User Dialog */}
      {showAddUserDialog && selectedTenant && (
        <ModalFrame
          open
          onClose={() => setShowAddUserDialog(false)}
          label="Add User to Tenant"
          overlayClassName="fixed inset-0 z-[200] flex items-center justify-center bg-overlay p-4 backdrop-blur-sm"
          className="bg-surface border border-border rounded-xl max-w-md w-full max-h-[80vh] flex flex-col shadow-lg"
        >
            <div className="p-4 border-b border-border flex items-center justify-between">
              <h3 className="text-lg font-semibold text-fg">Add User to Tenant</h3>
              <button
                onClick={() => setShowAddUserDialog(false)}
                className="text-fg-subtle hover:text-fg transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto p-4">
              {availableUsers.length === 0 ? (
                <EmptyState
                  variant="compact"
                  surface={false}
                  icon={<Users />}
                  title="Everyone is already here"
                  description="Every user already belongs to this tenant."
                />
              ) : (
                <div className="space-y-2">
                  {availableUsers.map((user) => (
                    <button
                      key={user.id}
                      onClick={() => handleAddUser(user.id)}
                      className="w-full p-3 bg-subtle hover:bg-subtle border border-border hover:border-border-strong rounded-lg transition-colors text-left"
                    >
                      <div className="flex items-center gap-3">
                        <div className="w-8 h-8 bg-accent/20 rounded-full flex items-center justify-center">
                          <span className="text-accent-fg text-sm font-medium">
                            {user.name.charAt(0).toUpperCase()}
                          </span>
                        </div>
                        <div>
                          <p className="text-fg font-medium">{user.name}</p>
                          <p className="text-fg-muted text-sm">{user.email}</p>
                        </div>
                      </div>
                    </button>
                  ))}
                </div>
              )}
            </div>
        </ModalFrame>
      )}
    </>
  );
}

