import NextAuth from 'next-auth';
import CredentialsProvider from 'next-auth/providers/credentials';
import { NextAuthOptions } from 'next-auth';
import {
  credentialsAuthorize,
  signInForProvider,
  ICredentials,
} from '../../../../../lib/auth/credentials';
import {
  buildAuthCookieOverrides,
  canonicalizeCrossAppCallback,
  isAllowedCallbackUrl,
} from '../../../../../lib/auth/cookie-options';
import { configuredOAuthProviders } from '../../../../../lib/auth/nextauth-oauth-providers';
import { resolveActiveTenantForLogin } from '../../../../../lib/auth/post-login-routing';

export const authOptions: NextAuthOptions = {
  secret: process.env.NEXTAUTH_SECRET,
  // Scope session cookies to NEXTAUTH_COOKIE_DOMAIN so subdomain apps
  // (e.g. the studio) can share the login session.
  ...buildAuthCookieOverrides(),
  providers: [
    // Every OAuth provider comes from the provider registry (OLO-2.3): a provider is
    // registered only when its env vars are configured, so disabling one via env removes
    // its sign-in route along with its login/link buttons. Email trust is decided by the
    // resolution engine inside signInForProvider (OLO-1.3/1.4), not here.
    ...configuredOAuthProviders(),
    CredentialsProvider({
      credentials: {},
      async authorize(credentials: any, req) {
        const credentialPayload = JSON.parse(credentials?.payload ?? '{}');
        return await credentialsAuthorize(credentialPayload as ICredentials);
      }
    })
  ],
  pages: {
    signIn: '/login',
    error: '/login',
  },
  callbacks: {
    signIn: async function (payload: any) {
      const user = payload.user;
      const loginProvider = payload.account?.provider ?? '';

      if (!user) {
        return '/login?error=User account not found';
      }

      // Credentials sign-ins run the account gates; every OAuth provider flows through the shared
      // account-resolution engine (OLO-1.3); an unconfigured provider is refused with the stable
      // `provider-not-configured` code (OLO-1.5).
      return signInForProvider(loginProvider, payload);
    },
    async redirect({ url, baseUrl }) {
      // Default NextAuth behaviour only allows same-origin callback URLs.
      // Also allow subdomains covered by the shared session cookie so login
      // can return to e.g. the studio app.
      if (url.startsWith('/') && !url.startsWith('//')) {
        return `${baseUrl}${url}`;
      }
      const canonical = canonicalizeCrossAppCallback(url);
      if (isAllowedCallbackUrl(canonical, baseUrl)) {
        return canonical;
      }
      return baseUrl;
    },
    // async redirect({ url, baseUrl }) {
    //     // Override the login, redirecting to the login page if properly set.
    //     if (url === '/login') {
    //         return baseUrl + '/login';
    //     }
    //
    //     // This flow moves to the tenants page after login succeeds.
    //     if (url === '/tenants') {
    //         return baseUrl + '/tenants';
    //     }
    //
    //     return baseUrl;
    // },
    async session(payload: any) {
      if (payload.token?.user_id) {
        payload.session.user.user_id = payload.token.user_id;
      }

      if (payload.token?.current_tenant_id) {
        payload.session.user.current_tenant_id = payload.token.current_tenant_id;
      }

      if (payload.token?.name) {
        payload.session.user.name = payload.token.name;
      }

      return payload.session;
    },
    async jwt(payload: any) {
      const token = payload.token;

      // If the trigger is "update", this indicates that the session payload has changed,
      // and the token should be updated accordingly.
      if (payload.trigger === 'update') {
        if (payload.session?.user?.name) {
          token.name = payload.session.user.name;
        }

        if (payload.session?.current_tenant_id) {
          token.current_tenant_id = payload.session.current_tenant_id;
        }
      }

      if (payload.user) {
        token.user_id = payload.user.id;
        // Seed the session's active tenant per the post-login routing rules
        // (OLO-3.3): prefer the signup one-time-code tenant, keep the previous
        // session's tenant when still a membership, else fall back to the user's
        // default tenant. Tenant-less users carry no current_tenant_id and meet
        // the first-tenant onboarding guard instead.
        const pendingTenant = (payload.user as { pending_tenant_id?: string }).pending_tenant_id;
        const activeTenant = await resolveActiveTenantForLogin(
          payload.user.id,
          pendingTenant ?? token.current_tenant_id
        );
        if (activeTenant) {
          token.current_tenant_id = activeTenant;
        } else {
          delete token.current_tenant_id;
        }
      }

      return token;
    },
  }
};

const handler = NextAuth(authOptions);

export { handler as GET, handler as POST };
