/**
 * @jest-environment node
 */
/**
 * Overlay manager BFF routes — COA-2.7 (#7050).
 *
 * `POST /api/versions/{v}/overlays/apply` and `POST …/overlays/preview` forward their JSON body to
 * apiome-rest for the session's tenant; a REST refusal's `code` is passed through.
 */

import { jest } from '@jest/globals';
import { NextRequest } from 'next/server';

const proxyRestPost = jest.fn<(...args: unknown[]) => Promise<Record<string, unknown>>>();

jest.mock('@lib/primitives-api-proxy', () => ({
  getAuthenticatedTenantContext: async () => ({
    ok: true,
    tenantSlug: 'acme',
    user: { id: 'u-1' },
  }),
  proxyRestGet: jest.fn(),
  proxyRestPost: (...args: unknown[]) => proxyRestPost(...args),
  proxyRestPut: jest.fn(),
  proxyRestDelete: jest.fn(),
}));

import { POST as applyPost } from '../src/app/api/versions/[versionId]/overlays/apply/route';
import { POST as previewPost } from '../src/app/api/versions/[versionId]/overlays/preview/route';

const PROJECT = 'p-1';
const REVISION = '11111111-1111-4111-8111-111111111111';

/** A POST to a BFF overlay route. */
function post(suffix: string, body: unknown): NextRequest {
  return new NextRequest(`http://x/api/versions/${REVISION}/overlays${suffix}?projectId=${PROJECT}`, {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

const params = { params: Promise.resolve({ versionId: REVISION }) };

beforeEach(() => proxyRestPost.mockReset());

test('apply forwards the label to REST …/overlays/apply', async () => {
  proxyRestPost.mockResolvedValue({
    data: { version_label: '1.2.0' },
    status: 201,
  });
  const response = await applyPost(post('/apply', { version_label: '1.2.0' }), params);
  expect(response.status).toBe(201);
  expect(await response.json()).toEqual({
    success: true,
    data: { version_label: '1.2.0' },
  });
  expect(proxyRestPost).toHaveBeenCalledWith({ id: 'u-1' }, `/versions/acme/${PROJECT}/${REVISION}/overlays/apply`, {
    version_label: '1.2.0',
  });
});

test('apply passes a refusal code through', async () => {
  proxyRestPost.mockResolvedValue({
    error: 'This revision has no overlays to apply.',
    status: 409,
    detail: {
      code: 'overlay-chain-empty',
      message: 'This revision has no overlays to apply.',
    },
  });
  const response = await applyPost(post('/apply', {}), params);
  expect(response.status).toBe(409);
  expect(await response.json()).toMatchObject({
    success: false,
    code: 'overlay-chain-empty',
  });
});

test('preview forwards a draft to REST …/overlays/preview', async () => {
  proxyRestPost.mockResolvedValue({ data: { draft: 'draft:x' }, status: 200 });
  const body = {
    draft: { name: 'x', document: { overlay: '1.1.0', actions: [] } },
  };
  const response = await previewPost(post('/preview', body), params);
  expect(response.status).toBe(200);
  expect(proxyRestPost).toHaveBeenCalledWith(
    { id: 'u-1' },
    `/versions/acme/${PROJECT}/${REVISION}/overlays/preview`,
    body
  );
});
