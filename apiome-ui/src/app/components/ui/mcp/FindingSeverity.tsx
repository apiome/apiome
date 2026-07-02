'use client';

import * as React from 'react';
import { cn } from '../../../../../lib/utils';
import { Badge } from '../Badge';
import {
  MCP_LINT_SEVERITY_TIER,
  mcpLintTierMeta,
  type McpLintTier,
} from '../../ade/dashboard/mcp/mcpLintUi';
import { MCP_LINT_TIER_LABEL } from '../../ade/dashboard/mcp/mcpUiPrimitives';

export interface FindingSeverityProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Requirement tier. Provide this OR {@link severity} (this wins when both are given). */
  tier?: McpLintTier;
  /** Raw finding severity (`error` → MUST, `warning` → SHOULD, `info` → advisory). */
  severity?: string;
  /** Append the finding count after the label (e.g. `MUST 3`). */
  count?: number;
}

/** Resolve the effective tier from an explicit tier or a raw severity (defaults to advisory). */
function resolveTier(tier?: McpLintTier, severity?: string): McpLintTier {
  if (tier) return tier;
  if (severity) return MCP_LINT_SEVERITY_TIER[severity] ?? 'advisory';
  return 'advisory';
}

/**
 * `<FindingSeverity>` — the shared MUST / SHOULD / Advisory chip used by the Lint & Score tab and by
 * inline hints. It renders the tier label through the project {@link Badge} primitive in the tier's
 * variant (MUST → error/red, SHOULD → warning/amber, Advisory → secondary/slate), reading both the
 * label and the variant from the single source of truth in `mcpLintUi` / `mcpUiPrimitives` so the
 * styling never drifts between surfaces.
 */
export const FindingSeverity = React.forwardRef<HTMLDivElement, FindingSeverityProps>(
  ({ tier, severity, count, className, ...props }, ref) => {
    const effective = resolveTier(tier, severity);
    const meta = mcpLintTierMeta(effective);
    const label = MCP_LINT_TIER_LABEL[effective];
    return (
      <Badge
        ref={ref}
        variant={meta.badgeVariant}
        className={cn('gap-1', className)}
        title={meta.description}
        {...props}
      >
        {label}
        {typeof count === 'number' ? <span className="tabular-nums">{count}</span> : null}
      </Badge>
    );
  },
);
FindingSeverity.displayName = 'FindingSeverity';
