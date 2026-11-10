'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  Users,
  CreditCard,
  Settings,
  LogOut,
  Shield,
  Database,
  Activity,
  AlertCircle,
  DollarSign,
  UserCheck,
} from 'lucide-react';

interface StatCardProps {
  title: string;
  value: string | number;
  icon: React.ReactNode;
  trend?: string;
  trendUp?: boolean;
}

const StatCard: React.FC<StatCardProps> = ({ title, value, icon, trend, trendUp }) => (
  <div className="bg-surface border border-border rounded-lg p-6 hover:border-border-strong transition-colors">
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

interface SidebarItemProps {
  icon: React.ReactNode;
  title: string;
  active?: boolean;
  onClick: () => void;
}

const SidebarItem: React.FC<SidebarItemProps> = ({ icon, title, active, onClick }) => (
  <button
    onClick={onClick}
    className={`w-full flex items-center gap-3 px-4 py-3 rounded-lg transition-all text-left ${
      active
        ? 'bg-danger text-fg-on-accent'
        : 'text-fg-muted hover:bg-subtle hover:text-fg'
    }`}
  >
    <div className={`flex-shrink-0 ${active ? 'text-fg-on-accent' : 'text-fg-subtle'}`}>
      {icon}
    </div>
    <span className="font-medium text-sm">{title}</span>
  </button>
);

export default function AdminDashboardClient() {
  const router = useRouter();
  const [isLoggingOut, setIsLoggingOut] = useState(false);
  const [activeSection, setActiveSection] = useState('overview');

  const handleLogout = async () => {
    setIsLoggingOut(true);
    try {
      await fetch('/api/admin/auth', { method: 'DELETE' });
      router.push('/admin');
      router.refresh();
    } catch (error) {
      console.error('Logout error:', error);
    } finally {
      setIsLoggingOut(false);
    }
  };

  const handleSectionClick = (sectionId: string) => {
    if (sectionId === 'users') {
      // Navigate to the user management page
      router.push('/admin/dashboard/users');
    } else {
      // For other sections, just update the active state
      setActiveSection(sectionId);
    }
  };

  const menuItems = [
    {
      id: 'users',
      icon: <Users className="w-5 h-5" />,
      title: 'Users',
      description: 'View, edit, and manage user accounts, permissions, and access levels',
      features: ['View all users', 'Edit user details', 'Manage permissions', 'Deactivate accounts', 'View user activity']
    },
    {
      id: 'payments',
      icon: <CreditCard className="w-5 h-5" />,
      title: 'Payments',
      description: 'Monitor subscriptions, process refunds, and manage billing information',
      features: ['View all transactions', 'Process refunds', 'Manage subscriptions', 'Export payment reports', 'Update pricing']
    },
    {
      id: 'database',
      icon: <Database className="w-5 h-5" />,
      title: 'Database',
      description: 'Run queries, view analytics, and manage database operations',
      features: ['Run SQL queries', 'View table statistics', 'Manage backups', 'Monitor performance', 'Data export/import']
    },
    {
      id: 'monitoring',
      icon: <Activity className="w-5 h-5" />,
      title: 'Monitoring',
      description: 'View system health, logs, and performance metrics',
      features: ['View system logs', 'Monitor API usage', 'Track errors', 'Performance metrics', 'Uptime monitoring']
    },
    {
      id: 'settings',
      icon: <Settings className="w-5 h-5" />,
      title: 'System settings',
      description: 'Manage application settings, feature flags, and configurations',
      features: ['Toggle feature flags', 'Update system settings', 'Configure integrations', 'Manage API keys', 'Email templates']
    }
  ];

  return (
    <div className="min-h-screen bg-subtle flex">
      {/* Sidebar */}
      <aside className="w-64 bg-surface border-r border-border flex flex-col">
        {/* Sidebar Header */}
        <div className="p-4 border-b border-border">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-danger rounded-lg">
              <Shield className="w-5 h-5 text-white" />
            </div>
            <div>
              <h1 className="text-sm font-bold text-fg">Super Admin</h1>
              <p className="text-xs text-fg-muted">Apiome</p>
            </div>
          </div>
        </div>

        {/* Navigation */}
        <nav className="flex-1 p-4 space-y-2 overflow-y-auto">
          <SidebarItem
            icon={<Shield className="w-5 h-5" />}
            title="Overview"
            active={activeSection === 'overview'}
            onClick={() => router.push('/admin/dashboard')}
          />

          <div className="pt-4 pb-2">
            <p className="text-xs font-semibold text-fg-muted uppercase tracking-wider px-4">
              Management
            </p>
          </div>

          {menuItems.map((item) => (
            <SidebarItem
              key={item.id}
              icon={item.icon}
              title={item.title}
              active={activeSection === item.id}
              onClick={() => handleSectionClick(item.id)}
            />
          ))}
        </nav>

        {/* Sidebar Footer */}
        <div className="p-4 border-t border-border">
          <button
            onClick={handleLogout}
            disabled={isLoggingOut}
            className="w-full flex items-center gap-2 px-4 py-2 bg-inset hover:bg-subtle text-fg rounded-lg transition-colors disabled:opacity-50 text-sm"
          >
            <LogOut className="w-4 h-4" />
            {isLoggingOut ? 'Logging out...' : 'Logout'}
          </button>
        </div>
      </aside>

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Header */}
        <header className="bg-surface/80 border-b border-border backdrop-blur-sm">
          <div className="px-6 py-4">
            <h2 className="text-2xl font-bold text-fg">
              {activeSection === 'overview'
                ? 'Dashboard Overview'
                : menuItems.find(item => item.id === activeSection)?.title || 'Dashboard'}
            </h2>
          </div>
        </header>

        {/* Main Content */}
        <main className="flex-1 overflow-y-auto p-6">
          {activeSection === 'overview' ? (
            <>
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
              <div className="bg-accent/30 border border-accent/50 rounded-lg p-4 flex items-start gap-3">
                <AlertCircle className="w-5 h-5 text-accent-fg flex-shrink-0 mt-0.5" />
                <div>
                  <h3 className="text-accent-fg font-semibold text-sm mb-1">
                    Admin Portal - Initial Setup
                  </h3>
                  <p className="text-accent-fg text-sm">
                    This is the foundation for your super admin portal. Use the sidebar to navigate between different management sections.
                    Connect to your backend API to enable full functionality.
                  </p>
                </div>
              </div>
            </>
          ) : (
            <>
              {/* Section Content */}
              <div className="bg-surface border border-border rounded-lg p-6">
                <div className="flex items-start gap-4 mb-6">
                  <div className="p-3 bg-danger/20 rounded-lg">
                    {menuItems.find(item => item.id === activeSection)?.icon}
                  </div>
                  <div className="flex-1">
                    <h3 className="text-fg font-semibold text-xl mb-2">
                      {menuItems.find(item => item.id === activeSection)?.title}
                    </h3>
                    <p className="text-fg-muted text-sm">
                      {menuItems.find(item => item.id === activeSection)?.description}
                    </p>
                  </div>
                </div>

                {/* Features List */}
                <div className="bg-subtle/50 rounded-lg p-4 border border-border">
                  <h4 className="text-fg font-semibold text-sm mb-3">Coming Soon Features:</h4>
                  <ul className="space-y-2">
                    {menuItems.find(item => item.id === activeSection)?.features.map((feature, index) => (
                      <li key={index} className="flex items-center gap-2 text-fg-muted text-sm">
                        <div className="w-1.5 h-1.5 bg-danger rounded-full"></div>
                        {feature}
                      </li>
                    ))}
                  </ul>
                </div>

                {/* Placeholder Content */}
                <div className="mt-6 p-4 bg-warn/20 border border-warn/50 rounded-lg">
                  <p className="text-warn-fg text-sm">
                    ⚠️ This section is under development. The features listed above will be implemented based on your specific requirements.
                  </p>
                </div>
              </div>
            </>
          )}

          {/* Footer Info */}
          <div className="mt-auto pt-6 border-t border-border">
            <div className="text-center text-fg-muted text-sm">
              <p>Super Admin Portal • Apiome Internal Use Only</p>
              <p className="mt-1">Session expires after 8 hours of inactivity</p>
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}

