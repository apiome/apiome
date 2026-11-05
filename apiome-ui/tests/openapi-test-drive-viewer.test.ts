/**
 * The OpenAPI test-drive viewer page — MFX-44.2 (#4368).
 *
 * - the page's CSP allows no network of its own (`connect-src 'none'`), no third-party origin, and pins
 *   the inline bridge by its hash; the page loads only the self-hosted bundles;
 * - the bridge script (run here against stub viewers): announces itself, renders Swagger UI with no
 *   validator and Try it out off unless the Studio turns it on, renders ReDoc, refuses every request
 *   while Try it out is off, posts requests to the Studio and resolves them from its answer, ignores
 *   messages that are not from the Studio, and renders a small document from the URL fragment.
 */

import { createHash } from 'node:crypto';
import path from 'node:path';

import {
  FRAGMENT_SPEC_MAX_CHARS,
  openApiViewerCsp,
  openApiViewerHtml,
  openApiViewerKind,
  TEST_DRIVE_VENDOR_ASSETS,
  VIEWER_SCRIPT,
} from '../lib/test-drive/openapi-viewer';
import { findInNodeModules, readTestDriveVendorAsset, testDriveVendorVersion } from '../lib/test-drive/vendor-assets';

const SPEC = { openapi: '3.1.0', info: { title: 'Pets', version: '1' }, paths: {} };

describe('the page and its policy', () => {
  it('allows no network, no third-party origin, and only the hashed bridge inline', () => {
    const csp = openApiViewerCsp();
    expect(csp).toContain("connect-src 'none'");
    expect(csp).toContain("default-src 'none'");
    expect(csp).toContain("frame-ancestors 'self'");
    expect(csp).not.toMatch(/https?:/);
    expect(csp).not.toContain("'unsafe-eval'");
    const hash = createHash('sha256').update(VIEWER_SCRIPT, 'utf8').digest('base64');
    expect(csp).toContain(`script-src 'self' 'sha256-${hash}'`);
  });

  it('loads only the self-hosted bundle of the chosen viewer, and inlines exactly the hashed bridge', () => {
    const swagger = openApiViewerHtml('swagger-ui', '5-2');
    expect(swagger).toContain('/test-drive/vendor/swagger-ui-bundle.js?v=5-2');
    expect(swagger).toContain('/test-drive/vendor/swagger-ui.css?v=5-2');
    expect(swagger).not.toContain('redoc.standalone.js');
    expect(swagger).toContain(`<script>${VIEWER_SCRIPT}</script>`);
    const redoc = openApiViewerHtml('redoc', '5-2');
    expect(redoc).toContain('/test-drive/vendor/redoc.standalone.js?v=5-2');
    expect(redoc).not.toContain('swagger-ui');
    for (const html of [swagger, redoc]) expect(html).not.toMatch(/(src|href)="https?:/);
  });

  it('picks ReDoc only when asked', () => {
    expect(openApiViewerKind('redoc')).toBe('redoc');
    expect(openApiViewerKind('swagger-ui')).toBe('swagger-ui');
    expect(openApiViewerKind('<script>')).toBe('swagger-ui');
    expect(openApiViewerKind(null)).toBe('swagger-ui');
  });
});

describe('the vendor bundles', () => {
  it('serves the allow-listed files from node_modules and nothing else', async () => {
    for (const [name, asset] of Object.entries(TEST_DRIVE_VENDOR_ASSETS)) {
      const found = await readTestDriveVendorAsset(name);
      expect(found?.contentType).toBe(asset.contentType);
      expect(found?.bytes.length).toBeGreaterThan(1000);
    }
    expect(await readTestDriveVendorAsset('../package.json')).toBeNull();
    expect(await readTestDriveVendorAsset('swagger-ui-dist/package.json')).toBeNull();
    expect(await readTestDriveVendorAsset('constructor')).toBeNull();
  });

  it('finds a file by walking up to the nearest node_modules', async () => {
    expect(await findInNodeModules('swagger-ui-dist/swagger-ui-bundle.js', path.join(__dirname, 'fixtures'))).toMatch(
      /node_modules[\\/]swagger-ui-dist[\\/]swagger-ui-bundle\.js$/,
    );
    expect(await findInNodeModules('no-such-package/x.js')).toBeNull();
    expect(testDriveVendorVersion()).toMatch(/^\d+\.\d+\.\d+-\d+\.\d+\.\d+$/);
  });
});

/* ------------------------------------------------------------------------ */
/* The bridge script, against stub viewers                                   */
/* ------------------------------------------------------------------------ */

type Posted = Record<string, unknown>;

class FakeResponse {
  constructor(
    public body: string | null,
    public init: { status: number; headers: Record<string, string> },
  ) {}
}

function runBridge(viewer: 'swagger-ui' | 'redoc', hash = '') {
  document.body.innerHTML = '<p id="test-drive-status"></p><div id="test-drive-root"></div>';
  document.body.setAttribute('data-viewer', viewer);
  window.history.replaceState(null, '', `/test-drive/openapi${hash}`);
  const posted: Posted[] = [];
  const swagger = jest.fn((config: Record<string, unknown>) => (config.onComplete as () => void)());
  const redoc = { init: jest.fn((_spec: unknown, _opts: unknown, _el: unknown, done: (e?: unknown) => void) => done()) };
  const originalPost = window.postMessage;
  Object.assign(window, { SwaggerUIBundle: swagger, Redoc: redoc, Response: FakeResponse });
  window.postMessage = ((message: Posted) => posted.push(message)) as typeof window.postMessage;
  new Function(VIEWER_SCRIPT)();
  const send = (data: Posted, source: unknown = window) =>
    window.dispatchEvent(new MessageEvent('message', { data, source: source as Window }));
  return { posted, swagger, redoc, send, restore: () => (window.postMessage = originalPost) };
}

describe('the bridge', () => {
  it('announces itself, then renders Swagger UI with no validator and Try it out off', () => {
    const bridge = runBridge('swagger-ui');
    expect(bridge.posted).toEqual([{ type: 'apiome-test-drive:ready' }]);
    bridge.send({ type: 'apiome-test-drive:load', spec: SPEC, tryOut: false, large: false });
    const config = bridge.swagger.mock.calls[0][0];
    expect(config).toMatchObject({ spec: SPEC, validatorUrl: null, supportedSubmitMethods: [], docExpansion: 'list' });
    expect(bridge.posted.at(-1)).toEqual({ type: 'apiome-test-drive:rendered' });
    bridge.restore();
  });

  it('opens a large document collapsed, and turns Try it out on only when told', () => {
    const bridge = runBridge('swagger-ui');
    bridge.send({ type: 'apiome-test-drive:load', spec: SPEC, tryOut: true, large: true });
    expect(bridge.swagger.mock.calls[0][0]).toMatchObject({ docExpansion: 'none' });
    expect(bridge.swagger.mock.calls[0][0].supportedSubmitMethods).toContain('get');
    bridge.restore();
  });

  it('renders ReDoc', () => {
    const bridge = runBridge('redoc');
    bridge.send({ type: 'apiome-test-drive:load', spec: SPEC });
    expect(bridge.redoc.init).toHaveBeenCalledWith(SPEC, expect.objectContaining({ hideDownloadButtons: true }),
      document.getElementById('test-drive-root'), expect.any(Function));
    expect(bridge.posted.at(-1)).toEqual({ type: 'apiome-test-drive:rendered' });
    bridge.restore();
  });

  it('refuses every request while Try it out is off', async () => {
    const bridge = runBridge('swagger-ui');
    bridge.send({ type: 'apiome-test-drive:load', spec: SPEC, tryOut: false });
    await expect(window.fetch('https://anywhere.example/pets')).rejects.toThrow('Requests are off');
    expect(bridge.posted.some((m) => m.type === 'apiome-test-drive:request')).toBe(false);
    bridge.restore();
  });

  it('posts a request to the Studio and resolves it from the answer', async () => {
    const bridge = runBridge('swagger-ui');
    bridge.send({ type: 'apiome-test-drive:load', spec: SPEC, tryOut: true });
    const pending = window.fetch('https://rest.example/v1/mock/m1/pets?limit=1', { method: 'post' });
    const request = bridge.posted.find((m) => m.type === 'apiome-test-drive:request')!;
    expect(request).toMatchObject({ method: 'POST', url: 'https://rest.example/v1/mock/m1/pets?limit=1' });
    bridge.send({ type: 'apiome-test-drive:response', id: request.id, status: 201, headers: { 'content-type': 'application/json' }, body: '{}' });
    const answered = (await pending) as unknown as FakeResponse;
    expect(answered.body).toBe('{}');
    expect(answered.init).toEqual({ status: 201, headers: { 'content-type': 'application/json' } });

    const failing = window.fetch('https://rest.example/v1/mock/m1/pets');
    const second = bridge.posted.filter((m) => m.type === 'apiome-test-drive:request').at(-1)!;
    bridge.send({ type: 'apiome-test-drive:response', id: second.id, error: 'Only requests to the running mock server are sent.' });
    await expect(failing).rejects.toThrow('Only requests to the running mock server');
    bridge.restore();
  });

  it('answers a 204 with no body', async () => {
    const bridge = runBridge('swagger-ui');
    bridge.send({ type: 'apiome-test-drive:load', spec: SPEC, tryOut: true });
    const pending = window.fetch('https://rest.example/v1/mock/m1/pets/1', { method: 'DELETE' });
    const request = bridge.posted.find((m) => m.type === 'apiome-test-drive:request')!;
    bridge.send({ type: 'apiome-test-drive:response', id: request.id, status: 204, headers: {}, body: '' });
    expect(((await pending) as unknown as FakeResponse).body).toBeNull();
    bridge.restore();
  });

  it('ignores messages that do not come from the Studio', () => {
    const bridge = runBridge('swagger-ui');
    bridge.send({ type: 'apiome-test-drive:load', spec: SPEC }, null);
    expect(bridge.swagger).not.toHaveBeenCalled();
    bridge.restore();
  });

  it('renders a small document from the URL fragment, and reports one it cannot read', () => {
    const fromFragment = runBridge('redoc', `#spec=${encodeURIComponent(JSON.stringify(SPEC))}`);
    expect(fromFragment.redoc.init.mock.calls[0][0]).toEqual(SPEC);
    fromFragment.restore();
    const broken = runBridge('redoc', '#spec=%7Bnot-json');
    expect(broken.redoc.init).not.toHaveBeenCalled();
    expect(broken.posted.find((m) => m.type === 'apiome-test-drive:error')).toBeTruthy();
    broken.restore();
    const tooBig = runBridge('redoc', `#spec=${'x'.repeat(FRAGMENT_SPEC_MAX_CHARS + 1)}`);
    expect(tooBig.redoc.init).not.toHaveBeenCalled();
    tooBig.restore();
  });
});
