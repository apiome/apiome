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

/**
 * A file read out of an archive by {@link readZip} — its path and decoded text.
 *
 * The reader is the counterpart to {@link buildZip} (MFX-43.2, #4362): it turns an emitted
 * multi-file bundle archive back into its files so the Studio's bundle tree can navigate them.
 * It reads via the archive's central directory (the authoritative index), so it tolerates archives
 * written with streaming data descriptors, not just this module's own stored output.
 */
export interface ReadZipFile {
  /** The file's path inside the archive. */
  path: string;
  /** The file's decoded text (UTF-8). */
  text: string;
}

/** Read a 16-bit little-endian value from `bytes` at `offset`. */
function readU16(bytes: Uint8Array, offset: number): number {
  return bytes[offset] | (bytes[offset + 1] << 8);
}

/** Read a 32-bit little-endian value from `bytes` at `offset` (unsigned). */
function readU32(bytes: Uint8Array, offset: number): number {
  return (
    (bytes[offset] |
      (bytes[offset + 1] << 8) |
      (bytes[offset + 2] << 16) |
      (bytes[offset + 3] << 24)) >>>
    0
  );
}

/** ZIP compression method: stored (no compression). */
const METHOD_STORED = 0;
/** ZIP compression method: DEFLATE. */
const METHOD_DEFLATE = 8;

/** End-of-central-directory record signature. */
const EOCD_SIGNATURE = 0x06054b50;
/** Central-directory file-header signature. */
const CENTRAL_SIGNATURE = 0x02014b50;

/**
 * Inflate a raw DEFLATE payload using the platform `DecompressionStream`. Emitted bundles are
 * small, so the whole buffer is inflated in one pass rather than streamed.
 *
 * @param bytes The raw-DEFLATE compressed bytes.
 * @returns The inflated bytes.
 * @throws Error When the runtime has no `DecompressionStream` (very old browsers).
 */
async function inflateRaw(bytes: Uint8Array): Promise<Uint8Array> {
  if (typeof DecompressionStream === 'undefined') {
    throw new Error('This browser cannot expand the compressed bundle (no DecompressionStream).');
  }
  const stream = new Blob([bytes as BlobPart]).stream().pipeThrough(new DecompressionStream('deflate-raw'));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

/** Locate the end-of-central-directory record by scanning back from the archive's end. */
function findEndOfCentralDirectory(archive: Uint8Array): number {
  // The EOCD is 22 bytes plus an optional comment (≤ 65535). Scan back over the max window.
  const minEocd = 22;
  const start = archive.length - minEocd;
  const limit = Math.max(0, archive.length - minEocd - 0xffff);
  for (let i = start; i >= limit; i--) {
    if (readU32(archive, i) === EOCD_SIGNATURE) return i;
  }
  return -1;
}

/**
 * Read the files out of a stored/deflated ZIP archive via its central directory. Directory entries
 * (names ending in `/`) are skipped; each file's bytes are decoded as UTF-8.
 *
 * @param archive The complete archive bytes (e.g. from a `.zip` emit response).
 * @returns The archive's files, in central-directory order.
 * @throws Error When the archive is malformed, or uses a compression method other than stored/deflate.
 */
export async function readZip(archive: Uint8Array): Promise<ReadZipFile[]> {
  const eocd = findEndOfCentralDirectory(archive);
  if (eocd < 0) {
    throw new Error('Not a readable ZIP archive: no end-of-central-directory record.');
  }
  const total = readU16(archive, eocd + 10);
  let pointer = readU32(archive, eocd + 16); // central directory offset

  const decoder = new TextDecoder('utf-8');
  const files: ReadZipFile[] = [];

  for (let i = 0; i < total; i++) {
    if (readU32(archive, pointer) !== CENTRAL_SIGNATURE) {
      throw new Error('Corrupt ZIP archive: bad central-directory header.');
    }
    const method = readU16(archive, pointer + 10);
    const compressedSize = readU32(archive, pointer + 20);
    const nameLength = readU16(archive, pointer + 28);
    const extraLength = readU16(archive, pointer + 30);
    const commentLength = readU16(archive, pointer + 32);
    const localHeaderOffset = readU32(archive, pointer + 42);
    const name = decoder.decode(archive.subarray(pointer + 46, pointer + 46 + nameLength));

    // Data lives after the *local* header, whose name/extra lengths may differ from the central one.
    const localNameLength = readU16(archive, localHeaderOffset + 26);
    const localExtraLength = readU16(archive, localHeaderOffset + 28);
    const dataStart = localHeaderOffset + 30 + localNameLength + localExtraLength;
    const compressed = archive.subarray(dataStart, dataStart + compressedSize);

    pointer += 46 + nameLength + extraLength + commentLength;

    // Directory markers carry no content.
    if (name.endsWith('/')) continue;

    let data: Uint8Array;
    if (method === METHOD_STORED) {
      data = compressed;
    } else if (method === METHOD_DEFLATE) {
      data = await inflateRaw(compressed);
    } else {
      throw new Error(`Unsupported ZIP compression method ${method} for "${name}".`);
    }
    files.push({ path: name, text: decoder.decode(data) });
  }

  return files;
}

/** The magic bytes that begin every ZIP local file header (`PK\x03\x04`). */
const ZIP_MAGIC = [0x50, 0x4b, 0x03, 0x04];

/**
 * Whether an emit response is a ZIP bundle, from its content type or leading magic bytes — used to
 * decide between the single-file preview and the bundle tree. An empty archive (`PK\x05\x06`, magic
 * for a zip with no local file headers) still reads as a zip by content type.
 *
 * @param bytes The response body bytes.
 * @param contentType The response `Content-Type`, when known.
 * @returns True when the bytes should be read as a ZIP archive.
 */
export function looksLikeZip(bytes: Uint8Array, contentType?: string | null): boolean {
  if ((contentType || '').toLowerCase().includes('zip')) return true;
  return bytes.length >= 4 && ZIP_MAGIC.every((byte, i) => bytes[i] === byte);
}
