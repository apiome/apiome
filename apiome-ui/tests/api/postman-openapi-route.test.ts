/**
 * @jest-environment node
 *
 * The Postman → OpenAPI proxy — MFI-32.7 (#4409): forwards the collection to
 * `POST /v1/import/{tenant}/postman/openapi`, keeps REST's status and refusal code, and refuses a
 * body without a `document` without calling apiome-rest.
 */

import { beforeEach, describe, expect, jest, test } from '@jest/globals';

const proxyRestPost = jest.fn<(...args: unknown[]) => Promise<unknown>>();

jest.mock('@lib/primitives-api-proxy', () => ({
  getAuthenticatedTenantContext: jest.fn(async () => ({ ok: true, user: { user_id: 'u-1' }, tenantSlug: 'acme' })),
  proxyRestPost: (...args: unknown[]) => proxyRestPost(...args),
}));

import { NextRequest } from 'next/server';
import { POST } from '@/app/api/import/postman/openapi/route';

/** A POST to the route with a JSON body. */
const post = (body: unknown) =>
  POST(new NextRequest('http://ui.test/api/import/postman/openapi', { method: 'POST', body: JSON.stringify(body) }));

beforeEach(() => {
  proxyRestPost.mockReset();
});

describe('the Postman → OpenAPI proxy', () => {
  test('forwards the collection to the tenant’s REST route and returns its result', async () => {
    proxyRestPost.mockResolvedValue({
      data: { source_kind: 'postman', openapi: { openapi: '3.1.0' }, warnings: ['w'] },
      error: null,
      status: 200,
    });
    const response = await post({ document: '{"info":{}}', filename: 'a.json', base_url: 'https://x' });
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({
      success: true,
      source_kind: 'postman',
      openapi: { openapi: '3.1.0' },
      warnings: ['w'],
    });
    expect(proxyRestPost).toHaveBeenCalledWith(
      { user_id: 'u-1' },
      '/import/acme/postman/openapi',
      { document: '{"info":{}}', filename: 'a.json', base_url: 'https://x' }
    );
  });

  test('keeps REST’s refusal and its taxonomy code', async () => {
    proxyRestPost.mockResolvedValue({
      data: null,
      error: 'Not a Postman collection',
      status: 422,
      detail: { code: 'INPUT_SEMANTIC_INVALID', message: 'Not a Postman collection' },
    });
    const response = await post({ document: '{}' });
    expect(response.status).toBe(422);
    expect(await response.json()).toEqual({
      success: false,
      error: 'Not a Postman collection',
      code: 'INPUT_SEMANTIC_INVALID',
    });
  });

  test('refuses a body without a document', async () => {
    const response = await post({ filename: 'a.json' });
    expect(response.status).toBe(400);
    expect(proxyRestPost).not.toHaveBeenCalled();
  });
});
