import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "../globals.css";
import SessionWrapper from "@/app/components/auth/SessionWrapper";
import AuthenticatedLayout from "@/app/components/auth/AuthenticatedLayout";
import TopHeader from '@/app/components/ade/TopHeader';
import * as React from 'react';

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Objectified: Studio",
  description: "Objectified Application",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased`}
      >
        <SessionWrapper>
          <AuthenticatedLayout>
            <TopHeader/>
            {children}
          </AuthenticatedLayout>
        </SessionWrapper>
      </body>
    </html>
  );
}
