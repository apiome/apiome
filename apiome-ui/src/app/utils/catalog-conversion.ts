/**
 * Types and presentation helpers for a catalog item's convert-to-OpenAPI back-link (MFI-23.11, #4020).
 *
 * Once a catalog item has been converted (the MFI-EPIC-22 fidelity-preview → convert flow), the REST
 * catalog list/detail responses carry a `conversion` object projected from the conversion-provenance
 * ledger (MFI-22.5): the publishable Project it produced, that Project's name/slug (or a `projectDeleted`
 * flag if it was since removed), the produced revision, whether the latest conversion was a re-convert,
 * and the fidelity grade/tier. The Catalog card and detail render this as **"Converted → {project}"**
 * with a link, and the convert action relabels to **"Re-convert to OpenAPI"**.
 *
 * These helpers are pure (no React, no fetch) so they can be unit-tested and reused by the card, the
 * table row, and the detail view.
 */

/** The convert-to-OpenAPI back-link for a catalog item (mirrors the REST `CatalogConversionRef`). */
export interface CatalogConversion {
  /** Id of the publishable Project the item was converted into. */
  projectId: string;
  /** Name of the converted Project (null once it has been deleted). */
  projectName?: string | null;
  /** Slug of the converted Project (null once it has been deleted). */
  projectSlug?: string | null;
  /** True when the converted Project has since been deleted (its link is no longer live). */
  projectDeleted?: boolean;
  /** Semantic version label of the produced revision (e.g. `1.0.1`). */
  versionId?: string | null;
  /** Row id of the produced revision. */
  versionRecordId?: string | null;
  /** True when the latest conversion superseded a prior one (the source changed and was re-converted). */
  reconverted?: boolean;
  /** When the latest conversion was committed (ISO timestamp). */
  convertedAt?: string | null;
  /** A-F fidelity grade the conversion achieved (MFI-22.3). */
  fidelityGrade?: string | null;
  /** Coarse fidelity tier (high/medium/low) of the conversion. */
  fidelityTier?: string | null;
}

/**
 * Href to the converted publishable Project. A catalog item's conversion produces a normal Project, so
 * we link to its versions screen (where it can be inspected and published) — the same destination the
 * catalog "View" action uses for an item's own project id.
 */
export function convertedProjectHref(conversion: CatalogConversion): string {
  return `/ade/dashboard/versions?projectId=${encodeURIComponent(conversion.projectId)}`;
}

/**
 * A friendly label for the converted Project: its name, else its slug, else a shortened id. Used as the
 * link text in the "Converted → {project}" badge.
 */
export function convertedProjectLabel(conversion: CatalogConversion): string {
  const name = conversion.projectName?.trim();
  if (name) return name;
  const slug = conversion.projectSlug?.trim();
  if (slug) return slug;
  return `project ${conversion.projectId.slice(0, 8)}`;
}

/**
 * Whether the converted Project link is still live — true unless the target Project has been deleted.
 * A deleted target still shows the converted state (so the history is visible) but as plain text, not a
 * link.
 */
export function isConvertedLinkLive(conversion: CatalogConversion | null | undefined): boolean {
  return Boolean(conversion) && !conversion!.projectDeleted;
}

/**
 * The convert action's label. The catalog only holds non-OpenAPI sources, so a first convert reads
 * "Convert to OpenAPI"; once an item has been converted the action becomes "Re-convert to OpenAPI"
 * (re-convert is always allowed — a changed source appends a new version rather than duplicating the
 * Project, MFI-22.5).
 */
export function convertActionLabel(conversion: CatalogConversion | null | undefined): string {
  return conversion ? 'Re-convert to OpenAPI' : 'Convert to OpenAPI';
}

/**
 * Copy stating the Export-vs-Convert distinction on catalog surfaces (MFX-41.2, #4349): Export
 * emits a document in another format and never mutates the catalog item or mints a Project;
 * Convert is the one action that turns the item into an OpenAPI Project. Shown wherever both
 * actions sit side by side (catalog list actions, detail CTAs).
 */
export const CATALOG_EXPORT_VS_CONVERT_COPY =
  'Produce a document in another API format. Unlike Convert, this never turns the item into a project.';
