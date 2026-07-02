'use server';

import { cookies } from 'next/headers';

export async function isAdminAuthenticated(): Promise<boolean> {
  try {
    const cookieStore = await cookies();
    const adminSession = cookieStore.get('admin_session');

    if (!adminSession) {
      return false;
    }

    // In a production environment, you'd want to verify the token more thoroughly
    // For now, just check if it exists and looks valid
    try {
      const decoded = Buffer.from(adminSession.value, 'base64').toString();
      if (decoded.startsWith('admin:')) {
        const timestamp = parseInt(decoded.split(':')[1]);
        const eightHoursAgo = Date.now() - (8 * 60 * 60 * 1000);

        // Check if token is still valid (within 8 hours)
        return timestamp > eightHoursAgo;
      }
    } catch {
      return false;
    }

    return false;
  } catch {
    return false;
  }
}

