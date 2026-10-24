/**
 * Catalog item detail × role — RC6-H5 (#6212).
 *
 * Renders a catalog item's page as Viewer, Editor and Owner and checks every control
 * `docs/catalog-projects-permission-matrix.json` puts on it (Categorize, Convert, Export).
 */

import React from 'react';
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';

let mockRole = 'owner';

jest.mock('../src/app/components/ade/access/useMyPermissions', () => ({
  ...jest.requireActual('../src/app/components/ade/access/useMyPermissions'),
  useMyPermissions: () => jest.requireActual<typeof import('./helpers/permission-matrix')>('./helpers/permission-matrix').permissionsFor(mockRole),
}));

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

jest.mock('@lib/auth/session-client', () => ({
  useAuthSession: () => ({ data: { user: { user_id: 'u-ada', current_tenant_id: 'tenant-1' } } }),
}));

jest.mock('@monaco-editor/react', () => ({ __esModule: true, default: () => null }));

import { CatalogItemDetailClient } from '../src/app/ade/dashboard/catalog/[id]/CatalogItemDetailClient';
import { ROLES, screenMismatches } from './helpers/permission-matrix';

const ITEM = {
  id: 'c3a5e1f0-0000-4000-8000-000000000001',
  name: 'Claims 837P',
  slug: 'claims-837p',
  description: 'Professional healthcare claim interchange.',
  enabled: true,
  deleted_at: null,
  created_at: '2026-08-12T14:40:00.000Z',
  updated_at: '2026-08-15T09:41:00.000Z',
  creator_name: 'Ada Lovelace',
  creator_email: 'ada@example.com',
  qualityScore: 84,
  qualityGrade: 'B',
  publishable: false,
  sourceFormat: 'x12',
  protocol: 'data-schema',
  formatMetadata: { sourceLabel: 'claims-837p-sample.edi', inputKind: 'file' },
  paradigm: 'data_schema',
  domain: null,
  tags: [],
  summary: { services: 1, operations: 1, types: 27, channels: null },
  source: { kind: 'file', label: 'claims-837p-sample.edi', hasContent: true, downloadable: true },
  conversion: null,
  parsed: [],
  relatedArtifacts: [],
};

beforeEach(() => {
  global.fetch = jest.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url === `/api/catalog/${encodeURIComponent(ITEM.id)}`) {
      return { ok: true, json: async () => ({ success: true, item: ITEM }) } as Response;
    }
    return { ok: true, json: async () => ({ success: true }) } as Response;
  }) as unknown as typeof fetch;
});

describe.each(ROLES)('a catalog item as %s', (role) => {
  it('offers each control exactly when the role may use it', async () => {
    mockRole = role;
    render(<CatalogItemDetailClient itemId={ITEM.id} />);
    await screen.findByRole('heading', { level: 1, name: /Claims 837P/ });

    expect(await screenMismatches('catalog-detail', role, { ids: {} })).toEqual([]);
  });
});
