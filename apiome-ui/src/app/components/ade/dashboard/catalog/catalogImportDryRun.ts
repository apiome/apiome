/**
 * The catalog import wizard's **Dry run** (MFI-26.4, #4097), as data.
 *
 * A dry run answers "what would Import do?" without doing it. It is the pre-flight
 * (`POST /api/import/preflight`, IXH-2.1): the server runs the very importer the commit runs —
 * detect, parse, normalize, route, fingerprint, lint — with `dry_run` forced on, so it writes no
 * catalog item, project, version or import job. This module reduces that report to the handful of
 * facts the Options step shows, so the panel stays presentational and every rule is unit-tested.
 */

import type { PreflightReport } from '@/app/utils/import-preflight';
import { resolveCatalogFormat, resolveCatalogProtocol } from '@/app/utils/catalog-format-registry';

/** Where the server's importer would put the document (REST `ImportTarget`). */
export type CatalogDryRunDestination = 'catalog' | 'project' | 'types';

/** The catalog identity the commit would use: the item it creates, or the one it adds a revision to. */
export interface CatalogDryRunIdentity {
  /** Display name, from the spec's title, the repository or the filename. */
  name: string;
  /** The slug the commit sends; an existing item with this slug gets a new revision. */
  slug: string;
}

/** Entity counts the commit would record. */
export interface CatalogDryRunCounts {
  services: number;
  operations: number;
  types: number;
  channels: number;
}

/** What a dry run predicts, ready to render. */
export interface CatalogDryRunPrediction {
  /** The importer accepted the document; `false` means Import would fail with {@link error}. */
  ok: boolean;
  /** The format the importer recognized, as a display label. */
  formatLabel: string | null;
  /** The paradigm of the normalized model, as a display label. */
  paradigmLabel: string | null;
  /** Where the importer would route it, or `null` when it never got that far. */
  destination: CatalogDryRunDestination | null;
  /** {@link destination} in words. */
  destinationLabel: string | null;
  /** The importer's own reason for that routing. */
  reason: string | null;
  /** The routing is somewhere other than the catalog, which is what this wizard expects. */
  routesElsewhere: boolean;
  /** The catalog item the commit would create or add a revision to. */
  identity: CatalogDryRunIdentity;
  /** What the normalized model holds. */
  counts: CatalogDryRunCounts;
  /** The revision fingerprint the commit would record. */
  fingerprint: string | null;
  /** The headline lint score, when the document reached lint; `grade` is `null` when none was assigned. */
  lint: { score: number; grade: string | null } | null;
  /** Why the importer refused the document, when {@link ok} is false. */
  error: { message: string; remediation: string | null } | null;
}

/** The words for each destination, matching the wizard's routing card. */
const DESTINATION_LABELS: Record<CatalogDryRunDestination, string> = {
  catalog: 'Catalog item (not publishable until converted)',
  project: 'Project (publishable)',
  types: 'Types (current schema)',
};

/**
 * Read the routing target out of the report's untyped `routing` block.
 *
 * @param routing The report's `routing` mapping (REST `ImportRoutingDecision.as_dict()`).
 * @returns The destination, or `null` when the block is missing or names an unknown target.
 */
function destinationOf(routing: Record<string, unknown> | null | undefined): CatalogDryRunDestination | null {
  const target = routing?.target;
  return target === 'catalog' || target === 'project' || target === 'types' ? target : null;
}

/**
 * Turn a pre-flight report into the dry run's prediction.
 *
 * @param report The pre-flight report for the candidate the commit would send.
 * @param identity The name and slug the commit would use — computed by the wizard, not the server.
 * @returns The prediction. A report with `ok: false` still yields one, carrying the error and
 *   whatever the importer learned before it stopped.
 */
export function predictCatalogImport(
  report: PreflightReport,
  identity: CatalogDryRunIdentity,
): CatalogDryRunPrediction {
  const routing = report.routing ?? null;
  const destination = destinationOf(routing);
  const format = report.format ?? report.detection?.adapter_key ?? null;
  const reason = typeof routing?.reason === 'string' && routing.reason.trim() ? routing.reason : null;
  const counts = report.counts ?? {};
  const error = report.error
    ? {
        message: report.error.message || 'The importer could not read this source.',
        remediation: report.error.remediation?.trim() || null,
      }
    : null;
  return {
    ok: report.ok,
    formatLabel: format ? resolveCatalogFormat(format)?.label ?? format : null,
    paradigmLabel: report.paradigm
      ? resolveCatalogProtocol(report.paradigm)?.label ?? report.paradigm
      : null,
    destination,
    destinationLabel: destination ? DESTINATION_LABELS[destination] : null,
    reason,
    routesElsewhere: destination !== null && destination !== 'catalog',
    identity,
    counts: {
      services: counts.services ?? 0,
      operations: counts.operations ?? 0,
      types: counts.types ?? 0,
      channels: counts.channels ?? 0,
    },
    fingerprint: report.fingerprint ?? null,
    lint:
      report.lint && typeof report.lint.score === 'number'
        ? { score: report.lint.score, grade: report.lint.grade ?? null }
        : null,
    error: report.ok ? null : error ?? { message: 'The importer could not read this source.', remediation: null },
  };
}

/**
 * The counts line, naming only what the model actually holds.
 *
 * @param counts The prediction's counts.
 * @returns e.g. `1 service · 4 operations · 12 types`, or `No entities` when all are zero.
 */
export function describeDryRunCounts(counts: CatalogDryRunCounts): string {
  const parts: string[] = [];
  const add = (n: number, one: string, many: string) => {
    if (n > 0) parts.push(`${n} ${n === 1 ? one : many}`);
  };
  add(counts.services, 'service', 'services');
  add(counts.operations, 'operation', 'operations');
  add(counts.types, 'type', 'types');
  add(counts.channels, 'channel', 'channels');
  return parts.length > 0 ? parts.join(' · ') : 'No entities';
}
