/**
 * Browser calls for the Backstage and Compass import (CDG-5.5, #5983), through `/api/catalog-migrations`.
 */

import * as React from 'react';

import { fetchMyPermissions } from '@/app/components/ade/access/accessApi';
import type {
  AcceptSuggestionInput,
  CatalogComponent,
  MigrationRun,
  MigrationSuggestion,
} from '@lib/catalog-migrations';

/**
 * Read a proxy answer, or throw its message.
 *
 * @param response - The proxy response.
 * @param fallback - The message when the answer carries none.
 */
async function readJson<T>(response: Response, fallback: string): Promise<T> {
  const body = (await response.json().catch(() => ({}))) as Record<string, unknown>;
  if (!response.ok) {
    throw new Error(typeof body.error === 'string' && body.error ? body.error : fallback);
  }
  return body as T;
}

/** A JSON POST. */
function post(url: string, body: unknown): Promise<Response> {
  return fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
}

/** Every import report, newest first. */
export async function fetchImportReports(): Promise<MigrationRun[]> {
  const body = await readJson<{ runs: MigrationRun[] }>(
    await fetch('/api/catalog-migrations', { cache: 'no-store' }),
    'Could not load the import reports',
  );
  return body.runs ?? [];
}

/** One report with its suggestions. */
export async function fetchImportReport(id: string): Promise<MigrationRun> {
  return readJson<MigrationRun>(
    await fetch(`/api/catalog-migrations/${encodeURIComponent(id)}`, { cache: 'no-store' }),
    'Could not load the import report',
  );
}

/** Upload a Compass export; returns its report. */
export async function uploadCompassExport(filename: string, content: string): Promise<MigrationRun> {
  return readJson<MigrationRun>(
    await post('/api/catalog-migrations/compass', { filename, content }),
    'Could not import the Compass export',
  );
}

/** Accept a suggestion. */
export async function acceptSuggestion(id: string, input: AcceptSuggestionInput = {}): Promise<MigrationSuggestion> {
  return readJson<MigrationSuggestion>(
    await post(`/api/catalog-migrations/suggestions/${encodeURIComponent(id)}/accept`, input),
    'Could not accept the suggestion',
  );
}

/** Dismiss a suggestion. */
export async function dismissSuggestion(id: string): Promise<MigrationSuggestion> {
  return readJson<MigrationSuggestion>(
    await post(`/api/catalog-migrations/suggestions/${encodeURIComponent(id)}/dismiss`, {}),
    'Could not dismiss the suggestion',
  );
}

/** One accepted component, by slug or id. */
export async function fetchComponent(ref: string): Promise<CatalogComponent> {
  return readJson<CatalogComponent>(
    await fetch(`/api/catalog-migrations/components/${encodeURIComponent(ref)}`, { cache: 'no-store' }),
    'Could not load the component',
  );
}

/**
 * Whether the viewer may upload and decide (`imports:create`); `false` until known.
 *
 * @returns The flag.
 */
export function useCanImport(): boolean {
  const [can, setCan] = React.useState(false);
  React.useEffect(() => {
    let live = true;
    fetchMyPermissions()
      .then((mine) => {
        if (live) setCan(Boolean(mine?.is_admin || mine?.permissions?.includes('imports:create')));
      })
      .catch(() => {
        if (live) setCan(false);
      });
    return () => {
      live = false;
    };
  }, []);
  return can;
}
