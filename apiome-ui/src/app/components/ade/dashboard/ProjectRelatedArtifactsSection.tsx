'use client';

/**
 * Fetches a publishable Project and renders the related-artifacts panel (MFI-6.4, #4410).
 */

import { useCallback, useEffect, useState } from 'react';
import { CatalogRelatedArtifactsPanel } from '@/app/components/ade/dashboard/catalog/CatalogRelatedArtifactsPanel';
import type { RelatedArtifact } from '@/app/utils/catalog-related-artifacts';

export interface ProjectRelatedArtifactsSectionProps {
  projectId: string;
}

export function ProjectRelatedArtifactsSection({ projectId }: ProjectRelatedArtifactsSectionProps) {
  const [identityGroupId, setIdentityGroupId] = useState<string | null>(null);
  const [relatedArtifacts, setRelatedArtifacts] = useState<RelatedArtifact[]>([]);
  const [loaded, setLoaded] = useState(false);

  const reload = useCallback(async () => {
    const res = await fetch(`/api/projects/${encodeURIComponent(projectId)}`);
    const data = await res.json();
    if (!res.ok || !data.success || !data.project) {
      setLoaded(true);
      return;
    }
    const project = data.project as {
      identityGroupId?: string | null;
      relatedArtifacts?: RelatedArtifact[];
    };
    setIdentityGroupId(project.identityGroupId ?? null);
    setRelatedArtifacts(Array.isArray(project.relatedArtifacts) ? project.relatedArtifacts : []);
    setLoaded(true);
  }, [projectId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  if (!loaded) {
    return null;
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
