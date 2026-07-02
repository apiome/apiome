import { redirect } from 'next/navigation';
import { isAdminAuthenticated } from '@/app/utils/adminAuth';

export default async function AdminPage() {
  const isAuthenticated = await isAdminAuthenticated();

  if (isAuthenticated) {
    redirect('/admin/dashboard');
  }

  // This will be handled by the layout which shows the login
  return null;
}

