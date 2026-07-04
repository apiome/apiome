'use client';

/**
 * Related artifacts panel for catalog item and project detail (MFI-6.4, #4410).
 */

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { Link2, Unlink, Sparkles } from 'lucide-react';
import { toast } from 'sonner';
import { cn } from '@lib/utils';
import { FormatPill } from '@/app/components/ui/catalog/FormatPill';
import { ProtocolPill } from '@/app/components/ui/catalog/ProtocolPill';
import { dashboardPanelClass } from '@/app/components/ade/dashboard/dashboardScreenClasses';
import {
  allRepresentationsHref,
  linkSourceLabel,
  relatedArtifactHref,
  type IdentitySuggestion,
  type RelatedArtifact,
} from '@/app/utils/catalog-related-artifacts';

export interface CatalogRelatedArtifactsPanelProps {
  projectId: string;
  identityGroupId?: string | null;
  relatedArtifacts?: RelatedArtifact[];
  readonly?: boolean;
  onChanged?: () => void;
}

export function CatalogRelatedArtifactsPanel({
  projectId,
  identityGroupId,
  relatedArtifacts: initialRelated = [],
  readonly = false,
  onChanged,
}: CatalogRelatedArtifactsPanelProps) {
  const [related, setRelated] = useState<RelatedArtifact[]>(initialRelated);
  const [suggestions, setSuggestions] = useState<IdentitySuggestion[]>([]);
  const [loadingSuggestions, setLoadingSuggestions] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);

  useEffect(() => {
    setRelated(initialRelated);
  }, [initialRelated]);

  const loadSuggestions = useCallback(async () => {
    setLoadingSuggestions(true);
    try {
      const res = await fetch(`/api/identity/projects/${encodeURIComponent(projectId)}/suggestions`);
      const data = await res.json();
      if (!res.ok || !data.success) {
        throw new Error(data.error || 'Failed to load suggestions');
      }
      setSuggestions(Array.isArray(data.suggestions) ? data.suggestions : []);
    } catch (error) {
      console.error(error);
      toast.error('Could not load link suggestions');
    } finally {
      setLoadingSuggestions(false);
    }
  }, [projectId]);

  const linkProject = useCallback(
    async (relatedProjectId: string) => {
      setBusyId(relatedProjectId);
      try {
        const res = await fetch('/api/identity/link', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ projectId, relatedProjectId }),
        });
        const data = await res.json();
        if (!res.ok || !data.success) {
          throw new Error(data.error || 'Link failed');
        }
        setRelated(Array.isArray(data.relatedArtifacts) ? data.relatedArtifacts : []);
        setSuggestions((prev) => prev.filter((s) => s.projectId !== relatedProjectId));
        toast.success('Artifacts linked');
        onChanged?.();
      } catch (error) {
        console.error(error);
        toast.error(error instanceof Error ? error.message : 'Link failed');
      } finally {
        setBusyId(null);
      }
    },
    [projectId, onChanged],
  );

  const unlinkProject = useCallback(
    async (relatedProjectId: string) => {
      setBusyId(relatedProjectId);
      try {
        const res = await fetch('/api/identity/link', {
          method: 'DELETE',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ projectId, relatedProjectId }),
        });
        const data = await res.json();
        if (!res.ok || !data.success) {
          throw new Error(data.error || 'Unlink failed');
        }
        setRelated(Array.isArray(data.relatedArtifacts) ? data.relatedArtifacts : []);
        toast.success('Artifact unlinked');
        onChanged?.();
      } catch (error) {
        console.error(error);
        toast.error(error instanceof Error ? error.message : 'Unlink failed');
      } finally {
        setBusyId(null);
      }
    },
    [projectId, onChanged],
  );

  const hasRelated = related.length > 0;

  return (
    <section
      className={`${dashboardPanelClass} p-6`}
      data-testid="catalog-detail-related-artifacts"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400">
          Related artifacts
        </h2>
        {identityGroupId ? (
          <Link
            href={allRepresentationsHref(identityGroupId)}
            className="text-xs font-medium text-indigo-600 hover:underline dark:text-indigo-400"
            data-testid="catalog-show-all-representations"
          >
            Show all representations
          </Link>
        ) : null}
      </div>

      {hasRelated ? (
        <ul className="mt-3 space-y-2">
          {related.map((artifact) => (
            <li
              key={artifact.projectId}
              className="flex flex-wrap items-center gap-2 rounded-lg border border-gray-200 px-3 py-2 dark:border-gray-700"
            >
              <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
                {artifact.deleted ? (
                  <span className="font-medium text-gray-500 line-through dark:text-gray-400">
                    {artifact.name}
                  </span>
                ) : (
                  <Link
                    href={relatedArtifactHref(artifact)}
                    className="font-medium text-indigo-700 hover:underline dark:text-indigo-300"
                  >
                    {artifact.name}
                  </Link>
                )}
                {artifact.sourceFormat ? <FormatPill format={artifact.sourceFormat} /> : null}
                {artifact.protocol ? <ProtocolPill protocol={artifact.protocol} /> : null}
                <span className="text-xs text-gray-500 dark:text-gray-400">
                  {linkSourceLabel(artifact.linkSource)}
                </span>
              </div>
              {!readonly ? (
                <button
                  type="button"
                  disabled={busyId === artifact.projectId}
                  onClick={() => void unlinkProject(artifact.projectId)}
                  className="inline-flex items-center gap-1 rounded-md border border-gray-200 px-2 py-1 text-xs text-gray-600 hover:bg-gray-50 disabled:opacity-50 dark:border-gray-600 dark:text-gray-300 dark:hover:bg-gray-800"
                  data-testid={`unlink-related-${artifact.projectId}`}
                >
                  <Unlink className="h-3.5 w-3.5" aria-hidden />
                  Unlink
                </button>
              ) : null}
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-3 text-sm text-gray-500 dark:text-gray-400">
          No linked artifacts yet. Link another format of this API to group representations together.
        </p>
      )}

      {!readonly ? (
        <div className="mt-4 border-t border-gray-100 pt-4 dark:border-gray-700">
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => void loadSuggestions()}
              disabled={loadingSuggestions}
              className="inline-flex items-center gap-1.5 rounded-md border border-indigo-200 bg-indigo-50 px-2.5 py-1.5 text-xs font-medium text-indigo-700 hover:bg-indigo-100 disabled:opacity-50 dark:border-indigo-800 dark:bg-indigo-950/40 dark:text-indigo-300"
              data-testid="catalog-load-suggestions"
            >
              <Sparkles className="h-3.5 w-3.5" aria-hidden />
              {loadingSuggestions ? 'Loading suggestions…' : 'Suggest links'}
            </button>
          </div>
          {suggestions.length > 0 ? (
            <ul className="mt-3 space-y-2" data-testid="catalog-identity-suggestions">
              {suggestions.map((suggestion) => (
                <li
                  key={suggestion.projectId}
                  className="flex flex-wrap items-center gap-2 rounded-lg border border-dashed border-gray-200 px-3 py-2 dark:border-gray-700"
                >
                  <div className="min-w-0 flex-1">
                    <p className="font-medium text-gray-800 dark:text-gray-200">{suggestion.name}</p>
                    <p className="text-xs text-gray-500 dark:text-gray-400">{suggestion.reason}</p>
                  </div>
                  {suggestion.sourceFormat ? <FormatPill format={suggestion.sourceFormat} /> : null}
                  <button
                    type="button"
                    disabled={busyId === suggestion.projectId}
                    onClick={() => void linkProject(suggestion.projectId)}
                    className={cn(
                      'inline-flex items-center gap-1 rounded-md bg-indigo-600 px-2 py-1 text-xs font-medium text-white hover:bg-indigo-700 disabled:opacity-50',
                    )}
                    data-testid={`link-suggestion-${suggestion.projectId}`}
                  >
                    <Link2 className="h-3.5 w-3.5" aria-hidden />
                    Link
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

export default CatalogRelatedArtifactsPanel;
