'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import { emailDomainForSso } from '@lib/workspace-sso';

/**
 * Email-first sign-in routing (EID-1.2, #5012).
 *
 * While the reader types their email, ask whether its domain signs in through a workspace's
 * identity provider (`POST /api/login/sso-domain`). Only a **verified** domain of an **enabled**
 * provider answers yes; the page then offers "Continue with SSO" in place of the password.
 *
 * Each domain is asked about once per page view. A failed lookup counts as "no": the password
 * path stays, and "Sign in with SSO" still works for anyone who needs it.
 */

/** How long typing must pause before a domain is looked up. */
export const SSO_LOOKUP_DEBOUNCE_MS = 300;

/** The lookup route. */
export const SSO_DOMAIN_LOOKUP_URL = '/api/login/sso-domain';

/**
 * Ask the server whether an address signs in with SSO.
 *
 * @param email The address.
 * @returns Whether a routable provider covers its domain; false on any failure.
 */
async function lookUp(email: string): Promise<boolean> {
  try {
    const response = await fetch(SSO_DOMAIN_LOOKUP_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email }),
      cache: 'no-store',
    });
    if (!response.ok) return false;
    const body = (await response.json()) as { sso?: unknown };
    return body?.sso === true;
  } catch {
    return false;
  }
}

/** What {@link useSsoEmailRouting} returns. */
export interface SsoEmailRouting {
  /** Whether the email typed so far signs in with SSO. False until a lookup says so. */
  routed: boolean;
  /**
   * Answer for an address now, without waiting for the debounce — used on submit, so a fast
   * typist is not sent down the password path before the lookup lands.
   */
  resolve: (email: string) => Promise<boolean>;
}

/**
 * Track whether the email in a sign-in field routes to SSO.
 *
 * @param email The field's current value.
 * @param enabled Whether any workspace identity provider is routable at all; when false nothing
 *   is ever looked up.
 * @returns See {@link SsoEmailRouting}.
 */
export function useSsoEmailRouting(email: string, enabled: boolean): SsoEmailRouting {
  // domain -> answer, for this page view.
  const known = useRef(new Map<string, boolean>());
  const [answers, setAnswers] = useState<Record<string, boolean>>({});
  const domain = enabled ? emailDomainForSso(email) : null;

  const resolve = useCallback(
    async (address: string): Promise<boolean> => {
      const target = enabled ? emailDomainForSso(address) : null;
      if (!target) return false;
      const cached = known.current.get(target);
      if (cached !== undefined) return cached;
      const answer = await lookUp(address.trim());
      known.current.set(target, answer);
      setAnswers((current) => ({ ...current, [target]: answer }));
      return answer;
    },
    [enabled],
  );

  useEffect(() => {
    if (!domain || known.current.has(domain)) return undefined;
    const timer = setTimeout(() => void resolve(email), SSO_LOOKUP_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [domain, email, resolve]);

  return { routed: Boolean(domain && answers[domain]), resolve };
}
