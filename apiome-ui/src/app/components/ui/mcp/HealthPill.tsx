'use client';

import * as React from 'react';
import { cn } from '../../../../../lib/utils';
import {
  mcpHealthFromDiscoveryStatus,
  mcpHealthMeta,
  type McpHealthStatus,
} from '../../ade/dashboard/mcp/mcpUiPrimitives';

export interface HealthPillProps extends React.HTMLAttributes<HTMLSpanElement> {
  /** Explicit health state. Provide this OR {@link discoveryStatus} (this wins when both given). */
  status?: McpHealthStatus;
  /** Raw discovery status to derive the health state from (e.g. `ok` / `degraded` / `failed`). */
  discoveryStatus?: string | null;
  /** Hide the text label, leaving just the colored status dot (e.g. in dense table cells). */
  dotOnly?: boolean;
}

/**
 * `<HealthPill>` — an endpoint's reachability as a colored dot + label: `Healthy` (green),
 * `Degraded` (amber), `Unreachable` (red), or `Unknown` (slate) before the first discovery. Pass an
 * explicit {@link HealthPillProps.status}, or a raw {@link HealthPillProps.discoveryStatus} to have
 * it resolved. All colors come from {@link mcpHealthMeta} — no literals in consumers.
 */
export const HealthPill = React.forwardRef<HTMLSpanElement, HealthPillProps>(
  ({ status, discoveryStatus, dotOnly = false, className, ...props }, ref) => {
    const resolved: McpHealthStatus = status ?? mcpHealthFromDiscoveryStatus(discoveryStatus);
    const meta = mcpHealthMeta(resolved);
    return (
      <span
        ref={ref}
        className={cn('inline-flex items-center gap-1.5 text-xs font-medium', meta.textClass, className)}
        title={dotOnly ? meta.label : undefined}
        {...props}
      >
        <span className={cn('inline-block h-2 w-2 shrink-0 rounded-full', meta.dotClass)} aria-hidden />
        {dotOnly ? <span className="sr-only">{meta.label}</span> : meta.label}
      </span>
    );
  },
);
HealthPill.displayName = 'HealthPill';
