/**
 * Catalog facts in the UI — CDG-5.4 (#5982).
 *
 * The wire shape of `GET /v1/catalog/{tenant}/entities/{kind}/{id}/facts`: typed facts with
 * evidence that GVM-1.x maturity ladders will read. Until those ladders land, pages show the facts
 * as a plain checklist — no score, and never a grade computed from partial facts.
 */

import { isFeatureReleased } from './feature-release';

/** A fact's status. `not_assessed` is never treated as met. */
export type FactStatus = 'met' | 'unmet' | 'not_applicable' | 'not_assessed';

/** Where to check a fact. */
export interface FactEvidence {
  label: string;
  href: string | null;
  api: string | null;
}

/** One fact. */
export interface CatalogFact {
  key: string;
  label: string;
  status: FactStatus;
  value: boolean | number | null;
  detail: string | null;
  evidence: FactEvidence[];
}

/** An entity's facts; `score` is always `null` until maturity ladders exist. */
export interface CatalogFactsResponse {
  kind: string;
  id: string;
  name: string;
  facts: CatalogFact[];
  score: null;
}

/** What each status reads as next to its icon (colour is never the only signal). */
export const FACT_STATUS_LABELS: Readonly<Record<FactStatus, string>> = {
  met: 'Met',
  unmet: 'Not met',
  not_applicable: 'Not applicable',
  not_assessed: 'Not assessed',
};

/** A registry kind key, as the facts route accepts. */
const KIND = /^[a-z][a-z0-9_]{0,39}$/;
/** An entity id. */
const UUID = /^[0-9a-fA-F-]{36}$/;

/**
 * The REST path (below `/v1/catalog/{slug}`) of an entity's facts, or `null` for a malformed request.
 *
 * @param kind - The registry kind.
 * @param id - The entity id.
 */
export function factsProxyPath(kind: string, id: string): string | null {
  return KIND.test(kind) && UUID.test(id) ? `entities/${kind}/${id}/facts` : null;
}

/** Facts that belong to a feature not released everywhere yet (`lib/feature-release.ts`), by key prefix. */
const FACT_FEATURES: ReadonlyArray<readonly [prefix: string, feature: string]> = [
  ['owner.', 'teams'],
  ['consumers.', 'consumers'],
  ['dependencies.', 'dependency-graph'],
  ['mcp.', 'mcp'],
  ['shadow.', 'shadow-apis'],
];

/** Routes evidence can link to that belong to a held-back feature. */
const EVIDENCE_ROUTE_FEATURES: ReadonlyArray<readonly [prefix: string, feature: string]> = [
  ['/ade/dashboard/graph', 'dependency-graph'],
  ['/ade/dashboard/connectors/shadow', 'shadow-apis'],
  ['/ade/dashboard/mcp', 'mcp'],
  ['/ade/dashboard/teams', 'teams'],
];

/**
 * The facts as this build shows them: facts about held-back features are left out, and so is any
 * evidence link into a held-back page (the evidence label stays out with it).
 *
 * @param facts - The facts the server returned.
 * @param released - Which feature ids are released; defaults to the build's gate.
 * @returns The facts to show.
 */
export function releasedFacts(
  facts: readonly CatalogFact[],
  released: (feature: string) => boolean = isFeatureReleased
): CatalogFact[] {
  const gated = (pairs: ReadonlyArray<readonly [string, string]>, value: string) =>
    pairs.some(([prefix, feature]) => value.startsWith(prefix) && !released(feature));
  return facts
    .filter((fact) => !gated(FACT_FEATURES, fact.key))
    .map((fact) => ({
      ...fact,
      evidence: fact.evidence.filter((entry) => !entry.href || !gated(EVIDENCE_ROUTE_FEATURES, entry.href)),
    }));
}
