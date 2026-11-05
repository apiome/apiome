/**
 * @jest-environment node
 */
/**
 * The GraphQL test-drive route — MFX-44.3 (#4369): `/test-drive/graphql` serves the GraphiQL page with
 * its no-network Content-Security-Policy and a bundle URL keyed by the package versions.
 */

import { graphiqlViewerCsp } from '../lib/test-drive/graphiql-viewer';
import { GET as page } from '../src/app/test-drive/graphql/route';

it('serves the GraphiQL page with its policy', async () => {
  const response = page();
  expect(response.headers.get('content-security-policy')).toBe(graphiqlViewerCsp());
  expect(response.headers.get('content-type')).toContain('text/html');
  expect(response.headers.get('referrer-policy')).toBe('no-referrer');
  expect(response.headers.get('x-content-type-options')).toBe('nosniff');
  expect(await response.text()).toMatch(/graphiql-test-drive\.js\?v=4\.1\.2-16\.15\.0/);
});
