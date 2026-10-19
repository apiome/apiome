'use client';

/**
 * The **Dependencies** tab (CDG-3.4, #5969), shared by the project version page, the catalog item
 * page and the MCP endpoint page.
 *
 * A list first: the entity's incoming and outgoing edges grouped by direction and kind, each with
 * its provenance and the other end's owner team; stale edges are dimmed, marked "Stale" and show
 * when they were last seen. Then the bounded drawing (depth 2, expandable per node). Loads only
 * when the tab is active. A project or catalog item also gets a **Blast radius** button.
 */

import * as React from 'react';
import Link from 'next/link';
import { Network, Radar } from 'lucide-react';
import { Badge, Button, EmptyState, ErrorState, LoadingState } from '@/app/components/ui';
import {
  EDGE_PAGE_LIMIT,
  NODE_KIND_LABELS,
  PROVENANCE_LABELS,
  graphNodeHref,
  graphPageHref,
  groupEdges,
  lastSeenLabel,
  mergeEdges,
  neighbourOf,
  nodeDisplayName,
  truncationNotice,
  type EdgeNeighbour,
  type GraphEdge,
  type GraphNodeKind,
  type GraphNodeLabel,
} from '@lib/graph';
import { BlastRadiusDrawer } from './BlastRadiusDrawer';
import { DependencyGraphSvg } from './DependencyGraphSvg';
import { GraphOwnerBadge } from './GraphOwnerBadge';
import { fetchEdges } from './graphApi';
import { graphLayout, type GraphLayoutNode } from './graphLayoutModel';

export interface DependenciesPanelProps {
  kind: GraphNodeKind;
  id: string;
  /** Load only once the tab is shown. */
  active: boolean;
  /** The entity's label, when the page already knows it. */
  label?: GraphNodeLabel | null;
  /** Show the link to the tenant graph page (off on the graph page itself). */
  showGraphLink?: boolean;
}

interface Loaded {
  edges: GraphEdge[];
  truncated: boolean;
  total: number;
}

async function loadBoth(kind: GraphNodeKind, id: string): Promise<Loaded> {
  const [incoming, outgoing] = await Promise.all([fetchEdges(kind, id, 'in'), fetchEdges(kind, id, 'out')]);
  return {
    edges: mergeEdges(outgoing.edges, incoming.edges),
    truncated: incoming.truncated || outgoing.truncated,
    total: incoming.total + outgoing.total,
  };
}

export function DependenciesPanel({ kind, id, active, label, showGraphLink = true }: DependenciesPanelProps) {
  const [state, setState] = React.useState<{ status: 'idle' | 'loading' | 'ready' | 'error'; error?: string }>({
    status: 'idle',
  });
  const [loaded, setLoaded] = React.useState<Loaded | null>(null);
  const [expanded, setExpanded] = React.useState<Map<string, EdgeNeighbour[]>>(new Map());
  const [loadingIds, setLoadingIds] = React.useState<Set<string>>(new Set());
  const [blastOpen, setBlastOpen] = React.useState(false);

  const load = React.useCallback(async () => {
    setState({ status: 'loading' });
    try {
      setLoaded(await loadBoth(kind, id));
      setExpanded(new Map());
      setState({ status: 'ready' });
    } catch (caught) {
      setState({ status: 'error', error: caught instanceof Error ? caught.message : String(caught) });
    }
  }, [kind, id]);

  // Load once per entity, the first time the tab is shown for it.
  const entityKey = `${kind}:${id}`;
  const [loadedKey, setLoadedKey] = React.useState<string | null>(null);
  React.useEffect(() => {
    if (!active || loadedKey === entityKey) return;
    setLoadedKey(entityKey);
    void load();
  }, [active, entityKey, loadedKey, load]);

  const toggle = React.useCallback(
    async (node: GraphLayoutNode) => {
      if (expanded.has(node.id)) {
        const next = new Map(expanded);
        next.delete(node.id);
        setExpanded(next);
        return;
      }
      setLoadingIds((current) => new Set(current).add(node.id));
      try {
        const page = await fetchEdges(node.kind, node.id, node.column < 0 ? 'in' : 'out');
        setExpanded((current) => new Map(current).set(node.id, page.edges.map((e) => neighbourOf(e, node.id))));
      } catch {
        // The node stays collapsed; the list is unaffected.
      } finally {
        setLoadingIds((current) => {
          const next = new Set(current);
          next.delete(node.id);
          return next;
        });
      }
    },
    [expanded]
  );

  const groups = React.useMemo(() => (loaded ? groupEdges(loaded.edges, id) : []), [loaded, id]);
  const layout = React.useMemo(
    () =>
      loaded
        ? graphLayout({
            centre: { kind, id, label },
            neighbours: loaded.edges.map((e) => neighbourOf(e, id)),
            expanded,
          })
        : null,
    [loaded, kind, id, label, expanded]
  );
  const canBlast = kind === 'project' || kind === 'catalog_item';
  const notice = loaded ? truncationNotice(loaded.edges.length, loaded.total, loaded.truncated) : null;

  if (!active) return null;
  return (
    <section className="dg-panel" aria-labelledby={`dg-title-${id}`} data-testid="dependencies-panel">
      <header className="dg-panel__head">
        <h2 id={`dg-title-${id}`} className="dg-panel__title">
          Dependencies
        </h2>
        <div className="dg-panel__actions">
          {canBlast ? (
            <Button type="button" variant="secondary" size="sm" onClick={() => setBlastOpen(true)}>
              <Radar aria-hidden />
              Blast radius
            </Button>
          ) : null}
          {showGraphLink ? (
            <Link href={graphPageHref(kind, id)} className="dg-panel__link">
              <Network aria-hidden />
              Open in the dependency graph
            </Link>
          ) : null}
        </div>
      </header>

      {state.status === 'loading' || state.status === 'idle' ? (
        <LoadingState message="Loading dependencies" />
      ) : state.status === 'error' ? (
        <ErrorState title="Dependencies could not be loaded" description={state.error} />
      ) : groups.length === 0 ? (
        <EmptyState
          icon={<Network aria-hidden />}
          title="Nothing depends on this yet"
          description="Contracts, conversions, declarations and syncs add edges here."
        />
      ) : (
        <>
          {notice ? (
            <p className="dg-notice" role="status" data-testid="dependencies-truncated">
              {notice}
            </p>
          ) : null}
          <div className="dg-groups">
            {groups.map((group) => (
              <section key={group.key} className="dg-group" aria-labelledby={`dg-group-${group.key}`}>
                <h3 id={`dg-group-${group.key}`} className="dg-group__title">
                  {group.title}
                  <span className="dg-group__count">{group.neighbours.length}</span>
                  {group.staleCount ? <span className="dg-group__stale">{group.staleCount} stale</span> : null}
                </h3>
                <ul className="dg-edges">
                  {group.neighbours.map((n) => (
                    <li
                      key={n.edge.id}
                      className="dg-edge"
                      data-stale={n.edge.stale ? '' : undefined}
                      data-testid={`dependency-edge-${n.edge.id}`}
                    >
                      <span className="dg-edge__kind">{NODE_KIND_LABELS[n.kind]}</span>
                      <Link href={graphNodeHref(n.kind, n.id)} className="dg-edge__name">
                        {nodeDisplayName(n.kind, n.id, n.label)}
                      </Link>
                      {n.edge.pointer ? <code className="dg-edge__pointer">{n.edge.pointer}</code> : null}
                      <Badge variant="neutral" className="dg-edge__provenance" data-provenance={n.edge.provenance}>
                        {PROVENANCE_LABELS[n.edge.provenance]}
                      </Badge>
                      <GraphOwnerBadge owner={n.label?.owner} testId={`dependency-owner-${n.edge.id}`} />
                      {n.edge.stale ? (
                        <span className="dg-edge__stale">
                          <Badge variant="warn">Stale</Badge>
                          <span className="dg-edge__seen">{lastSeenLabel(n.edge.last_seen_at)}</span>
                        </span>
                      ) : null}
                    </li>
                  ))}
                </ul>
              </section>
            ))}
          </div>
          {layout ? (
            <figure className="dg-figure">
              <figcaption className="dg-figure__caption">
                Graph · depth 2 · press + on a node to draw its own dependencies
              </figcaption>
              <DependencyGraphSvg layout={layout} onToggle={toggle} loadingIds={loadingIds} />
            </figure>
          ) : null}
          {loaded && loaded.edges.length >= EDGE_PAGE_LIMIT ? (
            <p className="dg-notice">The list shows the first {EDGE_PAGE_LIMIT} edges in each direction.</p>
          ) : null}
        </>
      )}

      {canBlast ? (
        <BlastRadiusDrawer
          open={blastOpen}
          onOpenChange={setBlastOpen}
          entity={{ kind, id, name: nodeDisplayName(kind, id, label) }}
        />
      ) : null}
    </section>
  );
}
