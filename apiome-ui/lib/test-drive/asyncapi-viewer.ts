/**
 * The AsyncAPI test-drive viewer page — MFX-44.4 (#4370).
 *
 * Export studio's AsyncAPI viewer tab renders the emitted AsyncAPI 2.x / 3.x document with the AsyncAPI
 * React component's **standalone bundle** (`@asyncapi/react-component`), inside a **sandboxed iframe**
 * (`sandbox="allow-scripts"`, no same-origin: an opaque origin, no cookies, no storage, no access to
 * the Studio). This module builds that page, served by `src/app/test-drive/asyncapi/route.ts`:
 *
 * - the bundle and its stylesheet, self-hosted under `/test-drive/vendor/…` — nothing loads from a CDN;
 * - one inline bridge script, pinned in the Content-Security-Policy by its SHA-256 hash;
 * - a policy with **`connect-src 'none'`**: the page cannot make a network request of its own.
 *
 * The bundled AsyncAPI parser validates the document with Ajv, which compiles each schema with
 * `new Function`, so — unlike the OpenAPI viewer page — the policy allows `'unsafe-eval'`. The sandbox
 * (opaque origin) and `connect-src 'none'` still confine whatever runs to the page itself.
 *
 * The document arrives from the Studio by `postMessage`, or, for a small document, in the URL fragment
 * (`#spec=…`, never sent to the server; the docs screenshots use it). The sidebar lists the servers,
 * operations (by channel), messages and schemas; each entry jumps to its section.
 */

import { createHash } from 'node:crypto';

import { FRAGMENT_SPEC_MAX_CHARS, TEST_DRIVE_VENDOR_PATH } from './openapi-viewer';

/** The route that serves the page. */
export const ASYNCAPI_VIEWER_PATH = '/test-drive/asyncapi';

/**
 * The bridge between the Studio and the renderer, run inside the sandbox.
 *
 * Messages (all `type`s prefixed `apiome-test-drive:`): the page posts `ready` once it listens, then
 * `rendered` once the document is drawn, or `error` (`message`) when the renderer rejects it; the
 * Studio posts `load` (`spec`). Only messages from the parent window are read. The renderer parses
 * asynchronously and reports nothing itself, so the bridge watches the root for the drawn document
 * (`#introduction`) or the renderer's error panel (`.aui-root h2`).
 */
export const ASYNCAPI_VIEWER_SCRIPT = `(function () {
  'use strict';
  var PREFIX = 'apiome-test-drive:';
  var CONFIG = {
    show: { sidebar: true, info: true, servers: true, operations: true, messages: true, schemas: true, errors: true },
    expand: { messageExamples: false },
  };
  var root = document.getElementById('test-drive-root');
  var status = document.getElementById('test-drive-status');
  var observer = null;

  function post(type, extra) {
    var message = { type: PREFIX + type };
    for (var key in extra || {}) message[key] = extra[key];
    window.parent.postMessage(message, '*');
  }

  function setStatus(text) {
    status.textContent = text;
    status.hidden = !text;
  }

  function failed(message) {
    setStatus('');
    post('error', { message: String(message) });
  }

  // Report once what the renderer drew: the document, or its error panel.
  function watch() {
    if (observer) observer.disconnect();
    function check() {
      if (root.querySelector('#introduction')) {
        observer.disconnect();
        setStatus('');
        post('rendered');
        return;
      }
      var heading = root.querySelector('.aui-root h2');
      if (heading && /^Error/.test(heading.textContent || '')) {
        observer.disconnect();
        var details = root.querySelector('.aui-root code');
        var text = String(heading.textContent).replace(/^Error:\\s*/, '');
        failed(details ? text + ': ' + details.textContent : text);
      }
    }
    observer = new MutationObserver(check);
    observer.observe(root, { childList: true, subtree: true });
    check();
  }

  function render(spec) {
    setStatus('Rendering…');
    try {
      if (!window.AsyncApiStandalone) throw new Error('The AsyncAPI renderer did not load.');
      root.textContent = '';
      watch();
      window.AsyncApiStandalone.render({ schema: spec, config: CONFIG }, root);
    } catch (error) {
      if (observer) observer.disconnect();
      setStatus('This document could not be rendered: ' + (error.message || error));
      post('error', { message: String(error.message || error) });
    }
  }

  window.addEventListener('message', function (event) {
    if (event.source !== window.parent) return;
    var message = event.data || {};
    if (message.type === PREFIX + 'load') render(message.spec);
  });

  // The fragment feed: a small document in the URL fragment, which never reaches the server.
  var fragment = new URLSearchParams(window.location.hash.slice(1)).get('spec');
  if (fragment && fragment.length <= ${FRAGMENT_SPEC_MAX_CHARS}) {
    try {
      render(JSON.parse(fragment));
    } catch (error) {
      failed(error.message || error);
    }
  }
  post('ready');
})();
`;

/** The CSP source for the inline bridge script: its SHA-256 hash. */
export function asyncApiViewerScriptHashSource(): string {
  return `'sha256-${createHash('sha256').update(ASYNCAPI_VIEWER_SCRIPT, 'utf8').digest('base64')}'`;
}

/**
 * The page's Content-Security-Policy.
 *
 * No network of its own (`connect-src 'none'`), no third-party origin anywhere, scripts limited to the
 * self-hosted bundle and the hashed bridge (plus `'unsafe-eval'` for the parser's schema validator),
 * and embeddable only by the app itself.
 *
 * @returns The header value.
 */
export function asyncApiViewerCsp(): string {
  return [
    "default-src 'none'",
    // 'unsafe-eval': the bundled parser's validator (Ajv) compiles schemas with `new Function`.
    `script-src 'self' 'unsafe-eval' ${asyncApiViewerScriptHashSource()}`,
    // The renderer injects its own styles at runtime.
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self' data:",
    "connect-src 'none'",
    "base-uri 'none'",
    "form-action 'none'",
    "frame-ancestors 'self'",
  ].join('; ');
}

/**
 * The viewer page's HTML.
 *
 * @param version A cache key for the vendor bundles (their package versions).
 * @returns The document.
 */
export function asyncApiViewerHtml(version: string): string {
  const vendor = (name: string) => `${TEST_DRIVE_VENDOR_PATH}/${name}?v=${encodeURIComponent(version)}`;
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>AsyncAPI test drive</title>
<link rel="stylesheet" href="${vendor('asyncapi-react.css')}">
<style>
  /* The renderer's stylesheet sets no body font of its own. */
  html, body { margin: 0; background: #fff; font-family: system-ui, -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; }
  #test-drive-status { margin: 0; padding: 16px; font-size: 14px; line-height: 1.5; color: #4b5563; }
  #test-drive-status[hidden] { display: none; }
</style>
</head>
<body>
<p id="test-drive-status">Waiting for the document…</p>
<div id="test-drive-root"></div>
<script src="${vendor('asyncapi-react.standalone.js')}"></script>
<script>${ASYNCAPI_VIEWER_SCRIPT}</script>
</body>
</html>
`;
}
