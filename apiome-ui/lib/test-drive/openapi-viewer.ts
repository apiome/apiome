/**
 * The OpenAPI test-drive viewer page — MFX-44.2 (#4368).
 *
 * Export studio's Swagger UI and ReDoc tabs render the emitted OpenAPI document inside a **sandboxed
 * iframe** (`sandbox="allow-scripts"`, no same-origin: the page has an opaque origin, no cookies, no
 * storage, no access to the Studio). This module builds that page, served by
 * `src/app/test-drive/openapi/route.ts`:
 *
 * - the viewer's standalone bundle (`swagger-ui-dist` or Redoc's), self-hosted under
 *   `/test-drive/vendor/…` — nothing loads from a CDN;
 * - one inline bridge script, pinned in the Content-Security-Policy by its SHA-256 hash;
 * - a policy with **`connect-src 'none'`**: the page cannot make a network request of its own.
 *
 * The document arrives from the Studio by `postMessage` (the emitted text, parsed in the Studio — no
 * server round-trip), or, for a small document, in the URL fragment (`#spec=…`, never sent to the
 * server; the docs screenshots use it). Swagger UI's **Try it out** is off unless the Studio says a
 * mock server is running; then the bridge replaces `fetch` so every request is posted to the Studio,
 * which sends it to the mock through its authenticated same-origin proxy and posts the answer back.
 */

import { createHash } from 'node:crypto';

/** The two viewers the page can draw. */
export type OpenApiViewerKind = 'swagger-ui' | 'redoc';

/** The route that serves the page. */
export const OPENAPI_VIEWER_PATH = '/test-drive/openapi';

/** The route that serves the self-hosted viewer bundles. */
export const TEST_DRIVE_VENDOR_PATH = '/test-drive/vendor';

/**
 * The vendor files the test-drive pages may load, and where each lives under `node_modules` — the
 * OpenAPI viewers' here and, since MFX-44.4, the AsyncAPI renderer's (`asyncapi-viewer.ts`).
 */
export const TEST_DRIVE_VENDOR_ASSETS: Readonly<Record<string, { file: string; contentType: string }>> = {
  'swagger-ui-bundle.js': { file: 'swagger-ui-dist/swagger-ui-bundle.js', contentType: 'text/javascript; charset=utf-8' },
  'swagger-ui.css': { file: 'swagger-ui-dist/swagger-ui.css', contentType: 'text/css; charset=utf-8' },
  'redoc.standalone.js': { file: 'redoc/bundles/redoc.standalone.js', contentType: 'text/javascript; charset=utf-8' },
  'asyncapi-react.standalone.js': {
    file: '@asyncapi/react-component/browser/standalone/index.js',
    contentType: 'text/javascript; charset=utf-8',
  },
  'asyncapi-react.css': { file: '@asyncapi/react-component/styles/default.min.css', contentType: 'text/css; charset=utf-8' },
};

/** The largest document the `#spec=` fragment feed accepts, in characters. */
export const FRAGMENT_SPEC_MAX_CHARS = 64_000;

/**
 * The bridge between the Studio and the viewer, run inside the sandbox.
 *
 * Messages (all `type`s prefixed `apiome-test-drive:`): the page posts `ready` once it listens, then
 * `rendered` or `error`; the Studio posts `load` (`viewer`, `spec`, `tryOut`, `large`). While `tryOut`
 * is on, a request becomes `request` (`id`, `method`, `url`), answered by `response` (`id`, `status`,
 * `headers`, `body`) or `response` with an `error`. Only messages from the parent window are read.
 */
export const VIEWER_SCRIPT = `(function () {
  'use strict';
  var PREFIX = 'apiome-test-drive:';
  var NULL_BODY_STATUSES = [101, 204, 205, 304];
  var SUBMIT_METHODS = ['get', 'put', 'post', 'delete', 'options', 'head', 'patch'];
  var root = document.getElementById('test-drive-root');
  var status = document.getElementById('test-drive-status');
  var viewer = document.body.getAttribute('data-viewer');
  var tryOut = false;
  var nextId = 0;
  var pending = {};

  function post(type, extra) {
    var message = { type: PREFIX + type };
    for (var key in extra || {}) message[key] = extra[key];
    window.parent.postMessage(message, '*');
  }

  function setStatus(text) {
    status.textContent = text;
    status.hidden = !text;
  }

  // Every request leaves through the Studio, never from here; connect-src 'none' backs this up.
  window.fetch = function (input, init) {
    var url = typeof input === 'string' ? input : (input && input.url) || String(input);
    var method = String((init && init.method) || (input && input.method) || 'GET').toUpperCase();
    if (!tryOut) {
      return Promise.reject(new TypeError('Requests are off. Start the mock server to try operations.'));
    }
    return new Promise(function (resolve, reject) {
      nextId += 1;
      pending[nextId] = { resolve: resolve, reject: reject };
      post('request', { id: nextId, method: method, url: url });
    });
  };

  function settle(message) {
    var entry = pending[message.id];
    if (!entry) return;
    delete pending[message.id];
    if (message.error) {
      entry.reject(new TypeError(String(message.error)));
      return;
    }
    var body = NULL_BODY_STATUSES.indexOf(message.status) >= 0 ? null : String(message.body || '');
    entry.resolve(new Response(body, { status: message.status, headers: message.headers || {} }));
  }

  function rendered(error) {
    if (error) {
      setStatus('This document could not be rendered: ' + (error.message || error));
      post('error', { message: String(error.message || error) });
    } else {
      setStatus('');
      post('rendered');
    }
  }

  function render(spec, options) {
    tryOut = Boolean(options.tryOut);
    root.textContent = '';
    setStatus('Rendering…');
    try {
      if (viewer === 'redoc') {
        window.Redoc.init(spec, {
          hideDownloadButtons: true,
          nativeScrollbars: true,
          expandResponses: '',
          jsonSampleExpandLevel: options.large ? 1 : 2,
        }, root, rendered);
      } else {
        window.SwaggerUIBundle({
          domNode: root,
          spec: spec,
          validatorUrl: null,
          deepLinking: false,
          docExpansion: options.large ? 'none' : 'list',
          defaultModelsExpandDepth: -1,
          supportedSubmitMethods: tryOut ? SUBMIT_METHODS : [],
          tryItOutEnabled: false,
          onComplete: function () { rendered(null); },
        });
      }
    } catch (error) {
      rendered(error);
    }
  }

  window.addEventListener('message', function (event) {
    if (event.source !== window.parent) return;
    var message = event.data || {};
    if (message.type === PREFIX + 'load') render(message.spec, message);
    else if (message.type === PREFIX + 'response') settle(message);
  });

  // The fragment feed: a small document in the URL fragment, which never reaches the server.
  var fragment = new URLSearchParams(window.location.hash.slice(1)).get('spec');
  if (fragment && fragment.length <= ${FRAGMENT_SPEC_MAX_CHARS}) {
    try {
      render(JSON.parse(fragment), {});
    } catch (error) {
      rendered(error);
    }
  }
  post('ready');
})();
`;

/** The CSP source for the inline bridge script: its SHA-256 hash. */
export function viewerScriptHashSource(): string {
  return `'sha256-${createHash('sha256').update(VIEWER_SCRIPT, 'utf8').digest('base64')}'`;
}

/**
 * The page's Content-Security-Policy.
 *
 * No network of its own (`connect-src 'none'`), no third-party origin anywhere, scripts limited to the
 * self-hosted bundles and the hashed bridge, and embeddable only by the app itself.
 *
 * @returns The header value.
 */
export function openApiViewerCsp(): string {
  return [
    "default-src 'none'",
    `script-src 'self' ${viewerScriptHashSource()}`,
    // Both viewers inject their own styles at runtime.
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self' data:",
    // Redoc's search index runs in a worker it builds from a blob.
    "worker-src blob:",
    "connect-src 'none'",
    "base-uri 'none'",
    "form-action 'none'",
    "frame-ancestors 'self'",
  ].join('; ');
}

/**
 * Which viewer a request asks for.
 *
 * @param value The `?viewer=` query value.
 * @returns `redoc` for ReDoc; Swagger UI otherwise.
 */
export function openApiViewerKind(value: string | null | undefined): OpenApiViewerKind {
  return value === 'redoc' ? 'redoc' : 'swagger-ui';
}

/**
 * The viewer page's HTML.
 *
 * @param viewer Which viewer to load.
 * @param version A cache key for the vendor bundles (their package versions).
 * @returns The document.
 */
export function openApiViewerHtml(viewer: OpenApiViewerKind, version: string): string {
  const vendor = (name: string) => `${TEST_DRIVE_VENDOR_PATH}/${name}?v=${encodeURIComponent(version)}`;
  const assets =
    viewer === 'redoc'
      ? `<script src="${vendor('redoc.standalone.js')}"></script>`
      : `<link rel="stylesheet" href="${vendor('swagger-ui.css')}">\n<script src="${vendor('swagger-ui-bundle.js')}"></script>`;
  const title = viewer === 'redoc' ? 'ReDoc' : 'Swagger UI';
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>${title} test drive</title>
<style>
  html, body { margin: 0; background: #fff; }
  #test-drive-status { margin: 0; padding: 16px; font: 14px/1.5 system-ui, sans-serif; color: #4b5563; }
  #test-drive-status[hidden] { display: none; }
</style>
</head>
<body data-viewer="${viewer}">
<p id="test-drive-status">Waiting for the document…</p>
<div id="test-drive-root"></div>
${assets}
<script>${VIEWER_SCRIPT}</script>
</body>
</html>
`;
}
