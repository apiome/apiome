import { readTestDriveVendorAsset } from '@lib/test-drive/vendor-assets';

/**
 * GET /test-drive/vendor/{asset} — the self-hosted Swagger UI / ReDoc bundles (MFX-44.2).
 *
 * Serves only the allow-listed files of `TEST_DRIVE_VENDOR_ASSETS` from `node_modules`, so the
 * sandboxed viewer page loads nothing from a CDN. Anything else is a 404.
 */
export async function GET(
  _request: Request,
  { params }: { params: Promise<{ asset: string }> },
): Promise<Response> {
  const { asset } = await params;
  const found = await readTestDriveVendorAsset(asset);
  if (!found) return new Response('Not found', { status: 404 });
  return new Response(new Uint8Array(found.bytes), {
    headers: {
      'Content-Type': found.contentType,
      'X-Content-Type-Options': 'nosniff',
      'Cache-Control': 'public, max-age=86400',
    },
  });
}
