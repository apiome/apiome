import type { Metadata } from "next";
import "./globals.css";
import "@radix-ui/themes/styles.css";
import SessionWrapper from "@/app/components/auth/SessionWrapper";
import ThemeRegistry from "@/app/components/theme/ThemeRegistry";
import { ThemeProvider } from "@/app/providers/ThemeProvider";
import { DialogProvider } from "@/app/components/providers/DialogProvider";
import { Toaster } from "@/app/components/ui/Toaster";
import { ThemeProvider as NextThemesProvider } from "next-themes";
import { Theme as RadixTheme } from "@radix-ui/themes";

export const metadata: Metadata = {
  title: "Objectified",
  description: "Objectified ADE Platform",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="antialiased">
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
            <ThemeRegistry>
              <SessionWrapper>
                <ThemeProvider>
                  <DialogProvider>
                    {children}
                    <Toaster />
                  </DialogProvider>
                </ThemeProvider>
              </SessionWrapper>
            </ThemeRegistry>
          </RadixTheme>
        </NextThemesProvider>
      </body>
    </html>
  );
}
