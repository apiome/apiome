'use client';

/**
 * The first-visit "catalog items are non-publishable" explainer (MFI-24.3; re-skinned
 * HIVE-7.1, #5318; made dismissible HIVE-11.6, #5602).
 *
 * Authority: `docs/mockups/proposals/catalog-quiet.html` annotation 4. Until HIVE-11.6 this was
 * a standing `role="note"` banner above the list — the one sentence that explains why the
 * screen exists beside Projects at all, but ≈ 75 px every visit for a fact that is learnt
 * once. It is now a {@link DismissibleCallout}: shown on a reader's first visit with
 * **Learn more** (opens "How the catalog works") and **Got it**, which hides it on this device
 * under `hive.seen.catalog-explainer`.
 *
 * Dismissing never hides information: the same three points live in `CatalogAboutDialog`,
 * reached from the page header's "How the catalog works" link and from the Import wizard's
 * step 1 — which is what `reopenFrom` states.
 *
 * The copy is the banner's, verbatim, because the mockup's Keeps (1:1) list quotes it.
 */

import * as React from 'react';
import Link from 'next/link';

import { DismissibleCallout } from '@/app/components/ui/DismissibleCallout';

/** The `hive.seen.<id>` the dismissal is stored under. */
export const CATALOG_EXPLAINER_ID = 'catalog-explainer';

/** Props for {@link CatalogExplainerCallout}. */
export interface CatalogExplainerCalloutProps {
  /** Opens the "How the catalog works" dialog. */
  onLearnMore: () => void;
}

/**
 * Render the callout, or nothing once the reader has dismissed it on this device.
 *
 * @param props See {@link CatalogExplainerCalloutProps}.
 * @returns The callout.
 */
export function CatalogExplainerCallout({ onLearnMore }: CatalogExplainerCalloutProps) {
  return (
    // No wrapper element: once dismissed this renders nothing at all, so it must not leave an
    // empty box behind to take a gap in the page body's stack.
    <DismissibleCallout
      id={CATALOG_EXPLAINER_ID}
      reopenFrom="How the catalog works (page header) and Import step 1"
      onLearnMore={onLearnMore}
    >
      <strong>Catalog items are non-publishable.</strong> They come from formats that don&apos;t
      map 1:1 to OpenAPI (gRPC, GraphQL, AsyncAPI, OData, WSDL, Avro, RAML, Smithy, TypeSpec,
      API&nbsp;Blueprint…). They are cataloged, versioned, diffed &amp; linted like Projects — but
      the only path to a publishable spec is <strong>Convert&nbsp;to&nbsp;OpenAPI</strong> (with a
      fidelity preview). OpenAPI/Swagger imports still land in{' '}
      <Link href="/ade/dashboard/projects" className="cat-note__link">
        Projects
      </Link>
      .
    </DismissibleCallout>
  );
}

export default CatalogExplainerCallout;
