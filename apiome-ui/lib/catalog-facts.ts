/**
 * Catalog facts in the UI — CDG-5.4 (#5982).
 *
 * The wire shape of `GET /v1/catalog/{tenant}/entities/{kind}/{id}/facts`: typed facts with
 * evidence that GVM-1.x maturity ladders will read. Until those ladders land, pages show the facts
 * as a plain checklist — no score, and never a grade computed from partial facts.
 */

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
