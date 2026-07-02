/**
 * Encryption for backup artifacts.
 *
 * Backups are encrypted at rest with AES-256-GCM (authenticated encryption: any tampering with
 * the ciphertext is detected on decrypt). The 32-byte data key is supplied by the operator via a
 * key file (`--encrypt-key-file`) or env (`APIOME_BACKUP_KEY`); we never generate or persist
 * keys ourselves. A passphrase can be turned into a key with `deriveKey` (scrypt).
 *
 * On-disk layout of an encrypted artifact (a single self-describing buffer):
 *
 *   magic(8) | version(1) | salt(16) | iv(12) | authTag(16) | ciphertext(…)
 *
 * The salt is only meaningful for passphrase-derived keys; with a raw key file it is still
 * written (random) but unused on decrypt. Keeping a fixed header keeps the format forward
 * compatible and lets `restore` validate it is reading an apiome backup before doing work.
 */

import crypto from "node:crypto";

import { CliError } from "../errors.js";

/** AES-256 key length in bytes. */
export const KEY_BYTES = 32;

const MAGIC = Buffer.from("ODBBKUP\0", "ascii"); // 8 bytes
const FORMAT_VERSION = 1;
const SALT_BYTES = 16;
const IV_BYTES = 12; // GCM standard nonce length
const TAG_BYTES = 16;
const HEADER_BYTES = MAGIC.length + 1 + SALT_BYTES + IV_BYTES + TAG_BYTES;

/**
 * Normalize operator-supplied key material into a 32-byte key.
 *
 * Accepts either raw bytes (exactly 32) or hex/base64 text of a 32-byte key. Whitespace around
 * text keys is ignored so a key file with a trailing newline still works.
 */
export function normalizeKey(material: Buffer | string): Buffer {
  if (Buffer.isBuffer(material) && material.length === KEY_BYTES) {
    return material;
  }
  const text = (Buffer.isBuffer(material) ? material.toString("utf8") : material).trim();
  if (/^[0-9a-fA-F]{64}$/.test(text)) {
    return Buffer.from(text, "hex");
  }
  // base64 of 32 bytes is 44 chars (single '=' pad).
  if (/^[A-Za-z0-9+/]{43}=$/.test(text)) {
    const decoded = Buffer.from(text, "base64");
    if (decoded.length === KEY_BYTES) return decoded;
  }
  throw new CliError("Backup encryption key must be 32 bytes (raw, or 64-char hex, or base64).", {
    hint: "Generate one with:  openssl rand -hex 32  > backup.key",
  });
}

/** Derive a 32-byte key from a passphrase and salt using scrypt (CPU/memory-hard). */
export function deriveKey(passphrase: string, salt: Buffer): Buffer {
  return crypto.scryptSync(passphrase, salt, KEY_BYTES);
}

/** True when a buffer starts with the apiome backup magic header. */
export function isEncryptedArtifact(buf: Buffer): boolean {
  return buf.length >= HEADER_BYTES && buf.subarray(0, MAGIC.length).equals(MAGIC);
}

/**
 * Encrypt `plaintext` with `key`, returning the self-describing artifact buffer.
 * A fresh random IV and salt are generated per call.
 */
export function encryptArtifact(plaintext: Buffer, key: Buffer): Buffer {
  if (key.length !== KEY_BYTES) {
    throw new CliError(`Encryption key must be ${KEY_BYTES} bytes (got ${key.length}).`);
  }
  const salt = crypto.randomBytes(SALT_BYTES);
  const iv = crypto.randomBytes(IV_BYTES);
  const cipher = crypto.createCipheriv("aes-256-gcm", key, iv);
  const ciphertext = Buffer.concat([cipher.update(plaintext), cipher.final()]);
  const authTag = cipher.getAuthTag();
  return Buffer.concat([MAGIC, Buffer.from([FORMAT_VERSION]), salt, iv, authTag, ciphertext]);
}

/** The random salt stored in an artifact header (for passphrase-derived keys). */
export function artifactSalt(artifact: Buffer): Buffer {
  if (!isEncryptedArtifact(artifact)) {
    throw new CliError("Not an apiome backup artifact (bad header).");
  }
  const start = MAGIC.length + 1;
  return artifact.subarray(start, start + SALT_BYTES);
}

/**
 * Decrypt an artifact produced by `encryptArtifact`. Throws a friendly error when the header is
 * not ours or when authentication fails (wrong key or tampered ciphertext).
 */
export function decryptArtifact(artifact: Buffer, key: Buffer): Buffer {
  if (!isEncryptedArtifact(artifact)) {
    throw new CliError("Not an apiome backup artifact (bad header).", {
      hint: "The file is not an encrypted apiome backup, or it is corrupt.",
    });
  }
  const version = artifact[MAGIC.length];
  if (version !== FORMAT_VERSION) {
    throw new CliError(`Unsupported backup format version ${String(version)}.`);
  }
  let offset = MAGIC.length + 1 + SALT_BYTES; // skip magic, version, salt
  const iv = artifact.subarray(offset, offset + IV_BYTES);
  offset += IV_BYTES;
  const authTag = artifact.subarray(offset, offset + TAG_BYTES);
  offset += TAG_BYTES;
  const ciphertext = artifact.subarray(offset);
  const decipher = crypto.createDecipheriv("aes-256-gcm", key, iv);
  decipher.setAuthTag(authTag);
  try {
    return Buffer.concat([decipher.update(ciphertext), decipher.final()]);
  } catch {
    throw new CliError("Backup decryption failed (wrong key or corrupt/tampered artifact).", {
      hint: "Confirm APIOME_BACKUP_KEY / --encrypt-key-file matches the key used to create it.",
    });
  }
}
