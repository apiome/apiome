"use client";

/**
 * The tenant-wide dependency graph (CDG-3.4, #5969).
 *
 * Every entity that has an edge, most connected first, searchable by name and filtered by kind,
 * owner team and edge provenance. Picking one (or opening `?entity=kind:id`) shows its
 * Dependencies panel — the same list and drawing as the entity pages' tab — and a project or
 * catalog item can open the **Blast radius** drawer. A search that matches more than the page shows
 * says "Showing 2,000 of N".
 */

import * as React from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Network, Radar } from "lucide-react";
import {
  Button,
  DataTableFilterChip,
  EmptyState,
  ErrorState,
  Input,
  LoadingState,
} from "@/app/components/ui";
import PageHeader from "@/app/components/shell/PageHeader";
import { Page, PageBody } from "@/app/components/shell/pageChrome";
import { OwnerFilter, useTeams } from "@/app/components/ade/owners";
import { BlastRadiusDrawer } from "@/app/components/ade/graph/BlastRadiusDrawer";
import { DependenciesPanel } from "@/app/components/ade/graph/DependenciesPanel";
import { GraphOwnerBadge } from "@/app/components/ade/graph/GraphOwnerBadge";
import { fetchGraphEntities } from "@/app/components/ade/graph/graphApi";
import {
  GRAPH_NODE_KINDS,
  GRAPH_PROVENANCES,
  NODE_KIND_LABELS,
  PROVENANCE_LABELS,
  graphNodeHref,
  nodeDisplayName,
  parseEntityParam,
  truncationNotice,
  type GraphEntity,
  type GraphEntityPage,
  type GraphNodeKind,
  type GraphProvenance,
} from "@lib/graph";

const HOME_ROUTE = "/ade/dashboard";

/** The kinds offered as filter chips (identity groups and MCP sources are reached through others). */
const KIND_FILTERS: readonly GraphNodeKind[] = GRAPH_NODE_KINDS.filter(
  (kind) => kind !== "identity_group" && kind !== "mcp_source",
);

function toggle<T>(list: readonly T[], value: T): T[] {
  return list.includes(value)
    ? list.filter((item) => item !== value)
    : [...list, value];
}

export default function GraphClient() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const focus = parseEntityParam(params?.get("entity"));
  const { teams, loading: teamsLoading } = useTeams();

  const [query, setQuery] = React.useState("");
  const [kinds, setKinds] = React.useState<GraphNodeKind[]>([]);
  const [team, setTeam] = React.useState<string | null>(null);
  const [provenances, setProvenances] = React.useState<GraphProvenance[]>([]);
  const [page, setPage] = React.useState<GraphEntityPage | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [blastFor, setBlastFor] = React.useState<GraphEntity | null>(null);

  React.useEffect(() => {
    let live = true;
    const timer = setTimeout(() => {
      setLoading(true);
      fetchGraphEntities({ q: query, kinds, team, provenances })
        .then((result) => {
          if (!live) return;
          setPage(result);
          setError(null);
        })
        .catch(
          (caught: unknown) =>
            live &&
            setError(caught instanceof Error ? caught.message : String(caught)),
        )
        .finally(() => live && setLoading(false));
    }, 200);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [query, kinds, team, provenances]);

  const setFocus = (entity: { kind: GraphNodeKind; id: string } | null) => {
    const next = new URLSearchParams(params?.toString() ?? "");
    if (entity) next.set("entity", `${entity.kind}:${entity.id}`);
    else next.delete("entity");
    const suffix = next.toString();
    router.replace(
      suffix ? `${pathname}?${suffix}` : (pathname ?? "/ade/dashboard/graph"),
      { scroll: false },
    );
  };

  const focused = focus ? page?.entities.find((e) => e.id === focus.id) : null;
  const notice = page
    ? truncationNotice(page.entities.length, page.total, page.truncated)
    : null;
  const filtered = Boolean(query || kinds.length || team || provenances.length);

  return (
    <Page>
      <PageHeader
        breadcrumb={[
          { label: "Home", href: HOME_ROUTE },
          { label: "Dependency graph" },
        ]}
        title="Dependency graph"
        description="What depends on what, across every API, consumer and source."
      />
      <PageBody>
        <div className="dg-filters" data-testid="graph-filters">
          <div className="dg-filters__search">
            <label htmlFor="graph-search" className="sr-only">
              Search entities
            </label>
            <Input
              id="graph-search"
              type="search"
              value={query}
              placeholder="Search by name or slug"
              onChange={(event) => setQuery(event.target.value)}
              data-testid="graph-search"
            />
            <OwnerFilter
              teams={teams}
              value={team}
              onChange={setTeam}
              loading={teamsLoading}
              testId="graph-team-filter"
            />
          </div>
          <div className="dg-filters__chips" role="group" aria-label="Kind">
            {KIND_FILTERS.map((kind) => (
              <DataTableFilterChip
                key={kind}
                active={kinds.includes(kind)}
                onClick={() => setKinds((current) => toggle(current, kind))}
                data-testid={`graph-kind-${kind}`}
              >
                {NODE_KIND_LABELS[kind]}
              </DataTableFilterChip>
            ))}
          </div>
          <div
            className="dg-filters__chips"
            role="group"
            aria-label="Provenance"
          >
            {GRAPH_PROVENANCES.map((provenance) => (
              <DataTableFilterChip
                key={provenance}
                active={provenances.includes(provenance)}
                onClick={() =>
                  setProvenances((current) => toggle(current, provenance))
                }
                data-testid={`graph-provenance-${provenance}`}
              >
                {PROVENANCE_LABELS[provenance]}
              </DataTableFilterChip>
            ))}
          </div>
        </div>

        {notice ? (
          <p className="dg-notice" role="status" data-testid="graph-truncated">
            {notice}
          </p>
        ) : null}

        {error ? (
          <ErrorState
            title="The dependency graph could not be loaded"
            description={error}
          />
        ) : loading && !page ? (
          <LoadingState message="Loading the dependency graph" />
        ) : !page || page.entities.length === 0 ? (
          <EmptyState
            icon={<Network aria-hidden />}
            title={
              filtered ? "Nothing matches these filters" : "The graph is empty"
            }
            description={
              filtered
                ? "Clear a filter or search for another name."
                : "Edges appear as consumers register contracts and APIs declare dependencies."
            }
          />
        ) : (
          <div className="dg-layout">
            <div className="dg-table-wrap">
              <table className="dg-table" data-testid="graph-entities">
                <caption className="sr-only">
                  Entities in the dependency graph
                </caption>
                <thead>
                  <tr>
                    <th scope="col">Entity</th>
                    <th scope="col">Kind</th>
                    <th scope="col">Owner</th>
                    <th scope="col" className="dg-table__num">
                      Depended on by
                    </th>
                    <th scope="col" className="dg-table__num">
                      Depends on
                    </th>
                    <th scope="col">
                      <span className="sr-only">Actions</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {page.entities.map((entity) => {
                    const name = nodeDisplayName(
                      entity.kind,
                      entity.id,
                      entity,
                    );
                    const current = focus?.id === entity.id;
                    return (
                      <tr
                        key={entity.id}
                        data-current={current ? "" : undefined}
                        data-testid={`graph-entity-${entity.id}`}
                      >
                        <td>
                          <Link
                            href={graphNodeHref(entity.kind, entity.id)}
                            className="dg-table__name"
                          >
                            {name}
                          </Link>
                          {entity.stale_count ? (
                            <span className="dg-table__stale">
                              {entity.stale_count} stale
                            </span>
                          ) : null}
                        </td>
                        <td>{NODE_KIND_LABELS[entity.kind]}</td>
                        <td>
                          <GraphOwnerBadge
                            owner={entity.owner}
                            testId={`graph-owner-${entity.id}`}
                          />
                        </td>
                        <td className="dg-table__num">{entity.in_count}</td>
                        <td className="dg-table__num">{entity.out_count}</td>
                        <td>
                          <div className="dg-table__actions">
                            <Button
                              type="button"
                              variant="secondary"
                              size="sm"
                              aria-pressed={current}
                              onClick={() => setFocus(current ? null : entity)}
                              data-testid={`graph-show-${entity.id}`}
                            >
                              <Network aria-hidden />
                              {current ? "Hide" : "Show"}
                              <span className="sr-only">
                                {" "}
                                dependencies of {name}
                              </span>
                            </Button>
                            {entity.kind === "project" ||
                            entity.kind === "catalog_item" ? (
                              <Button
                                type="button"
                                variant="secondary"
                                size="sm"
                                onClick={() => setBlastFor(entity)}
                                data-testid={`graph-blast-${entity.id}`}
                              >
                                <Radar aria-hidden />
                                Blast radius
                                <span className="sr-only"> of {name}</span>
                              </Button>
                            ) : null}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {focus ? (
              <DependenciesPanel
                kind={focused?.kind ?? focus.kind}
                id={focus.id}
                active
                label={focused ?? null}
                showGraphLink={false}
              />
            ) : null}
          </div>
        )}

        {blastFor ? (
          <BlastRadiusDrawer
            open
            onOpenChange={(open) => !open && setBlastFor(null)}
            entity={{
              kind: blastFor.kind,
              id: blastFor.id,
              name: nodeDisplayName(blastFor.kind, blastFor.id, blastFor),
            }}
          />
        ) : null}
      </PageBody>
    </Page>
  );
}
