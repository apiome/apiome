'use client';

/**
 * `<FormatPill>` (MFI-23.5, #4014) — the pill showing a catalog item's imported file format.
 *
 * Resolves the raw `sourceFormat` (e.g. `openapi-3.1`, `grpc`) through the catalog format registry
 * to an icon + tint + label. Per the acceptance criteria, an **unknown but present** format degrades
 * to a neutral pill that shows the raw token (so nothing is ever silently dropped), and an
 * **absent** format renders nothing.
 *
 * Used on the Catalog card (MFI-23.4) and the detail view (MFI-23.9).
 */

import * as React from 'react';
import { FileCode2, type LucideIcon } from 'lucide-react';
import { cn } from '../../../../../lib/utils';
import {
  resolveCatalogFormat,
  CATALOG_PILL_TONE_CLASS,
} from '../../../utils/catalog-format-registry';

export interface FormatPillProps extends React.HTMLAttributes<HTMLSpanElement> {
  /** The raw `sourceFormat` string off the catalog item. */
  format: string | null | undefined;
}

const PILL_BASE =
  'inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-medium';

/**
 * Render the format pill, or `null` when no format is present. A recognised format gets its
 * registry icon/colour/label; an unrecognised non-empty format gets a neutral pill showing the
 * raw string verbatim.
 */
export const FormatPill = React.forwardRef<HTMLSpanElement, FormatPillProps>(
  ({ format, className, ...props }, ref) => {
    if (!format || !format.trim()) return null;

    const entry = resolveCatalogFormat(format);
    const Icon: LucideIcon = entry?.icon ?? FileCode2;
    const tone = entry ? CATALOG_PILL_TONE_CLASS[entry.tone] : CATALOG_PILL_TONE_CLASS.neutral;
    const label = entry?.label ?? format.trim();

    return (
      <span
        ref={ref}
        className={cn(PILL_BASE, tone, className)}
        title={`Format: ${label}`}
        data-testid="format-pill"
        {...props}
      >
        <Icon className="h-3 w-3" aria-hidden />
        {label}
      </span>
    );
  },
);
FormatPill.displayName = 'FormatPill';
