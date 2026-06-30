'use client';

/**
 * `<ProtocolPill>` (MFI-23.5, #4014) — the pill showing a catalog item's protocol / paradigm.
 *
 * Resolves the raw `protocol` (the canonical `ApiParadigm`: REST / RPC / event / graph /
 * data-schema / agent) through the catalog format registry to an icon + tint + label. An unknown
 * but present protocol degrades to a neutral pill showing the raw token; an absent protocol renders
 * nothing.
 *
 * Used on the Catalog card (MFI-23.4) and the detail view (MFI-23.9).
 */

import * as React from 'react';
import { Workflow, type LucideIcon } from 'lucide-react';
import { cn } from '../../../../../lib/utils';
import {
  resolveCatalogProtocol,
  CATALOG_PILL_TONE_CLASS,
} from '../../../utils/catalog-format-registry';

export interface ProtocolPillProps extends React.HTMLAttributes<HTMLSpanElement> {
  /** The raw `protocol` / paradigm string off the catalog item. */
  protocol: string | null | undefined;
}

const PILL_BASE =
  'inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-medium';

/**
 * Render the protocol pill, or `null` when no protocol is present. A recognised protocol gets its
 * registry icon/colour/label; an unrecognised non-empty protocol gets a neutral pill showing the
 * raw string verbatim.
 */
export const ProtocolPill = React.forwardRef<HTMLSpanElement, ProtocolPillProps>(
  ({ protocol, className, ...props }, ref) => {
    if (!protocol || !protocol.trim()) return null;

    const entry = resolveCatalogProtocol(protocol);
    const Icon: LucideIcon = entry?.icon ?? Workflow;
    const tone = entry ? CATALOG_PILL_TONE_CLASS[entry.tone] : CATALOG_PILL_TONE_CLASS.neutral;
    const label = entry?.label ?? protocol.trim();

    return (
      <span
        ref={ref}
        className={cn(PILL_BASE, tone, className)}
        title={`Protocol: ${label}`}
        data-testid="protocol-pill"
        {...props}
      >
        <Icon className="h-3 w-3" aria-hidden />
        {label}
      </span>
    );
  },
);
ProtocolPill.displayName = 'ProtocolPill';
