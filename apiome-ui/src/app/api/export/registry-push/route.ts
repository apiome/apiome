import { NextRequest, NextResponse } from 'next/server';
import { forwardExportDelivery, jsonBodyOr400 } from '@lib/export-delivery-proxy';

export const dynamic = 'force-dynamic';

/**
 * POST /api/export/registry-push — register an Avro, JSON Schema or Protobuf export on a schema registry
 * through a `schema-registry` connector (MFX-46.3). Proxies REST `POST /v1/export/{tenant}/schema-registry/push`;
 * the connector's credentials stay on the server.
 */
export async function POST(request: NextRequest) {
  const body = await jsonBodyOr400(request);
  if (body instanceof NextResponse) return body;
  return forwardExportDelivery('POST', '/schema-registry/push', body);
}
