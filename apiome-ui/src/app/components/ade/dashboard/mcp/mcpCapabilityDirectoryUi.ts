/**
 * Capability directory — types and pure helpers (V2-MCP-35.4 / MCAT-21.4, #4663).
 *
 * The **Capability Directory** page lists every tool/resource/prompt across the tenant catalog with
 * owning-server links. This module holds wire types and adapters kept free of React for unit tests.
 */

import type { McpBadgeVariant } from './mcpBrowseUi';

export type McpCapabilityDirectoryKind = 'tool' | 'resource' | 'resource_template' | 'prompt';

export type McpCapabilityDirectorySort = 'server' | 'name' | 'type';

export interface McpCapabilityDirectoryEntry {
  kind: McpCapabilityDirectoryKind;
  itemId: string;
  itemName: string;
  itemTitle: string | null;
  description: string | null;
  endpointId: string;
  endpointName: string;
  endpointSlug: string;
  host: string;
  endpointUrl: string;
  category: string | null;
  visibility: string;
  currentVersionId: string | null;
  score: number | null;
  grade: string | null;
}

export interface McpCapabilityDirectoryFilters {
  name: string;
  type: McpCapabilityDirectoryKind | '';
  endpointId: string;
  host: string;
  visibility: '' | 'private' | 'public';
}

export interface McpCapabilityDirectoryPage {
  items: McpCapabilityDirectoryEntry[];
  total: number;
  limit: number;
  offset: number;
}

export const MCP_CAPABILITY_DIRECTORY_DEFAULT_FILTERS: McpCapabilityDirectoryFilters = {
  name: '',
  type: '',
  endpointId: '',
  host: '',
  visibility: '',
};

export const MCP_CAPABILITY_DIRECTORY_PAGE_SIZE = 50;

export const MCP_CAPABILITY_DIRECTORY_KINDS: McpCapabilityDirectoryKind[] = [
  'tool',
  'resource',
  'resource_template',
  'prompt',
];

export const MCP_CAPABILITY_DIRECTORY_SORTS: Array<{
  key: McpCapabilityDirectorySort;
  label: string;
}> = [
  { key: 'server', label: 'Server' },
  { key: 'name', label: 'Name' },
  { key: 'type', label: 'Type' },
];

function asString(value: unknown): string | null {
  return typeof value === 'string' && value.length > 0 ? value : null;
}

function asNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function asKind(value: unknown): McpCapabilityDirectoryKind | null {
  if (
    value === 'tool' ||
    value === 'resource' ||
    value === 'resource_template' ||
    value === 'prompt'
  ) {
    return value;
  }
  return null;
}

export function mcpCapabilityDirectoryEntryFromPayload(
  raw: unknown,
): McpCapabilityDirectoryEntry | null {
  if (!raw || typeof raw !== 'object') return null;
  const r = raw as Record<string, unknown>;
  const kind = asKind(r.kind);
  const itemId = asString(r.itemId) ?? asString(r.item_id);
  const itemName = asString(r.itemName) ?? asString(r.item_name);
  const endpointId = asString(r.endpointId) ?? asString(r.endpoint_id);
  const endpointName = asString(r.endpointName) ?? asString(r.endpoint_name);
  const endpointSlug = asString(r.endpointSlug) ?? asString(r.endpoint_slug);
  const host = asString(r.host);
  const endpointUrl = asString(r.endpointUrl) ?? asString(r.endpoint_url);
  if (!kind || !itemId || !itemName || !endpointId || !endpointName || !endpointSlug || !host || !endpointUrl) {
    return null;
  }
  return {
    kind,
    itemId,
    itemName,
    itemTitle: asString(r.itemTitle) ?? asString(r.item_title),
    description: asString(r.description),
    endpointId,
    endpointName,
    endpointSlug,
    host,
    endpointUrl,
    category: asString(r.category),
    visibility: asString(r.visibility) ?? 'private',
    currentVersionId: asString(r.currentVersionId) ?? asString(r.current_version_id),
    score: asNumber(r.score),
    grade: asString(r.grade),
  };
}

export function mcpCapabilityDirectoryFromPayload(payload: unknown): McpCapabilityDirectoryPage {
  const empty: McpCapabilityDirectoryPage = {
    items: [],
    total: 0,
    limit: MCP_CAPABILITY_DIRECTORY_PAGE_SIZE,
    offset: 0,
  };
  if (!payload || typeof payload !== 'object') return empty;
  const p = payload as Record<string, unknown>;
  const rawItems = Array.isArray(p.items) ? p.items : [];
  const items = rawItems
    .map((row) => mcpCapabilityDirectoryEntryFromPayload(row))
    .filter((row): row is McpCapabilityDirectoryEntry => row !== null);
  return {
    items,
    total: asNumber(p.total) ?? items.length,
    limit: asNumber(p.limit) ?? MCP_CAPABILITY_DIRECTORY_PAGE_SIZE,
    offset: asNumber(p.offset) ?? 0,
  };
}

export function mcpCapabilityDirectoryQueryParams(
  filters: McpCapabilityDirectoryFilters,
  sort: McpCapabilityDirectorySort,
  offset: number,
  limit = MCP_CAPABILITY_DIRECTORY_PAGE_SIZE,
): URLSearchParams {
  const params = new URLSearchParams();
  params.set('sort', sort);
  params.set('limit', String(limit));
  params.set('offset', String(offset));
  const name = filters.name.trim();
  if (name) params.set('name', name);
  if (filters.type) params.set('type', filters.type);
  const endpointId = filters.endpointId.trim();
  if (endpointId) params.set('endpoint_id', endpointId);
  const host = filters.host.trim();
  if (host) params.set('host', host);
  if (filters.visibility) params.set('visibility', filters.visibility);
  return params;
}

export function mcpCapabilityDirectoryEndpointHref(endpointId: string): string {
  return `/ade/dashboard/mcp/${encodeURIComponent(endpointId)}`;
}

export function mcpCapabilityDirectoryKindBadge(kind: McpCapabilityDirectoryKind): {
  label: string;
  variant: McpBadgeVariant;
} {
  const labels: Record<McpCapabilityDirectoryKind, string> = {
    tool: 'Tool',
    resource: 'Resource',
    resource_template: 'Resource template',
    prompt: 'Prompt',
  };
  return {
    label: labels[kind],
    variant: kind === 'tool' ? 'default' : 'secondary',
  };
}

export function mcpCapabilityDirectoryDisplayName(entry: McpCapabilityDirectoryEntry): string {
  return entry.itemTitle?.trim() || entry.itemName;
}
