/**
 * Client-side ZIP writer (MFX-6.3, #3857) — unit tests.
 *
 * Verifies the archive against the ZIP APPNOTE format directly: CRC-32 check vectors,
 * local/central/end-of-central-directory record layout, entry offsets, stored sizes,
 * UTF-8 names, determinism, and the duplicate-path guard.
 */

import {
  buildZip,
  crc32,
  type ZipEntry,
} from '../src/app/components/ade/dashboard/export/zipBundle';

/** Read a 16-bit little-endian value. */
function u16(bytes: Uint8Array, offset: number): number {
  return bytes[offset] | (bytes[offset + 1] << 8);
}

/** Read a 32-bit little-endian value (unsigned). */
function u32(bytes: Uint8Array, offset: number): number {
  return (
    (bytes[offset] | (bytes[offset + 1] << 8) | (bytes[offset + 2] << 16) | (bytes[offset + 3] << 24)) >>>
    0
  );
}

const utf8 = (s: string) => new TextEncoder().encode(s);

describe('crc32', () => {
  it('matches the standard check vectors', () => {
    // The canonical CRC-32/ISO-HDLC check value.
    expect(crc32(utf8('123456789'))).toBe(0xcbf43926);
    expect(crc32(utf8(''))).toBe(0);
    expect(crc32(utf8('a'))).toBe(0xe8b7be43);
  });
});

describe('buildZip', () => {
  const ENTRIES: ZipEntry[] = [
    { path: 'petstore.proto', content: 'syntax = "proto3";\n' },
    { path: 'com/example/User.avsc', content: '{"type":"record","name":"User"}' },
  ];

  it('ends with a correct end-of-central-directory record', () => {
    const zip = buildZip(ENTRIES);
    const eocd = zip.length - 22;
    expect(u32(zip, eocd)).toBe(0x06054b50); // EOCD signature
    expect(u16(zip, eocd + 8)).toBe(2); // entries on this disk
    expect(u16(zip, eocd + 10)).toBe(2); // total entries
    const cdSize = u32(zip, eocd + 12);
    const cdOffset = u32(zip, eocd + 16);
    expect(cdOffset + cdSize).toBe(eocd); // central directory sits right before the EOCD
    expect(u32(zip, cdOffset)).toBe(0x02014b50); // central directory header signature
  });

  it('writes stored entries whose central-directory offsets point at local headers', () => {
    const zip = buildZip(ENTRIES);
    const eocd = zip.length - 22;
    let cd = u32(zip, eocd + 16);

    for (const entry of ENTRIES) {
      const nameBytes = utf8(entry.path);
      const dataBytes = utf8(entry.content);
      expect(u32(zip, cd)).toBe(0x02014b50);
      expect(u16(zip, cd + 10)).toBe(0); // method 0: stored
      expect(u32(zip, cd + 16)).toBe(crc32(dataBytes)); // CRC-32
      expect(u32(zip, cd + 20)).toBe(dataBytes.length); // compressed size
      expect(u32(zip, cd + 24)).toBe(dataBytes.length); // uncompressed size
      expect(u16(zip, cd + 28)).toBe(nameBytes.length); // name length

      const local = u32(zip, cd + 42); // local header offset
      expect(u32(zip, local)).toBe(0x04034b50); // local file header signature
      const localNameLen = u16(zip, local + 26);
      expect(localNameLen).toBe(nameBytes.length);
      const name = new TextDecoder().decode(zip.subarray(local + 30, local + 30 + localNameLen));
      expect(name).toBe(entry.path);
      const data = zip.subarray(local + 30 + localNameLen, local + 30 + localNameLen + dataBytes.length);
      expect(new TextDecoder().decode(data)).toBe(entry.content);

      cd += 46 + u16(zip, cd + 28) + u16(zip, cd + 30) + u16(zip, cd + 32);
    }
  });

  it('sets the UTF-8 name flag and a fixed DOS-epoch timestamp for determinism', () => {
    const zip = buildZip([{ path: 'schema.graphql', content: 'type Query { ok: Boolean }' }]);
    expect(u16(zip, 6)).toBe(0x0800); // general-purpose flags: EFS only
    expect(u16(zip, 10)).toBe(0); // mod time 00:00:00
    expect(u16(zip, 12)).toBe(0x21); // mod date 1980-01-01
    expect(buildZip([{ path: 'schema.graphql', content: 'type Query { ok: Boolean }' }])).toEqual(zip);
  });

  it('produces a valid empty archive for zero entries', () => {
    const zip = buildZip([]);
    expect(zip.length).toBe(22);
    expect(u32(zip, 0)).toBe(0x06054b50);
    expect(u16(zip, 10)).toBe(0);
  });

  it('rejects duplicate entry paths instead of silently shadowing members', () => {
    expect(() =>
      buildZip([
        { path: 'a.json', content: '{}' },
        { path: 'a.json', content: '[]' },
      ]),
    ).toThrow(/duplicate zip entry path/i);
  });
});
