import type { Metadata } from "next";
import "../../globals.css";
import * as React from 'react';
import DashboardSideNav from '@/app/components/ade/dashboard/DashboardSideNav';

export const metadata: Metadata = {
  title: "Objectified: Dashboard",
  description: "Objectified Application",
};

export default function RootLayout({
                                     children,
                                   }: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <div
      className="bg-gradient-to-br from-slate-50 via-white to-slate-50 dark:from-gray-900 dark:via-gray-900 dark:to-gray-800"
      style={{ display: "flex", height: "calc(100vh - 48px)" }}
    >
      <DashboardSideNav/>

      <main
        className="bg-transparent"
        style={{ flex: 1, overflow: "auto" }}
      >
        {children}
      </main>
    </div>
  );
}
