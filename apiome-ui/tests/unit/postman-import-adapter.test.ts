/**
 * `convertPostmanWithAdapter` — the Postman import card's call to the REST adapter (MFI-32.7, #4409).
 */

import { describe, expect, jest, test } from '@jest/globals';
import { POSTMAN_TO_OPENAPI_ROUTE, convertPostmanWithAdapter } from '../../src/app/utils/postman-import-adapter';

/** A fetch stub answering with `body` and `status`. */
function answer(body: unknown, status = 200) {
  return jest.fn(async () => ({ ok: status >= 200 && status < 300, status, json: async () => body }) as Response) as unknown as typeof fetch;
}

describe('convertPostmanWithAdapter', () => {
  test('posts the collection and returns the OpenAPI document and warnings', async () => {
    const fetchImpl = answer({ success: true, openapi: { openapi: '3.1.0', paths: {} }, warnings: ['Scripts are not modelled.'] });
    const result = await convertPostmanWithAdapter('{"info":{}}', { baseUrl: 'https://api.example.com', filename: 'c.json', fetchImpl });
    expect(result).toEqual({ success: true, document: { openapi: '3.1.0', paths: {} }, warnings: ['Scripts are not modelled.'] });
    const [url, init] = (fetchImpl as unknown as jest.Mock).mock.calls[0] as [string, RequestInit];
    expect(url).toBe(POSTMAN_TO_OPENAPI_ROUTE);
    expect(JSON.parse(String(init.body))).toEqual({
      document: '{"info":{}}',
      filename: 'c.json',
      base_url: 'https://api.example.com',
    });
  });

  test('sends no base_url or filename when there is none', async () => {
    const fetchImpl = answer({ success: true, openapi: { openapi: '3.1.0' }, warnings: [] });
    await convertPostmanWithAdapter('{}', { fetchImpl });
    const [, init] = (fetchImpl as unknown as jest.Mock).mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(String(init.body))).toEqual({ document: '{}' });
  });

  test('returns the server’s error message', async () => {
    const result = await convertPostmanWithAdapter('{}', {
      fetchImpl: answer({ success: false, error: 'Not a Postman collection' }, 422),
    });
    expect(result).toEqual({ success: false, error: 'Not a Postman collection', warnings: [] });
  });

  test('names the status when the server gives no message', async () => {
    const result = await convertPostmanWithAdapter('{}', { fetchImpl: answer({}, 502) });
    expect(result).toEqual({ success: false, error: 'Conversion failed (502)', warnings: [] });
  });

  test('never throws when the request itself fails', async () => {
    const fetchImpl = jest.fn(async () => {
      throw new Error('offline');
    }) as unknown as typeof fetch;
    const result = await convertPostmanWithAdapter('{}', { fetchImpl });
    expect(result).toEqual({ success: false, error: 'Could not reach Apiome: offline', warnings: [] });
  });
});
