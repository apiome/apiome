import type { Metadata } from "next";
import "./globals.css";
import { ClientLayout } from "./components/ClientLayout";
import { getDirectoryStats } from "../../lib/db/helper";

export const metadata: Metadata = {
  title: "Apiome Browse - API Specification Browser",
  description: "Enterprise API specification browser for OpenAPI, Arazzo, and JSON Schema",
};

export const dynamic = "force-dynamic";

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const stats = await getDirectoryStats();

  return (
    <html lang="en" suppressHydrationWarning>
      <body className="antialiased">
        <ClientLayout stats={stats}>{children}</ClientLayout>
      </body>
    </html>
  );
}
