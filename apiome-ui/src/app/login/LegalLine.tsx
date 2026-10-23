import * as React from 'react';

import type { LegalLinks } from '@lib/auth/signup-page';

/** Props for {@link LegalLine}. */
export interface LegalLineProps {
  /** What the reader agrees by doing, e.g. `signing in` or `creating an account`. */
  action: string;
  /** The installation's legal pages (`legalLinksFromEnv`). */
  links: LegalLinks;
}

/**
 * "By signing in, you agree to our Terms of Service and Privacy Policy" — with only the links
 * the installation has. Neither page ships with Apiome, so the URLs come from
 * `APIOME_TERMS_URL` / `APIOME_PRIVACY_URL`; with neither set the line is left out rather than
 * drawn with links that go nowhere.
 *
 * @param props See {@link LegalLineProps}.
 * @returns The line, or `null`.
 */
export function LegalLine({ action, links }: LegalLineProps) {
  const { termsUrl, privacyUrl } = links;
  if (!termsUrl && !privacyUrl) return null;
  const terms = termsUrl ? (
    <a href={termsUrl} className="auth-link">
      Terms of Service
    </a>
  ) : null;
  const privacy = privacyUrl ? (
    <a href={privacyUrl} className="auth-link">
      Privacy Policy
    </a>
  ) : null;
  return (
    <p className="auth-terms mt-4" data-testid="legal-line">
      By {action}, you agree to our {terms}
      {terms && privacy ? ' and ' : null}
      {privacy}
    </p>
  );
}

export default LegalLine;
