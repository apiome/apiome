import type { Metadata } from 'next';
import '../../globals.css';
import * as React from 'react';
import AdeAppShell from '@/app/components/shell/AdeAppShell';
import { DashboardTooltipProvider } from '@/app/components/ade/dashboard/DashboardTooltipProvider';

export const metadata: Metadata = {
  title: 'Apiome: Merge request',
  description: 'Review and merge a draft branch',
};

/**
 * `/ade/merge-requests/**` — the merge request page (COL-4.3, #4527), inside the one chrome.
 *
 * Like the review page it sits beside `/ade/dashboard` rather than under it, so it mounts the same
 * Hive application shell and tooltip provider the dashboard layout does.
 */
export default function MergeRequestsLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <AdeAppShell>
      <DashboardTooltipProvider>{children}</DashboardTooltipProvider>
    </AdeAppShell>
  );
}
