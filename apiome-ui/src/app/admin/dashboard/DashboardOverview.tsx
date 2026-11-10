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
  <div className="rounded-lg border border-border bg-surface p-6 transition-colors hover:border-border-strong">
    <div className="flex items-start justify-between mb-4">
      <div className="p-2 bg-danger/20 rounded-lg">
        {icon}
      </div>
      {trend && (
        <span className={`text-sm font-medium ${trendUp ? 'text-ok-fg' : 'text-danger-fg'}`}>
          {trend}
        </span>
      )}
    </div>
    <h3 className="text-fg-muted text-sm font-medium mb-1">{title}</h3>
    <p className="text-fg text-2xl font-bold">{value}</p>
  </div>
);

export default function DashboardOverview() {
  return (
    <>
      {/* Header */}
      <header className="shrink-0 border-b border-border bg-surface">
        <div className="px-6 py-4">
          <h2 className="text-2xl font-bold text-fg">Dashboard Overview</h2>
        </div>
      </header>

      {/* Main Content */}
      <main className="min-h-0 flex-1 overflow-y-auto bg-subtle p-6">
        {/* Stats Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-6">
          <StatCard
            title="Total Users"
            value="—"
            icon={<Users className="w-6 h-6 text-danger-fg" />}
            trend="+12%"
            trendUp={true}
          />
          <StatCard
            title="Active Subscriptions"
            value="—"
            icon={<UserCheck className="w-6 h-6 text-danger-fg" />}
            trend="+8%"
            trendUp={true}
          />
          <StatCard
            title="Revenue (MTD)"
            value="—"
            icon={<DollarSign className="w-6 h-6 text-danger-fg" />}
            trend="+15%"
            trendUp={true}
          />
          <StatCard
            title="System Status"
            value="Healthy"
            icon={<Activity className="w-6 h-6 text-ok-fg" />}
          />
        </div>

        {/* Info Banner */}
        <div className="flex items-start gap-3 rounded-lg border border-accent/30 bg-accent-soft p-4">
          <AlertCircle className="mt-0.5 h-5 w-5 shrink-0 text-accent-fg" />
          <div>
            <h3 className="mb-1 text-sm font-semibold text-accent-fg">
              Admin Portal - Initial Setup
            </h3>
            <p className="text-sm text-accent-fg">
              This is the foundation for your super admin portal. Use the sidebar to navigate between different management sections.
              The Users section is now fully implemented with signup approval and user management features.
            </p>
          </div>
        </div>

        {/* Footer Info */}
        <div className="mt-auto border-t border-border pt-6">
          <div className="text-center text-sm text-fg-muted">
            <p>Super Admin Portal • Apiome Internal Use Only</p>
            <p className="mt-1">Session expires after 8 hours of inactivity</p>
          </div>
        </div>
      </main>
    </>
  );
}

