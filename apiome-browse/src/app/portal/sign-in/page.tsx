/**
 * `/portal/sign-in?tenant=<slug>` — reader sign-in, PCX-1.1 (#5889).
 *
 * Two states: the email form, and — after a request was accepted (`sent=1`) — **Check your email**.
 * The form posts to apiome-rest from the browser ({@link SignInForm}); this page never learns whether
 * a link was actually sent, and neither does the reader, so the page cannot be used to discover
 * accounts.
 */

import type { Metadata } from 'next';
import Link from 'next/link';

import { getPublicTenantBySlug } from '../../../../lib/db/helper';
import { isTenantSlug, portalPath, safeReturnTo } from '../../../../lib/portal/session';
import { SignInForm } from './SignInForm';

export const dynamic = 'force-dynamic';

export const metadata: Metadata = {
  title: 'Sign in · Apiome Browse',
  description: 'Sign in to read an API portal.',
};

type RawParams = Record<string, string | string[] | undefined>;

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export default async function ReaderSignInPage({ searchParams }: { searchParams: Promise<RawParams> }) {
  const params = await searchParams;
  const tenant = first(params.tenant);
  const sent = first(params.sent) === '1';

  if (!isTenantSlug(tenant)) {
    return (
      <div className="portal-page">
        <section className="portal-card" data-testid="reader-sign-in-no-tenant">
          <p className="portal-eyebrow">Reader sign-in</p>
          <h1 className="portal-title">Choose a portal first</h1>
          <p className="portal-body">
            Readers sign in to one organization&apos;s API portal at a time. Open the organization&apos;s page and
            choose <strong>Sign in</strong> there.
          </p>
          <p className="portal-fineprint">
            <Link className="portal-link" href="/">
              Back to Discover
            </Link>
          </p>
        </section>
      </div>
    );
  }

  const returnTo = safeReturnTo(first(params.return_to), `/tenant/${tenant}`);
  const row = await getPublicTenantBySlug(tenant);
  const tenantName: string = row?.name ?? tenant;

  if (sent) {
    return (
      <div className="portal-page">
        <section className="portal-card" data-testid="reader-magic-link-sent" aria-live="polite">
          <p className="portal-eyebrow">{tenantName}</p>
          <h1 className="portal-title">Check your email</h1>
          <p className="portal-body">
            If that address can read the <strong>{tenantName}</strong> portal, a sign-in link is on its way. The link
            works once and expires in 15 minutes.
          </p>
          <p className="portal-fineprint">
            No email after a few minutes? Check your spam folder, or{' '}
            <Link className="portal-link" href={portalPath('/portal/sign-in', { tenant, return_to: returnTo })}>
              send another link
            </Link>
            .
          </p>
        </section>
      </div>
    );
  }

  return (
    <div className="portal-page">
      <section className="portal-card" data-testid="reader-sign-in">
        <p className="portal-eyebrow">{tenantName}</p>
        <h1 className="portal-title">Sign in to read the {tenantName} APIs</h1>
        <p className="portal-body">Enter your email address and we&apos;ll send you a link that signs you in. No password needed.</p>
        <SignInForm
          tenantSlug={tenant}
          returnTo={returnTo}
          restBase={process.env.NEXT_PUBLIC_REST_API_BASE_URL || 'http://localhost:8000/v1'}
        />
        <p className="portal-fineprint">
          Building APIs in Apiome? <a className="portal-link" href="https://app.apiome.dev/">Sign in to the workspace</a>{' '}
          instead.
        </p>
      </section>
    </div>
  );
}
