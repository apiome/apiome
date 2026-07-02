'use client';

import { useMemo, useState } from 'react';
import Link from 'next/link';
import { AppShell } from '../../../components/AppShell';
import type { McpCapabilityItem, McpPublicEndpointDetail } from '../../../../../lib/types';
import { GradeBadge, TransportBadge } from '../../McpShared';

type ItemType = McpCapabilityItem['item_type'];

const TAB_ORDER: ItemType[] = ['tool', 'resource', 'resource_template', 'prompt'];
const TAB_LABELS: Record<ItemType, string> = {
  tool: 'Tools',
  resource: 'Resources',
  resource_template: 'Resource Templates',
  prompt: 'Prompts',
};

function formatDate(value: Date | null): string | null {
  if (!value) return null;
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
}

/**
 * Public MCP endpoint detail (MCAT-9.6): the grade/score/transport/host header and the endpoint's
 * current-snapshot capabilities split into tabs (tools / resources / resource templates / prompts).
 */
export function McpEndpointDetailClient({ detail }: { detail: McpPublicEndpointDetail }) {
  const { endpoint, items } = detail;

  const byType = useMemo(() => {
    const map: Record<ItemType, McpCapabilityItem[]> = {
      tool: [],
      resource: [],
      resource_template: [],
      prompt: [],
    };
    for (const item of items) map[item.item_type].push(item);
    return map;
  }, [items]);

  const availableTabs = TAB_ORDER.filter((t) => byType[t].length > 0);
  const [activeTab, setActiveTab] = useState<ItemType | null>(availableTabs[0] ?? null);
  const lastDiscovered = formatDate(endpoint.last_discovered_at);

  return (
    <AppShell containerSize="wide">
      <nav className="py-4 text-xs text-zinc-500 dark:text-zinc-400">
        <Link href="/mcp" className="hover:text-zinc-900 dark:hover:text-zinc-200">
          MCP Catalog
        </Link>
        <span className="px-1.5">/</span>
        <span className="text-zinc-700 dark:text-zinc-300">{endpoint.host ?? 'Unknown host'}</span>
      </nav>

      <header className="border-b border-zinc-200 pb-6 dark:border-zinc-800">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h1 className="text-2xl font-bold tracking-tight text-zinc-900 dark:text-zinc-50">
              {endpoint.name}
            </h1>
            <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">{endpoint.host ?? 'Unknown host'}</p>
          </div>
          <div className="flex items-center gap-2">
            <GradeBadge grade={endpoint.grade} score={endpoint.score} />
            <TransportBadge transport={endpoint.transport} />
          </div>
        </div>
        {endpoint.description && (
          <p className="mt-3 max-w-3xl text-sm text-zinc-600 dark:text-zinc-300">{endpoint.description}</p>
        )}
        <dl className="mt-4 flex flex-wrap gap-x-6 gap-y-2 text-[11px] text-zinc-500 dark:text-zinc-400">
          {endpoint.category && (
            <div>
              <dt className="inline font-medium text-zinc-600 dark:text-zinc-300">Category: </dt>
              <dd className="inline">{endpoint.category}</dd>
            </div>
          )}
          <div>
            <dt className="inline font-medium text-zinc-600 dark:text-zinc-300">Capabilities: </dt>
            <dd className="inline">
              {endpoint.tool_count} tools · {endpoint.resource_count} resources ·{' '}
              {endpoint.resource_template_count} templates · {endpoint.prompt_count} prompts
            </dd>
          </div>
          {lastDiscovered && (
            <div>
              <dt className="inline font-medium text-zinc-600 dark:text-zinc-300">Last discovered: </dt>
              <dd className="inline">{lastDiscovered}</dd>
            </div>
          )}
        </dl>
      </header>

      {availableTabs.length === 0 ? (
        <div className="my-10 rounded-xl border border-dashed border-zinc-300 bg-white/50 p-10 text-center dark:border-zinc-700 dark:bg-zinc-900/40">
          <p className="text-sm text-zinc-600 dark:text-zinc-400">
            No capabilities have been discovered for this server yet.
          </p>
        </div>
      ) : (
        <div className="py-6">
          <div className="mb-4 flex flex-wrap gap-1 border-b border-zinc-200 dark:border-zinc-800">
            {availableTabs.map((tab) => (
              <button
                key={tab}
                type="button"
                onClick={() => setActiveTab(tab)}
                className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium transition-colors ${
                  activeTab === tab
                    ? 'border-[var(--brand)] text-[var(--brand)]'
                    : 'border-transparent text-zinc-500 hover:text-zinc-800 dark:text-zinc-400 dark:hover:text-zinc-200'
                }`}
              >
                {TAB_LABELS[tab]}
                <span className="ml-1.5 rounded-full bg-zinc-100 px-1.5 py-0.5 text-[10px] text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
                  {byType[tab].length}
                </span>
              </button>
            ))}
          </div>

          <ul className="flex flex-col gap-2">
            {(activeTab ? byType[activeTab] : []).map((item) => (
              <li
                key={item.id}
                className="rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900"
              >
                <div className="flex items-baseline gap-2">
                  <h3 className="font-mono text-sm font-semibold text-zinc-900 dark:text-zinc-50">{item.name}</h3>
                  {item.title && (
                    <span className="truncate text-xs text-zinc-500 dark:text-zinc-400">{item.title}</span>
                  )}
                </div>
                {item.description && (
                  <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-300">{item.description}</p>
                )}
                {(item.uri || item.uri_template) && (
                  <p className="mt-1 truncate font-mono text-[11px] text-zinc-500 dark:text-zinc-400">
                    {item.uri ?? item.uri_template}
                  </p>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </AppShell>
  );
}
