import type { Metadata } from "next";
import "../globals.css";
import "@radix-ui/themes/styles.css";
import SessionWrapper from "@/app/components/auth/SessionWrapper";
import AuthenticatedLayout from "@/app/components/auth/AuthenticatedLayout";
import ConditionalHeader from '@/app/components/ade/ConditionalHeader';
import { ThemeProvider } from '@/app/providers/ThemeProvider';
import { ThemeProvider as NextThemesProvider } from "next-themes";
import { Theme as RadixTheme } from "@radix-ui/themes";
import * as React from 'react';

export const metadata: Metadata = {
  title: "Objectified: Studio",
  description: "Objectified ADE Platform - Studio",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <div className="antialiased">
      <NextThemesProvider
        attribute="class"
        defaultTheme="system"
        enableSystem
        storageKey="theme"
      >
        <RadixTheme
          accentColor="indigo"
          grayColor="slate"
          panelBackground="solid"
          radius="medium"
          scaling="100%"
        >
          <ThemeProvider>
            <SessionWrapper>
              <AuthenticatedLayout>
                <ConditionalHeader />
                {children}
              </AuthenticatedLayout>
            </SessionWrapper>
          </ThemeProvider>
        </RadixTheme>
      </NextThemesProvider>
    </div>
  );
}
