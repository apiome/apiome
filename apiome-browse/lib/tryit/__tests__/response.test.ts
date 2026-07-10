/**
 * Tests for the Try It response presentation helpers — SIM-3.3 (#4449).
 */

import { describe, expect, it } from 'vitest';
import { bytesToBase64 } from '../body';
import {
  bareMime,
  bodyDataUrl,
  classifyBody,
  describeGatewayFailure,
  describeSendFailure,
  extensionForMime,
  formatBytes,
  formatDuration,
  headerLookup,
  headersClipboardText,
  prettyPrintBody,
  prettyPrintJson,
  prettyPrintXml,
  suggestDownloadFilename,
} from '../response';
import type { TryItSendErrorKind } from '../send';

/** A classifiable result shape, overridable per test. */
const textResult = (over: Partial<Parameters<typeof classifyBody>[0]> = {}) => ({
  headers: { 'content-type': 'application/json' },
  bodyText: '{"ok":true}',
  bodyEncoding: 'text' as const,
  ...over,
});

describe('bareMime / headerLookup', () => {
  it('strips parameters and lower-cases the media type', () => {
    expect(bareMime('Application/JSON; charset=utf-8')).toBe('application/json');
    expect(bareMime(undefined)).toBe('');
    expect(bareMime('')).toBe('');
  });

  it('looks headers up case-insensitively', () => {
    expect(headerLookup({ 'Content-Type': 'text/html' }, 'content-type')).toBe('text/html');
    expect(headerLookup({ 'content-type': 'text/html' }, 'Content-Type')).toBe('text/html');
    expect(headerLookup({}, 'content-type')).toBeUndefined();
  });
});

describe('classifyBody', () => {
  it('classifies an empty body as empty regardless of type', () => {
    expect(classifyBody(textResult({ bodyText: '' })).view).toBe('empty');
  });

  it('renders images inline whatever their transport encoding', () => {
    expect(
      classifyBody(
        textResult({ headers: { 'content-type': 'image/png' }, bodyEncoding: 'base64', bodyText: 'iVBO' })
      )
    ).toMatchObject({ view: 'image', mime: 'image/png' });
    expect(
      classifyBody(textResult({ headers: { 'content-type': 'image/svg+xml' }, bodyText: '<svg/>' }))
    ).toMatchObject({ view: 'image', mime: 'image/svg+xml' });
  });

  it('treats non-image base64 bodies as binary downloads, whatever the declared type', () => {
    expect(
      classifyBody(
        textResult({ headers: { 'content-type': 'application/json' }, bodyEncoding: 'base64', bodyText: 'AAECAw==' })
      ).view
    ).toBe('binary');
    expect(
      classifyBody(
        textResult({ headers: { 'content-type': 'application/pdf' }, bodyEncoding: 'base64', bodyText: 'AAECAw==' })
      )
    ).toMatchObject({ view: 'binary', mime: 'application/pdf' });
  });

  it('maps text media types to Monaco languages and pretty-printers', () => {
    expect(classifyBody(textResult())).toMatchObject({
      view: 'text',
      monacoLanguage: 'json',
      pretty: 'json',
    });
    expect(
      classifyBody(textResult({ headers: { 'content-type': 'application/hal+json' } }))
    ).toMatchObject({ monacoLanguage: 'json', pretty: 'json' });
    expect(
      classifyBody(textResult({ headers: { 'content-type': 'text/xml' }, bodyText: '<a/>' }))
    ).toMatchObject({ monacoLanguage: 'xml', pretty: 'xml' });
    expect(
      classifyBody(
        textResult({ headers: { 'content-type': 'application/atom+xml' }, bodyText: '<a/>' })
      )
    ).toMatchObject({ monacoLanguage: 'xml', pretty: 'xml' });
    expect(
      classifyBody(textResult({ headers: { 'content-type': 'text/html' }, bodyText: '<p>x</p>' }))
    ).toMatchObject({ monacoLanguage: 'html', pretty: null });
    expect(
      classifyBody(textResult({ headers: { 'content-type': 'text/yaml' }, bodyText: 'a: 1' }))
    ).toMatchObject({ monacoLanguage: 'yaml' });
    expect(
      classifyBody(textResult({ headers: { 'content-type': 'text/javascript' }, bodyText: '1' }))
    ).toMatchObject({ monacoLanguage: 'javascript' });
    expect(
      classifyBody(textResult({ headers: { 'content-type': 'text/css' }, bodyText: 'a{}' }))
    ).toMatchObject({ monacoLanguage: 'css' });
  });

  it('sniffs JSON when the media type is missing or unhelpful', () => {
    expect(classifyBody(textResult({ headers: {} }))).toMatchObject({
      monacoLanguage: 'json',
      pretty: 'json',
    });
    expect(
      classifyBody(textResult({ headers: {}, bodyText: '  [1, 2]' }))
    ).toMatchObject({ monacoLanguage: 'json' });
    // Looks like JSON but is not — stays plain text.
    expect(
      classifyBody(textResult({ headers: {}, bodyText: '{not json' }))
    ).toMatchObject({ monacoLanguage: 'plaintext', pretty: null });
    expect(
      classifyBody(textResult({ headers: {}, bodyText: 'plain words' }))
    ).toMatchObject({ view: 'text', monacoLanguage: 'plaintext' });
  });
});

describe('pretty-printing', () => {
  it('pretty-prints JSON and rejects invalid JSON', () => {
    expect(prettyPrintJson('{"a":[1,2]}')).toBe('{\n  "a": [\n    1,\n    2\n  ]\n}');
    expect(prettyPrintJson('{oops')).toBeNull();
  });

  it('indents XML tags and leaves declarations/self-closing tags at level', () => {
    expect(prettyPrintXml('<?xml version="1.0"?><a><b>hi</b><c/></a>')).toBe(
      ['<?xml version="1.0"?>', '<a>', '  <b>', '    hi', '  </b>', '  <c/>', '</a>'].join('\n')
    );
  });

  it('returns null for non-XML and never throws on malformed markup', () => {
    expect(prettyPrintXml('not xml')).toBeNull();
    expect(prettyPrintXml('<a><b></a>')).toContain('<a>'); // lenient, display-only
  });

  it('dispatches by pretty mode', () => {
    expect(prettyPrintBody('{"a":1}', 'json')).toContain('"a": 1');
    expect(prettyPrintBody('<a><b/></a>', 'xml')).toContain('  <b/>');
    expect(prettyPrintBody('anything', null)).toBeNull();
    // A truncated JSON body no longer parses — pretty view degrades to null (raw only).
    expect(prettyPrintBody('{"a": [1, 2', 'json')).toBeNull();
  });
});

describe('download support', () => {
  it('maps media types to extensions with sensible fallbacks', () => {
    expect(extensionForMime('application/json', 'text')).toBe('json');
    expect(extensionForMime('application/problem+json', 'text')).toBe('json');
    expect(extensionForMime('application/atom+xml', 'text')).toBe('xml');
    expect(extensionForMime('image/jpeg', 'base64')).toBe('jpg');
    expect(extensionForMime('text/anything-odd', 'text')).toBe('txt');
    expect(extensionForMime('application/whoknows', 'text')).toBe('txt');
    expect(extensionForMime('application/whoknows', 'base64')).toBe('bin');
    expect(extensionForMime('', 'base64')).toBe('bin');
  });

  it('derives the filename from the operation path and media type', () => {
    expect(
      suggestDownloadFilename(
        { headers: { 'content-type': 'application/json' }, bodyEncoding: 'text' },
        '/pets/{petId}'
      )
    ).toBe('pets-petId-response.json');
    expect(
      suggestDownloadFilename({ headers: {}, bodyEncoding: 'base64' }, '/')
    ).toBe('response.bin');
  });

  it('prefers the Content-Disposition filename and strips path separators', () => {
    expect(
      suggestDownloadFilename(
        {
          headers: { 'Content-Disposition': 'attachment; filename="report.pdf"' },
          bodyEncoding: 'base64',
        },
        '/pets'
      )
    ).toBe('report.pdf');
    expect(
      suggestDownloadFilename(
        {
          headers: { 'content-disposition': 'attachment; filename=../../evil.sh' },
          bodyEncoding: 'text',
        },
        '/pets'
      )
    ).toBe('....evil.sh');
  });

  it('builds data URLs carrying the exact bytes for both encodings', () => {
    expect(bodyDataUrl({ bodyText: 'iVBORw==', bodyEncoding: 'base64' }, 'image/png')).toBe(
      'data:image/png;base64,iVBORw=='
    );
    const svg = '<svg xmlns="http://www.w3.org/2000/svg"/>';
    expect(bodyDataUrl({ bodyText: svg, bodyEncoding: 'text' }, 'image/svg+xml')).toBe(
      `data:image/svg+xml;base64,${bytesToBase64(new TextEncoder().encode(svg))}`
    );
    expect(bodyDataUrl({ bodyText: 'x', bodyEncoding: 'text' }, '')).toMatch(
      /^data:application\/octet-stream;base64,/
    );
  });
});

describe('formatting', () => {
  it('formats byte counts across magnitudes', () => {
    expect(formatBytes(0)).toBe('0 B');
    expect(formatBytes(532)).toBe('532 B');
    expect(formatBytes(1024)).toBe('1.0 KB');
    expect(formatBytes(1536)).toBe('1.5 KB');
    expect(formatBytes(1024 * 1024)).toBe('1.0 MB');
    expect(formatBytes(-5)).toBe('0 B');
  });

  it('formats durations in ms below a second, seconds above', () => {
    expect(formatDuration(0)).toBe('0 ms');
    expect(formatDuration(245)).toBe('245 ms');
    expect(formatDuration(999)).toBe('999 ms');
    expect(formatDuration(1000)).toBe('1.00 s');
    expect(formatDuration(1240)).toBe('1.24 s');
    expect(formatDuration(-1)).toBe('0 ms');
  });

  it('renders headers as Name: value lines', () => {
    expect(headersClipboardText({ 'content-type': 'text/plain', etag: '"abc"' })).toBe(
      'content-type: text/plain\netag: "abc"'
    );
    expect(headersClipboardText({})).toBe('');
  });
});

describe('failure wording', () => {
  it('gives every send-failure kind a distinct title and a hint', () => {
    const kinds: TryItSendErrorKind[] = [
      'invalid-url',
      'network',
      'proxy-unavailable',
      'refused',
      'bad-envelope',
    ];
    const titles = kinds.map((kind) => describeSendFailure(kind).title);
    expect(new Set(titles).size).toBe(kinds.length);
    for (const kind of kinds) {
      expect(describeSendFailure(kind).hint.length).toBeGreaterThan(10);
    }
  });

  it('describes gateway failures distinctly and ignores real upstream responses', () => {
    expect(describeGatewayFailure({ gateway: false, status: 504 })).toBeNull();
    expect(describeGatewayFailure({ gateway: true, status: 504 })?.title).toBe(
      'Request timed out'
    );
    expect(describeGatewayFailure({ gateway: true, status: 502 })?.title).toBe(
      'Target unreachable'
    );
  });
});
