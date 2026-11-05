/**
 * The AsyncAPI test-drive viewer page — MFX-44.4 (#4370).
 *
 * - the page's CSP allows no network of its own (`connect-src 'none'`), no third-party origin, pins the
 *   inline bridge by its hash, and allows `'unsafe-eval'` only for the parser's validator; the page
 *   loads only the self-hosted bundle and stylesheet;
 * - the bridge script (run here against a stub renderer): announces itself, renders the posted
 *   document with the sidebar on, reports `rendered` once the document is drawn or `error` with the
 *   renderer's own message, ignores messages that are not from the Studio, and renders a small
 *   document from the URL fragment.
 */

import { createHash } from 'node:crypto';

import {
  ASYNCAPI_VIEWER_PATH,
  ASYNCAPI_VIEWER_SCRIPT,
  asyncApiViewerCsp,
  asyncApiViewerHtml,
} from '../lib/test-drive/asyncapi-viewer';
import { FRAGMENT_SPEC_MAX_CHARS, TEST_DRIVE_VENDOR_ASSETS } from '../lib/test-drive/openapi-viewer';
import { readTestDriveVendorAsset } from '../lib/test-drive/vendor-assets';
import { asyncApiViewerSrc } from '../src/app/components/ade/dashboard/export/asyncApiTestDrive';

const SPEC = { asyncapi: '3.1.0', info: { title: 'Orders', version: '1' }, channels: {}, operations: {} };

describe('the page and its policy', () => {
  it('allows no network and no third-party origin, and pins the bridge by its hash', () => {
    const csp = asyncApiViewerCsp();
    expect(csp).toContain("connect-src 'none'");
    expect(csp).toContain("default-src 'none'");
    expect(csp).toContain("frame-ancestors 'self'");
    expect(csp).not.toMatch(/https?:/);
    const hash = createHash('sha256').update(ASYNCAPI_VIEWER_SCRIPT, 'utf8').digest('base64');
    expect(csp).toContain(`script-src 'self' 'unsafe-eval' 'sha256-${hash}'`);
  });

  it('loads only the self-hosted renderer, and inlines exactly the hashed bridge', () => {
    const html = asyncApiViewerHtml('3-2');
    expect(html).toContain('/test-drive/vendor/asyncapi-react.standalone.js?v=3-2');
    expect(html).toContain('/test-drive/vendor/asyncapi-react.css?v=3-2');
    expect(html).toContain(`<script>${ASYNCAPI_VIEWER_SCRIPT}</script>`);
    expect(html).not.toMatch(/(src|href)="https?:/);
    expect(html).not.toContain('swagger-ui');
  });

  it('is the page the Studio frames', () => {
    expect(asyncApiViewerSrc()).toBe(ASYNCAPI_VIEWER_PATH);
  });

  it('serves the renderer bundle and stylesheet from node_modules', async () => {
    for (const name of ['asyncapi-react.standalone.js', 'asyncapi-react.css']) {
      const found = await readTestDriveVendorAsset(name);
      expect(found?.contentType).toBe(TEST_DRIVE_VENDOR_ASSETS[name].contentType);
      expect(found?.bytes.length).toBeGreaterThan(1000);
    }
  });
});

/* ------------------------------------------------------------------------ */
/* The bridge script, against a stub renderer                                */
/* ------------------------------------------------------------------------ */

type Posted = Record<string, unknown>;

/** What the stub renderer draws: the document, its error panel, or nothing (it throws). */
type Outcome = 'document' | 'error' | 'throws';

const DOCUMENT_MARKUP = '<section class="aui-root"><div id="introduction"><h2>Orders 1</h2></div></section>';
const ERROR_MARKUP =
  '<section class="aui-root"><h2>Error: There are errors in your Asyncapi document</h2>' +
  '<pre><span>line 3:</span><code>"info" property must have required property "version"</code></pre></section>';

function runBridge(outcome: Outcome = 'document', hash = '', withRenderer = true) {
  document.body.innerHTML = '<p id="test-drive-status"></p><div id="test-drive-root"></div>';
  window.history.replaceState(null, '', `/test-drive/asyncapi${hash}`);
  const posted: Posted[] = [];
  const render = jest.fn((_props: { schema: unknown; config: Record<string, unknown> }, root: HTMLElement) => {
    if (outcome === 'throws') throw new Error('boom');
    // The real renderer parses first and draws later.
    setTimeout(() => {
      root.innerHTML = outcome === 'document' ? DOCUMENT_MARKUP : ERROR_MARKUP;
    }, 0);
  });
  const originalPost = window.postMessage;
  Object.assign(window, { AsyncApiStandalone: withRenderer ? { render } : undefined });
  window.postMessage = ((message: Posted) => posted.push(message)) as typeof window.postMessage;
  new Function(ASYNCAPI_VIEWER_SCRIPT)();
  const send = (data: Posted, source: unknown = window) =>
    window.dispatchEvent(new MessageEvent('message', { data, source: source as Window }));
  const settled = () => new Promise((resolve) => setTimeout(resolve, 10));
  return { posted, render, send, settled, restore: () => (window.postMessage = originalPost) };
}

describe('the bridge', () => {
  it('announces itself, renders the document with the sidebar, and reports it drawn', async () => {
    const bridge = runBridge();
    expect(bridge.posted).toEqual([{ type: 'apiome-test-drive:ready' }]);
    bridge.send({ type: 'apiome-test-drive:load', spec: SPEC });
    const [props, root] = bridge.render.mock.calls[0];
    expect(props.schema).toEqual(SPEC);
    expect(props.config).toMatchObject({ show: { sidebar: true, errors: true } });
    expect(root).toBe(document.getElementById('test-drive-root'));
    expect(document.getElementById('test-drive-status')!.textContent).toBe('Rendering…');
    await bridge.settled();
    expect(bridge.posted.at(-1)).toEqual({ type: 'apiome-test-drive:rendered' });
    expect(document.getElementById('test-drive-status')!.hidden).toBe(true);
    bridge.restore();
  });

  it("reports the renderer's own error, with its details", async () => {
    const bridge = runBridge('error');
    bridge.send({ type: 'apiome-test-drive:load', spec: { asyncapi: '3.0.0', info: {} } });
    await bridge.settled();
    expect(bridge.posted.at(-1)).toEqual({
      type: 'apiome-test-drive:error',
      message: 'There are errors in your Asyncapi document: "info" property must have required property "version"',
    });
    expect(bridge.posted.filter((m) => m.type === 'apiome-test-drive:rendered')).toEqual([]);
    bridge.restore();
  });

  it('reports a renderer that throws or did not load', () => {
    const throwing = runBridge('throws');
    throwing.send({ type: 'apiome-test-drive:load', spec: SPEC });
    expect(throwing.posted.at(-1)).toEqual({ type: 'apiome-test-drive:error', message: 'boom' });
    expect(document.getElementById('test-drive-status')!.textContent).toContain('could not be rendered: boom');
    throwing.restore();
    const missing = runBridge('document', '', false);
    missing.send({ type: 'apiome-test-drive:load', spec: SPEC });
    expect(missing.posted.at(-1)).toMatchObject({ type: 'apiome-test-drive:error', message: expect.stringContaining('did not load') });
    missing.restore();
  });

  it('ignores messages that do not come from the Studio', () => {
    const bridge = runBridge();
    bridge.send({ type: 'apiome-test-drive:load', spec: SPEC }, null);
    bridge.send({ type: 'something-else', spec: SPEC });
    expect(bridge.render).not.toHaveBeenCalled();
    bridge.restore();
  });

  it('renders a small document from the URL fragment, and reports one it cannot read', () => {
    const fromFragment = runBridge('document', `#spec=${encodeURIComponent(JSON.stringify(SPEC))}`);
    expect(fromFragment.render.mock.calls[0][0].schema).toEqual(SPEC);
    fromFragment.restore();
    const broken = runBridge('document', '#spec=%7Bnot-json');
    expect(broken.render).not.toHaveBeenCalled();
    expect(broken.posted.find((m) => m.type === 'apiome-test-drive:error')).toBeTruthy();
    broken.restore();
    const tooBig = runBridge('document', `#spec=${'x'.repeat(FRAGMENT_SPEC_MAX_CHARS + 1)}`);
    expect(tooBig.render).not.toHaveBeenCalled();
    tooBig.restore();
  });
});
