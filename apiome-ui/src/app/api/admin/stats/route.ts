import { NextResponse } from 'next/server';
import { isAdminAuthenticated } from '@/app/utils/adminAuth';

export async function GET() {
  const isAuthenticated = await isAdminAuthenticated();

  if (!isAuthenticated) {
    return NextResponse.json(
      { error: 'Unauthorized access', message: 'Admin authentication required' },
      { status: 401 }
    );
  }

  // Return dummy data for now
  return NextResponse.json({
    totalUsers: 0,
    activeUsers: 0,
    totalRevenue: 0,
    systemStatus: 'healthy',
  });
}

