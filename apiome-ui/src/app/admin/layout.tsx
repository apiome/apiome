import { isAdminAuthenticated } from '@/app/utils/adminAuth';
import AdminLoginClient from './AdminLoginClient';

export default async function AdminLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const isAuthenticated = await isAdminAuthenticated();

  // If not authenticated and not on the login page, show login
  if (!isAuthenticated) {
    return <AdminLoginClient />;
  }

  return <>{children}</>;
}

