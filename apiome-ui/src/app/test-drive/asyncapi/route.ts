import { asyncApiViewerCsp, asyncApiViewerHtml } from '@lib/test-drive/asyncapi-viewer';
import { testDriveVendorVersion } from '@lib/test-drive/vendor-assets';

/**
 * GET /test-drive/asyncapi — the AsyncAPI test-drive viewer page (MFX-44.4).
 *
 * The page Export studio's AsyncAPI viewer tab loads into a sandboxed iframe. It holds no data: the
 * document arrives from the Studio by `postMessage` after the page loads. Its CSP
 * (`connect-src 'none'`, hashed inline bridge, self-hosted bundle) is what makes "no network calls"
 * a guarantee rather than a convention. See `lib/test-drive/asyncapi-viewer.ts`.
 */
export function GET(): Response {
  return new Response(asyncApiViewerHtml(testDriveVendorVersion()), {
    headers: {
      'Content-Type': 'text/html; charset=utf-8',
      'Content-Security-Policy': asyncApiViewerCsp(),
      'X-Content-Type-Options': 'nosniff',
      'Referrer-Policy': 'no-referrer',
      'Cache-Control': 'no-store',
    },
  });
}
