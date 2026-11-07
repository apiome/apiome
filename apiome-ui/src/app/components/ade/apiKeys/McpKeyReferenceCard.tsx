'use client';

import * as React from 'react';
import { Check, Copy, Plug, SlidersHorizontal } from 'lucide-react';

import { Button } from '@/app/components/ui/Button';
import { useClipboardCopy } from '@/app/hooks/useClipboardCopy';

/**
 * The two reference cards under the MCP keys table.
 *
 * The MCP tab's counterpart of {@link ./ApiKeyReferenceCards}: *how do I point a host at the
 * server with this key*, and *what may the key call* — the second answered with where the
 * workspace's MCP settings and per-key capabilities are edited, because that editor needs the
 * workspace's tool ceiling and lives with it.
 */

/** Props for {@link McpKeyReferenceCard}. */
export interface McpKeyReferenceCardProps {
  /** The tenant's name, for the sentence about what a key runs as. */
  tenantName: string;
  /** Where the workspace's manage drawer is opened from. */
  workspacesHref: string;
}

/** The host settings the "Connect a host" card shows. */
const EXAMPLE_HOST_CONFIG = `URL:     https://mcp.apiome.dev/mcp
Header:  Authorization: Bearer <your-mcp-key>`;

/**
 * The two cards.
 *
 * @param props See {@link McpKeyReferenceCardProps}.
 * @returns The reference section.
 */
export default function McpKeyReferenceCard({ tenantName, workspacesHref }: McpKeyReferenceCardProps) {
  const { copied, copy } = useClipboardCopy();

  return (
    <section className="akey-reference" data-testid="mcp-keys-reference">
      <article className="akey-ref-card">
        <header className="akey-ref-card__header">
          <h2 className="akey-ref-card__title">
            <Plug aria-hidden />
            Connect a host
          </h2>
          <span className="akey-ref-card__note">Streamable HTTP, bearer token</span>
        </header>
        <div className="akey-ref-card__body">
          <div className="akey-code-wrap">
            <pre className="akey-code mono" data-testid="mcp-keys-example-config">
              <code>{EXAMPLE_HOST_CONFIG}</code>
            </pre>
            <Button
              variant="outline"
              size="sm"
              className="akey-code-copy"
              aria-label={copied ? 'Copied the host settings' : 'Copy the host settings'}
              onClick={() => void copy(EXAMPLE_HOST_CONFIG)}
            >
              {copied ? <Check aria-hidden /> : <Copy aria-hidden />}
              {copied ? 'Copied!' : 'Copy'}
            </Button>
          </div>
          <p className="akey-ref-card__desc">
            Calls run as <strong>{tenantName}</strong> and can read its private published specs.
            Leave the header out to read public specs only. REST keys are not accepted here.
          </p>
        </div>
      </article>

      <article className="akey-ref-card">
        <header className="akey-ref-card__header">
          <h2 className="akey-ref-card__title">
            <SlidersHorizontal aria-hidden />
            What a key may call
          </h2>
        </header>
        <div className="akey-ref-card__body">
          <p className="akey-ref-card__desc">
            A new key calls the workspace&apos;s default MCP tools —{' '}
            <strong>Workspace defaults</strong> in the table. Change the defaults under <strong>MCP settings</strong>, or give one key its own set
            under <strong>Per-key capabilities</strong> — both in the workspace&apos;s manage drawer.
          </p>
          <p className="akey-ref-card__desc">
            In Workspaces, click <strong>Manage</strong> on {tenantName}&apos;s row.
          </p>
          <div>
            <Button variant="outline" size="sm" asChild>
              <a href={workspacesHref} data-testid="mcp-keys-workspaces-link">
                Open Workspaces
              </a>
            </Button>
          </div>
        </div>
      </article>
    </section>
  );
}
