import type { Metadata } from "next";
import "../../globals.css";
import * as React from 'react';
import DashboardSideNav from '@/app/components/ade/dashboard/DashboardSideNav';
import { DashboardTooltipProvider } from '@/app/components/ade/dashboard/DashboardTooltipProvider';

export const metadata: Metadata = {
  title: "Apiome: Dashboard",
  description: "Apiome Application",
};

export default function RootLayout({
                                     children,
                                   }: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <div className="flex h-full min-h-0 overflow-hidden bg-gradient-to-br from-slate-50 via-white to-slate-50 dark:from-gray-900 dark:via-gray-900 dark:to-gray-800">
      <DashboardSideNav />

      <main className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-transparent">
        <DashboardTooltipProvider>{children}</DashboardTooltipProvider>
      </main>
    </div>
  );
}
