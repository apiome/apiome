/**
 * Per-request NextAuth handler wiring contract (OLO-8.6, #4972).
 *
 * Standing up the full NextAuth stack for the `[...nextauth]` route is heavy (see the sibling
 * `auth-rate-limit-contract.test.ts`), so — matching that convention — these assert the source-level
 * contract the epic depends on: the handler is a function of the request that rebuilds the options
 * (and thus the provider set) per invocation via the DB-over-env resolver, the credentials provider
 * and callbacks are shared through a single factory so the static and per-request builds cannot drift,
 * and the widely-imported `authOptions` export is preserved for `getServerSession`. The provider-
 * resolution behaviour itself is covered by `tests/nextauth-per-request-providers.test.ts`.
 */
import * as fs from 'fs';
import * as path from 'path';

const NEXTAUTH_ROUTE = path.resolve(
  __dirname,
  '..',
  '..',
  'src',
  'app',
  'api',
  'auth',
  '[...nextauth]',
  'route.ts'
);

const src = fs.readFileSync(NEXTAUTH_ROUTE, 'utf8');

describe('[...nextauth] route — per-request provider resolution', () => {
  it('builds the handler as a function of the request, not once at module load', () => {
    // The v4 App Router per-request form: NextAuth(req, ctx, options). The legacy
    // module-load form `NextAuth(authOptions)` must be gone.
    expect(src).toMatch(/async function handler\(\s*req: NextRequest,\s*ctx: RouteHandlerContext\s*\)/);
    expect(src).toMatch(/return NextAuth\(req, ctx, await buildRequestAuthOptions\(\)\)/);
    expect(src).not.toMatch(/NextAuth\(authOptions\)/);
  });

  it('resolves the per-request OAuth providers from the DB-over-env merge (8.5)', () => {
    expect(src).toMatch(/resolveOAuthProviders/);
    expect(src).toMatch(/makeAuthOptions\(await resolveOAuthProviders\(\)\)/);
  });

  it('shares one factory so the static and per-request builds cannot drift', () => {
    expect(src).toMatch(/function makeAuthOptions\(oauthProviders: Provider\[\]\): NextAuthOptions/);
    // Both entry points flow through the same factory.
    expect(src).toMatch(/makeAuthOptions\(configuredOAuthProviders\(\)\)/);
    expect(src).toMatch(/makeAuthOptions\(await resolveOAuthProviders\(\)\)/);
  });

  it('keeps the credentials provider and its IP-scoped authorize intact', () => {
    expect(src).toMatch(/CredentialsProvider\(/);
    expect(src).toMatch(/resolveClientIp\(req\?\.headers\)/);
    expect(src).toMatch(/credentialsAuthorize\(credentialPayload as ICredentials, clientIp\)/);
  });

  it('preserves the widely-imported authOptions export for getServerSession consumers', () => {
    expect(src).toMatch(/export const authOptions: NextAuthOptions = makeAuthOptions\(/);
  });

  it('still exports the handler as both GET and POST', () => {
    expect(src).toMatch(/export \{ handler as GET, handler as POST \}/);
  });
});
