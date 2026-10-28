/**
 * Export downloads after the security review — X6 (#6227).
 *
 * - The BFF passes REST's `Content-Type` and `Content-Disposition` through, adds
 *   `X-Content-Type-Options: nosniff`, and copies `Content-Length` only for a streamed job download
 *   (`lib/export-download-headers.ts`); both download routes use it.
 * - The browser keeps a non-ASCII file name: `filenameFromDisposition` prefers the RFC 6266
 *   `filename*=UTF-8''…` REST sends beside the ASCII `filename`.
 */

import * as fs from 'fs';
import * as path from 'path';

import { exportDownloadHeaders } from '../lib/export-download-headers';
import { filenameFromDisposition } from '../src/app/components/ade/dashboard/export/exportDownload';

const API = path.resolve(__dirname, '..', 'src', 'app', 'api', 'export');

describe('exportDownloadHeaders', () => {
  const upstream = new Headers({
    'content-type': 'application/zip',
    'content-disposition': `attachment; filename="API.zip"; filename*=UTF-8''%E6%B3%A8%E6%96%87.zip`,
    'content-length': '42',
    'set-cookie': 'session=leak',
    'x-internal': 'secret',
  });

  it('passes the type and disposition through and always sends nosniff', () => {
    const headers = exportDownloadHeaders(upstream);
    expect(headers.get('content-type')).toBe('application/zip');
    expect(headers.get('content-disposition')).toBe(upstream.get('content-disposition'));
    expect(headers.get('x-content-type-options')).toBe('nosniff');
    expect(headers.get('content-length')).toBeNull();
  });

  it('copies the length only when asked, and nothing else', () => {
    const headers = exportDownloadHeaders(upstream, { contentLength: true });
    expect(headers.get('content-length')).toBe('42');
    expect(headers.get('set-cookie')).toBeNull();
    expect(headers.get('x-internal')).toBeNull();
  });

  it('sends nosniff even when REST sends no type', () => {
    expect(exportDownloadHeaders(new Headers()).get('x-content-type-options')).toBe('nosniff');
  });

  it.each([
    ['document', 'route.ts'],
    ['jobs', '[jobId]', 'download', 'route.ts'],
  ])('the %s route builds its headers with it', (...segments) => {
    const source = fs.readFileSync(path.join(API, ...segments), 'utf8');
    expect(source).toContain("from '@lib/export-download-headers'");
    expect(source).toContain('exportDownloadHeaders(response.headers');
    expect(source).not.toMatch(/new Headers\(\)/);
  });
});

describe('filenameFromDisposition', () => {
  it.each([
    [`attachment; filename="openapi.json"`, 'openapi.json'],
    [`attachment; filename="API.jtd.json"; filename*=UTF-8''%E6%B3%A8%E6%96%87%20API.jtd.json`, '注文 API.jtd.json'],
    [`attachment; filename*=utf-8''r%C3%A9sum%C3%A9.json`, 'résumé.json'],
    [`attachment; filename="fallback.json"; filename*=UTF-8''%E0%A4%A`, 'fallback.json'],
    [`attachment; filename=plain.yaml`, 'plain.yaml'],
    ['inline', null],
  ])('reads %s', (header, expected) => {
    expect(filenameFromDisposition(header)).toBe(expected);
  });

  it('reads nothing from no header', () => {
    expect(filenameFromDisposition(null)).toBeNull();
  });
});
