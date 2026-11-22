import { NextRequest } from 'next/server';
import { forwardExportDelivery } from '@lib/export-delivery-proxy';

export const dynamic = 'force-dynamic';

/**
 * GET /api/export/storage-credentials — the workspace's S3-compatible bucket credentials (MFX-38.3),
 * described without secrets: what an object-storage delivery profile picks from (MFX-38.4, #4331).
 */
export async function GET() {
  return forwardExportDelivery('GET', '/storage-credentials');
}

/**
 * POST /api/export/storage-credentials — store a new bucket credential (COA-5.15, #7092), so
 * **Document storage** can add one without leaving the screen. The key pair is forwarded once and
 * sealed by REST; the answer describes the credential without it.
 */
export async function POST(request: NextRequest) {
  const raw = (await request.json().catch(() => ({}))) as Record<string, unknown>;
  const text = (value: unknown) => (typeof value === 'string' ? value : '');
  const endpointUrl = text(raw.endpointUrl).trim();
  return forwardExportDelivery('POST', '/storage-credentials', {
    name: text(raw.name).trim(),
    accessKeyId: text(raw.accessKeyId).trim(),
    secretAccessKey: text(raw.secretAccessKey),
    ...(endpointUrl ? { endpointUrl } : {}),
    region: text(raw.region).trim() || 'us-east-1',
    forcePathStyle: raw.forcePathStyle === true,
  });
}
