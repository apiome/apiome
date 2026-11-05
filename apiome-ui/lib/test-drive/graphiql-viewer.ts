/**
 * The GraphQL test-drive page (GraphiQL) — MFX-44.3 (#4369).
 *
 * Export studio's GraphiQL tab renders the emitted SDL inside a **sandboxed iframe**
 * (`sandbox="allow-scripts"`, no same-origin: an opaque origin with no cookies, no storage and no
 * access to the Studio), the same way the OpenAPI viewers do (`openapi-viewer.ts`). This module builds
 * that page, served by `src/app/test-drive/graphql/route.ts`:
 *
 * - one self-hosted bundle (React, GraphiQL, `graphql` and `@graphql-tools/mock`), built from
 *   `graphiql-app.tsx` by `scripts/build-test-drive-graphiql.mjs` into `public/test-drive/graphiql/`;
 * - **no inline script** at all, so the policy allows scripts from the app's own origin only;
 * - **`connect-src 'none'`**: queries run against mock resolvers inside the page, which cannot make a
 *   network request.
 *
 * The SDL arrives from the Studio by `postMessage` (`apiome-test-drive:load` with `sdl` and `theme`),
 * or, for a small file, in the URL fragment (`#sdl=…`, never sent to the server; the docs screenshot
 * uses it). The page posts `ready` once it listens, then `rendered` or `error`.
 */

/** The route that serves the page. */
export const GRAPHIQL_VIEWER_PATH = '/test-drive/graphql';

/** Where the build writes the bundle, under `public/` (and so the URL it is served from). */
export const GRAPHIQL_BUNDLE_PATH = '/test-drive/graphiql';

/** The bundle's script and stylesheet, under {@link GRAPHIQL_BUNDLE_PATH}. */
export const GRAPHIQL_BUNDLE_FILES = { script: 'graphiql-test-drive.js', style: 'graphiql-test-drive.css' } as const;

/** The largest SDL the `#sdl=` fragment feed accepts, in characters. */
export const FRAGMENT_SDL_MAX_CHARS = 64_000;

/**
 * The page's Content-Security-Policy.
 *
 * Scripts from the app's own origin only (no inline script, no `eval`), no network of its own, no
 * third-party origin anywhere, and embeddable only by the app itself.
 *
 * @returns The header value.
 */
export function graphiqlViewerCsp(): string {
  return [
    "default-src 'none'",
    "script-src 'self'",
    // GraphiQL's editor and popovers set inline styles at runtime.
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self' data:",
    "connect-src 'none'",
    "base-uri 'none'",
    "form-action 'none'",
    "frame-ancestors 'self'",
  ].join('; ');
}

/**
 * The page's HTML.
 *
 * @param version A cache key for the bundle (its package versions).
 * @returns The document.
 */
export function graphiqlViewerHtml(version: string): string {
  const asset = (name: string) => `${GRAPHIQL_BUNDLE_PATH}/${name}?v=${encodeURIComponent(version)}`;
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>GraphiQL test drive</title>
<link rel="stylesheet" href="${asset(GRAPHIQL_BUNDLE_FILES.style)}">
</head>
<body data-fragment-max="${FRAGMENT_SDL_MAX_CHARS}">
<p id="test-drive-status">Waiting for the schema…</p>
<div id="test-drive-root"></div>
<script src="${asset(GRAPHIQL_BUNDLE_FILES.script)}"></script>
</body>
</html>
`;
}
