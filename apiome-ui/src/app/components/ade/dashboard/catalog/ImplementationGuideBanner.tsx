'use client';

/**
 * `<ImplementationGuideBanner>` (FMT-6.10, #5454) — the shared "no implementation guide was
 * consulted" banner for the EDI and vertical-messaging family: X12, EDIFACT, TRADACOMS, IDoc,
 * SWIFT MT, HL7 v3 / CDA, NACHA, DICOM, NCPDP and FIX Orchestra.
 *
 * A green import of any of these formats means the document was *structurally readable*. Without
 * this banner a reader will reasonably infer it was *conformant*. The banner renders the reviewed
 * {@link ImplementationGuideStatement} from the format's capability entry — the syntax read, the
 * guides not consulted, and the claims recorded as the sender's — in one vocabulary for the whole
 * family. It renders nothing for a format with no statement.
 *
 * Purely presentational: the caller resolves the entry (see `implementationGuideFor`).
 */

import * as React from 'react';
import { ShieldQuestion } from 'lucide-react';
import { cn } from '@lib/utils';
import {
  implementationGuideFor,
  type FormatCapability,
} from './formatCapabilityRegistry';

export interface ImplementationGuideBannerProps {
  /** The format's capability entry; the banner renders only when it carries a reviewed statement. */
  capability: FormatCapability | null | undefined;
  className?: string;
}

/**
 * Render the format's implementation-guide statement, or nothing.
 *
 * @param props - See {@link ImplementationGuideBannerProps}.
 * @returns The banner, or `null` for a format outside the family.
 */
export function ImplementationGuideBanner({ capability, className }: ImplementationGuideBannerProps) {
  const guide = implementationGuideFor(capability);
  if (!guide || !capability) return null;
  return (
    <section
      role="note"
      aria-label={`${capability.label}: no implementation guide was consulted`}
      data-testid="catalog-implementation-guide-banner"
      data-format={capability.format}
      className={cn(
        'flex items-start gap-2 rounded-lg border border-accent bg-accent-soft px-3 py-2 text-xs text-accent-fg',
        className,
      )}
    >
      <ShieldQuestion className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
      <div className="min-w-0 space-y-1">
        <p className="font-semibold">No implementation guide was consulted</p>
        <p data-testid="catalog-implementation-guide-statement" className="leading-snug">
          {guide.statement}
        </p>
        <p className="leading-snug">
          <span className="font-medium">Not consulted: </span>
          <span data-testid="catalog-implementation-guide-not-consulted">
            {guide.guides_not_consulted.join(' · ')}
          </span>
        </p>
        {guide.claims_recorded.length > 0 ? (
          <p className="leading-snug">
            <span className="font-medium">Recorded as the sender’s claim: </span>
            <span data-testid="catalog-implementation-guide-claims">
              {guide.claims_recorded.join(' · ')}
            </span>
          </p>
        ) : null}
      </div>
    </section>
  );
}

export default ImplementationGuideBanner;
