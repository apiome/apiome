import graphiqlPackage from 'graphiql/package.json';
import graphqlPackage from 'graphql/package.json';
import { graphiqlViewerCsp, graphiqlViewerHtml } from '@lib/test-drive/graphiql-viewer';

/**
 * GET /test-drive/graphql — the GraphQL test-drive page, GraphiQL over mock data (MFX-44.3).
 *
 * The page Export studio's GraphiQL tab loads into a sandboxed iframe. It holds no data: the SDL
 * arrives from the Studio by `postMessage` after the page loads, and every query runs against mock
 * resolvers inside the page. Its CSP (`connect-src 'none'`, scripts from this origin only) is what
 * makes "no network calls" a guarantee rather than a convention. See `lib/test-drive/graphiql-viewer.ts`.
 */
export function GET(): Response {
  return new Response(graphiqlViewerHtml(`${graphiqlPackage.version}-${graphqlPackage.version}`), {
    headers: {
      'Content-Type': 'text/html; charset=utf-8',
      'Content-Security-Policy': graphiqlViewerCsp(),
      'X-Content-Type-Options': 'nosniff',
      'Referrer-Policy': 'no-referrer',
      'Cache-Control': 'no-store',
    },
  });
}
