'use client';

import Link from 'next/link';
import { useMemo, useState } from 'react';

interface SidebarVersion {
  id: string;
  version_id: string;
  published_at?: string;
}

interface OperationEntry {
  method: string;
  path: string;
  summary?: string;
  operationId?: string;
  anchorId: string;
}

interface TagGroup {
  tag: string;
  description?: string;
  operations: OperationEntry[];
}

interface SpecSidebarProps {
  tenantSlug: string;
  projectSlug: string;
  versionSlug: string;
  versions: SidebarVersion[];
  /** Fully-resolved spec object (OpenAPI / Arazzo / JSON Schema). May be null while loading. */
  spec: unknown;
  format: 'openapi' | 'arazzo' | 'jsonschema';
  /** Currently active anchor (for highlighting). */
  activeAnchorId?: string;
  onSelectAnchor?: (anchorId: string) => void;
}

const HTTP_METHOD_TONE: Record<string, string> = {
  get: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300',
  post: 'bg-sky-50 text-sky-700 dark:bg-sky-500/10 dark:text-sky-300',
  put: 'bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300',
  patch: 'bg-blue-50 text-blue-700 dark:bg-blue-500/10 dark:text-blue-300',
  delete: 'bg-rose-50 text-rose-700 dark:bg-rose-500/10 dark:text-rose-300',
  options: 'bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300',
  head: 'bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300',
  trace: 'bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300',
  cls: 'bg-fuchsia-50 text-fuchsia-800 dark:bg-fuchsia-500/10 dark:text-fuchsia-300',
  def: 'bg-sky-50 text-sky-800 dark:bg-sky-500/10 dark:text-sky-300',
  wf: 'bg-blue-50 text-blue-800 dark:bg-blue-500/10 dark:text-blue-300',
};

const HTTP_METHODS = ['get', 'post', 'put', 'patch', 'delete', 'options', 'head', 'trace'];

export function operationAnchorId(method: string, path: string): string {
  const slug = `${method.toLowerCase()}-${path}`
    .replace(/[{}]/g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
  return `op-${slug}`;
}

/** Anchor id for OpenAPI component schema / Swagger `definitions` entries (overview + sidebar TOC). */
export function schemaAnchorId(schemaName: string): string {
  const slug = schemaName
    .replace(/[^a-z0-9]+/gi, '-')
    .replace(/^-+|-+$/g, '');
  return `schema-${slug || 'unnamed'}`;
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function parseOpenApiToc(spec: unknown): TagGroup[] {
  if (!isObject(spec)) return [];
  const paths = isObject(spec.paths) ? spec.paths : {};
  const declaredTags = Array.isArray(spec.tags) ? spec.tags : [];

  const tagDescriptions = new Map<string, string>();
  for (const t of declaredTags) {
    if (isObject(t) && typeof t.name === 'string') {
      tagDescriptions.set(t.name, typeof t.description === 'string' ? t.description : '');
    }
  }

  const groups = new Map<string, TagGroup>();
  const ensure = (tag: string) => {
    let g = groups.get(tag);
    if (!g) {
      g = { tag, description: tagDescriptions.get(tag), operations: [] };
      groups.set(tag, g);
    }
    return g;
  };

  for (const [pathKey, pathValueRaw] of Object.entries(paths)) {
    if (!isObject(pathValueRaw)) continue;
    for (const method of HTTP_METHODS) {
      const opRaw = pathValueRaw[method];
      if (!isObject(opRaw)) continue;
      const tags = Array.isArray(opRaw.tags) && opRaw.tags.length > 0
        ? (opRaw.tags as unknown[]).filter((t): t is string => typeof t === 'string')
        : [];
      const targets = tags.length > 0 ? tags : ['Untagged'];

      const operation: OperationEntry = {
        method: method.toUpperCase(),
        path: pathKey,
        summary: typeof opRaw.summary === 'string' ? opRaw.summary : undefined,
        operationId: typeof opRaw.operationId === 'string' ? opRaw.operationId : undefined,
        anchorId: operationAnchorId(method, pathKey),
      };

      for (const t of targets) {
        ensure(t).operations.push(operation);
      }
    }
  }

  // Preserve declared tag order; append untagged groups last.
  const declaredOrder = declaredTags
    .map((t) => (isObject(t) && typeof t.name === 'string' ? t.name : null))
    .filter((n): n is string => n !== null);
  const seen = new Set<string>();
  const ordered: TagGroup[] = [];
  for (const name of declaredOrder) {
    const g = groups.get(name);
    if (g) {
      ordered.push(g);
      seen.add(name);
    }
  }
  for (const [name, g] of groups) {
    if (!seen.has(name)) ordered.push(g);
  }
  return ordered;
}

function parseOpenApiSchemaGroup(spec: unknown): TagGroup | null {
  if (!isObject(spec)) return null;
  const components = isObject(spec.components) ? spec.components : null;
  const componentSchemas = components && isObject(components.schemas) ? components.schemas : {};
  const legacyDefinitions = isObject(spec.definitions) ? spec.definitions : {};
  const names = [
    ...new Set([...Object.keys(componentSchemas), ...Object.keys(legacyDefinitions)]),
  ].sort((a, b) => a.localeCompare(b));
  if (names.length === 0) return null;

  return {
    tag: 'Schemas',
    operations: names.map((name) => {
      const raw =
        (isObject(componentSchemas[name]) ? componentSchemas[name] : null) ??
        (isObject(legacyDefinitions[name]) ? legacyDefinitions[name] : null);
      let summary: string | undefined;
      if (isObject(raw)) {
        if (typeof raw.title === 'string') summary = raw.title;
      }
      return {
        method: 'CLS',
        path: name,
        summary,
        anchorId: schemaAnchorId(name),
      };
    }),
  };
}

function parseArazzoOutline(spec: unknown): TagGroup[] {
  if (!isObject(spec)) return [];
  const workflows = Array.isArray(spec.workflows) ? spec.workflows : [];
  if (workflows.length === 0) return [];
  return [
    {
      tag: 'Workflows',
      operations: workflows.flatMap((w, idx) => {
        if (!isObject(w)) return [];
        const id = typeof w.workflowId === 'string' ? w.workflowId : `workflow-${idx}`;
        return [
          {
            method: 'WF',
            path: id,
            summary: typeof w.summary === 'string' ? w.summary : undefined,
            anchorId: `wf-${id}`,
          },
        ];
      }),
    },
  ];
}

function parseJsonSchemaOutline(spec: unknown): TagGroup[] {
  if (!isObject(spec)) return [];
  const defs =
    (isObject(spec.$defs) && spec.$defs) ||
    (isObject(spec.definitions) && spec.definitions) ||
    null;
  if (!defs) return [];
  const operations: OperationEntry[] = Object.keys(defs).map((name) => ({
    method: 'DEF',
    path: name,
    anchorId: `def-${name.replace(/[^a-z0-9]+/gi, '-')}`,
  }));
  return [{ tag: 'Definitions', operations }];
}

export function SpecSidebar({
  tenantSlug,
  projectSlug,
  versionSlug,
  versions,
  spec,
  format,
  activeAnchorId,
  onSelectAnchor,
}: SpecSidebarProps) {
  const [versionsOpen, setVersionsOpen] = useState(true);
  const [tocOpen, setTocOpen] = useState(true);
  const [collapsedTags, setCollapsedTags] = useState<Set<string>>(new Set());
  const [filter, setFilter] = useState('');

  const groups = useMemo(() => {
    if (!spec) return [];
    if (format === 'openapi') {
      const pathGroups = parseOpenApiToc(spec);
      const schemaGroup = parseOpenApiSchemaGroup(spec);
      return schemaGroup ? [...pathGroups, schemaGroup] : pathGroups;
    }
    if (format === 'arazzo') return parseArazzoOutline(spec);
    if (format === 'jsonschema') return parseJsonSchemaOutline(spec);
    return [];
  }, [spec, format]);

  const filteredGroups = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return groups;
    return groups
      .map((g) => ({
        ...g,
        operations: g.operations.filter(
          (op) =>
            op.path.toLowerCase().includes(q) ||
            op.method.toLowerCase().includes(q) ||
            (op.summary ?? '').toLowerCase().includes(q) ||
            (op.operationId ?? '').toLowerCase().includes(q)
        ),
      }))
      .filter((g) => g.operations.length > 0);
  }, [groups, filter]);

  const toggleTag = (tag: string) => {
    setCollapsedTags((prev) => {
      const next = new Set(prev);
      if (next.has(tag)) next.delete(tag);
      else next.add(tag);
      return next;
    });
  };

  const handleAnchorClick = (e: React.MouseEvent<HTMLAnchorElement>, anchorId: string) => {
    if (onSelectAnchor) {
      e.preventDefault();
      onSelectAnchor(anchorId);
      return;
    }
    const el = document.getElementById(anchorId);
    if (el) {
      e.preventDefault();
      el.scrollIntoView({ behavior: 'smooth', block: 'start' });
      history.replaceState(null, '', `#${anchorId}`);
    }
  };

  const totalOps = groups.reduce((sum, g) => sum + g.operations.length, 0);

  return (
    <nav className="space-y-5 text-[13px]" aria-label="Specification navigation">
      {/* Versions */}
      <div className="rounded-lg border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-950">
        <button
          type="button"
          onClick={() => setVersionsOpen((v) => !v)}
          className="flex w-full items-center justify-between px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-wider text-zinc-500 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100"
          aria-expanded={versionsOpen}
        >
          <span>Versions ({versions.length})</span>
          <Chevron open={versionsOpen} />
        </button>
        {versionsOpen && (
          <ul className="border-t border-zinc-100 py-1 dark:border-zinc-800/80">
            {versions.length === 0 && (
              <li className="px-3 py-2 text-xs text-zinc-500 dark:text-zinc-400">
                No other versions.
              </li>
            )}
            {versions.map((v, idx) => {
              const active = v.version_id === versionSlug;
              return (
                <li key={v.id}>
                  <Link
                    href={`/tenant/${tenantSlug}/${projectSlug}/${v.version_id}`}
                    className={`flex items-center justify-between gap-2 px-3 py-1.5 text-[13px] transition-colors ${
                      active
                        ? 'bg-[var(--brand-soft)] font-medium text-[var(--brand-soft-text)]'
                        : 'text-zinc-700 hover:bg-zinc-50 hover:text-zinc-900 dark:text-zinc-300 dark:hover:bg-zinc-800/60 dark:hover:text-zinc-50'
                    }`}
                  >
                    <span className="flex items-center gap-2">
                      <span
                        className={`h-1.5 w-1.5 rounded-full ${
                          active ? 'bg-[var(--brand)]' : 'bg-zinc-300 dark:bg-zinc-700'
                        }`}
                      ></span>
                      <span className="font-mono">v{v.version_id}</span>
                    </span>
                    {idx === 0 && (
                      <span className="rounded-full bg-emerald-50 px-1.5 py-0.5 text-[10px] font-medium text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300">
                        Latest
                      </span>
                    )}
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      {/* Contents (TOC) */}
      <div className="rounded-lg border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-950">
        <button
          type="button"
          onClick={() => setTocOpen((v) => !v)}
          className="flex w-full items-center justify-between px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-wider text-zinc-500 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100"
          aria-expanded={tocOpen}
        >
          <span>Contents{totalOps > 0 ? ` (${totalOps})` : ''}</span>
          <Chevron open={tocOpen} />
        </button>

        {tocOpen && (
          <div className="border-t border-zinc-100 dark:border-zinc-800/80">
            {!spec ? (
              <div className="space-y-2 px-3 py-3">
                <div className="skeleton h-3 w-3/4"></div>
                <div className="skeleton h-3 w-1/2"></div>
                <div className="skeleton h-3 w-2/3"></div>
              </div>
            ) : groups.length === 0 ? (
              <p className="px-3 py-3 text-xs text-zinc-500 dark:text-zinc-400">
                No outline available for this document.
              </p>
            ) : (
              <>
                <div className="px-2 pt-2">
                  <input
                    type="search"
                    value={filter}
                    onChange={(e) => setFilter(e.target.value)}
                    placeholder="Filter paths & schemas..."
                    className="h-7 w-full rounded-md border border-zinc-200 bg-white px-2 text-[12px] text-zinc-900 placeholder-zinc-400 focus-visible:border-[var(--brand)] focus-visible:outline-none dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-100 dark:placeholder-zinc-500"
                    aria-label="Filter table of contents"
                  />
                </div>
                <ul className="max-h-[60vh] overflow-y-auto py-1">
                  {filteredGroups.length === 0 ? (
                    <li className="px-3 py-3 text-xs text-zinc-500 dark:text-zinc-400">
                      No matches.
                    </li>
                  ) : (
                    filteredGroups.map((group) => {
                      const collapsed = collapsedTags.has(group.tag);
                      return (
                        <li key={group.tag}>
                          <button
                            type="button"
                            onClick={() => toggleTag(group.tag)}
                            className="flex w-full items-center gap-1.5 px-3 py-1.5 text-left text-[12px] font-semibold text-zinc-700 hover:bg-zinc-50 dark:text-zinc-200 dark:hover:bg-zinc-800/60"
                            aria-expanded={!collapsed}
                          >
                            <Chevron open={!collapsed} small />
                            <span className="truncate">{group.tag}</span>
                            <span className="ml-auto text-[10px] tabular-nums text-zinc-400 dark:text-zinc-500">
                              {group.operations.length}
                            </span>
                          </button>
                          {!collapsed && (
                            <ul className="border-l border-zinc-100 ml-[18px] dark:border-zinc-800/80">
                              {group.operations.map((op, i) => {
                                const active = activeAnchorId === op.anchorId;
                                return (
                                  <li key={`${op.anchorId}-${i}`}>
                                    <a
                                      href={`#${op.anchorId}`}
                                      onClick={(e) => handleAnchorClick(e, op.anchorId)}
                                      className={`flex items-center gap-2 rounded-r-md py-1 pl-3 pr-2 text-[12px] transition-colors ${
                                        active
                                          ? 'bg-[var(--brand-soft)] text-[var(--brand-soft-text)]'
                                          : 'text-zinc-600 hover:bg-zinc-50 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800/60 dark:hover:text-zinc-100'
                                      }`}
                                    >
                                      <span
                                        className={`shrink-0 rounded px-1 py-0 font-mono text-[10px] font-semibold uppercase tracking-wide ${
                                          HTTP_METHOD_TONE[op.method.toLowerCase()] ?? HTTP_METHOD_TONE.options
                                        }`}
                                      >
                                        {op.method.length > 3 ? op.method.slice(0, 3) : op.method}
                                      </span>
                                      <span
                                        className="truncate font-mono"
                                        title={op.summary ? `${op.path} — ${op.summary}` : op.path}
                                      >
                                        {op.path}
                                      </span>
                                    </a>
                                  </li>
                                );
                              })}
                            </ul>
                          )}
                        </li>
                      );
                    })
                  )}
                </ul>
              </>
            )}
          </div>
        )}
      </div>
    </nav>
  );
}

function Chevron({ open, small }: { open: boolean; small?: boolean }) {
  const size = small ? 'h-3 w-3' : 'h-3.5 w-3.5';
  return (
    <svg
      className={`${size} text-zinc-400 transition-transform ${open ? '' : '-rotate-90'}`}
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      viewBox="0 0 24 24"
      aria-hidden="true"
    >
      <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
    </svg>
  );
}
