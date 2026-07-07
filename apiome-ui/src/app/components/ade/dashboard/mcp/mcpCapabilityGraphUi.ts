/**
 * MCP capability relationship graph — presentation helpers (V2-MCP-29.2 / MCAT-15.2, #4632).
 *
 * The "Capability relationship graph" Insight panel renders a node-link diagram of a server's
 * tools / resources / resource templates / prompts and the concrete relationships between them. All
 * *edge inference* is done server-side (a testable Python helper — precision over recall); this
 * module is the *pure, React-free* client layer over that payload: the typed shape the 15.2 REST API
 * returns (`GET …/endpoints/{id}/insight/graph`), a defensive parser for it, a small legend
 * projection, and the builder that turns the graph into a **Mermaid** `flowchart` source string.
 *
 * Keeping this free of React/JSX lets it be unit-tested directly and keeps the panel component free of
 * payload-shaping and diagram-syntax branches. One deliberate exception to the "no color literals"
 * rule lives here: Mermaid renders an isolated SVG whose interior cannot be reached by our Tailwind
 * token layer, so the per-kind node colors must be emitted as literals *in the diagram source*. They
 * are centralized in {@link GRAPH_KIND_STYLES} (a single source of truth, light + dark variants) the
 * way `chartTokens.ts` centralizes the SVG chart palette — consumers never write a hex themselves.
 */

// --- Wire types ------------------------------------------------------------------------------
// One-to-one with the apiome-rest `McpCapabilityGraphOut` envelope (see apiome-rest models.py).

/** The four capability kinds a node can be (wire spelling), used to color and group nodes. */
export type McpGraphNodeType = 'tool' | 'resource' | 'resource_template' | 'prompt';

/** The three concrete edge signals the backend infers. */
export type McpGraphEdgeKind = 'prompt_reference' | 'resource_reference' | 'shared_type';

/** One capability rendered as a graph node. */
export interface McpGraphNode {
  /** Stable, Mermaid-safe id (e.g. `t_0`); referenced by edges. */
  id: string;
  item_type: McpGraphNodeType;
  name: string;
  title: string | null;
  /** Best display label — server `title` when present, else `name`. */
  label: string;
  /** Number of incident edges (0 ⇒ isolated). */
  degree: number;
}

/** One inferred relationship between two nodes. */
export interface McpGraphEdge {
  source: string;
  target: string;
  kind: McpGraphEdgeKind;
  /** Directed (reference kinds) vs undirected (`shared_type`). */
  directed: boolean;
  /** A short human label for the edge (the referenced name/URI or the shared type). */
  label: string;
  /** The concrete evidence for the edge (referenced tokens, URIs, or shared type ids). */
  signals: string[];
}

/** The full inferred graph for one version snapshot. */
export interface McpCapabilityGraph {
  nodes: McpGraphNode[];
  edges: McpGraphEdge[];
  node_count: number;
  edge_count: number;
  isolated_count: number;
  graph_fingerprint: string | null;
}

/** The insight/graph response envelope: the resolved snapshot identity plus its graph. */
export interface McpInsightGraph {
  endpoint_id: string;
  version_id: string;
  version_seq: number;
  version_tag: string | null;
  is_current: boolean;
  graph: McpCapabilityGraph;
}

// --- Defensive coercion ----------------------------------------------------------------------

function asString(value: unknown): string | null {
  return typeof value === 'string' && value.length > 0 ? value : null;
}

function asInt(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? Math.trunc(value) : 0;
}

function asBool(value: unknown): boolean {
  return value === true;
}

const NODE_TYPES: readonly McpGraphNodeType[] = [
  'tool',
  'resource',
  'resource_template',
  'prompt',
];
const EDGE_KINDS: readonly McpGraphEdgeKind[] = [
  'prompt_reference',
  'resource_reference',
  'shared_type',
];

function asNodeType(value: unknown): McpGraphNodeType {
  return NODE_TYPES.includes(value as McpGraphNodeType) ? (value as McpGraphNodeType) : 'tool';
}

function asEdgeKind(value: unknown): McpGraphEdgeKind {
  return EDGE_KINDS.includes(value as McpGraphEdgeKind)
    ? (value as McpGraphEdgeKind)
    : 'shared_type';
}

function nodeFromPayload(raw: unknown): McpGraphNode | null {
  const r = (raw ?? {}) as Record<string, unknown>;
  const id = asString(r.id);
  if (!id) return null;
  const name = String(r.name ?? '');
  const title = asString(r.title);
  return {
    id,
    item_type: asNodeType(r.item_type),
    name,
    title,
    label: asString(r.label) ?? title ?? name ?? id,
    degree: asInt(r.degree),
  };
}

function edgeFromPayload(raw: unknown, nodeIds: Set<string>): McpGraphEdge | null {
  const r = (raw ?? {}) as Record<string, unknown>;
  const source = asString(r.source);
  const target = asString(r.target);
  // Drop dangling edges defensively so the diagram never references a missing node.
  if (!source || !target || !nodeIds.has(source) || !nodeIds.has(target)) return null;
  const signals = Array.isArray(r.signals)
    ? r.signals.filter((s): s is string => typeof s === 'string')
    : [];
  return {
    source,
    target,
    kind: asEdgeKind(r.kind),
    directed: r.directed === undefined ? true : asBool(r.directed),
    label: String(r.label ?? ''),
    signals,
  };
}

function graphFromPayload(raw: unknown): McpCapabilityGraph {
  const r = (raw ?? {}) as Record<string, unknown>;
  const nodes = Array.isArray(r.nodes)
    ? r.nodes.map(nodeFromPayload).filter((n): n is McpGraphNode => n !== null)
    : [];
  const nodeIds = new Set(nodes.map((n) => n.id));
  const edges = Array.isArray(r.edges)
    ? r.edges.map((e) => edgeFromPayload(e, nodeIds)).filter((e): e is McpGraphEdge => e !== null)
    : [];
  const isolatedCount = nodes.filter((n) => n.degree === 0).length;
  return {
    nodes,
    edges,
    // Derive counts from the parsed arrays so they can never disagree with what renders.
    node_count: nodes.length,
    edge_count: edges.length,
    isolated_count: isolatedCount,
    graph_fingerprint: asString(r.graph_fingerprint),
  };
}

/**
 * Parse an `insight/graph` response defensively into an {@link McpInsightGraph}, or `null` when the
 * payload carries no resolvable snapshot id (a malformed or error body). Malformed nodes/edges and
 * edges that dangle to a missing node are dropped so a partial payload still renders a coherent graph
 * rather than throwing.
 */
export function mcpInsightGraphFromPayload(data: unknown): McpInsightGraph | null {
  const r = (data ?? {}) as Record<string, unknown>;
  const versionId = asString(r.version_id);
  if (!versionId) return null;
  return {
    endpoint_id: String(r.endpoint_id ?? ''),
    version_id: versionId,
    version_seq: asInt(r.version_seq),
    version_tag: asString(r.version_tag),
    is_current: asBool(r.is_current),
    graph: graphFromPayload(r.graph),
  };
}

// --- Kind styling & legend -------------------------------------------------------------------

/** The color literals (light + dark) a Mermaid node of each kind paints with. See module note. */
export interface GraphKindStyle {
  /** Human label for the legend. */
  label: string;
  fillLight: string;
  strokeLight: string;
  textLight: string;
  fillDark: string;
  strokeDark: string;
  textDark: string;
}

/**
 * Per-kind node palette, matched to the Tailwind ramp the rest of the MCP UI uses (tools = indigo,
 * resources = emerald, resource templates = violet, prompts = amber). Light uses the 100/500/900
 * fill/stroke/text ramp; dark inverts to 900/400/100 — the same intensity the chart kit and badges
 * use, so the graph sits in one palette.
 */
export const GRAPH_KIND_STYLES: Record<McpGraphNodeType, GraphKindStyle> = {
  tool: {
    label: 'Tool',
    fillLight: '#e0e7ff',
    strokeLight: '#6366f1',
    textLight: '#312e81',
    fillDark: '#312e81',
    strokeDark: '#818cf8',
    textDark: '#e0e7ff',
  },
  resource: {
    label: 'Resource',
    fillLight: '#d1fae5',
    strokeLight: '#10b981',
    textLight: '#064e3b',
    fillDark: '#064e3b',
    strokeDark: '#34d399',
    textDark: '#d1fae5',
  },
  resource_template: {
    label: 'Resource template',
    fillLight: '#ede9fe',
    strokeLight: '#8b5cf6',
    textLight: '#4c1d95',
    fillDark: '#4c1d95',
    strokeDark: '#a78bfa',
    textDark: '#ede9fe',
  },
  prompt: {
    label: 'Prompt',
    fillLight: '#fef3c7',
    strokeLight: '#f59e0b',
    textLight: '#78350f',
    fillDark: '#78350f',
    strokeDark: '#fbbf24',
    textDark: '#fef3c7',
  },
};

/** The edge-color literals (light + dark) for the Mermaid link styling. */
export const GRAPH_EDGE_COLOR = { light: '#94a3b8', dark: '#64748b' } as const;

/** One legend row: a kind, its human label, and how many nodes of that kind the graph has. */
export interface McpGraphLegendEntry {
  kind: McpGraphNodeType;
  label: string;
  count: number;
}

/**
 * The legend rows for a graph, in a stable kind order (tool → resource → resource template →
 * prompt), each carrying its node count. Kinds with zero nodes are omitted so the legend only names
 * what the diagram actually shows.
 */
export function mcpGraphLegend(graph: McpCapabilityGraph): McpGraphLegendEntry[] {
  return NODE_TYPES.map((kind) => ({
    kind,
    label: GRAPH_KIND_STYLES[kind].label,
    count: graph.nodes.filter((n) => n.item_type === kind).length,
  })).filter((entry) => entry.count > 0);
}

// --- Mermaid source builder ------------------------------------------------------------------

/** Longest a node/edge label may be before it is elided, so the diagram stays legible. */
const MAX_LABEL_LENGTH = 36;

/**
 * Sanitize free text for use inside a Mermaid quoted label. Mermaid's parser treats `"` and a handful
 * of structural characters (`|`, `<`, `>`, braces, backticks, `#`) specially even inside quotes, so
 * they are replaced with safe equivalents; newlines collapse to spaces; and the result is elided to
 * {@link MAX_LABEL_LENGTH}. Never returns an empty string (Mermaid needs at least one character).
 */
function mermaidLabel(text: string): string {
  const cleaned = text
    .replace(/[\r\n]+/g, ' ')
    .replace(/["`]/g, "'")
    .replace(/[|<>{}#]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
  const elided =
    cleaned.length > MAX_LABEL_LENGTH ? `${cleaned.slice(0, MAX_LABEL_LENGTH - 1)}…` : cleaned;
  return elided.length > 0 ? elided : ' ';
}

/**
 * A friendly display label for an edge. Reference edges show their signal verbatim (a tool name or a
 * URI); a `shared_type` edge shows the shared type name — the tail segment of a `$ref` (`…/Foo` →
 * `Foo`) or the value of a `title:Foo` identifier — prefixed with `~` to read as "shares".
 */
export function mcpGraphEdgeDisplayLabel(edge: McpGraphEdge): string {
  if (edge.kind !== 'shared_type') return edge.label;
  const raw = edge.label ?? '';
  if (raw.startsWith('title:')) return `~ ${raw.slice('title:'.length)}`;
  const tail = raw.split('/').filter(Boolean).pop() ?? raw;
  return `~ ${tail}`;
}

/**
 * Build a Mermaid `flowchart LR` source string for a capability graph, or `null` when the graph has
 * no nodes (the panel shows an empty state instead of an empty diagram).
 *
 * Every node is declared (isolated nodes included) with a per-kind style class; directed reference
 * edges render as arrows (`-->`) and undirected `shared_type` edges as plain links (`---`), each with
 * an elided label. Colors are chosen from {@link GRAPH_KIND_STYLES} by the `dark` flag so the diagram
 * matches the active theme.
 *
 * @param graph The parsed capability graph.
 * @param dark  Whether to emit the dark-theme palette (the caller passes the resolved theme).
 */
export function mcpGraphToMermaid(graph: McpCapabilityGraph, dark = false): string | null {
  if (graph.nodes.length === 0) return null;

  const lines: string[] = ['flowchart LR'];

  // One classDef per kind, so each node paints with its palette. Node text is the dark-mode "color".
  for (const kind of NODE_TYPES) {
    const s = GRAPH_KIND_STYLES[kind];
    const fill = dark ? s.fillDark : s.fillLight;
    const stroke = dark ? s.strokeDark : s.strokeLight;
    const text = dark ? s.textDark : s.textLight;
    lines.push(
      `  classDef ${kind} fill:${fill},stroke:${stroke},color:${text},stroke-width:1.5px;`,
    );
  }

  // Node declarations. Mermaid ids come from the backend (already safe); labels are sanitized.
  for (const node of graph.nodes) {
    lines.push(`  ${node.id}["${mermaidLabel(node.label)}"]:::${node.item_type}`);
  }

  // Edges. Directed reference edges use arrows; shared-type edges use undirected links.
  for (const edge of graph.edges) {
    const connector = edge.directed ? '-->' : '---';
    const label = mermaidLabel(mcpGraphEdgeDisplayLabel(edge));
    lines.push(`  ${edge.source} ${connector}|"${label}"| ${edge.target}`);
  }

  // Uniform link color for the active theme (link indices are implicit; `default` styles them all).
  const edgeColor = dark ? GRAPH_EDGE_COLOR.dark : GRAPH_EDGE_COLOR.light;
  if (graph.edges.length > 0) {
    lines.push(`  linkStyle default stroke:${edgeColor},stroke-width:1.5px;`);
  }

  return lines.join('\n');
}
