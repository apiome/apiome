/**
 * @jest-environment node
 */
/**
 * The OpenAPI test-drive routes — MFX-44.2 (#4368): `/test-drive/openapi` serves the viewer page with its
 * no-network Content-Security-Policy; `/test-drive/vendor/{asset}` serves only the allow-listed bundles.
 */

import { NextRequest } from 'next/server';

import { openApiViewerCsp } from '../lib/test-drive/openapi-viewer';
import { GET as page } from '../src/app/test-drive/openapi/route';
import { GET as vendor } from '../src/app/test-drive/vendor/[asset]/route';

const params = (asset: string) => ({ params: Promise.resolve({ asset }) });

it('serves the viewer page with its policy', async () => {
  const response = page(new NextRequest('http://localhost/test-drive/openapi?viewer=redoc'));
  expect(response.headers.get('content-security-policy')).toBe(openApiViewerCsp());
  expect(response.headers.get('content-type')).toContain('text/html');
  expect(response.headers.get('referrer-policy')).toBe('no-referrer');
  expect(await response.text()).toContain('data-viewer="redoc"');
});

it('serves the allow-listed vendor files and nothing else', async () => {
  const css = await vendor(new Request('http://localhost/x'), params('swagger-ui.css'));
  expect(css.status).toBe(200);
  expect(css.headers.get('content-type')).toContain('text/css');
  const bundle = await vendor(new Request('http://localhost/x'), params('swagger-ui-bundle.js'));
  expect(bundle.headers.get('content-type')).toContain('text/javascript');
  for (const asset of ['secrets.env', '../package.json', '..%2Fpackage.json']) {
    expect((await vendor(new Request('http://localhost/x'), params(asset))).status).toBe(404);
  }
});
