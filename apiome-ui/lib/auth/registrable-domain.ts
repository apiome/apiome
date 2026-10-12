/**
 * Registrable-domain lookup backed by the Public Suffix List (OLO-7.3 follow-up, #4961).
 *
 * The *registrable domain* (eTLD+1) of a host is the part someone can actually register: the
 * public suffix plus one label — `apiome.dev` for `suite.apiome.dev`, `example.co.uk` for
 * `app.example.co.uk`. Two hosts under the same registrable domain belong to one owner; two hosts
 * that merely share a public suffix (`a.vercel.app` and `b.vercel.app`) do not.
 *
 * That boundary cannot be computed by counting labels. Taking "the last two labels" turns
 * `apiome.vercel.app` into `vercel.app`, which every other customer of that platform also sits
 * under — so a trust decision or a cookie `Domain` derived that way spans strangers. The Public
 * Suffix List is the registry of where the boundary really is, and `tldts` ships a copy of it.
 *
 * The **private** section of the list is honoured as well as the ICANN one: hosting platforms
 * (`vercel.app`, `pages.dev`, `github.io`, …) are listed there precisely because each subdomain
 * belongs to a different tenant.
 */

import { getDomain } from 'tldts';

/**
 * Return the registrable domain (eTLD+1) of a hostname.
 *
 * @param hostname A bare hostname (no scheme, port or path), in any case.
 * @returns The registrable domain in lower case, or `null` when the host has none: an empty
 *   value, `localhost` or any other single-label host, an IP address, or a host that *is* a
 *   public suffix (`co.uk`, `vercel.app`). A suffix that is not on the list — an internal name
 *   such as `apiome.corp` — falls back to its last label, so `app.apiome.corp` yields
 *   `apiome.corp`.
 */
export function registrableDomain(hostname: string): string | null {
  const host = hostname?.trim().toLowerCase().replace(/\.$/, '');
  if (!host || host === 'localhost') return null;
  return getDomain(host, { allowPrivateDomains: true });
}
