import { NextRequest } from 'next/server';
import { openApiViewerCsp, openApiViewerHtml, openApiViewerKind } from '@lib/test-drive/openapi-viewer';
import { testDriveVendorVersion } from '@lib/test-drive/vendor-assets';

/**
 * GET /test-drive/openapi?viewer=swagger-ui|redoc — the OpenAPI test-drive viewer page (MFX-44.2).
 *
 * The page Export studio's Swagger UI / ReDoc tabs load into a sandboxed iframe. It holds no data:
 * the document arrives from the Studio by `postMessage` after the page loads. Its CSP
 * (`connect-src 'none'`, hashed inline bridge, self-hosted bundles) is what makes "no network calls"
 * a guarantee rather than a convention. See `lib/test-drive/openapi-viewer.ts`.
 */
export function GET(request: NextRequest): Response {
  const viewer = openApiViewerKind(request.nextUrl.searchParams.get('viewer'));
  return new Response(openApiViewerHtml(viewer, testDriveVendorVersion()), {
    headers: {
      'Content-Type': 'text/html; charset=utf-8',
      'Content-Security-Policy': openApiViewerCsp(),
      'X-Content-Type-Options': 'nosniff',
      'Referrer-Policy': 'no-referrer',
      'Cache-Control': 'no-store',
    },
  });
}
