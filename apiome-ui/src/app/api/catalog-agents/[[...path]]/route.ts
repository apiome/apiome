/**
 * The catalog agents proxy — CDG-5.2 (#5980): `/api/catalog-agents/…` → `/v1/tenants/{t}/catalog-agents/…`.
 */

import { NextRequest } from 'next/server';
import { forwardCatalogAgents } from '@lib/catalog-agents-proxy';

export const dynamic = 'force-dynamic';

type Context = { params: Promise<{ path?: string[] }> };

export async function GET(request: NextRequest, context: Context) {
  return forwardCatalogAgents('catalog-agents', request, (await context.params).path, 'GET');
}

export async function POST(request: NextRequest, context: Context) {
  return forwardCatalogAgents('catalog-agents', request, (await context.params).path, 'POST');
}

export async function PATCH(request: NextRequest, context: Context) {
  return forwardCatalogAgents('catalog-agents', request, (await context.params).path, 'PATCH');
}

export async function PUT(request: NextRequest, context: Context) {
  return forwardCatalogAgents('catalog-agents', request, (await context.params).path, 'PUT');
}

export async function DELETE(request: NextRequest, context: Context) {
  return forwardCatalogAgents('catalog-agents', request, (await context.params).path, 'DELETE');
}
