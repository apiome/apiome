/**
 * `/tenant/<tenant>/products/<product>` — an API product's portal page, APX-1.3 (#6100).
 *
 * What a consumer may ask for, on which terms, and how: the product's summary, its member APIs
 * (each linking to the version page it resolves to), and one card per plan — how a consumer
 * authenticates, the limits it promises, whether a person approves — with a **Request access**
 * action. The page renders without sign-in; requesting needs a reader session (PCX-1.1).
 *
 * Only a `portal` product that is published or deprecated is found here; a draft, retired, private
 * or workspace product is a 404, exactly like a product that does not exist.
 */

import type { Metadata } from 'next';
import Link from 'next/link';
import { notFound } from 'next/navigation';

import { loadProductPage } from '../../../../../../lib/db/routeLoaders';
import {
  approvalLabel,
  authStrategyLabel,
  formatLimit,
  memberKindLabel,
  productHref,
  type PortalMember,
  type PortalPlan,
} from '../../../../../../lib/products/portalProducts';
import { relativeTime } from '../../../../../../lib/relativeTime';
import { AppShell } from '../../../../components/AppShell';
import { Breadcrumb } from '../../../../components/Breadcrumb';
import { EntityHeader } from '../../../../components/EntityHeader';
import { ReaderStatus } from '../../../../components/ReaderStatus';
import { PactBadges } from '../../[projectSlug]/PactBadges';
import { RequestAccess } from '../../../../components/RequestAccess';
import { getReaderSession } from '../../../../portal/readerSession';

export const dynamic = 'force-dynamic';

/** One product read per request, shared by the metadata and the page (`cache()` in the loader). */
const loadProduct = loadProductPage;

interface ProductPageParams {
  params: Promise<{ tenantSlug: string; productSlug: string }>;
}

export async function generateMetadata({ params }: ProductPageParams): Promise<Metadata> {
  const { tenantSlug, productSlug } = await params;
  const product = await loadProduct(tenantSlug, productSlug);
  if (!product) return { title: 'Product not found · Apiome Browse' };
  return {
    title: `${product.name} · ${product.tenantName} · Apiome Browse`,
    description: product.summary ?? `The ${product.name} API product and its plans.`,
  };
}

export default async function ProductPage({ params }: ProductPageParams) {
  const { tenantSlug, productSlug } = await params;
  const product = await loadProduct(tenantSlug, productSlug);
  if (!product) notFound();

  const session = await getReaderSession(tenantSlug);
  const returnTo = productHref(tenantSlug, product.slug);
  const apiCount = product.members.filter((m) => m.kind !== 'mcp_server').length;

  return (
    <AppShell containerSize="wide">
      <div className="space-y-8 py-8" data-testid="product-page">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <Breadcrumb
            items={[
              { label: product.tenantName, href: `/tenant/${tenantSlug}` },
              { label: 'Products', href: `/tenant/${tenantSlug}#products` },
              { label: product.name },
            ]}
          />
          <ReaderStatus tenantSlug={tenantSlug} returnTo={returnTo} />
        </div>

        <EntityHeader
          variant="product"
          title={product.name}
          subtitle={`/${tenantSlug}/products/${product.slug}`}
          description={product.summary ?? undefined}
          badges={
            product.state === 'deprecated' ? (
              <span className="product-badge product-badge-warning">Deprecated</span>
            ) : (
              <span className="product-badge">API product</span>
            )
          }
          meta={[
            { label: 'APIs', value: apiCount },
            { label: 'Plans', value: product.plans.length },
            { label: 'Owner', value: product.ownerTeam ?? '—' },
            { label: 'Last updated', value: relativeTime(product.updatedAt) ?? '—' },
          ]}
        />

        <section className="space-y-3" aria-labelledby="product-members-heading">
          <h2 id="product-members-heading" className="product-section-title">
            What&apos;s included
          </h2>
          {product.members.length === 0 ? (
            <p className="product-empty">This product does not list any APIs yet.</p>
          ) : (
            <ul className="product-members" data-testid="product-members">
              {product.members.map((member, index) => (
                <MemberRow key={`${member.kind}:${member.name}:${index}`} member={member} tenantSlug={tenantSlug} />
              ))}
            </ul>
          )}
        </section>

        <section className="space-y-3" aria-labelledby="product-plans-heading">
          <div>
            <h2 id="product-plans-heading" className="product-section-title">
              Plans
            </h2>
            <p className="product-section-hint">
              Each plan says how you authenticate, the limits it promises and how a request is approved.
            </p>
          </div>
          {product.plans.length === 0 ? (
            <p className="product-empty">No plans are offered for this product yet.</p>
          ) : (
            <ul className="product-plans" data-testid="product-plans">
              {product.plans.map((plan) => (
                <li key={plan.slug}>
                  <PlanCard plan={plan} tenantSlug={tenantSlug} returnTo={returnTo} signedIn={Boolean(session)} />
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </AppShell>
  );
}

/**
 * One member: its kind, its name (linked when a reader can open it) and the version it resolves to;
 * a project member also shows its public pact badges and consumer count (PFX-7.5, #6965).
 */
function MemberRow({ member, tenantSlug }: { member: PortalMember; tenantSlug: string }) {
  const version = member.versionLabel
    ? `v${member.versionLabel}`
    : member.kind === 'project_latest' || member.kind === 'project_version'
      ? 'No public version yet'
      : null;
  return (
    <li className="product-member" data-testid="product-member">
      <span className="product-member-kind">{memberKindLabel(member.kind)}</span>
      {member.href ? (
        <Link className="product-member-name product-member-link" href={member.href}>
          {member.name}
        </Link>
      ) : (
        <span className="product-member-name">{member.name}</span>
      )}
      <span className="product-member-meta">
        {[version, member.versionSelector ? `tracks ${member.versionSelector}` : null, member.environment]
          .filter(Boolean)
          .join(' · ')}
      </span>
      {member.projectSlug ? (
        <div className="product-member-pacts">
          <PactBadges tenantSlug={tenantSlug} projectSlug={member.projectSlug} compact />
        </div>
      ) : null}
    </li>
  );
}

interface PlanCardProps {
  plan: PortalPlan;
  tenantSlug: string;
  returnTo: string;
  signedIn: boolean;
}

/** One plan card: authentication, limits, approval and terms, with the Request access action. */
function PlanCard({ plan, tenantSlug, returnTo, signedIn }: PlanCardProps) {
  const headingId = `plan-${plan.slug}-name`;
  return (
    <article className="product-plan" aria-labelledby={headingId} data-testid="product-plan">
      <header className="product-plan-header">
        <h3 id={headingId} className="product-plan-name">
          {plan.name}
        </h3>
        {plan.state === 'deprecated' && <span className="product-badge product-badge-warning">Deprecated</span>}
      </header>
      {plan.description && <p className="product-plan-description">{plan.description}</p>}

      <dl className="product-plan-facts">
        <div>
          <dt>Authentication</dt>
          <dd>
            {authStrategyLabel(plan.authStrategy)}
            {plan.headerName && (
              <>
                {' '}in the <code>{plan.headerName}</code> header
              </>
            )}
            {plan.scopes.length > 0 && (
              <span className="product-plan-scopes">
                Scopes:{' '}
                {plan.scopes.map((scope) => (
                  <code key={scope}>{scope}</code>
                ))}
              </span>
            )}
          </dd>
        </div>
        <div>
          <dt>Limits</dt>
          <dd>
            {plan.limits.length === 0 ? (
              'No declared limits'
            ) : (
              <ul className="product-plan-limits">
                {plan.limits.map((limit) => (
                  <li key={limit.window}>{formatLimit(limit)}</li>
                ))}
              </ul>
            )}
            {plan.concurrency && <span className="product-plan-scopes">Up to {plan.concurrency} requests in flight</span>}
          </dd>
        </div>
        <div>
          <dt>Approval</dt>
          <dd>{approvalLabel(plan.approval)}</dd>
        </div>
        {plan.credentialTtlDays && (
          <div>
            <dt>Key lifetime</dt>
            <dd>
              {plan.credentialTtlDays} {plan.credentialTtlDays === 1 ? 'day' : 'days'}
            </dd>
          </div>
        )}
        {plan.pricingNote && (
          <div>
            <dt>Pricing</dt>
            <dd>{plan.pricingNote}</dd>
          </div>
        )}
      </dl>

      <footer className="product-plan-footer">
        <RequestAccess
          tenantSlug={tenantSlug}
          returnTo={returnTo}
          planSlug={plan.slug}
          planName={plan.name}
          signedIn={signedIn}
        />
        {plan.termsUrl && (
          <a className="portal-link" href={plan.termsUrl} target="_blank" rel="noopener noreferrer">
            Terms<span className="sr-only"> for the {plan.name} plan (opens in a new tab)</span>
          </a>
        )}
      </footer>
    </article>
  );
}
