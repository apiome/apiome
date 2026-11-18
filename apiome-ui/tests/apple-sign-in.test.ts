/**
 * @jest-environment node
 *
 * Sign in with Apple core tests (OLO-9.30, #5043).
 *
 * Covers the three pieces that make Apple unlike every other catalog provider (`apple-sign-in.ts`):
 * the `.p8` private key read however it was pasted, the ES256 client-secret JWT, and the
 * `form_post` bridge that turns Apple's cross-site POST into the GET Better Auth serves while
 * keeping only the first-consent name. The provider flow itself (exchange → normalize → resolve)
 * lives in `better-auth-oauth-providers.test.ts`.
 */

import { generateKeyPairSync, verify } from 'node:crypto';

import { describe, expect, test } from '@jest/globals';

import {
  APPLE_CLIENT_SECRET_TTL_SECONDS,
  AppleClientSecretError,
  appleCredentials,
  appleFirstConsentName,
  appleFormPostRedirect,
  createAppleClientSecret,
  currentAppleFirstConsentName,
  parseApplePrivateKey,
  runWithAppleCallbackScope,
} from '../lib/auth/apple-sign-in';

const KEY_PAIR = generateKeyPairSync('ec', { namedCurve: 'prime256v1' });
const PEM = KEY_PAIR.privateKey.export({ format: 'pem', type: 'pkcs8' }).toString();
/** The base64 body of the PEM, without armour or line breaks. */
const BODY = PEM.replace(/-----(BEGIN|END) PRIVATE KEY-----/g, '').replace(/\s+/g, '');

const CREDENTIALS = {
  clientId: 'com.example.web',
  teamId: 'A1B2C3D4E5',
  keyId: 'ABC123DEFG',
  privateKey: PEM,
};

const CALLBACK = 'https://app.example.com/api/auth/oauth2/callback/apple';

/** Decode one base64url JWT segment. */
const decodeSegment = (segment: string) =>
  JSON.parse(Buffer.from(segment, 'base64url').toString('utf8'));

describe('parseApplePrivateKey — the .p8 key however it was pasted', () => {
  test.each([
    ['the PEM as downloaded', PEM],
    ['the PEM with its line breaks removed (a single-line input)', PEM.replace(/\n/g, '')],
    ['the PEM with literal \\n escapes (a .env value)', PEM.replace(/\n/g, '\\n')],
    ['the PEM with CRLF line breaks', PEM.replace(/\n/g, '\r\n')],
    ['the bare base64 body', BODY],
    ['the PEM with surrounding whitespace', `  \n${PEM}\n  `],
  ])('accepts %s', (_label, raw) => {
    const key = parseApplePrivateKey(raw);
    expect(key.asymmetricKeyType).toBe('ec');
    expect(key.asymmetricKeyDetails?.namedCurve).toBe('prime256v1');
  });

  test.each([
    ['blank text', '   '],
    ['text that is not base64', 'not a key at all!'],
    ['base64 that is not a key', Buffer.from('hello world').toString('base64')],
  ])('rejects %s without echoing it', (_label, raw) => {
    expect(() => parseApplePrivateKey(raw)).toThrow(AppleClientSecretError);
    try {
      parseApplePrivateKey(raw);
    } catch (error) {
      if (raw.trim()) expect((error as Error).message).not.toContain(raw.trim());
    }
  });

  test('rejects a key on another curve, or an RSA key', () => {
    const p384 = generateKeyPairSync('ec', { namedCurve: 'secp384r1' })
      .privateKey.export({ format: 'pem', type: 'pkcs8' })
      .toString();
    const rsa = generateKeyPairSync('rsa', { modulusLength: 2048 })
      .privateKey.export({ format: 'pem', type: 'pkcs8' })
      .toString();
    expect(() => parseApplePrivateKey(p384)).toThrow('EC P-256');
    expect(() => parseApplePrivateKey(rsa)).toThrow('EC P-256');
  });
});

describe('createAppleClientSecret — the ES256 JWT Apple requires', () => {
  test('signs header { ES256, kid } and claims { iss, iat, exp, aud, sub } with the .p8 key', () => {
    const jwt = createAppleClientSecret(CREDENTIALS, 1_700_000_000);
    const [header, claims, signature] = jwt.split('.');

    expect(decodeSegment(header)).toEqual({ alg: 'ES256', kid: 'ABC123DEFG' });
    expect(decodeSegment(claims)).toEqual({
      iss: 'A1B2C3D4E5',
      iat: 1_700_000_000,
      exp: 1_700_000_000 + APPLE_CLIENT_SECRET_TTL_SECONDS,
      aud: 'https://appleid.apple.com',
      sub: 'com.example.web',
    });
    // JOSE ES256 is the raw 64-byte r||s pair, not DER.
    const raw = Buffer.from(signature, 'base64url');
    expect(raw).toHaveLength(64);
    expect(
      verify(
        'sha256',
        Buffer.from(`${header}.${claims}`),
        { key: KEY_PAIR.publicKey, dsaEncoding: 'ieee-p1363' },
        raw,
      ),
    ).toBe(true);
  });

  test('is short-lived: five minutes by default, well inside Apple’s six-month ceiling', () => {
    expect(APPLE_CLIENT_SECRET_TTL_SECONDS).toBe(300);
    const claims = decodeSegment(createAppleClientSecret(CREDENTIALS, 100, 60).split('.')[1]);
    expect(claims.exp - claims.iat).toBe(60);
  });

  test('a key pasted without line breaks signs the same way', () => {
    const jwt = createAppleClientSecret({ ...CREDENTIALS, privateKey: PEM.replace(/\n/g, '') }, 1);
    const [header, claims, signature] = jwt.split('.');
    expect(
      verify(
        'sha256',
        Buffer.from(`${header}.${claims}`),
        { key: KEY_PAIR.publicKey, dsaEncoding: 'ieee-p1363' },
        Buffer.from(signature, 'base64url'),
      ),
    ).toBe(true);
  });

  test('names every missing value, and never signs with a blank one', () => {
    expect(() =>
      createAppleClientSecret({ clientId: '', teamId: ' ', keyId: 'k', privateKey: PEM }),
    ).toThrow('Apple sign-in is missing APPLE_CLIENT_ID, APPLE_TEAM_ID.');
  });
});

describe('appleCredentials', () => {
  test('reads the four APPLE_* values, trimmed, with blanks for anything unset', () => {
    expect(
      appleCredentials({
        APPLE_CLIENT_ID: ' com.example.web ',
        APPLE_TEAM_ID: 'A1B2C3D4E5',
        APPLE_KEY_ID: '',
      }),
    ).toEqual({ clientId: 'com.example.web', teamId: 'A1B2C3D4E5', keyId: '', privateKey: '' });
  });
});

describe('appleFirstConsentName — the name Apple sends once', () => {
  test.each([
    ['first and last', { name: { firstName: 'Ada', lastName: 'Lovelace' } }, 'Ada Lovelace'],
    ['first only', { name: { firstName: 'Ada' } }, 'Ada'],
    ['last only', { name: { lastName: 'Lovelace' } }, 'Lovelace'],
    ['parts with whitespace', { name: { firstName: '  Ada ', lastName: ' ' } }, 'Ada'],
    ['an email but no name', { email: 'ada@example.com' }, null],
    ['an empty name', { name: {} }, null],
    ['non-string parts', { name: { firstName: 7, lastName: true } }, null],
  ])('%s', (_label, user, expected) => {
    expect(appleFirstConsentName(JSON.stringify(user))).toBe(expected);
  });

  test.each([
    ['absent', undefined],
    ['empty', ''],
    ['not JSON', '{nope'],
    ['JSON that is not an object', '"Ada"'],
  ])('%s → null', (_label, raw) => {
    expect(appleFirstConsentName(raw)).toBeNull();
  });

  test('caps each name part at 100 characters', () => {
    const name = appleFirstConsentName(JSON.stringify({ name: { firstName: 'a'.repeat(500) } }));
    expect(name).toHaveLength(100);
  });
});

describe('appleFormPostRedirect — Apple’s form_post becomes a same-path GET', () => {
  /** A form_post the way Apple sends it. */
  const formPost = (fields: Record<string, string>, url = CALLBACK) =>
    new Request(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams(fields).toString(),
    });

  test('forwards code and state, and only the name from the first-consent user field', async () => {
    const response = await appleFormPostRedirect(
      formPost({
        code: 'the-code',
        state: 'the-state',
        id_token: 'header.claims.sig',
        user: JSON.stringify({
          name: { firstName: 'Ada', lastName: 'Lovelace' },
          email: 'attacker@example.com',
        }),
      }),
    );

    expect(response?.status).toBe(303);
    expect(response?.headers.get('Cache-Control')).toBe('no-store');
    const location = response?.headers.get('Location') ?? '';
    // Relative: a proxied deployment keeps its public host.
    expect(location.startsWith('/api/auth/oauth2/callback/apple?')).toBe(true);
    const params = new URLSearchParams(location.split('?')[1]);
    expect(params.get('code')).toBe('the-code');
    expect(params.get('state')).toBe('the-state');
    expect(JSON.parse(params.get('user') ?? '')).toEqual({ name: { fullName: 'Ada Lovelace' } });
    // The unsigned email and the id token never travel further.
    expect(location).not.toContain('attacker');
    expect(params.has('id_token')).toBe(false);
  });

  test('a repeat sign-in carries no user field', async () => {
    const response = await appleFormPostRedirect(formPost({ code: 'c', state: 's' }));
    const params = new URLSearchParams((response?.headers.get('Location') ?? '').split('?')[1]);
    expect([...params.keys()]).toEqual(['code', 'state']);
  });

  test('a cancelled authorization forwards Apple’s error', async () => {
    const response = await appleFormPostRedirect(
      formPost({ error: 'user_cancelled_authorize', state: 's' }),
    );
    const params = new URLSearchParams((response?.headers.get('Location') ?? '').split('?')[1]);
    expect(params.get('error')).toBe('user_cancelled_authorize');
    expect(params.has('code')).toBe(false);
  });

  test('leaves every other request to Better Auth', async () => {
    expect(await appleFormPostRedirect(new Request(CALLBACK))).toBeNull();
    expect(
      await appleFormPostRedirect(
        formPost({ code: 'c' }, 'https://app.example.com/api/auth/oauth2/callback/google'),
      ),
    ).toBeNull();
    expect(
      await appleFormPostRedirect(
        formPost({ code: 'c' }, 'https://app.example.com/api/auth/sign-in/email'),
      ),
    ).toBeNull();
  });
});

describe('runWithAppleCallbackScope — the name reaches the normalizer for one request', () => {
  const callbackWithName = `${CALLBACK}?code=c&state=s&user=${encodeURIComponent(
    JSON.stringify({ name: { fullName: 'Ada Lovelace' } }),
  )}`;

  test('a GET to Apple’s callback exposes the forwarded name', async () => {
    const name = await runWithAppleCallbackScope(new Request(callbackWithName), async () =>
      currentAppleFirstConsentName(),
    );
    expect(name).toBe('Ada Lovelace');
  });

  test('no user field, a malformed one, or another path → no name', async () => {
    const read = (url: string) =>
      runWithAppleCallbackScope(new Request(url), async () => currentAppleFirstConsentName());
    expect(await read(`${CALLBACK}?code=c&state=s`)).toBeNull();
    expect(await read(`${CALLBACK}?code=c&user=%7Bnope`)).toBeNull();
    expect(await read(callbackWithName.replace('/callback/apple', '/callback/google'))).toBeNull();
  });

  test('the name never leaks outside its request', async () => {
    await runWithAppleCallbackScope(new Request(callbackWithName), async () => undefined);
    expect(currentAppleFirstConsentName()).toBeNull();
  });
});
