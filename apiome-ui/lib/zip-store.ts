/**
 * A minimal ZIP writer — PFX-8.18 (#7315), for **Every pact for this provider (.zip)**.
 *
 * Writes a ZIP archive with every entry *stored* (method 0, no compression): pact files are small
 * JSON, and storing keeps the writer short and dependency-free. Each entry carries its CRC-32 and
 * sizes in the local header, and the archive ends with the central directory and its end record,
 * so `unzip`, Finder and Windows Explorer all read it. No ZIP64: the caller keeps the archive far
 * below 4 GB (at most {@link MAX_ZIP_ENTRIES} small files).
 */

/** One file of the archive. */
export interface ZipEntry {
  /** The path inside the archive, `/`-separated (UTF-8). */
  name: string;
  /** The file's bytes. */
  data: Uint8Array;
}

/** The most entries one archive takes (well below the format's 65 535). */
export const MAX_ZIP_ENTRIES = 1000;

/** The CRC-32 (IEEE) lookup table. */
const CRC_TABLE: Uint32Array = (() => {
  const table = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c >>> 0;
  }
  return table;
})();

/**
 * The CRC-32 of some bytes, as ZIP stores it.
 *
 * @param data - The bytes.
 * @returns The checksum (unsigned).
 */
export function crc32(data: Uint8Array): number {
  let crc = 0xffffffff;
  for (let i = 0; i < data.length; i++) crc = CRC_TABLE[(crc ^ data[i]) & 0xff] ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}

/** A little-endian byte writer. */
class Bytes {
  private readonly chunks: Uint8Array[] = [];
  length = 0;

  u16(value: number): void {
    this.raw(new Uint8Array([value & 0xff, (value >>> 8) & 0xff]));
  }

  u32(value: number): void {
    this.raw(new Uint8Array([value & 0xff, (value >>> 8) & 0xff, (value >>> 16) & 0xff, (value >>> 24) & 0xff]));
  }

  raw(bytes: Uint8Array): void {
    this.chunks.push(bytes);
    this.length += bytes.length;
  }

  join(): Uint8Array {
    const out = new Uint8Array(this.length);
    let offset = 0;
    for (const chunk of this.chunks) {
      out.set(chunk, offset);
      offset += chunk.length;
    }
    return out;
  }
}

/** Bit 11 of the general-purpose flags: the name is UTF-8. */
const UTF8_FLAG = 0x0800;

/** 1980-01-01 00:00 in MS-DOS date/time (ZIP's earliest), so the archive is reproducible. */
const DOS_TIME = 0;
const DOS_DATE = (0 << 9) | (1 << 5) | 1;

/**
 * Write a ZIP archive of stored entries.
 *
 * @param entries - The files, in order. Names must be unique, relative, without `..` segments.
 * @returns The archive's bytes.
 * @throws Error for no entries, too many, a duplicate name or an unsafe one — a programming error.
 */
export function createZip(entries: readonly ZipEntry[]): Uint8Array {
  if (entries.length === 0) throw new Error('A zip needs at least one entry.');
  if (entries.length > MAX_ZIP_ENTRIES) throw new Error(`A zip takes at most ${MAX_ZIP_ENTRIES} entries.`);
  const seen = new Set<string>();
  const encoder = new TextEncoder();
  const out = new Bytes();
  const central = new Bytes();
  for (const entry of entries) {
    if (!entry.name || entry.name.startsWith('/') || entry.name.split('/').includes('..')) {
      throw new Error(`Unsafe zip entry name: ${entry.name}`);
    }
    if (seen.has(entry.name)) throw new Error(`Duplicate zip entry name: ${entry.name}`);
    seen.add(entry.name);
    const name = encoder.encode(entry.name);
    const crc = crc32(entry.data);
    const offset = out.length;

    out.u32(0x04034b50);
    out.u16(20); // version needed: 2.0
    out.u16(UTF8_FLAG);
    out.u16(0); // stored
    out.u16(DOS_TIME);
    out.u16(DOS_DATE);
    out.u32(crc);
    out.u32(entry.data.length);
    out.u32(entry.data.length);
    out.u16(name.length);
    out.u16(0); // extra field length
    out.raw(name);
    out.raw(entry.data);

    central.u32(0x02014b50);
    central.u16(20); // version made by
    central.u16(20); // version needed
    central.u16(UTF8_FLAG);
    central.u16(0);
    central.u16(DOS_TIME);
    central.u16(DOS_DATE);
    central.u32(crc);
    central.u32(entry.data.length);
    central.u32(entry.data.length);
    central.u16(name.length);
    central.u16(0); // extra
    central.u16(0); // comment
    central.u16(0); // disk number
    central.u16(0); // internal attributes
    central.u32(0); // external attributes
    central.u32(offset);
    central.raw(name);
  }
  const centralOffset = out.length;
  const directory = central.join();
  out.raw(directory);
  out.u32(0x06054b50);
  out.u16(0);
  out.u16(0);
  out.u16(entries.length);
  out.u16(entries.length);
  out.u32(directory.length);
  out.u32(centralOffset);
  out.u16(0); // comment length
  return out.join();
}
