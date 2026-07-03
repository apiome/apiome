/**
 * Outbound marketing CTAs ("Launch App", "Browse APIs", "Watch Demo").
 *
 * Resolved on the server at request time so Docker / process env overrides
 * work without rebuilding. Client components must read these via
 * `useLinks()` from `@/lib/links-context` (provided by the root layout).
 *
 * Precedence per URL: bare name (APP_URL) → NEXT_PUBLIC_* → default.
 * Bare names are preferred in production containers; NEXT_PUBLIC_* remains
 * supported for local `.env` files.
 */

export type SiteLinks = {
  /** "Launch App" — the authenticated product. */
  app: string;
  /** "Browse APIs" — the public spec browser. */
  browse: string;
  /** "Watch Demo" — the demo video channel. */
  demo: string;
};

const DEFAULTS: SiteLinks = {
  app: "https://app.apiome.app",
  browse: "https://browse.apiome.app",
  demo: "https://www.youtube.com/@objectifieddev",
};

function firstDefined(...values: Array<string | undefined>): string | undefined {
  for (const value of values) {
    const trimmed = value?.trim();
    if (trimmed) return trimmed;
  }
  return undefined;
}

/** Read link destinations from the current process environment. */
export function getLinks(): SiteLinks {
  return {
    app:
      firstDefined(process.env.APP_URL, process.env.NEXT_PUBLIC_APP_URL) ??
      DEFAULTS.app,
    browse:
      firstDefined(process.env.BROWSE_URL, process.env.NEXT_PUBLIC_BROWSE_URL) ??
      DEFAULTS.browse,
    demo:
      firstDefined(process.env.DEMO_URL, process.env.NEXT_PUBLIC_DEMO_URL) ??
      DEFAULTS.demo,
  };
}
