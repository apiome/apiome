/**
 * Projection-evidence page contract + integrity guards (EFP-2.1, #4813).
 *
 * `POST /api/export/projection-evidence` returns one bounded, cursor-paginated page of
 * source→target projection evidence for a configured export — the traceable rows behind
 * the projection summary the fidelity envelope embeds. This module mirrors those REST
 * models field-for-field so the response deserialises directly, and adds the pure
 * integrity guard the graph (EFP-2.2) and evidence drawer (EFP-2.3) run before trusting
 * a page: every edge must use a canonical status, carry a canonical reason where one is
 * required, and reference nodes the page actually bundles — and the page must name the
 * snapshot it belongs to.
 *
 * Everything here is pure (no React, no fetch) so it can be unit-tested directly —
 * mirroring `./capabilityRegistry.ts`. Keep the vocabulary in sync with
 * `apiome-rest/src/app/{projection_taxonomy,export_projection}.py`.
 */

import { isKnownReasonCode } from './capabilityRegistry';
import type { DocumentationEvidence } from './capabilityRegistry';
import type {
  LossinessSeverity,
  ProjectionManifestSummary,
  ProjectionStatus,
} from './exportFidelityPreview';

/** Which projection layer a node belongs to (mirrors Python `ProjectionNodeKind`). */
export type ProjectionNodeKind = 'native' | 'canonical' | 'target';

/** The relationship an edge expresses (mirrors Python `ProjectionEdgeRelation`). */
export type ProjectionEdgeRelation = 'derives' | 'projects';

/** The canonical projection statuses, as a runtime-checkable set. */
export const PROJECTION_STATUSES: readonly ProjectionStatus[] = [
  'retained',
  'transformed',
  'approximated',
  'synthesized',
  'dropped',
  'unavailable',
  'not-applicable',
];

const STATUS_SET: ReadonlySet<string> = new Set(PROJECTION_STATUSES);

/** Statuses that must carry a reason code (mirrors the server-side edge validator). */
const REASON_REQUIRED_STATUSES: ReadonlySet<string> = new Set([
  'approximated',
  'synthesized',
  'dropped',
  'unavailable',
]);

/** Source-native evidence for a construct (mirrors Python `NativeEvidence`). */
export interface NativeEvidence {
  /** Source-native stable identifier, when captured (may be a redaction placeholder). */
  native_id?: string | null;
  /** The construct's name in the source document. */
  native_name?: string | null;
  /** Source location the construct came from, when captured (may be redacted). */
  source_location?: string | null;
}

/** Where a construct lands in the emitted artifact (mirrors Python `TargetLocation`). */
export interface TargetLocation {
  /** RFC 6901 JSON Pointer into the emitted document (JSON/YAML targets). */
  json_pointer?: string | null;
  /** Target-native path into the emitted artifact (SDL/schema/proto targets). */
  native_path?: string | null;
}

/** One node in the projection graph (mirrors Python `ProjectionNode`). */
export interface ProjectionNode {
  /** Deterministic, stable node id (unique within a manifest). */
  id: string;
  /** Which projection layer this node belongs to. */
  kind: ProjectionNodeKind;
  /** Short human label for the node. */
  label: string;
  /** The canonical construct key this node concerns. */
  construct_key?: string | null;
  /** Coarse construct class on a canonical node: operation / channel / type / field. */
  canonical_kind?: string | null;
  /** Source-native evidence, on a `native` node. */
  native?: NativeEvidence | null;
  /** Target location, on a `target` node. */
  target?: TargetLocation | null;
}

/** One edge in the projection graph (mirrors Python `ProjectionEdge`). */
export interface ProjectionEdge {
  /** Deterministic, stable edge id (unique within a manifest). */
  id: string;
  /** derives (provenance) or projects (outcome). */
  relation: ProjectionEdgeRelation;
  /** Id of the node this edge starts at. */
  source: string;
  /** Id of the node this edge ends at; null for a projects edge to a dropped construct. */
  target?: string | null;
  /** The projection outcome this edge records. */
  status: ProjectionStatus;
  /** Cause category for a non-preserved status. */
  reason?: string | null;
  /** How much the outcome matters (info / warn / critical). */
  severity: LossinessSeverity;
  /** Human-readable explanation of the outcome. */
  detail: string;
  /** How the construct landed in the target when not dropped. */
  target_mapping?: string | null;
  /** Reviewed, reason-specific explanation from the capability registry (EFP-1.2). */
  explanation?: string | null;
  /** Reason-scoped documentation evidence from the capability registry (EFP-1.2). */
  documentation?: DocumentationEvidence | null;
}

/** One cursor-paginated page of evidence (mirrors Python `ProjectionEvidencePage`). */
export interface ProjectionEvidencePage {
  /** The manifest hash this page belongs to (the snapshot id). */
  manifest_hash: string;
  /** This page's outcome edges, in canonical order. */
  edges: ProjectionEdge[];
  /** The nodes referenced by this page's edges. */
  nodes: ProjectionNode[];
  /** Opaque cursor for the next page, or null when this is the last page. */
  next_cursor?: string | null;
  /** Total outcome edges across the whole manifest. */
  total: number;
}

/** The `POST /api/export/projection-evidence` response (mirrors REST, EFP-2.1). */
export interface ExportProjectionEvidenceResponse {
  /** The artifact (project) id the evidence describes. */
  artifact: string;
  /** The version selector as requested (label, UUID, or null). */
  version?: string | null;
  /** The resolved revision record id. */
  version_record_id: string;
  /** The resolved revision's version label. */
  version_label?: string | null;
  /** The bounded snapshot summary — hash, provenance, and status/reason counts. */
  summary: ProjectionManifestSummary;
  /** This page of outcome edges + the nodes they reference. */
  page: ProjectionEvidencePage;
  /** True when source-native evidence values were redacted in this response. */
  redacted: boolean;
}

/** Return true when `status` is a member of the canonical projection-status vocabulary. */
export function isKnownProjectionStatus(status: string): status is ProjectionStatus {
  return STATUS_SET.has(status);
}

/**
 * Return every integrity problem in one evidence page.
 *
 * The guard the graph/drawer run before rendering: a page whose edges use vocabulary the
 * contract does not define, omit a required reason, or reference nodes the page did not
 * bundle is refused rather than partially rendered. Returns human-readable issue
 * descriptions; empty when the page is internally consistent.
 */
export function evidencePageIssues(page: ProjectionEvidencePage): string[] {
  const issues: string[] = [];
  if (!page.manifest_hash) {
    issues.push('evidence page has no manifest_hash (snapshot id)');
  }

  const nodeIds = new Set(page.nodes.map((node) => node.id));
  for (const edge of page.edges) {
    if (!isKnownProjectionStatus(edge.status)) {
      issues.push(`edge '${edge.id}' uses unknown status '${edge.status}'`);
    }
    if (edge.reason != null && !isKnownReasonCode(edge.reason)) {
      issues.push(`edge '${edge.id}' uses unknown reason code '${edge.reason}'`);
    }
    if (REASON_REQUIRED_STATUSES.has(edge.status) && edge.reason == null) {
      issues.push(`edge '${edge.id}' with status '${edge.status}' is missing its reason code`);
    }
    if (!nodeIds.has(edge.source)) {
      issues.push(`edge '${edge.id}' references source node '${edge.source}' not on this page`);
    }
    if (edge.target != null && !nodeIds.has(edge.target)) {
      issues.push(`edge '${edge.id}' references target node '${edge.target}' not on this page`);
    }
  }

  if (page.edges.length > page.total) {
    issues.push(`page carries ${page.edges.length} edges but claims a total of ${page.total}`);
  }
  return issues;
}
