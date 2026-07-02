'use client';

import { Users, DollarSign, UserCheck, Activity, AlertCircle } from 'lucide-react';

interface StatCardProps {
  title: string;
  value: string | number;
  icon: React.ReactNode;
  trend?: string;
  trendUp?: boolean;
}

const StatCard: React.FC<StatCardProps> = ({ title, value, icon, trend, trendUp }) => (
  <div className="rounded-lg border border-slate-200 bg-white p-6 transition-colors hover:border-slate-300 dark:border-slate-800 dark:bg-slate-900 dark:hover:border-slate-700">
    <div className="flex items-start justify-between mb-4">
      <div className="p-2 bg-red-600/20 rounded-lg">
        {icon}
      </div>
      {trend && (
        <span className={`text-sm font-medium ${trendUp ? 'text-green-400' : 'text-red-400'}`}>
          {trend}
        </span>
      )}
    </div>
    <h3 className="text-gray-500 dark:text-gray-400 text-sm font-medium mb-1">{title}</h3>
    <p className="text-gray-900 dark:text-white text-2xl font-bold">{value}</p>
  </div>
);

export default function DashboardOverview() {
  return (
    <>
      {/* Header */}
      <header className="shrink-0 border-b border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
        <div className="px-6 py-4">
          <h2 className="text-2xl font-bold text-gray-900 dark:text-white">Dashboard Overview</h2>
        </div>
      </header>

      {/* Main Content */}
      <main className="min-h-0 flex-1 overflow-y-auto bg-slate-50 p-6 dark:bg-slate-950">
        {/* Stats Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-6">
          <StatCard
            title="Total Users"
            value="—"
            icon={<Users className="w-6 h-6 text-red-400" />}
            trend="+12%"
            trendUp={true}
          />
          <StatCard
            title="Active Subscriptions"
            value="—"
            icon={<UserCheck className="w-6 h-6 text-red-400" />}
            trend="+8%"
            trendUp={true}
          />
          <StatCard
            title="Revenue (MTD)"
            value="—"
            icon={<DollarSign className="w-6 h-6 text-red-400" />}
            trend="+15%"
            trendUp={true}
          />
          <StatCard
            title="System Status"
            value="Healthy"
            icon={<Activity className="w-6 h-6 text-green-400" />}
          />
        </div>

        {/* Info Banner */}
        <div className="flex items-start gap-3 rounded-lg border border-blue-200 bg-blue-50 p-4 dark:border-blue-900/50 dark:bg-blue-950/50">
          <AlertCircle className="mt-0.5 h-5 w-5 shrink-0 text-blue-600 dark:text-blue-400" />
          <div>
            <h3 className="mb-1 text-sm font-semibold text-blue-900 dark:text-blue-300">
              Admin Portal - Initial Setup
            </h3>
            <p className="text-sm text-blue-800 dark:text-blue-200/90">
              This is the foundation for your super admin portal. Use the sidebar to navigate between different management sections.
              The User Management section is now fully implemented with signup approval and user management features.
            </p>
          </div>
        </div>

        {/* Footer Info */}
        <div className="mt-auto border-t border-slate-200 pt-6 dark:border-slate-800">
          <div className="text-center text-sm text-gray-500 dark:text-slate-400">
            <p>Super Admin Portal • Apiome Internal Use Only</p>
            <p className="mt-1">Session expires after 8 hours of inactivity</p>
          </div>
        </div>
      </main>
    </>
  );
}

