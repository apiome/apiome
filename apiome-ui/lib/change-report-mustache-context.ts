/**
 * Client-side Mustache context for change report templates (mirrors apiome-rest
 * `change_report_render.build_mustache_context` enough for preview in the ADE UI).
 */

export type ChangeModelJson = Record<string, unknown>;

const GENERATOR_PREVIEW = 'apiome-ui/preview';

function counts(cm: ChangeModelJson) {
  const schemas = typeof cm.schemas === 'object' && cm.schemas !== null ? (cm.schemas as Record<string, unknown>) : {};
  const added = Array.isArray(schemas.added) ? schemas.added : [];
  const removed = Array.isArray(schemas.removed) ? schemas.removed : [];
  const modified = Array.isArray(schemas.modified) ? schemas.modified : [];
  const props = Array.isArray(cm.properties) ? cm.properties : [];
  const refs = Array.isArray(cm.references) ? cm.references : [];
  const rels = Array.isArray(cm.relationships) ? cm.relationships : [];
  const docs = Array.isArray(cm.documentation) ? cm.documentation : [];
  const warns = Array.isArray(cm.warnings) ? cm.warnings : [];
  const skipped = Array.isArray(cm.skipped) ? cm.skipped : [];
  return {
    schemaCounts: {
      added: added.length,
      removed: removed.length,
      modified: modified.length,
    },
    propertyCount: props.length,
    referenceCount: refs.length,
    relationshipCount: rels.length,
    documentationCount: docs.length,
    warningCount: warns.length,
    skippedCount: skipped.length,
  };
}

/**
 * Total number of *substantive* changes in a change model (schemas added/removed/
 * modified plus property, reference, relationship, and documentation deltas).
 *
 * Diagnostic `warnings` / `skipped` notes are excluded, mirroring the apiome-rest
 * `change_report_change_counts` helper, so a refresh whose only output is a warning is
 * still treated as a no-op (RAR-4.3).
 */
export function changeModelTotalChanges(cm: ChangeModelJson): number {
  const c = counts(cm);
  return (
    c.schemaCounts.added +
    c.schemaCounts.removed +
    c.schemaCounts.modified +
    c.propertyCount +
    c.referenceCount +
    c.relationshipCount +
    c.documentationCount
  );
}

/**
 * True when a change model carries no substantive change — a zero-change refresh that
 * should render as a no-op. Honors an explicit `noChanges` flag stamped by the
 * apiome-rest refresh pipeline, falling back to recomputing from the model.
 */
export function isNoOpChangeModel(cm: ChangeModelJson): boolean {
  if (typeof cm.noChanges === 'boolean') {
    return cm.noChanges;
  }
  return changeModelTotalChanges(cm) === 0;
}

/**
 * Build the merged Mustache context used by header, body, and footnote templates.
 */
export function buildMustacheContext(
  changeModel: ChangeModelJson,
  metadata?: Record<string, string> | null,
): Record<string, unknown> {
  const md = metadata ?? {};
  const cm: ChangeModelJson = { ...changeModel };

  const productName = md.productName ?? md.product_name ?? 'API';
  const fromVersionLabel = md.fromVersionLabel ?? md.from_version_label ?? '—';
  const toVersionLabel = md.toVersionLabel ?? md.to_version_label ?? '—';
  const publishTimestamp = md.publishTimestamp ?? md.publish_timestamp ?? '—';
  const staticFootnote = md.staticFootnote ?? md.static_footnote ?? '';

  const meta = {
    productName,
    fromVersionLabel,
    toVersionLabel,
    publishTimestamp,
    staticFootnote,
  };

  const schemas = typeof cm.schemas === 'object' && cm.schemas !== null ? cm.schemas : {};
  const properties = Array.isArray(cm.properties) ? cm.properties : [];
  const references = Array.isArray(cm.references) ? cm.references : [];
  const relationships = Array.isArray(cm.relationships) ? cm.relationships : [];
  const documentation = Array.isArray(cm.documentation) ? cm.documentation : [];
  const warnings = Array.isArray(cm.warnings) ? cm.warnings : [];
  const skipped = Array.isArray(cm.skipped) ? cm.skipped : [];

  const schemaObj = schemas as Record<string, unknown>;
  const schemaAdded = Array.isArray(schemaObj.added) ? schemaObj.added : [];
  const schemaRemoved = Array.isArray(schemaObj.removed) ? schemaObj.removed : [];
  const schemaModified = Array.isArray(schemaObj.modified) ? schemaObj.modified : [];

  return {
    ...meta,
    staticNote: staticFootnote || md.staticNote || '',
    schemaVersion: (cm.schemaVersion as string) ?? (cm.schema_version as string) ?? '?',
    schemas,
    properties,
    references,
    relationships,
    documentation,
    warnings,
    skipped,
    ...counts(cm),
    generatorVersion: GENERATOR_PREVIEW,
    schemaSection: schemaAdded.length > 0 || schemaRemoved.length > 0 || schemaModified.length > 0,
    propertiesSection: properties.length > 0,
    referencesSection: references.length > 0,
    relationshipsSection: relationships.length > 0,
    documentationSection: documentation.length > 0,
    warningsSection: warnings.length > 0,
    skippedSection: skipped.length > 0,
    noChangesSection: isNoOpChangeModel(cm),
  };
}
