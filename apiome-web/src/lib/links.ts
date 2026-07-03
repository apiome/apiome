/**
 * Centralized, env-configurable outbound links for the marketing site.
 *
 * These are the primary call-to-action destinations ("Launch App",
 * "Browse APIs", "Watch Demo"). Override them per-environment via the
 * NEXT_PUBLIC_* vars below. Because NEXT_PUBLIC_* values are inlined at build
 * time, changing them requires a rebuild (or setting them in the deploy
 * environment before `next build`).
 */
export const links = {
  /** "Launch App" — the authenticated product. */
  app: process.env.NEXT_PUBLIC_APP_URL || "https://app.apiome.app",
  /** "Browse APIs" — the public spec browser. */
  browse: process.env.NEXT_PUBLIC_BROWSE_URL || "https://browse.apiome.app",
  /** "Watch Demo" — the demo video channel. */
  demo:
    process.env.NEXT_PUBLIC_DEMO_URL ||
    "https://www.youtube.com/@objectifieddev",
} as const;
