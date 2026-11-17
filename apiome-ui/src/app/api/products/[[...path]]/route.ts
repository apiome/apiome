/**
 * The API products proxy — APX-1.1 (#6098): `/api/products[/{slug}[/members[/{id}]]]` →
 * apiome-rest's `/v1/tenants/{t}/products…`.
 */

import { NextRequest } from 'next/server';
import { forwardApiProducts } from '@lib/api-products-proxy';

export const dynamic = 'force-dynamic';

type Context = { params: Promise<{ path?: string[] }> };

export async function GET(request: NextRequest, context: Context) {
  return forwardApiProducts(request, (await context.params).path, 'GET');
}

export async function POST(request: NextRequest, context: Context) {
  return forwardApiProducts(request, (await context.params).path, 'POST');
}

export async function PATCH(request: NextRequest, context: Context) {
  return forwardApiProducts(request, (await context.params).path, 'PATCH');
}

export async function DELETE(request: NextRequest, context: Context) {
  return forwardApiProducts(request, (await context.params).path, 'DELETE');
}
