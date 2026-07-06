'use client';

import { useEffect, useState } from 'react';

/**
 * The catalog-item context the Export Studio's Source step shows when the export was launched from
 * a catalog item (MFX-41.2, #4349): the imported format, its paradigm/protocol, and the normalized
 * content counts — the same provenance the catalog detail idhead renders.
 */
export interface CatalogSourceContext {
  /** The imported source format (e.g. `grpc`), for the `<FormatPill>`. */
  sourceFormat: string | null;
  /** The paradigm/protocol (e.g. `rpc`), for the `<ProtocolPill>`. */
  protocol: string | null;
  /** The normalized-content counts; each null until the import captured it. */
  summary: {
    services: number | null;
    operations: number | null;
    types: number | null;
    channels: number | null;
  };
}

export interface UseCatalogSourceContextResult {
  /** The catalog context once loaded, else null. */
  context: CatalogSourceContext | null;
  loading: boolean;
  /**
   * Load error. The Source step's catalog context is decorative — on failure it simply renders
   * nothing extra, so callers can safely ignore this beyond debugging.
   */
  error: string | null;
}

/** Read a nullable numeric count out of a loose summary bag. */
function numberOrNull(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

/**
 * Load a catalog item's format/paradigm/summary for the Export Studio Source step (MFX-41.2, #4349).
 *
 * When the Studio is opened from a catalog item (`origin === 'catalog'`), the Source step shows the
 * item's provenance — format pill, protocol pill, and normalized counts — so a non-OpenAPI import
 * is recognizable before the user picks a target. Fetches `GET /api/catalog/{itemId}` while
 * `enabled`, mirroring `./useExportPreview`. The context is advisory: a failed/absent fetch leaves
 * the Source step showing just the name and version, never blocking the export.
 *
 * @param enabled Only fetch while truthy (the source is a catalog item).
 * @param itemId The catalog item (artifact) id to describe; no fetch while empty.
 */
export function useCatalogSourceContext(
  enabled: boolean,
  itemId: string,
): UseCatalogSourceContextResult {
  const [context, setContext] = useState<CatalogSourceContext | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!enabled || !itemId) return;

    let cancelled = false;

    const load = async () => {
      setLoading(true);
      setError(null);
      setContext(null);
      try {
        const res = await fetch(`/api/catalog/${encodeURIComponent(itemId)}`, {
          credentials: 'include',
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || data?.success === false || !data?.item) {
          throw new Error(
            typeof data?.error === 'string' ? data.error : 'Could not load the catalog item.',
          );
        }
        if (cancelled) return;
        const item = data.item as Record<string, unknown>;
        const rawSummary = (item.summary ?? {}) as Record<string, unknown>;
        setContext({
          sourceFormat: typeof item.sourceFormat === 'string' ? item.sourceFormat : null,
          protocol: typeof item.protocol === 'string' ? item.protocol : null,
          summary: {
            services: numberOrNull(rawSummary.services),
            operations: numberOrNull(rawSummary.operations),
            types: numberOrNull(rawSummary.types),
            channels: numberOrNull(rawSummary.channels),
          },
        });
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : 'Could not load the catalog item.');
        setContext(null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    void load();

    return () => {
      cancelled = true;
    };
  }, [enabled, itemId]);

  return { context, loading, error };
}
