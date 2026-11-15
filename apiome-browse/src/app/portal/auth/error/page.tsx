/**
 * `/portal/auth/error?tenant=<slug>&reason=expired|used|invalid` — a sign-in link that could not be
 * used, PCX-1.1 (#5889). Names the reason and offers a new link; never a silent redirect.
 */

import type { Metadata } from 'next';
import Link from 'next/link';

import { isTenantSlug, parseRefusal, portalPath, REFUSAL_COPY } from '../../../../../lib/portal/session';

export const dynamic = 'force-dynamic';

export const metadata: Metadata = {
  title: 'Sign-in link problem · Apiome Browse',
  description: 'A sign-in link could not be used.',
};

type RawParams = Record<string, string | string[] | undefined>;

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export default async function SignInErrorPage({ searchParams }: { searchParams: Promise<RawParams> }) {
  const params = await searchParams;
  const tenant = first(params.tenant);
  const reason = parseRefusal(first(params.reason));
  const copy = REFUSAL_COPY[reason];

  return (
    <div className="portal-page">
      <section className="portal-card" data-testid="reader-sign-in-error" data-reason={reason}>
        <p className="portal-eyebrow">Reader sign-in</p>
        <h1 className="portal-title">{copy.title}</h1>
        <p className="portal-body">{copy.body}</p>
        <div className="portal-form">
          {isTenantSlug(tenant) ? (
            <Link className="portal-button" href={portalPath('/portal/sign-in', { tenant })}>
              Send a new link
            </Link>
          ) : (
            <Link className="portal-button" href="/">
              Back to Discover
            </Link>
          )}
        </div>
      </section>
    </div>
  );
}
