'use client';

import { useSession } from 'next-auth/react';
import { getTenantsForUser, getTenantsAdministratedByUser, getTenantUsers, addTenantAdministrator, addTenantUser, removeTenantAdministrator, removeTenantUser } from '../../../../../lib/db/helper';
import { useEffect, useState } from 'react';
import { Plus, Trash2, Users, Shield, ChevronDown, ChevronUp, X, Building2, Edit2 } from 'lucide-react';
import Dialog from '@mui/material/Dialog';
import DialogTitle from '@mui/material/DialogTitle';
import DialogContent from '@mui/material/DialogContent';
import DialogActions from '@mui/material/DialogActions';
import Button from '@mui/material/Button';
import TextField from '@mui/material/TextField';
import Alert from '@mui/material/Alert';
import Checkbox from '@mui/material/Checkbox';
import FormControlLabel from '@mui/material/FormControlLabel';

interface Tenant {
  id: string;
  name: string;
  description: string;
  slug: string;
  enabled: boolean;
  deleted_at: string | null;
  created_at: string;
  updated_at: string;
}

interface AdminUser {
  id: string;
  tenant_id: string;
  user_id: string;
  name: string;
  email: string;
}

interface TenantUser {
  id: string;
  tenant_id: string;
  user_id: string;
  name: string;
  email: string;
}

const Tenants = () => {
  const { data: session, update } = useSession();
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [adminTenants, setAdminTenants] = useState<AdminUser[]>([]);
  const [tenantUsers, setTenantUsers] = useState<Record<string, TenantUser[]>>({});
  const [isMembersExpanded, setIsMembersExpanded] = useState(false);
  const [memberFilter, setMemberFilter] = useState('');
  const [showAddMemberModal, setShowAddMemberModal] = useState(false);
  const [showEditMemberModal, setShowEditMemberModal] = useState(false);
  const [selectedTenantId, setSelectedTenantId] = useState<string>('');
  const [memberEmail, setMemberEmail] = useState('');
  const [isAdmin, setIsAdmin] = useState(false);
  const [editingMember, setEditingMember] = useState<{ userId: string; name: string; email: string; isAdmin: boolean } | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');
  const currentTenantId = (session?.user as any)?.current_tenant_id;
  const currentUserId = (session?.user as any)?.user_id;

  useEffect(() => {
    if (session) {
      const userId: string = (session.user as any)?.user_id;

      getTenantsForUser(userId)
        .then(x => {
          setTenants(JSON.parse(x));
        });

      getTenantsAdministratedByUser(userId)
        .then(x => {
          setAdminTenants(JSON.parse(x));
        });
    }
  }, [session]);

  useEffect(() => {
    // Load tenant users for all tenants where current user is an admin
    if (adminTenants.length > 0) {
      const adminTenantIds = [...new Set(adminTenants.map(admin => admin.tenant_id))];

      adminTenantIds.forEach(tenantId => {
        getTenantUsers(tenantId).then(x => {
          const users = JSON.parse(x);
          setTenantUsers(prev => ({
            ...prev,
            [tenantId]: users
          }));
        });
      });
    }
  }, [adminTenants]);

  const refreshData = async () => {
    if (session) {
      const userId: string = (session.user as any)?.user_id;

      const [tenantsData, adminTenantsData] = await Promise.all([
        getTenantsForUser(userId),
        getTenantsAdministratedByUser(userId)
      ]);

      setTenants(JSON.parse(tenantsData));
      const admins = JSON.parse(adminTenantsData);
      setAdminTenants(admins);

      // Refresh tenant users for all admin tenants
      const adminTenantIds = [...new Set(admins.map((admin: AdminUser) => admin.tenant_id))];
      const usersMap: Record<string, TenantUser[]> = {};

      await Promise.all(
        adminTenantIds.map(async (tenantId: any) => {
          const users = await getTenantUsers(tenantId);
          usersMap[tenantId] = JSON.parse(users);
        })
      );

      setTenantUsers(usersMap);
    }
  };

  const handleSelectTenant = async (tenant: Tenant) => {
    const tenantId = tenant.id;

    await update({
      current_tenant_id: tenantId,
    });
  };

  const handleAddMember = (tenantId: string) => {
    setSelectedTenantId(tenantId);
    setMemberEmail('');
    setIsAdmin(false);
    setErrorMessage('');
    setShowAddMemberModal(true);
  };

  const handleAddMemberSubmit = async () => {
    if (!memberEmail.trim()) {
      setErrorMessage('Please enter an email address');
      return;
    }

    setIsLoading(true);
    setErrorMessage('');

    try {
      // Add as tenant user first
      const userResult = await addTenantUser(selectedTenantId, memberEmail.trim());
      const userResponse = JSON.parse(userResult);

      if (!userResponse.success) {
        setErrorMessage(userResponse.error || 'Failed to add member');
        setIsLoading(false);
        return;
      }

      // If admin role is selected, also add as administrator
      if (isAdmin) {
        const adminResult = await addTenantAdministrator(selectedTenantId, memberEmail.trim());
        const adminResponse = JSON.parse(adminResult);

        if (!adminResponse.success) {
          setErrorMessage(adminResponse.error || 'Failed to add administrator role');
          setIsLoading(false);
          return;
        }
      }

      setShowAddMemberModal(false);
      setMemberEmail('');
      setIsAdmin(false);
      await refreshData();
    } catch (error: any) {
      setErrorMessage(error.message || 'An error occurred');
    } finally {
      setIsLoading(false);
    }
  };

  const handleEditMember = (member: { userId: string; name: string; email: string; isAdmin: boolean }) => {
    setEditingMember(member);
    setIsAdmin(member.isAdmin);
    setErrorMessage('');
    setShowEditMemberModal(true);
  };

  const handleEditMemberSubmit = async () => {
    if (!editingMember) return;

    setIsLoading(true);
    setErrorMessage('');

    try {
      const members = getMembersForTenant(selectedTenantId);
      const member = members.find((m: any) => m.userId === editingMember.userId);

      if (!member) {
        setErrorMessage('Member not found');
        setIsLoading(false);
        return;
      }

      // Handle admin role changes
      if (isAdmin && !member.isAdmin) {
        // Add admin role
        const result = await addTenantAdministrator(selectedTenantId, member.email);
        const response = JSON.parse(result);
        if (!response.success) {
          setErrorMessage(response.error || 'Failed to add administrator role');
          setIsLoading(false);
          return;
        }
      } else if (!isAdmin && member.isAdmin && member.adminRecordId) {
        // Remove admin role
        const result = await removeTenantAdministrator(member.adminRecordId);
        const response = JSON.parse(result);
        if (!response.success) {
          setErrorMessage(response.error || 'Failed to remove administrator role');
          setIsLoading(false);
          return;
        }
      }

      setShowEditMemberModal(false);
      setEditingMember(null);
      await refreshData();
    } catch (error: any) {
      setErrorMessage(error.message || 'An error occurred');
    } finally {
      setIsLoading(false);
    }
  };

  const handleRemoveMember = async (member: { userId: string; name: string; isAdmin: boolean; adminRecordId?: string; userRecordId?: string }) => {
    // Enhanced warning for administrators
    const warningMessage = member.isAdmin
      ? `Are you sure you want to remove ${member.name} from the tenant?\n\n⚠️ WARNING: This user is also an ADMINISTRATOR and will lose all administrative privileges.`
      : `Are you sure you want to remove ${member.name} from the tenant?`;

    if (!confirm(warningMessage)) {
      return;
    }

    try {
      // Remove admin role if exists
      if (member.adminRecordId) {
        const adminResult = await removeTenantAdministrator(member.adminRecordId);
        const adminResponse = JSON.parse(adminResult);
        if (!adminResponse.success) {
          alert(adminResponse.error || 'Failed to remove administrator role');
          return;
        }
      }

      // Remove user role if exists
      if (member.userRecordId) {
        const userResult = await removeTenantUser(member.userRecordId);
        const userResponse = JSON.parse(userResult);
        if (!userResponse.success) {
          alert(userResponse.error || 'Failed to remove member');
          return;
        }
      }

      await refreshData();
    } catch (error: any) {
      alert(error.message || 'An error occurred');
    }
  };

  const getMembersForTenant = (tenantId: string) => {
    const users = tenantUsers[tenantId] || [];
    const admins = adminTenants.filter((admin: AdminUser) => admin.tenant_id === tenantId);

    // Create a map of all members with their roles
    const memberMap = new Map<string, { userId: string; name: string; email: string; isAdmin: boolean; isMember: boolean; adminRecordId?: string; userRecordId?: string }>();

    // Add all users
    users.forEach((user: TenantUser) => {
      memberMap.set(user.user_id, {
        userId: user.user_id,
        name: user.name,
        email: user.email,
        isAdmin: false,
        isMember: true,
        userRecordId: user.id
      });
    });

    // Add admin role to existing members or create new entries for admins
    admins.forEach((admin: AdminUser) => {
      if (memberMap.has(admin.user_id)) {
        const member = memberMap.get(admin.user_id)!;
        member.isAdmin = true;
        member.adminRecordId = admin.id;
      } else {
        memberMap.set(admin.user_id, {
          userId: admin.user_id,
          name: admin.name,
          email: admin.email,
          isAdmin: true,
          isMember: false,
          adminRecordId: admin.id
        });
      }
    });

    let members = Array.from(memberMap.values());

    // Apply filter
    if (memberFilter) {
      const filterLower = memberFilter.toLowerCase();
      members = members.filter(member =>
        member.name.toLowerCase().includes(filterLower) ||
        member.email.toLowerCase().includes(filterLower)
      );
    }

    // Sort: admins first, then alphabetically by name
    return members.sort((a, b) => {
      if (a.isAdmin && !b.isAdmin) return -1;
      if (!a.isAdmin && b.isAdmin) return 1;
      return a.name.localeCompare(b.name);
    });
  };

  const isCurrentUserAdmin = (tenantId: string) => {
    return adminTenants.some((admin: AdminUser) => admin.tenant_id === tenantId && admin.user_id === currentUserId);
  };

  return (
    <div className="p-6">
      <div className="flex justify-between items-center mb-6">
        <div>
          <h1 className="text-3xl font-bold mb-2">Tenants</h1>
          <p className="text-gray-600 dark:text-gray-400">
            Manage tenants and switch between them
          </p>
        </div>
      </div>

      {tenants.length === 0 ? (
        <div className="bg-gray-50 dark:bg-gray-800 border-2 border-dashed border-gray-300 dark:border-gray-600 rounded-lg p-12 text-center">
          <Building2 className="h-16 w-16 text-gray-400 dark:text-gray-500 mx-auto mb-4" />
          <h3 className="text-xl font-semibold text-gray-700 dark:text-gray-300 mb-2">
            No Tenants Available
          </h3>
          <p className="text-gray-600 dark:text-gray-400">
            You are not a member of any tenants yet
          </p>
        </div>
      ) : (
        <div className="space-y-6">
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow overflow-hidden">
            <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
              <thead className="bg-gray-50 dark:bg-gray-900">
                <tr>
                  <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                    Tenant Name
                  </th>
                  <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                    Description
                  </th>
                  <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                    Status
                  </th>
                  <th scope="col" className="px-6 py-3 text-right text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white dark:bg-gray-800 divide-y divide-gray-200 dark:divide-gray-700">
                {tenants.map(tenant => (
                  <tr
                    key={tenant.id}
                    className={`transition-colors ${
                      tenant.id === currentTenantId 
                        ? 'bg-blue-50 dark:bg-blue-900/20' 
                        : 'hover:bg-gray-50 dark:hover:bg-gray-700'
                    }`}
                  >
                    <td className="px-6 py-4 whitespace-nowrap">
                      <div className="flex items-center gap-2">
                        <div className="text-sm font-medium text-gray-900 dark:text-white">
                          {tenant.name}
                        </div>
                        {tenant.id === currentTenantId && (
                          <span className="inline-flex px-2 py-1 text-xs font-semibold rounded-full bg-blue-100 text-blue-800">
                            Current
                          </span>
                        )}
                      </div>
                      <div className="text-xs text-gray-500 dark:text-gray-400">
                        {tenant.slug}
                      </div>
                    </td>
                    <td className="px-6 py-4">
                      <div className="text-sm text-gray-600 dark:text-gray-400 max-w-xs truncate">
                        {tenant.description || '—'}
                      </div>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      {tenant.enabled ? (
                        <span className="inline-flex px-2 py-1 text-xs font-semibold rounded-full bg-green-100 text-green-800">
                          Enabled
                        </span>
                      ) : (
                        <span className="inline-flex px-2 py-1 text-xs font-semibold rounded-full bg-red-100 text-red-800">
                          Disabled
                        </span>
                      )}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                      <div className="flex justify-end gap-2">
                        {tenant.id !== currentTenantId && (
                          <button
                            onClick={() => handleSelectTenant(tenant)}
                            className="px-3 py-1 bg-blue-600 hover:bg-blue-700 text-white rounded cursor-pointer transition-colors text-sm font-medium"
                          >
                            Select
                          </button>
                        )}
                        {isCurrentUserAdmin(tenant.id) && (
                          <button
                            onClick={() => {
                              // Toggle expanded state for this specific tenant
                              const expandedTenant = document.getElementById(`tenant-${tenant.id}`);
                              if (expandedTenant) {
                                expandedTenant.classList.toggle('hidden');
                              }
                            }}
                            className="px-3 py-1 bg-gray-600 hover:bg-gray-700 text-white rounded cursor-pointer transition-colors text-sm font-medium"
                          >
                            Manage
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Admin sections for each tenant */}
          {tenants.map(tenant => (
            isCurrentUserAdmin(tenant.id) && (
              <div
                key={`admin-${tenant.id}`}
                id={`tenant-${tenant.id}`}
                className="hidden bg-white dark:bg-gray-800 rounded-lg shadow p-6"
              >
                <h2 className="text-xl font-bold mb-4 flex items-center gap-2">
                  <Building2 className="h-5 w-5" />
                  {tenant.name} - Administration
                </h2>

                <div className="space-y-6">
                  {/* Members (Users and Administrators Combined) */}
                  <div>
                    <div className="flex justify-between items-center mb-3">
                      <button
                        onClick={() => setIsMembersExpanded(!isMembersExpanded)}
                        className="text-lg font-semibold flex items-center gap-2 cursor-pointer hover:text-gray-700 dark:hover:text-gray-300 transition-colors"
                      >
                        <Users className="h-5 w-5" />
                        Members
                        {isMembersExpanded ? (
                          <ChevronUp className="h-4 w-4" />
                        ) : (
                          <ChevronDown className="h-4 w-4" />
                        )}
                      </button>
                      <button
                        onClick={() => {
                          setSelectedTenantId(tenant.id);
                          handleAddMember(tenant.id);
                        }}
                        className="flex items-center gap-1 bg-green-600 hover:bg-green-700 text-white font-bold py-2 px-4 rounded-lg cursor-pointer text-sm transition-colors"
                      >
                        <Plus className="h-4 w-4" />
                        Add Member
                      </button>
                    </div>
                    {isMembersExpanded && (
                      <>
                        <div className="relative mb-3">
                          <input
                            type="text"
                            placeholder="Filter by name or email..."
                            value={memberFilter}
                            onChange={(e) => setMemberFilter(e.target.value)}
                            className="w-full p-2 pr-8 border border-gray-300 dark:border-gray-600 rounded-lg text-sm bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                          />
                          {memberFilter && (
                            <button
                              onClick={() => setMemberFilter('')}
                              className="absolute right-2 top-1/2 transform -translate-y-1/2 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 cursor-pointer"
                            >
                              <X className="h-4 w-4" />
                            </button>
                          )}
                        </div>
                        <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden">
                          <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
                            <thead className="bg-gray-50 dark:bg-gray-900">
                              <tr>
                                <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                                  Name
                                </th>
                                <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                                  Email
                                </th>
                                <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                                  Role
                                </th>
                                <th scope="col" className="px-6 py-3 text-right text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                                  Actions
                                </th>
                              </tr>
                            </thead>
                            <tbody className="bg-white dark:bg-gray-800 divide-y divide-gray-200 dark:divide-gray-700">
                              {getMembersForTenant(tenant.id).length === 0 ? (
                                <tr>
                                  <td colSpan={4} className="px-6 py-4 text-center text-gray-500 dark:text-gray-400 text-sm italic">
                                    No members match the filter
                                  </td>
                                </tr>
                              ) : (
                                getMembersForTenant(tenant.id).map((member) => (
                                  <tr key={member.userId} className="hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors">
                                    <td className="px-6 py-4 whitespace-nowrap">
                                      <div className="text-sm font-medium text-gray-900 dark:text-white">
                                        {member.name}
                                      </div>
                                    </td>
                                    <td className="px-6 py-4 whitespace-nowrap">
                                      <div className="text-sm text-gray-600 dark:text-gray-400">
                                        {member.email}
                                      </div>
                                    </td>
                                    <td className="px-6 py-4 whitespace-nowrap">
                                      <div className="flex gap-2">
                                        {member.isAdmin && (
                                          <span className="inline-flex items-center gap-1 px-2 py-1 text-xs font-semibold rounded-full bg-purple-100 text-purple-800 dark:bg-purple-900/30 dark:text-purple-300">
                                            <Shield className="h-3 w-3" />
                                            Admin
                                          </span>
                                        )}
                                        {member.isMember && (
                                          <span className="inline-flex items-center gap-1 px-2 py-1 text-xs font-semibold rounded-full bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300">
                                            <Users className="h-3 w-3" />
                                            Member
                                          </span>
                                        )}
                                      </div>
                                    </td>
                                    <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                                      <div className="flex justify-end gap-2">
                                        {member.userId !== currentUserId && (
                                          <>
                                            <button
                                              onClick={() => {
                                                setSelectedTenantId(tenant.id);
                                                handleEditMember({
                                                  userId: member.userId,
                                                  name: member.name,
                                                  email: member.email,
                                                  isAdmin: member.isAdmin
                                                });
                                              }}
                                              className="p-2 hover:bg-gray-100 dark:hover:bg-gray-600 rounded cursor-pointer transition-colors"
                                              title="Edit roles"
                                            >
                                              <Edit2 className="h-4 w-4 text-blue-600 dark:text-blue-400" />
                                            </button>
                                            <button
                                              onClick={() => handleRemoveMember({
                                                userId: member.userId,
                                                name: member.name,
                                                isAdmin: member.isAdmin,
                                                adminRecordId: member.adminRecordId,
                                                userRecordId: member.userRecordId
                                              })}
                                              className="p-2 hover:bg-gray-100 dark:hover:bg-gray-600 rounded cursor-pointer transition-colors"
                                              title="Remove member"
                                            >
                                              <Trash2 className="h-4 w-4 text-red-600 dark:text-red-400" />
                                            </button>
                                          </>
                                        )}
                                      </div>
                                    </td>
                                  </tr>
                                ))
                              )}
                            </tbody>
                          </table>
                        </div>
                      </>
                    )}
                  </div>
                </div>
              </div>
            )
          ))}
        </div>
      )}

      {/* Add Member Modal */}
      <Dialog
        open={showAddMemberModal}
        onClose={() => !isLoading && setShowAddMemberModal(false)}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>Add Member</DialogTitle>
        <DialogContent>
          {errorMessage && (
            <Alert severity="error" sx={{ mb: 2 }}>
              {errorMessage}
            </Alert>
          )}
          <TextField
            autoFocus
            margin="dense"
            label="Email Address"
            type="email"
            fullWidth
            variant="outlined"
            value={memberEmail}
            onChange={(e) => setMemberEmail(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && !isLoading && handleAddMemberSubmit()}
            placeholder="user@example.com"
            disabled={isLoading}
            sx={{ mb: 2, mt: 1 }}
          />
          <FormControlLabel
            control={
              <Checkbox
                checked={isAdmin}
                onChange={(e) => setIsAdmin(e.target.checked)}
                disabled={isLoading}
                sx={{
                  color: 'rgba(156, 163, 175, 1)',
                  '&.Mui-checked': {
                    color: '#3b82f6',
                  },
                  '&:hover': {
                    backgroundColor: 'rgba(59, 130, 246, 0.1)',
                  },
                }}
              />
            }
            label={
              <span className="text-sm font-medium text-gray-500 dark:text-gray-400 flex items-center gap-1">
                <Shield className="h-4 w-4" />
                Administrator
              </span>
            }
          />
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-2 ml-8">
            Administrators can manage tenant members and settings. All members have access to the tenant.
          </p>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setShowAddMemberModal(false)} disabled={isLoading}>
            Cancel
          </Button>
          <Button onClick={handleAddMemberSubmit} variant="contained" disabled={isLoading}>
            {isLoading ? 'Adding...' : 'Add Member'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Edit Member Modal */}
      <Dialog
        open={showEditMemberModal}
        onClose={() => !isLoading && setShowEditMemberModal(false)}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>Edit Member Roles</DialogTitle>
        <DialogContent>
          {errorMessage && (
            <Alert severity="error" sx={{ mb: 2 }}>
              {errorMessage}
            </Alert>
          )}
          {editingMember && (
            <>
              <div className="mb-4 mt-2">
                <p className="text-sm font-medium text-gray-900 dark:text-gray-600">
                  {editingMember.name}
                </p>
                <p className="text-sm text-gray-600 dark:text-gray-400">
                  {editingMember.email}
                </p>
              </div>
              <FormControlLabel
                control={
                  <Checkbox
                    checked={isAdmin}
                    onChange={(e) => setIsAdmin(e.target.checked)}
                    disabled={isLoading}
                    sx={{
                      color: 'rgba(156, 163, 175, 1)',
                      '&.Mui-checked': {
                        color: '#3b82f6',
                      },
                      '&:hover': {
                        backgroundColor: 'rgba(59, 130, 246, 0.1)',
                      },
                    }}
                  />
                }
                label={
                  <span className="text-sm font-medium text-gray-500 dark:text-gray-400 flex items-center gap-1">
                    <Shield className="h-4 w-4" />
                    Administrator
                  </span>
                }
              />
              <p className="text-xs text-gray-500 dark:text-gray-400 mt-2 ml-8">
                Toggle administrator privileges for this member.
              </p>
            </>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setShowEditMemberModal(false)} disabled={isLoading}>
            Cancel
          </Button>
          <Button onClick={handleEditMemberSubmit} variant="contained" disabled={isLoading}>
            {isLoading ? 'Saving...' : 'Save Changes'}
          </Button>
        </DialogActions>
      </Dialog>
    </div>
  );
};

export default Tenants;