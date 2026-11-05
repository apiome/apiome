/**
 * @jest-environment node
 */
/**
 * The AsyncAPI test-drive route — MFX-44.4 (#4370): `/test-drive/asyncapi` serves the renderer page
 * with its no-network Content-Security-Policy and bundle URLs keyed by the package versions; the
 * vendor route serves the renderer's bundle and stylesheet.
 */

import { asyncApiViewerCsp } from '../lib/test-drive/asyncapi-viewer';
import { testDriveVendorVersion } from '../lib/test-drive/vendor-assets';
import { GET as page } from '../src/app/test-drive/asyncapi/route';
import { GET as vendor } from '../src/app/test-drive/vendor/[asset]/route';

const params = (asset: string) => ({ params: Promise.resolve({ asset }) });

it('serves the AsyncAPI page with its policy', async () => {
  const response = page();
  expect(response.headers.get('content-security-policy')).toBe(asyncApiViewerCsp());
  expect(response.headers.get('content-type')).toContain('text/html');
  expect(response.headers.get('referrer-policy')).toBe('no-referrer');
  expect(response.headers.get('x-content-type-options')).toBe('nosniff');
  const html = await response.text();
  expect(html).toContain(`asyncapi-react.standalone.js?v=${testDriveVendorVersion()}`);
  expect(testDriveVendorVersion()).toMatch(/-3\.2\.2$/);
});

it('serves the renderer bundle and stylesheet', async () => {
  const bundle = await vendor(new Request('http://localhost/x'), params('asyncapi-react.standalone.js'));
  expect(bundle.status).toBe(200);
  expect(bundle.headers.get('content-type')).toContain('text/javascript');
  const css = await vendor(new Request('http://localhost/x'), params('asyncapi-react.css'));
  expect(css.headers.get('content-type')).toContain('text/css');
  expect((await vendor(new Request('http://localhost/x'), params('@asyncapi%2Freact-component%2Fpackage.json'))).status).toBe(404);
});
