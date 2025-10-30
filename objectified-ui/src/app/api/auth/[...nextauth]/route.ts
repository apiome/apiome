import NextAuth from 'next-auth';
import CredentialsProvider from 'next-auth/providers/credentials';
import { NextAuthOptions } from 'next-auth';
import { credentialsAuthorize, credentialsSignIn, ICredentials } from '../../../../../lib/auth/credentials';

export const authOptions: NextAuthOptions = {
  providers: [
  // GithubProvider({
  //     clientId: process.env.GITHUB_ID as string,
  //     clientSecret: process.env.GITHUB_SECRET as string,
  // }),
  // GitlabProvider({
  //     clientId: process.env.GITLAB_CLIENT_ID as string,
  //     clientSecret: process.env.GITLAB_CLIENT_SECRET as string,
  // }),
  // GoogleProvider({
  //     clientId: process.env.GOOGLE_CLIENT_ID as string,
  //     clientSecret: process.env.GOOGLE_CLIENT_SECRET as string,
  // }),
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

      // Handle different types of login providers here.
      if (loginProvider === 'credentials') {
        return credentialsSignIn(payload);
      }

      console.log('[signIn] unsupported provider:', loginProvider, 'user:', user, 'payload:', payload);

      return `/login?error=Your login attempt failed, provider "${loginProvider}" is not yet supported`;
    },
    // async redirect({ url, baseUrl }) {
    //     console.log(`[next-auth::redirect]: url=${JSON.stringify(url)} baseUrl=${JSON.stringify(baseUrl)}`);
    //
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

      console.log('Token', payload);

      return payload.session;
    },
    async jwt(payload: any) {
      const token = payload.token;

      console.log('[JWT] JWT:', payload);

      if (payload.user) {
        token.user_id = payload.user.id;
      }

      if (payload.session) {
        console.log('[JWT] Adjusting session:', payload.session);
        token.current_tenant_id = payload.session.current_tenant_id;
      }

      return token;
    },
  }
};

const handler = NextAuth(authOptions);

export { handler as GET, handler as POST };
