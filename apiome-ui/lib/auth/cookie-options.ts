const DEFAULT_LOGIN_LANDING = '/ade';

const TRUSTED_URL_ENVS = [
  'NEXTAUTH_URL',
  'NEXT_PUBLIC_STUDIO_URL',
  'NEXT_PUBLIC_MAIN_APP_URL',
] as const;

function registrableDomain(hostname: string): string | null {
  if (!hostname || hostname === 'localhost' || hostname === '127.0.0.1') {
    return null;
  }
  const parts = hostname.split('.').filter(Boolean);
  if (parts.length < 2) return null;
  return parts.slice(-2).join('.');
}

function normalizeCookieDomain(domain: string): string {
  const trimmed = domain.trim();
  return trimmed.startsWith('.') ? trimmed : `.${trimmed}`;
}

/** Origins of the main app, studio, and NextAuth base — always trusted callback targets. */
export function trustedAppOrigins(): Set<string> {
  const origins = new Set<string>();
  for (const key of TRUSTED_URL_ENVS) {
    const raw = process.env[key]?.trim();
    if (!raw) continue;
    try {
      origins.add(new URL(raw).origin);
    } catch {
      // ignore malformed env
    }
  }
  return origins;
}

function inferCookieDomain(): string | undefined {
  if (process.env.NODE_ENV !== 'production') return undefined;
  for (const key of TRUSTED_URL_ENVS) {
    const raw = process.env[key]?.trim();
    if (!raw) continue;
    try {
      const domain = registrableDomain(new URL(raw).hostname);
      if (domain) return normalizeCookieDomain(domain);
    } catch {
      // ignore malformed env
    }
  }
  return undefined;
}

/** Parent domain for shared session cookies, or undefined on localhost / dev. */
export function getSharedCookieDomain(): string | undefined {
  const configured = process.env.NEXTAUTH_COOKIE_DOMAIN?.trim();
  if (configured) {
    if (process.env.NODE_ENV !== 'production') return undefined;
    return normalizeCookieDomain(configured);
  }
  return inferCookieDomain();
}

/**
 * Cookie overrides for NextAuth when sharing sessions across subdomains
 * (e.g. app + studio on *.apiome.dev). Must mirror the studio's
 * private-suite/suite/designer/lib/auth/cookie-options.ts so both apps
 * read and write the same cookies.
 */
export function buildAuthCookieOverrides() {
  const cookieDomain = getSharedCookieDomain();
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

function hostnameMatchesCookieDomain(hostname: string, cookieDomain: string): boolean {
  const suffix = normalizeCookieDomain(cookieDomain);
  const bare = suffix.slice(1);
  return hostname === bare || hostname.endsWith(suffix);
}

/**
 * A login callback URL may leave this origin only for hosts covered by the
 * shared session cookie (e.g. suite.apiome.dev when the cookie domain is
 * .apiome.dev) or configured app URLs — anything else is an open-redirect vector.
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
      // Malformed baseUrl — fall through.
    }
  }

  if (trustedAppOrigins().has(target.origin)) {
    return process.env.NODE_ENV !== 'production' || target.protocol === 'https:';
  }

  if (process.env.NODE_ENV !== 'production') {
    return target.hostname === 'localhost' || target.hostname === '127.0.0.1';
  }

  if (target.protocol !== 'https:') return false;

  const cookieDomain = getSharedCookieDomain();
  if (!cookieDomain) return false;
  return hostnameMatchesCookieDomain(target.hostname, cookieDomain);
}

/** Validated callback URL for the login flow, or the default landing page. */
export function resolveCallbackUrl(url: string | undefined | null, baseUrl?: string): string {
  const trimmed = url?.trim();
  if (!trimmed) return DEFAULT_LOGIN_LANDING;
  return isAllowedCallbackUrl(trimmed, baseUrl ?? process.env.NEXTAUTH_URL)
    ? trimmed
    : DEFAULT_LOGIN_LANDING;
}
