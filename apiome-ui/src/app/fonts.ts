import { Inter, JetBrains_Mono, Manrope } from "next/font/google";

/**
 * App typography: Inter for UI text, JetBrains Mono for code — the pairing
 * established by the unified-workspace mockups
 * (private-suite/docs/mockups/new-layout/canvas-density-patterns.html).
 * next/font downloads the files at build time and serves them from our
 * origin, so no runtime request ever goes to Google.
 *
 * The variables are consumed by globals.css: `--app-font-sans` and
 * `--app-font-mono` resolve them with the previous system stacks as the
 * var() fallback, so sibling apps that import globals.css without mounting
 * these classes (e.g. the private-suite designer, which aliases `@` to this
 * repo's src) degrade to system fonts instead of breaking.
 */
export const interSans = Inter({
  subsets: ["latin"],
  display: "swap",
  variable: "--app-webfont-sans",
});

export const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  display: "swap",
  variable: "--app-webfont-mono",
});

/**
 * The display voice (facelift idea "type", PROPOSALS_FACELIFT.md §2): Manrope at 700/800 for
 * page titles, greetings, section and dialog titles and the big numbers. Inter stays the text
 * face. `globals.css` reads it as `--font-display`, with the sans stack as the fallback.
 */
export const manropeDisplay = Manrope({
  subsets: ["latin"],
  weight: ["600", "700", "800"],
  display: "swap",
  variable: "--app-webfont-display",
});
