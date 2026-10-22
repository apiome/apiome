import { redirect } from 'next/navigation';

import { PLATFORM_NAV_SDK_SETTINGS_HREF } from '@lib/platform-nav';

/**
 * `/ade/dashboard/sdk-settings` — kept so old links and bookmarks still resolve (HIVE-12.2, #5609).
 *
 * SDK settings left the rail and became the **SDK & branding** tab of Export studio
 * (`/ade/dashboard/export/studio?tab=sdk`), which mounts `SdkSettingsClient` from this folder
 * and carries the release gate. This route only sends the reader there.
 *
 * @returns Never — `redirect()` ends the render.
 */
export default function SdkSettingsPage(): never {
  redirect(PLATFORM_NAV_SDK_SETTINGS_HREF);
}
