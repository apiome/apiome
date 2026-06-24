import crypto from "node:crypto";

import { describe, expect, it } from "vitest";

import {
  KEY_BYTES,
  artifactSalt,
  decryptArtifact,
  deriveKey,
  encryptArtifact,
  isEncryptedArtifact,
  normalizeKey,
} from "../src/backup/crypto.js";
import { CliError } from "../src/errors.js";

const key = crypto.randomBytes(KEY_BYTES);

describe("encrypt/decrypt round-trip", () => {
  it("recovers the original plaintext", () => {
    const plaintext = Buffer.from("the source of truth must be recoverable", "utf8");
    const artifact = encryptArtifact(plaintext, key);
    expect(isEncryptedArtifact(artifact)).toBe(true);
    expect(artifact.equals(plaintext)).toBe(false); // actually encrypted
    expect(decryptArtifact(artifact, key)).toEqual(plaintext);
  });

  it("uses a fresh IV so identical plaintext encrypts differently", () => {
    const plaintext = Buffer.from("same input", "utf8");
    const a = encryptArtifact(plaintext, key);
    const b = encryptArtifact(plaintext, key);
    expect(a.equals(b)).toBe(false);
    expect(decryptArtifact(a, key)).toEqual(plaintext);
    expect(decryptArtifact(b, key)).toEqual(plaintext);
  });

  it("handles empty plaintext", () => {
    const artifact = encryptArtifact(Buffer.alloc(0), key);
    expect(decryptArtifact(artifact, key)).toEqual(Buffer.alloc(0));
  });
});

describe("authentication", () => {
  it("rejects the wrong key", () => {
    const artifact = encryptArtifact(Buffer.from("secret"), key);
    const wrong = crypto.randomBytes(KEY_BYTES);
    expect(() => decryptArtifact(artifact, wrong)).toThrow(CliError);
  });

  it("detects tampering with the ciphertext", () => {
    const artifact = encryptArtifact(Buffer.from("secret payload"), key);
    artifact[artifact.length - 1] ^= 0xff; // flip a ciphertext bit
    expect(() => decryptArtifact(artifact, key)).toThrow(/decryption failed/i);
  });

  it("rejects buffers without the magic header", () => {
    expect(isEncryptedArtifact(Buffer.from("not a backup"))).toBe(false);
    expect(() => decryptArtifact(Buffer.from("not a backup"), key)).toThrow(/not an objectified backup/i);
  });
});

describe("normalizeKey", () => {
  it("accepts raw 32-byte buffers", () => {
    expect(normalizeKey(key)).toEqual(key);
  });

  it("accepts 64-char hex (with trailing whitespace)", () => {
    const hex = key.toString("hex");
    expect(normalizeKey(`${hex}\n`)).toEqual(key);
  });

  it("accepts base64 of a 32-byte key", () => {
    expect(normalizeKey(key.toString("base64"))).toEqual(key);
  });

  it("rejects keys of the wrong size", () => {
    expect(() => normalizeKey("deadbeef")).toThrow(CliError);
    expect(() => normalizeKey(crypto.randomBytes(16))).toThrow(CliError);
  });
});

describe("deriveKey", () => {
  it("is deterministic for a passphrase + salt and yields a 32-byte key", () => {
    const salt = Buffer.from("0123456789abcdef");
    const k1 = deriveKey("correct horse battery staple", salt);
    const k2 = deriveKey("correct horse battery staple", salt);
    expect(k1).toEqual(k2);
    expect(k1.length).toBe(KEY_BYTES);
  });

  it("changes with the salt", () => {
    const a = deriveKey("pw", Buffer.from("0123456789abcdef"));
    const b = deriveKey("pw", Buffer.from("fedcba9876543210"));
    expect(a.equals(b)).toBe(false);
  });

  it("can round-trip a passphrase-derived key via the artifact salt", () => {
    const k = deriveKey("pw", crypto.randomBytes(16));
    const artifact = encryptArtifact(Buffer.from("hello"), k);
    expect(artifactSalt(artifact).length).toBe(16);
    expect(decryptArtifact(artifact, k).toString()).toBe("hello");
  });
});
