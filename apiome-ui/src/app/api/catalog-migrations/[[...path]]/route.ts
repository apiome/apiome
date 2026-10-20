/**
 * The catalog imports proxy — CDG-5.5 (#5983): `/api/catalog-migrations/…` → apiome-rest's
 * `catalog-migrations`, `catalog-migration-suggestions` and `catalog-components` routes.
 */

import { NextRequest } from 'next/server';
import { forwardCatalogMigrations } from '@lib/catalog-migrations-proxy';

export const dynamic = 'force-dynamic';

type Context = { params: Promise<{ path?: string[] }> };

export async function GET(request: NextRequest, context: Context) {
  return forwardCatalogMigrations(request, (await context.params).path, 'GET');
}

export async function POST(request: NextRequest, context: Context) {
  return forwardCatalogMigrations(request, (await context.params).path, 'POST');
}
