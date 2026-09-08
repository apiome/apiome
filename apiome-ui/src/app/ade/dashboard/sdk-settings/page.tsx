import SdkSettingsClient from './SdkSettingsClient';

/**
 * SDK settings — `/ade/dashboard/sdk-settings` (SDK-3.4, #4494).
 *
 * A thin server shell, like every other dashboard screen: all state, loading and permission
 * gating live in the client component.
 *
 * @returns The SDK settings screen.
 */
export default function SdkSettingsPage() {
  return <SdkSettingsClient />;
}
