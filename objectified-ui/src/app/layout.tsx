import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import SessionWrapper from "@/app/components/auth/SessionWrapper";
import ThemeRegistry from "@/app/components/theme/ThemeRegistry";

const inter = Inter({
  subsets: ['latin'],
  display: 'swap',
  variable: '--font-inter',
});

export const metadata: Metadata = {
  title: "Objectified",
  description: "Objectified",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={inter.variable}>
      <body className="antialiased">
        <ThemeRegistry>
          <SessionWrapper>
            {children}
          </SessionWrapper>
        </ThemeRegistry>
      </body>
    </html>
  );
}
