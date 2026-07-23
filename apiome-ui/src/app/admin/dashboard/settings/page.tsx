import AuthProviderSettingsClient from './AuthProviderSettingsClient';

/**
 * System Configuration (`/admin/dashboard/settings`, OLO-8.7, #4973).
 *
 * The admin sidebar has reserved this path since the portal shipped; it now hosts the sign-in
 * provider configuration screen. Auth gating happens in the shared dashboard layout
 * (`../layout.tsx` redirects to `/admin` without a valid signed session), and every data
 * read/write goes through the super-admin proxy routes (`/api/admin/auth-providers`), which
 * verify the session again.
 */
export default function AdminSettingsPage() {
  return <AuthProviderSettingsClient />;
}
