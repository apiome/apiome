/**
 * Tests for the Try It body transport encoding — SIM-3.3 (#4449).
 */

import { describe, expect, it } from 'vitest';
import { base64ToBytes, bytesToBase64, decodeBodyBytes, encodeBodyBytes } from '../body';

const bytes = (...values: number[]) => new Uint8Array(values);
const utf8 = (text: string) => new TextEncoder().encode(text);

describe('bytesToBase64', () => {
  it('matches the RFC 4648 test vectors', () => {
    expect(bytesToBase64(utf8(''))).toBe('');
    expect(bytesToBase64(utf8('f'))).toBe('Zg==');
    expect(bytesToBase64(utf8('fo'))).toBe('Zm8=');
    expect(bytesToBase64(utf8('foo'))).toBe('Zm9v');
    expect(bytesToBase64(utf8('foob'))).toBe('Zm9vYg==');
    expect(bytesToBase64(utf8('fooba'))).toBe('Zm9vYmE=');
    expect(bytesToBase64(utf8('foobar'))).toBe('Zm9vYmFy');
  });

  it('encodes arbitrary binary bytes', () => {
    expect(bytesToBase64(bytes(0x00, 0xff, 0x10))).toBe('AP8Q');
  });
});

describe('base64ToBytes', () => {
  it('round-trips binary data exactly', () => {
    const original = bytes(0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0x00, 0xff, 0x7f);
    expect(Array.from(base64ToBytes(bytesToBase64(original)))).toEqual(Array.from(original));
  });

  it('round-trips every padding length', () => {
    for (const text of ['', 'f', 'fo', 'foo', 'foob']) {
      expect(Array.from(base64ToBytes(bytesToBase64(utf8(text))))).toEqual(
        Array.from(utf8(text))
      );
    }
  });

  it('ignores embedded whitespace', () => {
    expect(Array.from(base64ToBytes('Zm9v\nYmFy'))).toEqual(Array.from(utf8('foobar')));
  });

  it('returns empty for invalid characters or impossible lengths', () => {
    expect(base64ToBytes('Zm9v!')).toHaveLength(0);
    expect(base64ToBytes('é===')).toHaveLength(0);
    expect(base64ToBytes('Zm9vY')).toHaveLength(0); // length % 4 === 1
  });
});

describe('encodeBodyBytes', () => {
  it('keeps valid UTF-8 text as text (including multi-byte codepoints)', () => {
    expect(encodeBodyBytes(utf8('{"name":"Rex"}'))).toEqual({
      body: '{"name":"Rex"}',
      bodyEncoding: 'text',
    });
    expect(encodeBodyBytes(utf8('héllo 🐕'))).toEqual({
      body: 'héllo 🐕',
      bodyEncoding: 'text',
    });
    expect(encodeBodyBytes(utf8(''))).toEqual({ body: '', bodyEncoding: 'text' });
  });

  it('base64-encodes bytes that are not valid UTF-8', () => {
    const png = bytes(0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a);
    const encoded = encodeBodyBytes(png);
    expect(encoded.bodyEncoding).toBe('base64');
    expect(Array.from(base64ToBytes(encoded.body))).toEqual(Array.from(png));
  });

  it('treats NUL-containing text as binary', () => {
    const withNul = bytes(0x61, 0x00, 0x62); // "a\0b" — valid UTF-8, but not viewable text
    const encoded = encodeBodyBytes(withNul);
    expect(encoded.bodyEncoding).toBe('base64');
    expect(Array.from(base64ToBytes(encoded.body))).toEqual(Array.from(withNul));
  });

  it('trims an incomplete trailing codepoint only when asked (truncated bodies)', () => {
    const cut = utf8('ab🐕').subarray(0, 4); // 'ab' + first 2 of the 4 dog-emoji bytes
    expect(encodeBodyBytes(cut).bodyEncoding).toBe('base64');
    expect(encodeBodyBytes(cut, { trimIncompleteTrailing: true })).toEqual({
      body: 'ab',
      bodyEncoding: 'text',
    });
  });

  it('still base64-encodes truly binary bodies when trimming is allowed', () => {
    const binary = bytes(0xff, 0xfe, 0xfd, 0xfc, 0xfb, 0xfa);
    const encoded = encodeBodyBytes(binary, { trimIncompleteTrailing: true });
    expect(encoded.bodyEncoding).toBe('base64');
    expect(Array.from(base64ToBytes(encoded.body))).toEqual(Array.from(binary));
  });
});

describe('decodeBodyBytes', () => {
  it('recovers exact bytes for both encodings', () => {
    expect(Array.from(decodeBodyBytes('héllo', 'text'))).toEqual(Array.from(utf8('héllo')));
    const binary = bytes(0x00, 0x01, 0xfe, 0xff);
    expect(Array.from(decodeBodyBytes(bytesToBase64(binary), 'base64'))).toEqual(
      Array.from(binary)
    );
  });
});
