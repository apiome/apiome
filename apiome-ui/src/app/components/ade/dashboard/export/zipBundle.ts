/**
 * Minimal in-browser ZIP writer for export downloads (MFX-6.3, #3857).
 *
 * Builds a stored (uncompressed, method 0) ZIP archive from text files entirely
 * client-side, so the ExportDialog can offer a "Download .zip" alongside the single-file
 * download without a server round-trip or a compression dependency. Emitted documents
 * are small text artifacts, so store-only is a size non-issue.
 *
 * The writer takes a *list* of files: today the export document proxy returns one file
 * (the emitter's primary output, MFX-4.1), and when the multi-file bundle endpoint
 * (MFX-4.2) lands, every file of the bundle is passed here unchanged.
 *
 * Deterministic on purpose: entries are timestamped with the DOS epoch (1980-01-01) so
 * the same input always produces byte-identical output — testable and diff-friendly.
 * Filenames are encoded as UTF-8 with the EFS flag (bit 11) set.
 */

/** One file to include in the archive. */
export interface ZipEntry {
  /** The path inside the archive (e.g. `petstore.proto` or `com/example/User.avsc`). */
  path: string;
  /** The file's text content (encoded as UTF-8 in the archive). */
  content: string;
}

/** CRC-32 lookup table (IEEE 802.3 polynomial, reflected: 0xEDB88320), built once. */
const CRC_TABLE: Uint32Array = (() => {
  const table = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) {
      c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    }
    table[n] = c >>> 0;
  }
  return table;
})();

/**
 * Compute the CRC-32 checksum (IEEE, as used by ZIP/gzip/PNG) of a byte buffer.
 *
 * @param bytes The input bytes.
 * @returns The unsigned 32-bit checksum.
 */
export function crc32(bytes: Uint8Array): number {
  let crc = 0xffffffff;
  for (let i = 0; i < bytes.length; i++) {
    crc = CRC_TABLE[(crc ^ bytes[i]) & 0xff] ^ (crc >>> 8);
  }
  return (crc ^ 0xffffffff) >>> 0;
}

/** DOS date for 1980-01-01 (day 1, month 1, year 0) — the fixed, deterministic timestamp. */
const DOS_EPOCH_DATE = 0x21;

/** General-purpose flag with only the EFS bit (11) set: filenames are UTF-8. */
const FLAG_UTF8 = 0x0800;

/** Write a 16-bit little-endian value into `out` at `offset`, returning the next offset. */
function writeU16(out: Uint8Array, offset: number, value: number): number {
  out[offset] = value & 0xff;
  out[offset + 1] = (value >>> 8) & 0xff;
  return offset + 2;
}

/** Write a 32-bit little-endian value into `out` at `offset`, returning the next offset. */
function writeU32(out: Uint8Array, offset: number, value: number): number {
  out[offset] = value & 0xff;
  out[offset + 1] = (value >>> 8) & 0xff;
  out[offset + 2] = (value >>> 16) & 0xff;
  out[offset + 3] = (value >>> 24) & 0xff;
  return offset + 4;
}

/** One entry's precomputed bytes and archive metadata, shared by both header records. */
interface PreparedEntry {
  nameBytes: Uint8Array;
  dataBytes: Uint8Array;
  crc: number;
  /** Byte offset of this entry's local file header from the start of the archive. */
  localHeaderOffset: number;
}

/**
 * Build a stored ZIP archive from the given text files.
 *
 * @param entries The files to include. Paths must be unique — duplicate paths would
 *   produce an archive whose members silently shadow each other, so they are rejected.
 * @returns The complete archive bytes, ready to wrap in a `Blob` for download.
 * @throws Error When two entries share a path.
 */
export function buildZip(entries: ZipEntry[]): Uint8Array<ArrayBuffer> {
  const seen = new Set<string>();
  for (const entry of entries) {
    if (seen.has(entry.path)) {
      throw new Error(`Duplicate zip entry path: ${entry.path}`);
    }
    seen.add(entry.path);
  }

  const encoder = new TextEncoder();
  const prepared: PreparedEntry[] = [];

  // Local file headers (30 bytes + name) followed by the stored data, per entry.
  let localSize = 0;
  for (const entry of entries) {
    const nameBytes = encoder.encode(entry.path);
    const dataBytes = encoder.encode(entry.content);
    prepared.push({
      nameBytes,
      dataBytes,
      crc: crc32(dataBytes),
      localHeaderOffset: localSize,
    });
    localSize += 30 + nameBytes.length + dataBytes.length;
  }

  // Central directory headers (46 bytes + name each) and the 22-byte end record.
  const centralSize = prepared.reduce((sum, e) => sum + 46 + e.nameBytes.length, 0);
  const out = new Uint8Array(localSize + centralSize + 22);

  let offset = 0;
  for (const entry of prepared) {
    offset = writeU32(out, offset, 0x04034b50); // local file header signature
    offset = writeU16(out, offset, 20); // version needed to extract (2.0)
    offset = writeU16(out, offset, FLAG_UTF8);
    offset = writeU16(out, offset, 0); // method 0: stored
    offset = writeU16(out, offset, 0); // mod time (00:00:00)
    offset = writeU16(out, offset, DOS_EPOCH_DATE); // mod date (1980-01-01)
    offset = writeU32(out, offset, entry.crc);
    offset = writeU32(out, offset, entry.dataBytes.length); // compressed size (stored)
    offset = writeU32(out, offset, entry.dataBytes.length); // uncompressed size
    offset = writeU16(out, offset, entry.nameBytes.length);
    offset = writeU16(out, offset, 0); // extra field length
    out.set(entry.nameBytes, offset);
    offset += entry.nameBytes.length;
    out.set(entry.dataBytes, offset);
    offset += entry.dataBytes.length;
  }

  const centralStart = offset;
  for (const entry of prepared) {
    offset = writeU32(out, offset, 0x02014b50); // central directory header signature
    offset = writeU16(out, offset, 20); // version made by
    offset = writeU16(out, offset, 20); // version needed to extract
    offset = writeU16(out, offset, FLAG_UTF8);
    offset = writeU16(out, offset, 0); // method 0: stored
    offset = writeU16(out, offset, 0); // mod time
    offset = writeU16(out, offset, DOS_EPOCH_DATE); // mod date
    offset = writeU32(out, offset, entry.crc);
    offset = writeU32(out, offset, entry.dataBytes.length);
    offset = writeU32(out, offset, entry.dataBytes.length);
    offset = writeU16(out, offset, entry.nameBytes.length);
    offset = writeU16(out, offset, 0); // extra field length
    offset = writeU16(out, offset, 0); // file comment length
    offset = writeU16(out, offset, 0); // disk number start
    offset = writeU16(out, offset, 0); // internal file attributes
    offset = writeU32(out, offset, 0); // external file attributes
    offset = writeU32(out, offset, entry.localHeaderOffset);
    out.set(entry.nameBytes, offset);
    offset += entry.nameBytes.length;
  }

  offset = writeU32(out, offset, 0x06054b50); // end of central directory signature
  offset = writeU16(out, offset, 0); // this disk number
  offset = writeU16(out, offset, 0); // disk with the central directory
  offset = writeU16(out, offset, prepared.length); // entries on this disk
  offset = writeU16(out, offset, prepared.length); // total entries
  offset = writeU32(out, offset, centralSize); // central directory size
  offset = writeU32(out, offset, centralStart); // central directory offset
  writeU16(out, offset, 0); // comment length

  return out;
}
