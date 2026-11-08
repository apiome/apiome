'use client';

/**
 * The Done step of an MCP registry import (AAU-5.4, #5725).
 *
 * Shows what the connector's first sync did: how many servers the registry listed, how many were
 * added and graded, and each server left "discovered" with the reason (it only ships packages, its
 * remote needs a `{variable}`, resolves to a private address, or did not answer). Links go to the MCP
 * catalog and to the connector that keeps them in sync.
 */

import * as React from 'react';
import Link from 'next/link';
import { AlertTriangle, ArrowRight, CheckCircle2 } from 'lucide-react';

import { Button } from '@/app/components/ui/Button';
import { EmptyState } from '@/app/components/ui/EmptyState';
import {
  splitDiscoveredReason,
  type RegistryImportSummary,
} from '../dashboard/mcp/mcpRegistryImport';

export interface McpRegistryImportDonePanelProps {
  /** The connector the import registered. */
  connectorId: string;
  /** What its first sync did. */
  summary: RegistryImportSummary;
  /** Called before navigating away, so the dialog can settle its own state. */
  onNavigate: () => void;
}

/** "3 servers" / "1 server". */
function servers(n: number): string {
  return `${n} server${n === 1 ? '' : 's'}`;
}

/**
 * The headline sentence for a summary.
 *
 * @param summary - The run summary.
 * @returns The title and description the panel shows.
 */
export function registryImportHeadline(summary: RegistryImportSummary): { title: string; description: string } {
  if (summary.imported === 0) {
    return {
      title: summary.listed === 0 ? 'The registry listed no servers' : 'No servers could be added yet',
      description:
        summary.listed === 0
          ? 'Nothing matched. Check the search, or leave it empty to import every server the registry lists.'
          : `The registry listed ${servers(summary.listed)}, but none has a remote Apiome can reach. Each one is listed below with the reason.`,
    };
  }
  const left = summary.discovered + summary.failed;
  return {
    title: `${servers(summary.imported)} imported from the registry`,
    description:
      `The registry listed ${servers(summary.listed)}. ${servers(summary.imported)} ${summary.imported === 1 ? 'was' : 'were'} ` +
      'added to MCP Servers, discovered and graded' +
      (left ? `; ${servers(left)} could not be added yet (below).` : '.'),
  };
}

export function McpRegistryImportDonePanel({ connectorId, summary, onNavigate }: McpRegistryImportDonePanelProps) {
  const { title, description } = registryImportHeadline(summary);
  return (
    <div className="flex flex-col gap-4" data-testid="mcp-registry-done">
      <EmptyState
        tone={summary.imported > 0 ? 'honey' : 'danger'}
        icon={summary.imported > 0 ? <CheckCircle2 /> : <AlertTriangle />}
        title={title}
        description={description}
        action={
          <div className="flex flex-wrap items-center justify-center gap-4">
            <Button asChild variant="link" size="sm">
              <Link href="/ade/dashboard/mcp" onClick={onNavigate}>
                View MCP servers
                <ArrowRight className="size-[var(--icon-dense)]" aria-hidden />
              </Link>
            </Button>
            <Button asChild variant="link" size="sm">
              <Link href={`/ade/dashboard/connectors/${encodeURIComponent(connectorId)}`} onClick={onNavigate}>
                Open the connector
                <ArrowRight className="size-[var(--icon-dense)]" aria-hidden />
              </Link>
            </Button>
          </div>
        }
      />
      {summary.discoveredEntries.length > 0 ? (
        <section aria-labelledby="mcp-registry-discovered-heading" className="flex flex-col gap-2">
          <h4 id="mcp-registry-discovered-heading" className="text-sm font-semibold text-fg">
            Not added yet
          </h4>
          <ul className="flex flex-col divide-y divide-border rounded-md border border-border">
            {summary.discoveredEntries.map((entry) => {
              const { code, detail } = splitDiscoveredReason(entry.reason);
              return (
                <li key={entry.remoteId} className="flex flex-col gap-0.5 px-3 py-2 text-sm">
                  <span className="font-mono text-fg">{entry.remoteId}</span>
                  <span className="text-xs text-fg-muted">
                    {code ? <code className="me-1">{code}</code> : null}
                    {detail}
                  </span>
                </li>
              );
            })}
          </ul>
        </section>
      ) : null}
    </div>
  );
}

export default McpRegistryImportDonePanel;
