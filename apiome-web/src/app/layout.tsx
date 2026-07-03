import type { Metadata } from "next";
import { Geist, Geist_Mono, Instrument_Serif } from "next/font/google";
import "./globals.css";
import { ThemeProvider } from "next-themes";
import { getLinks } from "@/lib/links";
import { LinksProvider } from "@/lib/links-context";
import { Navbar } from "./components/Navbar";
import { Footer } from "./components/Footer";
import { ScrollProgress } from "./components/motion/ScrollProgress";

// Resolve APP_URL / BROWSE_URL / DEMO_URL from the process environment on
// each request so container env overrides work without a rebuild.
export const dynamic = "force-dynamic";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
  display: "swap",
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
  display: "swap",
});

const instrumentSerif = Instrument_Serif({
  variable: "--font-display",
  subsets: ["latin"],
  weight: "400",
  style: ["normal", "italic"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "Apiome - Visual API & Database Design Platform",
  description: "Design, build, and manage your APIs and database schemas with our intuitive visual editor. OpenAPI 3.1.0 compliant with multi-tenant support.",
  keywords: "API design, OpenAPI, database schema, visual editor, REST API, GraphQL, API documentation",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const links = getLinks();

  return (
    <html lang="en" suppressHydrationWarning>
      <body
        className={`${geistSans.variable} ${geistMono.variable} ${instrumentSerif.variable} antialiased`}
      >
        <ThemeProvider attribute="class" defaultTheme="system" enableSystem>
          <LinksProvider links={links}>
            <ScrollProgress />
            <div className="relative flex min-h-screen flex-col">
              <Navbar />
              <main className="flex-1">{children}</main>
              <Footer />
            </div>
          </LinksProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
