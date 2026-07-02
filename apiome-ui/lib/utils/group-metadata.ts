/**
 * Build `apiome.groups.metadata` JSON from a client canvas group payload.
 * Tags live on `group.tags`; legacy saves used `group.metadata` or the whole `styleOptions` object (#95).
 */
export function buildGroupMetadataForSync(group: Record<string, unknown>): Record<string, unknown> {
  const rawMeta = group.metadata;
  const hasMeta =
    rawMeta &&
    typeof rawMeta === 'object' &&
    !Array.isArray(rawMeta);

  if (hasMeta) {
    const meta = { ...(rawMeta as Record<string, unknown>) };
    if (group.tags !== undefined) {
      meta.tags = group.tags;
    }
    return meta;
  }

  const meta: Record<string, unknown> = {};
  const so = group.styleOptions;
  if (so && typeof so === 'object' && !Array.isArray(so)) {
    Object.assign(meta, so as Record<string, unknown>);
  }
  if (group.tags !== undefined) {
    meta.tags = group.tags;
  }
  return meta;
}
