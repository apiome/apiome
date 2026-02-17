'use client';

import { useSession } from 'next-auth/react';
import { User, Mail, Hash, Clock, Building2, Edit2, Key, Shield } from 'lucide-react';
import { useState } from 'react';
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
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '../../../components/ui/Card';
import { updateUserName, updateUserPassword } from '../../../../../lib/db/helper';

const Profile = () => {
  const { data: session, update } = useSession();
  const [showEditDialog, setShowEditDialog] = useState(false);
  const [editedName, setEditedName] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');

  const [showPasswordDialog, setShowPasswordDialog] = useState(false);
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [passwordError, setPasswordError] = useState('');
  const [successMessage, setSuccessMessage] = useState('');

  const handleEditClick = () => {
    setEditedName(session?.user?.name || '');
    setErrorMessage('');
    setShowEditDialog(true);
  };

  const handleSaveName = async () => {
    if (!editedName.trim()) {
      setErrorMessage('Name cannot be empty');
      return;
    }
    setIsLoading(true);
    setErrorMessage('');
    try {
      const userId = (session?.user as any)?.user_id;
      const result = await updateUserName(userId, editedName.trim());
      const response = JSON.parse(result);
      if (response.success) {
        await update({
          ...session,
          user: { ...session?.user, name: editedName.trim() },
        });
        setShowEditDialog(false);
      } else {
        setErrorMessage(response.error || 'Failed to update name');
      }
    } catch (error: any) {
      setErrorMessage(error.message || 'An error occurred');
    } finally {
      setIsLoading(false);
    }
  };

  const handlePasswordChangeClick = () => {
    setCurrentPassword('');
    setNewPassword('');
    setConfirmPassword('');
    setPasswordError('');
    setShowPasswordDialog(true);
  };

  const handleSavePassword = async () => {
    if (!currentPassword) {
      setPasswordError('Please enter your current password');
      return;
    }
    if (!newPassword) {
      setPasswordError('Please enter a new password');
      return;
    }
    if (newPassword !== confirmPassword) {
      setPasswordError('New passwords do not match');
      return;
    }
    setIsLoading(true);
    setPasswordError('');
    try {
      const userId = (session?.user as any)?.user_id;
      const result = await updateUserPassword(userId, currentPassword, newPassword);
      const response = JSON.parse(result);
      if (response.success) {
        setShowPasswordDialog(false);
        setCurrentPassword('');
        setNewPassword('');
        setConfirmPassword('');
        setSuccessMessage('Password changed successfully.');
      } else {
        setPasswordError(response.error || 'Failed to update password');
      }
    } catch (error: any) {
      setPasswordError(error.message || 'An error occurred');
    } finally {
      setIsLoading(false);
    }
  };

  if (!session) {
    return (
      <div className="p-6 max-w-7xl mx-auto">
        <div className="flex flex-col items-center justify-center min-h-[320px] gap-4">
          <div className="w-10 h-10 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin" />
          <p className="text-sm text-gray-500 dark:text-gray-400">Loading profile…</p>
        </div>
      </div>
    );
  }

  const { user, expires } = session;
  const expiryDate = new Date(expires);

  const InfoRow = ({
    icon: Icon,
    iconClassName,
    label,
    value,
    mono,
    action,
  }: {
    icon: React.ElementType;
    iconClassName: string;
    label: string;
    value: React.ReactNode;
    mono?: boolean;
    action?: React.ReactNode;
  }) => (
    <div className="flex items-start gap-4 py-4 first:pt-0 last:pb-0 border-b border-gray-100 dark:border-gray-700/50 last:border-0">
      <div className={`rounded-lg p-2.5 flex-shrink-0 ${iconClassName}`}>
        <Icon className="h-5 w-5" />
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-xs font-medium uppercase tracking-wider text-gray-400 dark:text-gray-500 mb-1">{label}</p>
        <div className="flex items-center gap-2 flex-wrap">
          <p className={mono ? 'text-sm font-mono text-gray-700 dark:text-gray-300 bg-gray-50 dark:bg-gray-900/50 px-2.5 py-1.5 rounded-md break-all' : 'text-base font-medium text-gray-900 dark:text-white'}>
            {value}
          </p>
          {action}
        </div>
      </div>
    </div>
  );

  return (
    <div className="p-6 max-w-7xl mx-auto">
      {/* Page header */}
      <div className="flex items-center gap-4 mb-8">
        <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center shadow-lg shadow-indigo-500/25">
          <User className="h-7 w-7 text-white" />
        </div>
        <div>
          <h1 className="text-3xl font-bold text-gray-900 dark:text-white tracking-tight">Profile</h1>
          <p className="text-gray-500 dark:text-gray-400 mt-1">
            Manage your account and security settings
          </p>
        </div>
      </div>

      {successMessage && (
        <Alert variant="success" className="mb-6" onClose={() => setSuccessMessage('')}>
          {successMessage}
        </Alert>
      )}

      <div className="space-y-6">
        {/* Account card */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <User className="h-5 w-5 text-indigo-500" />
              Account
            </CardTitle>
            <CardDescription>Your identity and session information</CardDescription>
          </CardHeader>
          <CardContent className="space-y-0">
            <InfoRow
              icon={User}
              iconClassName="bg-indigo-50 dark:bg-indigo-900/30 text-indigo-600 dark:text-indigo-400"
              label="Full name"
              value={user?.name || 'Not set'}
              action={
                <button
                  onClick={handleEditClick}
                  className="p-1.5 rounded-md hover:bg-indigo-50 dark:hover:bg-indigo-900/30 text-gray-400 hover:text-indigo-600 dark:hover:text-indigo-400 transition-colors"
                  title="Edit name"
                >
                  <Edit2 className="h-4 w-4" />
                </button>
              }
            />
            <InfoRow
              icon={Mail}
              iconClassName="bg-emerald-50 dark:bg-emerald-900/30 text-emerald-600 dark:text-emerald-400"
              label="Email"
              value={user?.email || 'Not set'}
            />
            <InfoRow
              icon={Hash}
              iconClassName="bg-violet-50 dark:bg-violet-900/30 text-violet-600 dark:text-violet-400"
              label="User ID"
              value={(user as any)?.user_id ?? '—'}
              mono
            />
            {(user as any)?.current_tenant_id && (
              <InfoRow
                icon={Building2}
                iconClassName="bg-blue-50 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400"
                label="Current tenant"
                value={(user as any).current_tenant_id}
                mono
              />
            )}
            <InfoRow
              icon={Clock}
              iconClassName="bg-amber-50 dark:bg-amber-900/30 text-amber-600 dark:text-amber-400"
              label="Session expires"
              value={
                <>
                  {expiryDate.toLocaleString()}
                  <span className="block text-sm font-normal text-gray-500 dark:text-gray-400 mt-0.5">
                    {expiryDate.toLocaleDateString('en-US', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' })}
                  </span>
                </>
              }
            />
          </CardContent>
          <CardFooter className="flex flex-wrap gap-2 border-t border-gray-100 dark:border-gray-700/50 pt-6">
            <Button variant="outline" size="sm" onClick={handleEditClick}>
              <Edit2 className="h-4 w-4 mr-2" />
              Edit name
            </Button>
          </CardFooter>
        </Card>

        {/* Security card */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Shield className="h-5 w-5 text-emerald-500" />
              Security
            </CardTitle>
            <CardDescription>Password and account security</CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-gray-600 dark:text-gray-400">
              Use a strong, unique password. Change it periodically or if you suspect it has been compromised.
            </p>
          </CardContent>
          <CardFooter className="border-t border-gray-100 dark:border-gray-700/50 pt-6">
            <Button size="sm" onClick={handlePasswordChangeClick}>
              <Key className="h-4 w-4 mr-2" />
              Change password
            </Button>
          </CardFooter>
        </Card>
      </div>

      {/* Edit name dialog */}
      <Dialog open={showEditDialog} onOpenChange={(open) => !isLoading && setShowEditDialog(open)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <div className="p-1.5 rounded-lg bg-indigo-100 dark:bg-indigo-900/40">
                <Edit2 className="h-5 w-5 text-indigo-600 dark:text-indigo-400" />
              </div>
              Edit name
            </DialogTitle>
            <DialogDescription>Update your display name.</DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            {errorMessage && <Alert variant="error">{errorMessage}</Alert>}
            <div className="space-y-2">
              <Label htmlFor="name">Full name</Label>
              <Input
                id="name"
                value={editedName}
                onChange={(e) => setEditedName(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && !isLoading && handleSaveName()}
                disabled={isLoading}
                placeholder="Your name"
                autoFocus
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowEditDialog(false)} disabled={isLoading}>
              Cancel
            </Button>
            <Button onClick={handleSaveName} disabled={isLoading}>
              {isLoading ? 'Saving…' : 'Save'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Change password dialog */}
      <Dialog open={showPasswordDialog} onOpenChange={(open) => !isLoading && setShowPasswordDialog(open)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <div className="p-1.5 rounded-lg bg-emerald-100 dark:bg-emerald-900/40">
                <Key className="h-5 w-5 text-emerald-600 dark:text-emerald-400" />
              </div>
              Change password
            </DialogTitle>
            <DialogDescription>Enter your current password and choose a new one.</DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            {passwordError && <Alert variant="error">{passwordError}</Alert>}
            <Alert variant="info">
              <div>
                <p className="font-medium mb-2">Password requirements</p>
                <ul className="list-disc list-inside text-sm space-y-1 text-gray-600 dark:text-gray-400">
                  <li>At least 8 characters</li>
                  <li>One uppercase and one lowercase letter</li>
                  <li>One number or special character</li>
                </ul>
              </div>
            </Alert>
            <div className="space-y-2">
              <Label htmlFor="currentPassword">Current password</Label>
              <Input
                id="currentPassword"
                type="password"
                value={currentPassword}
                onChange={(e) => setCurrentPassword(e.target.value)}
                disabled={isLoading}
                autoFocus
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="newPassword">New password</Label>
              <Input
                id="newPassword"
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                disabled={isLoading}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="confirmPassword">Confirm new password</Label>
              <Input
                id="confirmPassword"
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && !isLoading && handleSavePassword()}
                disabled={isLoading}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowPasswordDialog(false)} disabled={isLoading}>
              Cancel
            </Button>
            <Button onClick={handleSavePassword} disabled={isLoading}>
              {isLoading ? 'Updating…' : 'Change password'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default Profile;
