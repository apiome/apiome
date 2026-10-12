/**
 * @jest-environment node
 *
 * Linked-account token encryption-at-rest (OLO-7.3 follow-up, #4960).
 *
 * Covers the contract of `lib/auth/linked-account-token-crypto.ts`:
 *
 * - a token round-trips through the sealed `enc:v1` string, and the stored value carries no plaintext;
 * - a legacy plaintext value still reads (the upgrade path);
 * - sealing fails closed and unsealing fails safe — the ciphertext is never returned as a token;
 * - key rotation and key-map validation;
 * - the vectors apiome-rest sealed open here (the two implementations share one format).
 */
import { randomBytes } from 'node:crypto';
import { afterEach, beforeEach, describe, expect, jest, test } from '@jest/globals';

import {
  ACTIVE_VERSION_SETTING,
  KEYS_SETTING,
  LinkedAccountTokenEncryptionError,
  SEALED_PREFIX,
  isSealed,
  loadKeyMap,
  sealToken,
  sealTokenOrNull,
  tokenEncryptionConfigured,
  unsealToken,
  type TokenCryptoEnv,
} from '../lib/auth/linked-account-token-crypto';
import vectors from './fixtures/linked-account-token-vectors.json';

const TOKEN = 'gho_test_token_not_a_real_credential_0001';

/** A fresh base64-encoded 32-byte AES-256 master key. */
const newKey = () => randomBytes(32).toString('base64');

/** An environment holding `keys`, optionally pinning the active version. */
const envWith = (keys: Record<string, string>, active?: number): TokenCryptoEnv => ({
  [KEYS_SETTING]: JSON.stringify(keys),
  ...(active === undefined ? {} : { [ACTIVE_VERSION_SETTING]: String(active) }),
});

let warn: ReturnType<typeof jest.spyOn>;

beforeEach(() => {
  warn = jest.spyOn(console, 'warn').mockImplementation(() => undefined);
});

afterEach(() => {
  warn.mockRestore();
});

describe('sealToken / unsealToken', () => {
  test.each([TOKEN, 'glpat-x', 't', 'ünïcode-tøken', 'a:b:c', 'x'.repeat(4096)])('round-trips %#', (token) => {
    const env = envWith({ '1': newKey() });
    const sealed = sealToken(token, env);
    expect(sealed.startsWith(`${SEALED_PREFIX}1:`)).toBe(true);
    expect(isSealed(sealed)).toBe(true);
    expect(unsealToken(sealed, env)).toBe(token);
  });

  test('the sealed value carries no plaintext and differs on every call', () => {
    const env = envWith({ '1': newKey() });
    const sealed = sealToken(TOKEN, env);
    expect(sealed).not.toContain(TOKEN);
    expect(Buffer.from(sealed.split(':')[3], 'base64').includes(Buffer.from(TOKEN))).toBe(false);
    expect(sealToken(TOKEN, env)).not.toBe(sealed);
  });

  test('sealing fails closed when no key is configured', () => {
    expect(tokenEncryptionConfigured({})).toBe(false);
    expect(() => sealToken(TOKEN, {})).toThrow(LinkedAccountTokenEncryptionError);
    expect(() => sealToken(TOKEN, {})).toThrow(KEYS_SETTING);
    expect(() => sealToken(TOKEN, { [KEYS_SETTING]: '   ' })).toThrow(KEYS_SETTING);
  });

  test('sealing rejects an empty token', () => {
    expect(() => sealToken('', envWith({ '1': newKey() }))).toThrow(LinkedAccountTokenEncryptionError);
  });

  test.each([null, undefined, '', '   ', 12])('unsealing %p yields no token', (value) => {
    expect(unsealToken(value, envWith({ '1': newKey() }))).toBeNull();
  });

  test('a legacy plaintext value reads unchanged, with or without a key', () => {
    expect(isSealed(TOKEN)).toBe(false);
    expect(unsealToken(TOKEN, envWith({ '1': newKey() }))).toBe(TOKEN);
    expect(unsealToken(TOKEN, {})).toBe(TOKEN);
  });

  test('a sealed value without its key is absent — never the ciphertext', () => {
    const sealed = sealToken(TOKEN, envWith({ '1': newKey() }));
    expect(unsealToken(sealed, {})).toBeNull();
    expect(unsealToken(sealed, envWith({ '1': newKey() }))).toBeNull();
    expect(unsealToken(sealed, { [KEYS_SETTING]: 'not json' })).toBeNull();
  });

  test.each<[string, (sealed: string) => string]>([
    ['a tampered tail', (s) => s.slice(0, -4) + (s.endsWith('AAAA') ? 'BBBB' : 'AAAA')],
    ['re-tagged to another key-version', (s) => s.replace(':1:', ':2:')],
    ['a non-integer version', (s) => s.replace(':1:', ':x:')],
    ['a body that is not base64', (s) => `${s.slice(0, s.lastIndexOf(':'))}:not base64!`],
    ['a body that is too short', (s) => `${s.slice(0, s.lastIndexOf(':'))}:${Buffer.from('short').toString('base64')}`],
    ['no body at all', () => `${SEALED_PREFIX}1`],
  ])('%s is absent', (_name, mangle) => {
    const env = envWith({ '1': newKey(), '2': newKey() }, 1);
    expect(unsealToken(mangle(sealToken(TOKEN, env)), env)).toBeNull();
  });

  test('a failure is logged without the token, the key or the ciphertext', () => {
    const key = newKey();
    const sealed = sealToken(TOKEN, envWith({ '1': key }));
    unsealToken(sealed, envWith({ '1': newKey() }));
    unsealToken(`${SEALED_PREFIX}x:y`, envWith({ '1': key }));
    expect(warn).toHaveBeenCalledTimes(2);
    const logged = warn.mock.calls.flat().join(' ');
    expect(logged).not.toContain(TOKEN);
    expect(logged).not.toContain(key);
    expect(logged).not.toContain(sealed);
  });
});

describe('sealTokenOrNull', () => {
  test('seals a token when encryption is configured', () => {
    const env = envWith({ '1': newKey() });
    expect(unsealToken(sealTokenOrNull(TOKEN, env), env)).toBe(TOKEN);
  });

  test.each([null, undefined, ''])('stores nothing for %p', (value) => {
    expect(sealTokenOrNull(value, envWith({ '1': newKey() }))).toBeNull();
    expect(warn).not.toHaveBeenCalled();
  });

  test('stores nothing — not plaintext — when encryption is not configured', () => {
    expect(sealTokenOrNull(TOKEN, {})).toBeNull();
    expect(warn).toHaveBeenCalledTimes(1);
    expect(warn.mock.calls.flat().join(' ')).not.toContain(TOKEN);
  });
});

describe('key rotation and configuration', () => {
  test('old rows stay readable and new tokens use the highest version', () => {
    const keys: Record<string, string> = { '1': newKey() };
    const old = sealToken(TOKEN, envWith(keys));
    keys['2'] = newKey();
    const fresh = sealToken(TOKEN, envWith(keys));
    expect(fresh.startsWith(`${SEALED_PREFIX}2:`)).toBe(true);
    expect(unsealToken(old, envWith(keys))).toBe(TOKEN);
    expect(unsealToken(fresh, envWith(keys))).toBe(TOKEN);
  });

  test('the active version can be pinned', () => {
    const env = envWith({ '1': newKey(), '2': newKey() }, 1);
    expect(sealToken(TOKEN, env).startsWith(`${SEALED_PREFIX}1:`)).toBe(true);
  });

  test('accepts URL-safe base64 keys', () => {
    const urlSafe = randomBytes(32).toString('base64url');
    const env = envWith({ '1': urlSafe });
    expect(unsealToken(sealToken(TOKEN, env), env)).toBe(TOKEN);
  });

  test.each<[string, TokenCryptoEnv]>([
    ['not JSON', { [KEYS_SETTING]: 'not json' }],
    ['not an object', { [KEYS_SETTING]: '[]' }],
    ['an empty object', { [KEYS_SETTING]: '{}' }],
    ['a short key', { [KEYS_SETTING]: JSON.stringify({ '1': 'c2hvcnQ=' }) }],
    ['a key that is not base64', { [KEYS_SETTING]: JSON.stringify({ '1': '!!!' }) }],
    ['a key that is not a string', { [KEYS_SETTING]: JSON.stringify({ '1': 5 }) }],
    ['a non-integer version', { [KEYS_SETTING]: JSON.stringify({ one: newKey() }) }],
    ['version zero', { [KEYS_SETTING]: JSON.stringify({ '0': newKey() }) }],
    ['an active version with no key', envWith({ '1': newKey() }, 7)],
    ['a non-integer active version', { ...envWith({ '1': newKey() }), [ACTIVE_VERSION_SETTING]: 'two' }],
  ])('a misconfigured key map (%s) cannot seal', (_name, env) => {
    expect(tokenEncryptionConfigured(env)).toBe(false);
    expect(() => sealToken(TOKEN, env)).toThrow(LinkedAccountTokenEncryptionError);
  });

  test('an unset key map parses to nothing', () => {
    expect(loadKeyMap({}).size).toBe(0);
  });
});

describe('cross-language vectors', () => {
  const env = envWith(vectors.keys);

  test.each([...vectors.python, ...vectors.typescript])('opens $token', ({ sealed, token, key_version }) => {
    expect(sealed.startsWith(`${SEALED_PREFIX}${key_version}:`)).toBe(true);
    expect(unsealToken(sealed, env)).toBe(token);
  });

  test('covers values sealed by both implementations', () => {
    expect(vectors.python.length).toBeGreaterThanOrEqual(2);
    expect(vectors.typescript.length).toBeGreaterThanOrEqual(2);
  });
});
