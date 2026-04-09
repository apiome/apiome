import NextAuth from 'next-auth';
import CredentialsProvider from 'next-auth/providers/credentials';
import GithubProvider from 'next-auth/providers/github';
import GitlabProvider from 'next-auth/providers/gitlab';
import { NextAuthOptions } from 'next-auth';
import {
  credentialsAuthorize,
  credentialsSignIn,
  credentialsGithub,
  credentialsGitlab,
  linkGithubAccount,
  linkGitlabAccount,
  checkLinkingIntent,
  ICredentials,
} from '../../../../../lib/auth/credentials';

export const authOptions: NextAuthOptions = {
  providers: [
    GithubProvider({
      clientId: process.env.GITHUB_ID as string,
      clientSecret: process.env.GITHUB_SECRET as string,
    }),
    GitlabProvider({
      clientId: process.env.GITLAB_CLIENT_ID as string,
      clientSecret: process.env.GITLAB_CLIENT_SECRET as string,
    }),
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

      if (loginProvider === 'github') {
        // Check if this is an account linking flow
        const linkIntent = await checkLinkingIntent();

        if (linkIntent && linkIntent.provider === 'github') {
          // Link the GitHub account to the current user
          const account = payload.account;
          const profile = payload.profile || user;

          const linked = await linkGithubAccount(linkIntent.userId, account, profile);

          if (linked) {
            return '/ade/dashboard/linked-accounts?linked=true';
          } else {
            return '/ade/dashboard/linked-accounts?error=Failed to link account. It may already be linked to another user.';
          }
        }

        const gh = await credentialsGithub(payload);
        return gh;
      }

      if (loginProvider === 'gitlab') {
        // Check if this is an account linking flow
        const linkIntent = await checkLinkingIntent();

        if (linkIntent && linkIntent.provider === 'gitlab') {
          // Link the GitLab account to the current user
          const account = payload.account;
          const profile = payload.profile || user;

          const linked = await linkGitlabAccount(linkIntent.userId, account, profile);

          if (linked) {
            return '/ade/dashboard/linked-accounts?linked=true';
          } else {
            return '/ade/dashboard/linked-accounts?error=Failed to link account. It may already be linked to another user.';
          }
        }

        const gl = await credentialsGitlab(payload);
        return gl;
      }

      return `/login?error=Your login attempt failed, provider "${loginProvider}" is not yet supported`;
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
        const pendingTenant = (payload.user as { pending_tenant_id?: string }).pending_tenant_id;
        if (pendingTenant) {
          token.current_tenant_id = pendingTenant;
        }
      }

      return token;
    },
  }
};

const handler = NextAuth(authOptions);

export { handler as GET, handler as POST };
