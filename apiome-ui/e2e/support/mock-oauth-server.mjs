/**
 * Mock OAuth/OIDC provider for the OLO-7.4 end-to-end journey suite (#4226).
 *
 * One dependency-free Node HTTP server that impersonates all four MVP sign-in providers,
 * path-prefixed so a single port serves them all:
 *
 *   - GitHub  — OAuth2 web flow + REST profile/emails API
 *       authorize:  GET  /github/login/oauth/authorize
 *       token:      POST /github/login/oauth/access_token
 *       profile:    GET  /github/api/user            (point GITHUB_API_BASE_URL here)
 *       emails:     GET  /github/api/user/emails
 *   - GitLab  — OAuth2 web flow + /api/v4/user profile
 *       authorize:  GET  /gitlab/oauth/authorize
 *       token:      POST /gitlab/oauth/token
 *       profile:    GET  /gitlab/api/v4/user         (point GITLAB_BASE_URL at /gitlab)
 *   - Azure (Entra ID) — OIDC authorization-code flow with PKCE + signed RS256 id_token
 *       discovery:  GET  /azure/<tenant>/v2.0/.well-known/openid-configuration
 *       authorize:  GET  /azure/<tenant>/v2.0/authorize
 *       token:      POST /azure/<tenant>/v2.0/token
 *       jwks:       GET  /azure/jwks
 *     (point AZURE_AD_AUTHORITY_BASE_URL at /azure; any AZURE_AD_TENANT works)
 *   - Google — OIDC authorization-code flow with PKCE + signed RS256 id_token (OLO-10.13)
 *       discovery:  GET  /google/.well-known/openid-configuration
 *       authorize:  GET  /google/o/oauth2/v2/auth
 *       token:      POST /google/token
 *       jwks:       GET  /azure/jwks   (shared keypair)
 *     (point GOOGLE_ISSUER at /google)
 *
 * Control API (used by the Playwright journey to drive who "logs in" next):
 *   POST /__mock__/persona   body: {"email","name","login","providerUserId","verified":bool}
 *       → the persona returned by the next authorize/token/profile round-trip
 *   GET  /__mock__/health    → 200 once the server is ready
 *
 * The persona is snapshotted at authorize time (code → persona, then token → persona), so
 * switching personas between logins can never bleed into an in-flight exchange.
 *
 * Verified-email semantics mirror each provider's real signal (see `verified-email.ts` and
 * the nOAuth rules in `account-resolution.ts`):
 *   - github: `/user/emails` entry `verified` flag
 *   - gitlab: `confirmed_at` present on `/api/v4/user`
 *   - azure:  explicit `email_verified: true` claim in the id_token (omitted when unverified)
 *   - google: explicit `email_verified: true` claim in the id_token (omitted when unverified)
 *
 * Test-only: this server performs no real authentication and must never be deployed.
 * Run with:  node e2e/support/mock-oauth-server.mjs   (MOCK_OAUTH_PORT, default 8091)
 */
import { createServer } from 'node:http';
import { createHash, createSign, generateKeyPairSync, randomBytes } from 'node:crypto';

const PORT = Number(process.env.MOCK_OAUTH_PORT || 8091);

/** RSA keypair for signing Azure id_tokens; regenerated every server start. */
const { publicKey, privateKey } = generateKeyPairSync('rsa', { modulusLength: 2048 });
const KEY_ID = 'mock-oauth-key';

/** The persona the next login round-trip resolves to (set via the control API). */
let currentPersona = defaultPersona();

/** Authorization codes issued but not yet exchanged: code → {persona, nonce, codeChallenge}. */
const pendingCodes = new Map();
/** Access tokens issued by the token endpoints: token → persona snapshot. */
const issuedTokens = new Map();

/**
 * The out-of-the-box persona, used when a test never posts to the control API.
 *
 * @returns A verified persona with distinct provider-side ids.
 */
function defaultPersona() {
  return {
    email: 'journey.user@example.test',
    name: 'Journey User',
    login: 'journey-user',
    providerUserId: '9001',
    verified: true,
  };
}

/**
 * Base64url-encode a buffer or UTF-8 string (JWT alphabet, no padding).
 *
 * @param input Buffer or string to encode.
 * @returns The base64url string.
 */
function b64url(input) {
  return Buffer.from(input).toString('base64url');
}

/**
 * Sign an RS256 JWT with the server's private key.
 *
 * @param claims JWT payload claims.
 * @returns The compact-serialized signed token.
 */
function signJwt(claims) {
  const header = b64url(JSON.stringify({ alg: 'RS256', typ: 'JWT', kid: KEY_ID }));
  const payload = b64url(JSON.stringify(claims));
  const signer = createSign('RSA-SHA256');
  signer.update(`${header}.${payload}`);
  return `${header}.${payload}.${signer.sign(privateKey).toString('base64url')}`;
}

/**
 * Verify a PKCE S256 code_verifier against the challenge captured at authorize time.
 * A missing challenge (non-PKCE client, e.g. the GitHub flow) always passes.
 *
 * @param codeChallenge Challenge from the authorize request, or undefined.
 * @param codeVerifier Verifier from the token request, or undefined.
 * @returns True when the exchange is acceptable.
 */
function pkceOk(codeChallenge, codeVerifier) {
  if (!codeChallenge) return true;
  if (!codeVerifier) return false;
  return createHash('sha256').update(codeVerifier).digest('base64url') === codeChallenge;
}

/**
 * Issue an authorization code for the current persona and redirect back to the client.
 *
 * @param url Parsed request URL (carries redirect_uri, state, nonce, code_challenge).
 * @param res Node response to write the 302 onto.
 */
function handleAuthorize(url, res) {
  const redirectUri = url.searchParams.get('redirect_uri');
  if (!redirectUri) {
    sendJson(res, 400, { error: 'invalid_request', error_description: 'redirect_uri required' });
    return;
  }
  const code = randomBytes(16).toString('hex');
  pendingCodes.set(code, {
    persona: { ...currentPersona },
    nonce: url.searchParams.get('nonce') || undefined,
    codeChallenge: url.searchParams.get('code_challenge') || undefined,
  });
  const target = new URL(redirectUri);
  target.searchParams.set('code', code);
  const state = url.searchParams.get('state');
  if (state) target.searchParams.set('state', state);
  res.writeHead(302, { Location: target.toString() });
  res.end();
}

/**
 * Exchange an authorization code for tokens.
 *
 * @param body Parsed form body of the token request.
 * @param issuer OIDC issuer string when the caller expects an id_token (azure); null for
 *   the plain OAuth2 providers (github/gitlab).
 * @param clientId OAuth client id claimed by the request (id_token audience).
 * @returns The token-endpoint JSON payload, or null when the code is unknown/PKCE fails.
 */
function exchangeCode(body, issuer, clientId) {
  const grant = pendingCodes.get(body.code);
  if (!grant || !pkceOk(grant.codeChallenge, body.code_verifier)) return null;
  pendingCodes.delete(body.code);

  const accessToken = `mock-access-${randomBytes(12).toString('hex')}`;
  issuedTokens.set(accessToken, grant.persona);
  const response = {
    access_token: accessToken,
    token_type: 'bearer',
    expires_in: 3600,
    scope: body.scope || '',
  };

  if (issuer) {
    const persona = grant.persona;
    const now = Math.floor(Date.now() / 1000);
    response.token_type = 'Bearer';
    response.refresh_token = `mock-refresh-${randomBytes(8).toString('hex')}`;
    response.id_token = signJwt({
      iss: issuer,
      aud: clientId,
      sub: `sub-${persona.providerUserId}`,
      oid: `oid-${persona.providerUserId}`,
      tid: 'mock-tenant',
      name: persona.name,
      email: persona.email,
      preferred_username: persona.email,
      // Verified persona → explicit positive claim, the evidence the nOAuth rules
      // (OLO-1.4) accept. Unverified persona → no claim at all, which fails closed.
      ...(persona.verified ? { email_verified: true } : {}),
      ...(grant.nonce ? { nonce: grant.nonce } : {}),
      iat: now,
      exp: now + 3600,
    });
  }
  return response;
}

/**
 * Resolve the persona bound to a request's bearer token.
 *
 * @param req Incoming request (Authorization: Bearer <token>).
 * @returns The persona snapshot, or null for an unknown/missing token.
 */
function personaForToken(req) {
  const auth = req.headers.authorization || '';
  const token = auth.replace(/^bearer\s+/i, '').trim();
  return issuedTokens.get(token) ?? null;
}

/**
 * Write a JSON response.
 *
 * @param res Node response.
 * @param status HTTP status code.
 * @param payload JSON-serializable body.
 */
function sendJson(res, status, payload) {
  const body = JSON.stringify(payload);
  res.writeHead(status, { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body) });
  res.end(body);
}

/**
 * Read and parse a request body as either a URL-encoded form or JSON.
 *
 * @param req Incoming request.
 * @returns Parsed key/value body object.
 */
async function readBody(req) {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  const raw = Buffer.concat(chunks).toString('utf8');
  const type = req.headers['content-type'] || '';
  if (type.includes('application/json')) {
    try {
      return JSON.parse(raw || '{}');
    } catch {
      return {};
    }
  }
  return Object.fromEntries(new URLSearchParams(raw));
}

/** GitHub `/user` profile for a persona (public email always present in the mock). */
function githubProfile(persona) {
  return {
    id: Number(persona.providerUserId),
    login: persona.login,
    name: persona.name,
    email: persona.email,
    avatar_url: `http://localhost:${PORT}/avatar/${persona.login}.png`,
    html_url: `http://localhost:${PORT}/github/${persona.login}`,
  };
}

/** GitLab `/api/v4/user` profile; `confirmed_at` only when the persona is verified. */
function gitlabProfile(persona) {
  return {
    id: Number(persona.providerUserId),
    username: persona.login,
    name: persona.name,
    email: persona.email,
    confirmed_at: persona.verified ? '2026-01-01T00:00:00Z' : null,
    avatar_url: `http://localhost:${PORT}/avatar/${persona.login}.png`,
    web_url: `http://localhost:${PORT}/gitlab/${persona.login}`,
  };
}

/** The public JWK set for id_token signature validation. */
function jwks() {
  return { keys: [{ ...publicKey.export({ format: 'jwk' }), use: 'sig', alg: 'RS256', kid: KEY_ID }] };
}

/** OIDC discovery document for the mock Azure authority. */
function azureDiscovery(origin, tenant) {
  const issuer = `${origin}/azure/${tenant}/v2.0`;
  return {
    issuer,
    authorization_endpoint: `${issuer}/authorize`,
    token_endpoint: `${issuer}/token`,
    jwks_uri: `${origin}/azure/jwks`,
    response_types_supported: ['code'],
    subject_types_supported: ['public'],
    id_token_signing_alg_values_supported: ['RS256'],
    token_endpoint_auth_methods_supported: ['client_secret_basic', 'client_secret_post'],
    scopes_supported: ['openid', 'profile', 'email', 'offline_access'],
    code_challenge_methods_supported: ['S256'],
  };
}

/**
 * OIDC discovery document for the mock Google provider (OLO-10.13).
 *
 * The app points Google at this mock via `GOOGLE_ISSUER` (`google-workspace-domain.ts`), which drives
 * the discovery URL both on the NextAuth path and the Better Auth generic-OAuth path. The `issuer`
 * here and the id_token `iss` (set in `exchangeCode`) must equal `${origin}/google`. Endpoints and the
 * signing machinery are reused from the shared authorize/token/jwks helpers — Google uses the same
 * code + PKCE(S256) flow the Azure provider already exercises.
 */
function googleDiscovery(origin) {
  const issuer = `${origin}/google`;
  return {
    issuer,
    authorization_endpoint: `${issuer}/o/oauth2/v2/auth`,
    token_endpoint: `${issuer}/token`,
    jwks_uri: `${origin}/azure/jwks`,
    response_types_supported: ['code'],
    subject_types_supported: ['public'],
    id_token_signing_alg_values_supported: ['RS256'],
    token_endpoint_auth_methods_supported: ['client_secret_basic', 'client_secret_post'],
    scopes_supported: ['openid', 'profile', 'email'],
    code_challenge_methods_supported: ['S256'],
  };
}

const server = createServer(async (req, res) => {
  const url = new URL(req.url, `http://localhost:${PORT}`);
  const path = url.pathname;
  const origin = `http://localhost:${PORT}`;

  try {
    // ── Control API ────────────────────────────────────────────────────────────────
    if (path === '/__mock__/health') {
      sendJson(res, 200, { ok: true });
      return;
    }
    if (path === '/__mock__/persona' && req.method === 'POST') {
      const body = await readBody(req);
      currentPersona = { ...defaultPersona(), ...body };
      sendJson(res, 200, { persona: currentPersona });
      return;
    }

    // ── GitHub ─────────────────────────────────────────────────────────────────────
    if (path === '/github/login/oauth/authorize') {
      handleAuthorize(url, res);
      return;
    }
    if (path === '/github/login/oauth/access_token' && req.method === 'POST') {
      const tokens = exchangeCode(await readBody(req), null, null);
      if (!tokens) return sendJson(res, 400, { error: 'bad_verification_code' });
      sendJson(res, 200, tokens);
      return;
    }
    if (path === '/github/api/user') {
      const persona = personaForToken(req);
      if (!persona) return sendJson(res, 401, { message: 'Bad credentials' });
      sendJson(res, 200, githubProfile(persona));
      return;
    }
    if (path === '/github/api/user/emails') {
      const persona = personaForToken(req);
      if (!persona) return sendJson(res, 401, { message: 'Bad credentials' });
      sendJson(res, 200, [
        { email: persona.email, primary: true, verified: persona.verified, visibility: 'public' },
      ]);
      return;
    }

    // ── GitLab ─────────────────────────────────────────────────────────────────────
    if (path === '/gitlab/oauth/authorize') {
      handleAuthorize(url, res);
      return;
    }
    if (path === '/gitlab/oauth/token' && req.method === 'POST') {
      const tokens = exchangeCode(await readBody(req), null, null);
      if (!tokens) return sendJson(res, 400, { error: 'invalid_grant' });
      sendJson(res, 200, tokens);
      return;
    }
    if (path === '/gitlab/api/v4/user') {
      const persona = personaForToken(req);
      if (!persona) return sendJson(res, 401, { message: '401 Unauthorized' });
      sendJson(res, 200, gitlabProfile(persona));
      return;
    }

    // ── Azure (Entra ID, OIDC) ─────────────────────────────────────────────────────
    const azureMatch = path.match(/^\/azure\/([^/]+)\/v2\.0(\/.*)?$/);
    if (path === '/azure/jwks') {
      sendJson(res, 200, jwks());
      return;
    }
    if (azureMatch) {
      const [, tenant, rest = ''] = azureMatch;
      if (rest === '/.well-known/openid-configuration') {
        sendJson(res, 200, azureDiscovery(origin, tenant));
        return;
      }
      if (rest === '/authorize') {
        handleAuthorize(url, res);
        return;
      }
      if (rest === '/token' && req.method === 'POST') {
        const body = await readBody(req);
        // client_secret_basic puts the client id in the Authorization header; fall back
        // to the form body (client_secret_post).
        const basic = (req.headers.authorization || '').replace(/^basic\s+/i, '');
        const basicId = basic
          ? decodeURIComponent(Buffer.from(basic, 'base64').toString('utf8').split(':')[0] ?? '')
          : '';
        const clientId = basicId || body.client_id || '';
        const issuer = `${origin}/azure/${tenant}/v2.0`;
        const tokens = exchangeCode(body, issuer, clientId);
        if (!tokens) return sendJson(res, 400, { error: 'invalid_grant' });
        sendJson(res, 200, tokens);
        return;
      }
    }

    // ── Google (OIDC) ──────────────────────────────────────────────────────────────
    // Reuses the shared authorize/token/jwks helpers (Google uses the same authorization-code + PKCE
    // S256 flow). The id_token carries `sub`/`email`/`email_verified`, which Google's normalizer reads
    // (`better-auth-oauth-providers.ts` normalizeGoogle / `google-provider.ts`).
    if (path === '/google/.well-known/openid-configuration') {
      sendJson(res, 200, googleDiscovery(origin));
      return;
    }
    if (path === '/google/o/oauth2/v2/auth') {
      handleAuthorize(url, res);
      return;
    }
    if (path === '/google/token' && req.method === 'POST') {
      const body = await readBody(req);
      // client_secret_basic carries the client id in the Authorization header; fall back to the form
      // body (client_secret_post) — identical to the Azure token handler.
      const basic = (req.headers.authorization || '').replace(/^basic\s+/i, '');
      const basicId = basic
        ? decodeURIComponent(Buffer.from(basic, 'base64').toString('utf8').split(':')[0] ?? '')
        : '';
      const clientId = basicId || body.client_id || '';
      const tokens = exchangeCode(body, `${origin}/google`, clientId);
      if (!tokens) return sendJson(res, 400, { error: 'invalid_grant' });
      sendJson(res, 200, tokens);
      return;
    }

    sendJson(res, 404, { error: 'not_found', path });
  } catch (error) {
    sendJson(res, 500, { error: 'mock_oauth_internal', message: String(error) });
  }
});

server.listen(PORT, () => {
  console.log(`[mock-oauth] listening on http://localhost:${PORT}`);
});
