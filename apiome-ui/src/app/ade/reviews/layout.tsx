import type { Metadata } from 'next';
import '../../globals.css';
import * as React from 'react';
import AdeAppShell from '@/app/components/shell/AdeAppShell';
import { DashboardTooltipProvider } from '@/app/components/ade/dashboard/DashboardTooltipProvider';

export const metadata: Metadata = {
  title: 'Apiome: Review',
  description: 'Review a draft version',
};

/**
 * `/ade/reviews/**` — the review page (COL-2.2, #4518), inside the one chrome.
 *
 * The route sits beside `/ade/dashboard` rather than under it, as the issue names it, so it mounts
 * the same Hive application shell and tooltip provider the dashboard layout does.
 */
export default function ReviewsLayout({
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
