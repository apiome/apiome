'use client';

/**
 * Fetches a publishable Project and renders the related-artifacts panel (MFI-6.4, #4410).
 *
 * While the project reads, a card-shaped placeholder holds the panel's place; a failed read is an
 * `ErrorState` with a retry rather than an empty panel that reads as "no linked artifacts"
 * (RC6-H3, #6210).
 */

import { useCallback, useEffect, useState } from 'react';
import { CatalogRelatedArtifactsPanel } from '@/app/components/ade/dashboard/catalog/CatalogRelatedArtifactsPanel';
import { ErrorState } from '@/app/components/ui/ErrorState';
import { LoadingState } from '@/app/components/ui/LoadingState';
import { SkeletonCard } from '@/app/components/ui/Skeleton';
import type { RelatedArtifact } from '@/app/utils/catalog-related-artifacts';

export interface ProjectRelatedArtifactsSectionProps {
  projectId: string;
}

export function ProjectRelatedArtifactsSection({ projectId }: ProjectRelatedArtifactsSectionProps) {
  const [identityGroupId, setIdentityGroupId] = useState<string | null>(null);
  const [relatedArtifacts, setRelatedArtifacts] = useState<RelatedArtifact[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      const res = await fetch(`/api/projects/${encodeURIComponent(projectId)}`);
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.success || !data.project) {
        throw new Error(typeof data.error === 'string' && data.error ? data.error : `The project could not be read (${res.status}).`);
      }
      const project = data.project as {
        identityGroupId?: string | null;
        relatedArtifacts?: RelatedArtifact[];
      };
      setIdentityGroupId(project.identityGroupId ?? null);
      setRelatedArtifacts(Array.isArray(project.relatedArtifacts) ? project.relatedArtifacts : []);
      setError(null);
    } catch (e) {
      setError(e instanceof Error && e.message ? e.message : 'The project could not be read.');
    } finally {
      setLoaded(true);
    }
  }, [projectId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  if (!loaded) {
    return (
      <LoadingState
        message="Loading related artifacts…"
        data-testid="related-artifacts-loading"
        skeleton={<SkeletonCard />}
      />
    );
  }

  if (error) {
    return (
      <ErrorState
        variant="compact"
        title="Couldn't load related artifacts"
        description={error}
        onRetry={() => void reload()}
        data-testid="related-artifacts-error"
      />
    );
  }

  return (
    <CatalogRelatedArtifactsPanel
      projectId={projectId}
      identityGroupId={identityGroupId}
      relatedArtifacts={relatedArtifacts}
      onChanged={() => void reload()}
    />
  );
}

export default ProjectRelatedArtifactsSection;
