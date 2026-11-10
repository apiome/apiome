'use client';

import { useState, useEffect, type FormEvent } from 'react';
import {
  Users,
  UserPlus,
  UserCheck,
  Mail,
  Trash2,
  CheckCircle,
  XCircle,
  RefreshCw,
  AlertCircle,
  MoreVertical,
  Power,
  Award,
  Flag,
  Plus,
  ShieldOff,
  Layers,
  X,
} from 'lucide-react';
import {
  createUser,
  updateUser,
  deleteUser,
  getUserStats,
  getAllUsersWithLicenses,
  getAllLicenses,
  assignLicenseToUser,
  removeUserLicense,
} from '../../../../../lib/db/admin-actions';
import { FeatureFlagUserOverridesPanel } from '../components/FeatureFlagUserOverridesPanel';
import { useDialog } from '@/app/components/providers/DialogProvider';
import { destructiveConfirm } from '@/app/components/dialogs/destructiveConfirm';
import { EmptyState } from '@/app/components/ui/EmptyState';
import { ResetTwoFactorDialog } from '@/app/components/ade/account/ResetTwoFactorDialog';
import { Button } from '@/app/components/ui/Button';
import { Input } from '@/app/components/ui/Input';
import { ModalFrame } from '@/app/components/ui/ModalFrame';

interface User {
  id: string;
  name: string;
  email: string;
  verified: boolean;
  enabled: boolean;
  /** Suite Access (`users.suite_access`): shows the Designer and Developer suites. */
  suite_access?: boolean | null;
  created_at: string;
  updated_at: string;
  /** Last completed sign-in (`users.last_login_at`); null when never recorded. */
  last_login_at?: string | null;
  /** The later of the last sign-in and the newest session refresh; null for an unused account. */
  last_active_at?: string | null;
  license_id: string | null;
  license_name: string | null;
  license_type: string | null;
  /** Whether the user has two-factor on (`users."twoFactorEnabled"`). */
  two_factor_enabled?: boolean | null;
}

interface UserStats {
  total_users: number;
  enabled_users: number;
  verified_users: number;
  new_users_30_days: number;
  new_users_7_days: number;
}

interface License {
  id: string;
  name: string;
  license_type: string;
  enabled: boolean;
}

const LICENSE_TYPE_COLORS: Record<string, string> = {
  free:    'bg-inset text-fg-muted',
  paid:    'bg-accent text-fg-on-accent',
  sponsor: 'bg-warn text-fg-on-accent',
};

/**
 * The route the super-admin resets a user's two-factor through (TFA-1.2, #5656).
 *
 * @param userId The user's id.
 * @returns The URL to POST to.
 */
const adminTwoFactorResetEndpoint = (userId: string) =>
  `/api/admin/users/${encodeURIComponent(userId)}/two-factor/reset`;

export default function UserManagementClient() {
  const { confirm } = useDialog();
  const [users, setUsers] = useState<User[]>([]);
  const [licenses, setLicenses] = useState<License[]>([]);
  const [userStats, setUserStats] = useState<UserStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [openUserDropdown, setOpenUserDropdown] = useState<string | null>(null);
  const [userDropdownPos, setUserDropdownPos] = useState<{ top: number; right: number } | null>(null);
  const [licenseSubMenu, setLicenseSubMenu] = useState<string | null>(null);
  const [flagsUser, setFlagsUser] = useState<User | null>(null);
  /** The user whose two-factor reset dialog is open (TFA-1.2, #5656). */
  const [resetTwoFactorUser, setResetTwoFactorUser] = useState<User | null>(null);
  const [showCreateUserDialog, setShowCreateUserDialog] = useState(false);
  const [creatingUser, setCreatingUser] = useState(false);
  const [newUser, setNewUser] = useState({
    name: '',
    email: '',
    password: '',
    verified: true,
    enabled: true,
  });

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    setLoading(true);
    try {
      const [usersRes, userStatsRes, licensesRes] = await Promise.all([
        getAllUsersWithLicenses(),
        getUserStats(),
        getAllLicenses(),
      ]);

      const usersData = JSON.parse(usersRes);
      const userStatsData = JSON.parse(userStatsRes);
      const licensesData = JSON.parse(licensesRes);

      if (usersData.success) setUsers(usersData.users);
      if (userStatsData.success) setUserStats(userStatsData.stats);
      if (licensesData.success) setLicenses(licensesData.licenses.filter((l: License) => l.enabled));
    } catch (error) {
      console.error('Error loading data:', error);
      showMessage('error', 'Failed to load data');
    } finally {
      setLoading(false);
    }
  };

  const handleAssignLicense = async (userId: string, licenseId: string) => {
    try {
      const result = await assignLicenseToUser(userId, licenseId);
      const data = JSON.parse(result);
      if (data.success) {
        showMessage('success', 'License assigned successfully');
        await loadData();
      } else {
        showMessage('error', data.error || 'Failed to assign license');
      }
    } catch {
      showMessage('error', 'Failed to assign license');
    } finally {
      setLicenseSubMenu(null);
      setOpenUserDropdown(null);
    }
  };

  const handleRemoveLicense = async (userId: string) => {
    try {
      const result = await removeUserLicense(userId);
      const data = JSON.parse(result);
      if (data.success) {
        showMessage('success', 'License removed');
        await loadData();
      } else {
        showMessage('error', data.error || 'Failed to remove license');
      }
    } catch {
      showMessage('error', 'Failed to remove license');
    } finally {
      setOpenUserDropdown(null);
    }
  };

  const handleOpenFlagsModal = (user: User) => {
    setOpenUserDropdown(null);
    setFlagsUser(user);
  };

  const showMessage = (type: 'success' | 'error', text: string) => {
    setMessage({ type, text });
    setTimeout(() => setMessage(null), 5000);
  };

  const resetNewUserForm = () => {
    setNewUser({
      name: '',
      email: '',
      password: '',
      verified: true,
      enabled: true,
    });
  };

  const handleCreateUser = async (event: FormEvent) => {
    event.preventDefault();

    const name = newUser.name.trim();
    const email = newUser.email.trim().toLowerCase();

    if (!name || !email || !newUser.password) {
      showMessage('error', 'Name, email, and password are required');
      return;
    }

    setCreatingUser(true);
    try {
      const result = await createUser(
        name,
        email,
        newUser.password,
        newUser.verified,
        newUser.enabled
      );
      const data = JSON.parse(result);

      if (data.success) {
        showMessage('success', `User created successfully for ${name}`);
        setShowCreateUserDialog(false);
        resetNewUserForm();
        await loadData();
      } else {
        showMessage('error', data.error || 'Failed to create user');
      }
    } catch (error) {
      console.error('Error creating user:', error);
      showMessage('error', 'Failed to create user');
    } finally {
      setCreatingUser(false);
    }
  };

  const handleToggleUserEnabled = async (user: User) => {
    try {
      const result = await updateUser(user.id, { enabled: !user.enabled });
      const data = JSON.parse(result);

      if (data.success) {
        showMessage('success', `User ${user.enabled ? 'disabled' : 'enabled'} successfully`);
        await loadData();
      } else {
        showMessage('error', data.error || 'Failed to update user');
      }
    } catch (error) {
      console.error('Error updating user:', error);
      showMessage('error', 'Failed to update user');
    }
  };

  const handleToggleUserVerified = async (user: User) => {
    try {
      const result = await updateUser(user.id, { verified: !user.verified });
      const data = JSON.parse(result);

      if (data.success) {
        showMessage('success', `User ${user.verified ? 'unverified' : 'verified'} successfully`);
        await loadData();
      } else {
        showMessage('error', data.error || 'Failed to update user');
      }
    } catch (error) {
      console.error('Error updating user:', error);
      showMessage('error', 'Failed to update user');
    }
  };

  const handleToggleSuiteAccess = async (user: User) => {
    try {
      const result = await updateUser(user.id, { suite_access: !user.suite_access });
      const data = JSON.parse(result);

      if (data.success) {
        showMessage('success', `Suite Access ${user.suite_access ? 'removed' : 'granted'}`);
        await loadData();
      } else {
        showMessage('error', data.error || 'Failed to update Suite Access');
      }
    } catch (error) {
      console.error('Error updating Suite Access:', error);
      showMessage('error', 'Failed to update Suite Access');
    }
  };

  const handleDeleteUser = async (user: User) => {
    // Type-to-confirm: #5286 names the admin user delete alongside tenants and projects as
    // the irreversible cases. The phrase is the email, not the display name — two people
    // can share a name, and it is the email the row is identified by everywhere else.
    const confirmed = await confirm(
      destructiveConfirm({
        action: 'Delete',
        noun: 'user',
        name: user.email,
        consequence: `${user.name} loses their account, every tenant membership it carried and any licence assigned to it.`,
        typeToConfirm: true,
        confirmLabel: 'Delete user',
      })
    );
    if (!confirmed) return;

    try {
      const result = await deleteUser(user.id);
      const data = JSON.parse(result);

      if (data.success) {
        showMessage('success', 'User deleted successfully');
        await loadData();
      } else {
        showMessage('error', data.error || 'Failed to delete user');
      }
    } catch (error) {
      console.error('Error deleting user:', error);
      showMessage('error', 'Failed to delete user');
    }
  };

  /** A row's date, or `fallback` when it is missing or unparseable (never "Invalid Date"). */
  const formatDate = (dateString: string | null | undefined, fallback = '—', withTime = true) => {
    if (!dateString) return fallback;
    const date = new Date(dateString);
    if (Number.isNaN(date.getTime())) return fallback;
    return date.toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      ...(withTime ? { hour: '2-digit', minute: '2-digit' } : {}),
    } as Intl.DateTimeFormatOptions);
  };

  return (
    <>
      {/* Header */}
      <header className="shrink-0 border-b border-border bg-surface">
        <div className="px-6 py-4">
          <div className="flex items-center justify-between gap-4">
            <div>
              <h2 className="text-2xl font-bold text-fg">Users</h2>
              <p className="text-fg-muted text-sm mt-1">Manage user accounts, licenses and access</p>
            </div>
            <Button
              type="button"
              onClick={() => setShowCreateUserDialog(true)}
              variant="primary" className="shrink-0"
            >
              <Plus className="w-4 h-4" />
              New User
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
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        <div className="rounded-lg border border-border bg-surface p-4">
          <div className="flex items-center gap-3 mb-2">
            <div className="p-2 bg-accent/20 rounded-lg">
              <Users className="w-5 h-5 text-accent-fg" />
            </div>
            <div>
              <p className="text-fg-muted text-xs">Total Users</p>
              <p className="text-fg text-xl font-bold">{userStats?.total_users || 0}</p>
            </div>
          </div>
          <p className="text-xs text-fg-muted">
            {userStats?.new_users_7_days || 0} new this week
          </p>
        </div>

        <div className="rounded-lg border border-border bg-surface p-4">
          <div className="flex items-center gap-3 mb-2">
            <div className="p-2 bg-ok/20 rounded-lg">
              <UserCheck className="w-5 h-5 text-ok-fg" />
            </div>
            <div>
              <p className="text-fg-muted text-xs">Verified Users</p>
              <p className="text-fg text-xl font-bold">{userStats?.verified_users || 0}</p>
            </div>
          </div>
          <p className="text-xs text-fg-muted">
            {userStats?.enabled_users || 0} enabled
          </p>
        </div>

        <div className="rounded-lg border border-border bg-surface p-4">
          <div className="flex items-center gap-3 mb-2">
            <div className="p-2 bg-violet/20 rounded-lg">
              <UserPlus className="w-5 h-5 text-violet-fg" />
            </div>
            <div>
              <p className="text-fg-muted text-xs">New Users</p>
              <p className="text-fg text-xl font-bold">{userStats?.new_users_30_days || 0}</p>
            </div>
          </div>
          <p className="text-xs text-fg-muted">Last 30 days</p>
        </div>
      </div>

      {/* Refresh Button */}
      <div className="flex justify-end">
        <button
          onClick={loadData}
          disabled={loading}
          className="flex items-center gap-2 px-4 py-2 bg-inset hover:bg-inset text-fg-muted rounded-lg transition-colors disabled:opacity-50"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {/* Content */}
      {loading ? (
        <div className="flex items-center justify-center py-12">
          <RefreshCw className="w-8 h-8 text-fg-subtle animate-spin" />
        </div>
      ) : (
        // Users Table
        <div className="bg-surface border border-border rounded-lg overflow-hidden">
          {users.length === 0 ? (
            <EmptyState
              surface={false}
              icon={<Users />}
              title="No users yet"
              description="People appear here once they sign up or an administrator creates their account."
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead className="border-b border-border bg-subtle">
                  <tr>
                    <th className="px-4 py-3 text-left text-xs font-medium text-fg-muted uppercase tracking-wider">
                      User
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-fg-muted uppercase tracking-wider">
                      Email
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-fg-muted uppercase tracking-wider">
                      License
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-fg-muted uppercase tracking-wider">
                      Status
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-fg-muted uppercase tracking-wider">
                      Created
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-fg-muted uppercase tracking-wider">
                      Last active
                    </th>
                    <th className="px-4 py-3 text-right text-xs font-medium text-fg-muted uppercase tracking-wider">
                      Actions
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {users.map((user) => (
                    <tr key={user.id} className="hover:bg-subtle">
                      <td className="px-4 py-4 whitespace-nowrap">
                        <div className="flex items-center gap-3">
                          <div className="w-8 h-8 bg-danger/20 rounded-full flex items-center justify-center">
                            <span className="text-danger-fg text-sm font-medium">
                              {user.name.charAt(0).toUpperCase()}
                            </span>
                          </div>
                          <div className="text-sm font-medium text-fg">{user.name}</div>
                        </div>
                      </td>
                      <td className="px-4 py-4 whitespace-nowrap">
                        <div className="flex items-center gap-2">
                          <Mail className="w-4 h-4 text-fg-subtle" />
                          <span className="text-sm text-fg-muted">{user.email}</span>
                        </div>
                      </td>
                      <td className="px-4 py-4 whitespace-nowrap">
                        {user.license_name && user.license_type ? (
                          <span className={`inline-flex items-center gap-1.5 px-2 py-1 rounded-xs text-xs font-semibold uppercase tracking-wide ${LICENSE_TYPE_COLORS[user.license_type] ?? 'bg-inset text-fg-muted'}`}>
                            <Award className="w-3 h-3" />
                            {user.license_name}
                          </span>
                        ) : (
                          <span className="text-xs text-fg-subtle italic">No license</span>
                        )}
                      </td>
                      <td className="px-4 py-4 whitespace-nowrap">
                        <div className="flex items-center gap-2">
                          {user.verified ? (
                            <span className="inline-flex items-center gap-1 px-2 py-1 bg-ok/20 text-ok-fg text-xs rounded-xs">
                              <CheckCircle className="w-3 h-3" />
                              Verified
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1 px-2 py-1 bg-warn/20 text-warn-fg text-xs rounded-xs">
                              <AlertCircle className="w-3 h-3" />
                              Unverified
                            </span>
                          )}
                          {user.enabled ? (
                            <span className="inline-flex items-center gap-1 px-2 py-1 bg-accent/20 text-accent-fg text-xs rounded-xs">
                              Enabled
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1 px-2 py-1 bg-inset text-fg-muted text-xs rounded-xs">
                              Disabled
                            </span>
                          )}
                          {user.suite_access && (
                            <span
                              className="inline-flex items-center gap-1 px-2 py-1 bg-violet/20 text-violet-fg text-xs rounded-xs"
                              data-testid="admin-user-suite-access"
                            >
                              <Layers className="w-3 h-3" />
                              Suite
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="px-4 py-4 whitespace-nowrap">
                        <span
                          className="text-sm text-fg-muted"
                          title={formatDate(user.created_at, '')}
                        >
                          {formatDate(user.created_at, '—', false)}
                        </span>
                      </td>
                      <td className="px-4 py-4 whitespace-nowrap">
                        <span
                          className="text-sm text-fg-muted"
                          data-testid="admin-user-last-active"
                        >
                          {formatDate(user.last_active_at ?? user.last_login_at, 'Never')}
                        </span>
                      </td>
                      <td className="px-4 py-4 whitespace-nowrap text-right text-sm font-medium">
                        <div className="relative inline-block">
                          <button
                            onClick={(e) => {
                              const rect = e.currentTarget.getBoundingClientRect();
                              setUserDropdownPos({
                                top: rect.bottom + 4,
                                right: window.innerWidth - rect.right
                              });
                              setOpenUserDropdown(openUserDropdown === user.id ? null : user.id);
                            }}
                            className="p-2 hover:bg-subtle rounded-xs transition-colors text-fg-subtle hover:text-fg-muted"
                          >
                            <MoreVertical className="w-4 h-4" />
                          </button>

                          {openUserDropdown === user.id && userDropdownPos && (
                            <>
                              <div
                                className="fixed inset-0 z-[100]"
                                onClick={() => setOpenUserDropdown(null)}
                              />
                              <div
                                className="fixed w-52 bg-surface border border-border rounded-lg shadow-lg z-[101]"
                                style={{
                                  top: `${userDropdownPos.top}px`,
                                  right: `${userDropdownPos.right}px`
                                }}
                              >
                                <div className="py-1">
                                  <button
                                    onClick={() => {
                                      setOpenUserDropdown(null);
                                      handleToggleUserVerified(user);
                                    }}
                                    className="w-full px-4 py-2 text-left text-sm hover:bg-subtle flex items-center gap-3 text-fg-muted hover:text-fg transition-colors"
                                  >
                                    {user.verified ? (
                                      <>
                                        <XCircle className="w-4 h-4 text-warn-fg" />
                                        Mark Unverified
                                      </>
                                    ) : (
                                      <>
                                        <CheckCircle className="w-4 h-4 text-ok-fg" />
                                        Mark Verified
                                      </>
                                    )}
                                  </button>
                                  <button
                                    onClick={() => {
                                      setOpenUserDropdown(null);
                                      handleToggleUserEnabled(user);
                                    }}
                                    className="w-full px-4 py-2 text-left text-sm hover:bg-subtle flex items-center gap-3 text-fg-muted hover:text-fg transition-colors"
                                  >
                                    {user.enabled ? (
                                      <>
                                        <Power className="w-4 h-4 text-orange-fg" />
                                        Disable User
                                      </>
                                    ) : (
                                      <>
                                        <Power className="w-4 h-4 text-accent-fg" />
                                        Enable User
                                      </>
                                    )}
                                  </button>
                                  <button
                                    onClick={() => {
                                      setOpenUserDropdown(null);
                                      handleToggleSuiteAccess(user);
                                    }}
                                    data-testid={`admin-toggle-suite-access-${user.id}`}
                                    className="w-full px-4 py-2 text-left text-sm hover:bg-subtle flex items-center gap-3 text-fg-muted hover:text-fg transition-colors"
                                  >
                                    <Layers className="w-4 h-4 text-violet-fg" />
                                    {user.suite_access ? 'Remove Suite Access' : 'Grant Suite Access'}
                                  </button>

                                  <div className="border-t border-border mt-1 pt-1">
                                    <div className="relative">
                                      <button
                                        onClick={() => setLicenseSubMenu(licenseSubMenu === user.id ? null : user.id)}
                                        className="w-full px-4 py-2 text-left text-sm hover:bg-subtle flex items-center gap-3 text-accent-fg hover:text-accent-fg transition-colors"
                                      >
                                        <Award className="w-4 h-4" />
                                        Assign License…
                                      </button>
                                      {licenseSubMenu === user.id && (
                                        <div className="pl-4 pb-1">
                                          {licenses.map(lic => (
                                            <button
                                              key={lic.id}
                                              onClick={() => handleAssignLicense(user.id, lic.id)}
                                              className="w-full px-3 py-1.5 text-left text-xs hover:bg-subtle flex items-center gap-2 text-fg-muted hover:text-fg transition-colors rounded-xs"
                                            >
                                              <span className={`w-2 h-2 rounded-full ${lic.license_type === 'free' ? 'bg-fg-faint' : lic.license_type === 'paid' ? 'bg-accent' : 'bg-warn'}`} />
                                              {lic.name}
                                              {lic.id === user.license_id && <CheckCircle className="w-3 h-3 text-ok-fg ml-auto" />}
                                            </button>
                                          ))}
                                          {user.license_id && (
                                            <button
                                              onClick={() => handleRemoveLicense(user.id)}
                                              className="w-full px-3 py-1.5 text-left text-xs hover:bg-subtle flex items-center gap-2 text-danger-fg hover:text-danger-fg transition-colors rounded-xs"
                                            >
                                              <Trash2 className="w-3 h-3" />
                                              Remove License
                                            </button>
                                          )}
                                        </div>
                                      )}
                                    </div>
                                  </div>

                                  <div className="border-t border-border mt-1 pt-1">
                                    <button
                                      onClick={() => handleOpenFlagsModal(user)}
                                      className="w-full px-4 py-2 text-left text-sm hover:bg-subtle flex items-center gap-3 text-ok-fg hover:text-ok-fg transition-colors"
                                    >
                                      <Flag className="w-4 h-4" />
                                      Manage Feature Flags…
                                    </button>
                                  </div>

                                  {/* Only where there is a second factor to reset (TFA-1.2, #5656). */}
                                  {user.two_factor_enabled && (
                                    <div className="border-t border-border mt-1 pt-1">
                                      <button
                                        onClick={() => {
                                          setOpenUserDropdown(null);
                                          setResetTwoFactorUser(user);
                                        }}
                                        data-testid={`admin-reset-two-factor-${user.id}`}
                                        className="w-full px-4 py-2 text-left text-sm hover:bg-subtle flex items-center gap-3 text-warn-fg hover:text-warn-fg transition-colors"
                                      >
                                        <ShieldOff className="w-4 h-4" />
                                        Reset two-factor…
                                      </button>
                                    </div>
                                  )}

                                  <div className="border-t border-border mt-1 pt-1">
                                    <button
                                      onClick={() => {
                                        setOpenUserDropdown(null);
                                        handleDeleteUser(user);
                                      }}
                                      className="w-full px-4 py-2 text-left text-sm hover:bg-subtle flex items-center gap-3 text-danger-fg hover:text-danger-fg transition-colors"
                                    >
                                      <Trash2 className="w-4 h-4" />
                                      Delete User
                                    </button>
                                  </div>
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
      )}
        </div>
      </main>

      {/* Create User Dialog */}
      {showCreateUserDialog && (
        <ModalFrame
          open
          onClose={() => {
            setShowCreateUserDialog(false);
            resetNewUserForm();
          }}
          label="Create New User"
          overlayClassName="fixed inset-0 z-[200] flex items-center justify-center bg-overlay p-4 backdrop-blur-sm"
          className="bg-surface border border-border rounded-xl max-w-md w-full shadow-lg"
        >
            <div className="p-4 border-b border-border flex items-center justify-between">
              <h3 className="text-lg font-semibold text-fg">Create New User</h3>
              <button
                type="button"
                onClick={() => {
                  setShowCreateUserDialog(false);
                  resetNewUserForm();
                }}
                className="text-fg-subtle hover:text-fg transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <form onSubmit={handleCreateUser} className="p-4 space-y-4">
              <div>
                <label className="block text-sm font-medium text-fg mb-[var(--space-field)]">
                  Name *
                </label>
                <Input
                  type="text"
                  value={newUser.name}
                  onChange={(e) => setNewUser({ ...newUser, name: e.target.value })}
                  placeholder="Jane Doe"
                  required
                  autoFocus
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-fg mb-[var(--space-field)]">
                  Email *
                </label>
                <Input
                  type="email"
                  value={newUser.email}
                  onChange={(e) => setNewUser({ ...newUser, email: e.target.value })}
                  placeholder="jane@example.com"
                  required
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-fg mb-[var(--space-field)]">
                  Password *
                </label>
                <Input
                  type="password"
                  value={newUser.password}
                  onChange={(e) => setNewUser({ ...newUser, password: e.target.value })}
                  placeholder="Temporary password"
                  required
                  minLength={8}
                />
                <p className="text-fg-muted text-xs mt-1">Minimum 8 characters. Stored as a bcrypt hash.</p>
              </div>
              <div className="space-y-2">
                <div className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    id="newUserVerified"
                    checked={newUser.verified}
                    onChange={(e) => setNewUser({ ...newUser, verified: e.target.checked })}
                    className="w-4 h-4 rounded-xs border-border-strong bg-surface text-danger-fg focus:ring-2 focus:ring-danger focus:ring-offset-0"
                  />
                  <label htmlFor="newUserVerified" className="text-sm text-fg-muted">
                    Mark email as verified
                  </label>
                </div>
                <div className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    id="newUserEnabled"
                    checked={newUser.enabled}
                    onChange={(e) => setNewUser({ ...newUser, enabled: e.target.checked })}
                    className="w-4 h-4 rounded-xs border-border-strong bg-surface text-danger-fg focus:ring-2 focus:ring-danger focus:ring-offset-0"
                  />
                  <label htmlFor="newUserEnabled" className="text-sm text-fg-muted">
                    Enable account immediately
                  </label>
                </div>
              </div>
              <div className="flex items-center justify-end gap-2 pt-2">
                <Button
                  type="button"
                  onClick={() => {
                    setShowCreateUserDialog(false);
                    resetNewUserForm();
                  }}
                  variant="ghost"
                  disabled={creatingUser}
                >
                  Cancel
                </Button>
                <Button
                  type="submit"
                  disabled={creatingUser}
                  variant="primary"
                >
                  {creatingUser ? 'Creating…' : 'Create User'}
                </Button>
              </div>
            </form>
        </ModalFrame>
      )}

      {/* Feature Flags Modal */}
      {flagsUser && (
        <ModalFrame
          open
          onClose={() => setFlagsUser(null)}
          label="Feature Flags"
          overlayClassName="fixed inset-0 z-[200] flex items-center justify-center bg-overlay p-4 backdrop-blur-sm"
          className="bg-surface border border-border rounded-xl shadow-lg w-full max-w-3xl h-[90vh] max-h-[90vh] flex flex-col overflow-hidden"
        >
            <div className="flex items-center gap-3 px-6 py-4 border-b border-border shrink-0">
              <div className="p-2 bg-ok/20 rounded-lg">
                <Flag className="w-5 h-5 text-ok-fg" />
              </div>
              <div className="flex-1 min-w-0">
                <h3 className="text-fg font-semibold text-lg">Feature Flags</h3>
                <p className="text-fg-subtle text-xs truncate">{flagsUser.name} — {flagsUser.email}</p>
              </div>
              <button onClick={() => setFlagsUser(null)} className="text-fg-subtle hover:text-fg p-1 rounded-xs transition-colors">
                <XCircle className="w-5 h-5" />
              </button>
            </div>
            <div className="flex min-h-0 flex-1 flex-col overflow-hidden px-6 py-4">
              <FeatureFlagUserOverridesPanel
                className="h-full min-h-0"
                userId={flagsUser.id}
                userName={flagsUser.name}
                userEmail={flagsUser.email}
                onNotify={showMessage}
              />
            </div>
            <div className="px-6 py-3 border-t border-border flex justify-end shrink-0">
              <button
                onClick={() => setFlagsUser(null)}
                className="px-4 py-2 bg-inset hover:bg-inset text-fg-muted text-sm rounded-lg transition-colors"
              >
                Done
              </button>
            </div>
        </ModalFrame>
      )}

      {/* Reset a user's two-factor (TFA-1.2, #5656). The dialog makes the call and shows the
          result, including whether the user was emailed; the list reloads so the menu item goes. */}
      <ResetTwoFactorDialog
        open={resetTwoFactorUser !== null}
        onOpenChange={(open) => !open && setResetTwoFactorUser(null)}
        target={
          resetTwoFactorUser
            ? {
                userId: resetTwoFactorUser.id,
                email: resetTwoFactorUser.email,
                name: resetTwoFactorUser.name,
              }
            : null
        }
        endpoint={adminTwoFactorResetEndpoint}
        onReset={() => void loadData()}
      />
    </>
  );
}

