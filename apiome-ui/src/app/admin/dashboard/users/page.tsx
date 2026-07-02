import { redirect } from 'next/navigation';
import { isAdminAuthenticated } from '@/app/utils/adminAuth';
import UserManagementClient from './UserManagementClient';

export default async function UserManagementPage() {
  const isAuthenticated = await isAdminAuthenticated();

  if (!isAuthenticated) {
    redirect('/admin');
  }

  return <UserManagementClient />;
}

