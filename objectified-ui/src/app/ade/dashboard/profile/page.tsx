'use client';

import { useSession } from 'next-auth/react';
import { User, Mail, Hash, Calendar, Clock, Building2 } from 'lucide-react';

const Profile = () => {
  const { data: session } = useSession();

  if (!session) {
    return (
      <div className="flex items-center justify-center h-64">
        <p className="text-gray-500 dark:text-gray-400">Loading profile...</p>
      </div>
    );
  }

  const { user, expires } = session;
  const expiryDate = new Date(expires);

  return (
    <div className="container mx-auto px-4 py-8 max-w-4xl">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900 dark:text-white">
          Profile
        </h1>
        <p className="text-gray-600 dark:text-gray-400 mt-2">
          View and manage your account information
        </p>
      </div>

      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md overflow-hidden">
        {/* Header Section */}
        <div className="bg-gradient-to-r from-blue-500 to-blue-600 dark:from-blue-600 dark:to-blue-700 px-6 py-8">
          <div className="flex items-center space-x-4">
            <div className="bg-white dark:bg-gray-800 rounded-full p-4">
              <User className="h-12 w-12 text-blue-600 dark:text-blue-400" />
            </div>
            <div>
              <h2 className="text-2xl font-bold text-white">
                {user?.name || 'Unknown User'}
              </h2>
              <p className="text-blue-100 dark:text-blue-200">
                {user?.email || 'No email'}
              </p>
            </div>
          </div>
        </div>

        {/* Details Section */}
        <div className="px-6 py-6 space-y-6">
          {/* Name */}
          <div className="flex items-start space-x-4">
            <div className="bg-blue-50 dark:bg-blue-900/20 rounded-lg p-3">
              <User className="h-5 w-5 text-blue-600 dark:text-blue-400" />
            </div>
            <div className="flex-1">
              <label className="text-sm font-medium text-gray-500 dark:text-gray-400">
                Full Name
              </label>
              <p className="text-lg text-gray-900 dark:text-white mt-1">
                {user?.name || 'Not provided'}
              </p>
            </div>
          </div>

          {/* Email */}
          <div className="flex items-start space-x-4">
            <div className="bg-green-50 dark:bg-green-900/20 rounded-lg p-3">
              <Mail className="h-5 w-5 text-green-600 dark:text-green-400" />
            </div>
            <div className="flex-1">
              <label className="text-sm font-medium text-gray-500 dark:text-gray-400">
                Email Address
              </label>
              <p className="text-lg text-gray-900 dark:text-white mt-1">
                {user?.email || 'Not provided'}
              </p>
            </div>
          </div>

          {/* User ID */}
          <div className="flex items-start space-x-4">
            <div className="bg-purple-50 dark:bg-purple-900/20 rounded-lg p-3">
              <Hash className="h-5 w-5 text-purple-600 dark:text-purple-400" />
            </div>
            <div className="flex-1">
              <label className="text-sm font-medium text-gray-500 dark:text-gray-400">
                User ID
              </label>
              <p className="text-lg font-mono text-gray-900 dark:text-white mt-1 break-all">
                {(user as any)?.user_id || 'Not available'}
              </p>
            </div>
          </div>

          {/* Current Tenant ID */}
          {(user as any)?.current_tenant_id && (
            <div className="flex items-start space-x-4">
              <div className="bg-indigo-50 dark:bg-indigo-900/20 rounded-lg p-3">
                <Building2 className="h-5 w-5 text-indigo-600 dark:text-indigo-400" />
              </div>
              <div className="flex-1">
                <label className="text-sm font-medium text-gray-500 dark:text-gray-400">
                  Current Tenant ID
                </label>
                <p className="text-lg font-mono text-gray-900 dark:text-white mt-1 break-all">
                  {(user as any)?.current_tenant_id}
                </p>
              </div>
            </div>
          )}

          {/* Session Expiry */}
          <div className="flex items-start space-x-4">
            <div className="bg-orange-50 dark:bg-orange-900/20 rounded-lg p-3">
              <Clock className="h-5 w-5 text-orange-600 dark:text-orange-400" />
            </div>
            <div className="flex-1">
              <label className="text-sm font-medium text-gray-500 dark:text-gray-400">
                Session Expiration
              </label>
              <p className="text-lg text-gray-900 dark:text-white mt-1">
                {expiryDate.toLocaleString()}
              </p>
              <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                {expiryDate.toLocaleDateString('en-US', {
                  weekday: 'long',
                  year: 'numeric',
                  month: 'long',
                  day: 'numeric'
                })}
              </p>
            </div>
          </div>
        </div>

        {/* Footer Actions */}
        <div className="bg-gray-50 dark:bg-gray-900/50 px-6 py-4 border-t border-gray-200 dark:border-gray-700">
          <div className="flex justify-end space-x-3">
            <button
              disabled
              className="px-4 py-2 text-sm font-medium text-gray-400 dark:text-gray-600 bg-gray-200 dark:bg-gray-800 rounded-lg cursor-not-allowed opacity-60"
            >
              Edit Profile (Coming Soon)
            </button>
            <button
              disabled
              className="px-4 py-2 text-sm font-medium text-gray-400 dark:text-gray-600 bg-gray-200 dark:bg-gray-800 rounded-lg cursor-not-allowed opacity-60"
            >
              Change Password (Coming Soon)
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default Profile;