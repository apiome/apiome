'use client';

import { useRouter, usePathname } from 'next/navigation';
import { useState } from 'react';
import {
  Users,
  CreditCard,
  Settings,
  LogOut,
  Shield,
  Database,
  Activity,
  Building2,
  Package,
} from 'lucide-react';

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
        ? 'bg-red-600 text-white'
        : 'text-gray-300 hover:bg-gray-700 hover:text-white'
    }`}
  >
    <div className={`flex-shrink-0 ${active ? 'text-white' : 'text-gray-400'}`}>
      {icon}
    </div>
    <span className="font-medium text-sm">{title}</span>
  </button>
);

export default function AdminSidebar() {
  const router = useRouter();
  const pathname = usePathname();
  const [isLoggingOut, setIsLoggingOut] = useState(false);

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

  const menuItems = [
    {
      id: 'users',
      path: '/admin/dashboard/users',
      icon: <Users className="w-5 h-5" />,
      title: 'User Management',
    },
    {
      id: 'tenants',
      path: '/admin/dashboard/tenants',
      icon: <Building2 className="w-5 h-5" />,
      title: 'Tenant Management',
    },
    {
      id: 'templates',
      path: '/admin/dashboard/templates',
      icon: <Package className="w-5 h-5" />,
      title: 'Property Templates',
    },
    {
      id: 'payments',
      path: '/admin/dashboard/payments',
      icon: <CreditCard className="w-5 h-5" />,
      title: 'Payment Management',
    },
    {
      id: 'database',
      path: '/admin/dashboard/database',
      icon: <Database className="w-5 h-5" />,
      title: 'Database Administration',
    },
    {
      id: 'monitoring',
      path: '/admin/dashboard/monitoring',
      icon: <Activity className="w-5 h-5" />,
      title: 'System Monitoring',
    },
    {
      id: 'settings',
      path: '/admin/dashboard/settings',
      icon: <Settings className="w-5 h-5" />,
      title: 'System Configuration',
    }
  ];

  return (
    <aside className="w-64 bg-gray-800 border-r border-gray-700 flex flex-col">
      {/* Sidebar Header */}
      <div className="p-4 border-b border-gray-700">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-red-600 rounded-lg">
            <Shield className="w-5 h-5 text-white" />
          </div>
          <div>
            <h1 className="text-sm font-bold text-white">Super Admin</h1>
            <p className="text-xs text-gray-400">Objectified</p>
          </div>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 p-4 space-y-2 overflow-y-auto">
        <SidebarItem
          icon={<Shield className="w-5 h-5" />}
          title="Overview"
          active={pathname === '/admin/dashboard'}
          onClick={() => router.push('/admin/dashboard')}
        />

        <div className="pt-4 pb-2">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider px-4">
            Management
          </p>
        </div>

        {menuItems.map((item) => (
          <SidebarItem
            key={item.id}
            icon={item.icon}
            title={item.title}
            active={pathname === item.path}
            onClick={() => router.push(item.path)}
          />
        ))}
      </nav>

      {/* Sidebar Footer */}
      <div className="p-4 border-t border-gray-700">
        <button
          onClick={handleLogout}
          disabled={isLoggingOut}
          className="w-full flex items-center gap-2 px-4 py-2 bg-gray-700 hover:bg-gray-600 text-white rounded-lg transition-colors disabled:opacity-50 text-sm"
        >
          <LogOut className="w-4 h-4" />
          {isLoggingOut ? 'Logging out...' : 'Logout'}
        </button>
      </div>
    </aside>
  );
}

