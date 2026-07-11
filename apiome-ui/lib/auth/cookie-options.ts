const DEFAULT_LOGIN_LANDING = '/ade';

function resolveCookieDomain(): string | undefined {
  const configured = process.env.NEXTAUTH_COOKIE_DOMAIN?.trim();
  if (!configured) return undefined;
  // Localhost cannot use production cookie domains (e.g. .apiome.app).
  if (process.env.NODE_ENV !== 'production') return undefined;
  return configured;
}

/**
 * Cookie overrides for NextAuth when sharing sessions across subdomains
 * (e.g. app + studio on *.apiome.app). Must mirror the studio's
 * private-suite/suite/designer/lib/auth/cookie-options.ts so both apps
 * read and write the same cookies.
 */
export function buildAuthCookieOverrides() {
  const cookieDomain = resolveCookieDomain();
  const sharedCookieOptions = {
    httpOnly: true,
    sameSite: 'lax' as const,
    path: '/',
    secure: process.env.NODE_ENV === 'production',
    ...(cookieDomain ? { domain: cookieDomain } : {}),
  };

  return {
    cookies: {
      sessionToken: {
        name:
          process.env.NODE_ENV === 'production'
            ? '__Secure-next-auth.session-token'
            : 'next-auth.session-token',
        options: sharedCookieOptions,
      },
      callbackUrl: {
        name:
          process.env.NODE_ENV === 'production'
            ? '__Secure-next-auth.callback-url'
            : 'next-auth.callback-url',
        options: sharedCookieOptions,
      },
      csrfToken: {
        name:
          process.env.NODE_ENV === 'production'
            ? '__Host-next-auth.csrf-token'
            : 'next-auth.csrf-token',
        options: {
          httpOnly: true,
          sameSite: 'lax' as const,
          path: '/',
          secure: process.env.NODE_ENV === 'production',
        },
      },
    },
  };
}

/**
 * A login callback URL may leave this origin only for hosts covered by the
 * shared session cookie (e.g. studio.apiome.app when NEXTAUTH_COOKIE_DOMAIN
 * is .apiome.app) — anything else is an open-redirect vector.
 */
export function isAllowedCallbackUrl(url: string, baseUrl?: string): boolean {
  if (url.startsWith('/')) return !url.startsWith('//');

  let target: URL;
  try {
    target = new URL(url);
  } catch {
    return false;
  }

  if (baseUrl) {
    try {
      if (target.origin === new URL(baseUrl).origin) return true;
    } catch {
      // Malformed baseUrl — fall through to the cookie-domain check.
    }
  }

  if (process.env.NODE_ENV !== 'production') {
    return target.hostname === 'localhost' || target.hostname === '127.0.0.1';
  }

  const cookieDomain = resolveCookieDomain();
  if (!cookieDomain || target.protocol !== 'https:') return false;
  const suffix = cookieDomain.startsWith('.') ? cookieDomain : `.${cookieDomain}`;
  return target.hostname === suffix.slice(1) || target.hostname.endsWith(suffix);
}

/** Validated callback URL for the login flow, or the default landing page. */
export function resolveCallbackUrl(url: string | undefined | null, baseUrl?: string): string {
  const trimmed = url?.trim();
  if (!trimmed) return DEFAULT_LOGIN_LANDING;
  return isAllowedCallbackUrl(trimmed, baseUrl ?? process.env.NEXTAUTH_URL)
    ? trimmed
    : DEFAULT_LOGIN_LANDING;
}
