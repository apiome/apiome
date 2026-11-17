/**
 * The product-lifecycle notice on an API's changelog — APX-1.4 (#6101).
 *
 * One block per portal product that includes the API and is deprecated or has a deprecated plan:
 * the product's own deprecation, then each deprecated plan with its retirement date and the plan to
 * move to. Server-rendered; the words come from `lib/products/lifecycle.ts`.
 */

import Link from 'next/link';
import { productHref } from '../../../lib/products/portalProducts';
import { planSentence, productSentence, type LifecycleNotice } from '../../../lib/products/lifecycle';

/**
 * Render the notices, or nothing when there are none.
 *
 * @param props - The tenant (for the product links) and the notices.
 * @returns The notice section.
 */
export function ProductLifecycleNotice({ tenantSlug, notices }: { tenantSlug: string; notices: LifecycleNotice[] }) {
  if (notices.length === 0) return null;
  return (
    <section aria-labelledby="product-lifecycle-title" className="product-lifecycle" data-testid="product-lifecycle">
      <h2 id="product-lifecycle-title" className="product-section-title">
        Plan and product changes
      </h2>
      {notices.map((notice) => {
        const own = productSentence(notice);
        return (
          <div key={notice.productSlug} className="product-lifecycle-item">
            <p>
              This API is part of{' '}
              <Link href={productHref(tenantSlug, notice.productSlug)} className="product-lifecycle-link">
                {notice.productName}
              </Link>
              .{own ? ` ${own}` : ''}
            </p>
            {notice.message ? <p className="product-section-hint">{notice.message}</p> : null}
            {notice.plans.length > 0 ? (
              <ul className="product-lifecycle-plans">
                {notice.plans.map((plan) => (
                  <li key={plan.slug}>
                    {planSentence(plan)}
                    {plan.message ? <span className="product-section-hint"> {plan.message}</span> : null}
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        );
      })}
    </section>
  );
}
