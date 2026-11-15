/**
 * `/portal/auth/exchange?tenant=<slug>&token=<token>` — where a magic link lands, PCX-1.1 (#5889).
 *
 * Opening the link does **not** sign in by itself: the page asks the reader to press
 * **Continue**, which posts the token to `/portal/auth/session`. Mail scanners and link previews
 * fetch links with `GET`; if a `GET` burned the one-time token, the reader's own click would then be
 * refused as "already used".
 */

import type { Metadata } from 'next';

import { getPublicTenantBySlug } from '../../../../../lib/db/helper';
import { isTenantSlug, portalPath } from '../../../../../lib/portal/session';
import { withBasePath } from '../../readerSession';
import { redirect } from 'next/navigation';

export const dynamic = 'force-dynamic';

export const metadata: Metadata = {
  title: 'Finish signing in · Apiome Browse',
  description: 'Finish signing in to an API portal.',
  referrer: 'no-referrer',
};

type RawParams = Record<string, string | string[] | undefined>;

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export default async function ExchangePage({ searchParams }: { searchParams: Promise<RawParams> }) {
  const params = await searchParams;
  const tenant = first(params.tenant);
  const token = first(params.token);
  if (!isTenantSlug(tenant) || !token) {
    redirect(portalPath('/portal/auth/error', { tenant: isTenantSlug(tenant) ? tenant : null, reason: 'invalid' }));
  }
  const row = await getPublicTenantBySlug(tenant);
  const tenantName: string = row?.name ?? tenant;

  return (
    <div className="portal-page">
      <section className="portal-card" data-testid="reader-exchange">
        <p className="portal-eyebrow">{tenantName}</p>
        <h1 className="portal-title">Finish signing in</h1>
        <p className="portal-body">
          Continue to sign in to the <strong>{tenantName}</strong> portal in this browser.
        </p>
        <form className="portal-form" method="post" action={withBasePath('/portal/auth/session')}>
          <input type="hidden" name="tenant" value={tenant} />
          <input type="hidden" name="token" value={token} />
          <button className="portal-button" type="submit">
            Continue
          </button>
        </form>
      </section>
    </div>
  );
}
