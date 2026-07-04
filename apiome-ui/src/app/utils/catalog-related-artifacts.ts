/**
 * Cross-format API identity types and helpers (MFI-6.4, #4410).
 */

export interface RelatedArtifact {
  projectId: string;
  name: string;
  slug: string;
  publishable?: boolean;
  sourceFormat?: string | null;
  protocol?: string | null;
  linkSource?: 'manual' | 'conversion' | string;
  deleted?: boolean;
}

export interface IdentitySuggestion {
  projectId: string;
  name: string;
  slug: string;
  publishable?: boolean;
  sourceFormat?: string | null;
  protocol?: string | null;
  reason: string;
  score: number;
}

/** Navigate to a related artifact — catalog items vs publishable projects. */
export function relatedArtifactHref(artifact: RelatedArtifact): string {
  if (artifact.publishable) {
    return `/ade/dashboard/versions?projectId=${encodeURIComponent(artifact.projectId)}`;
  }
  return `/ade/dashboard/catalog/${encodeURIComponent(artifact.projectId)}`;
}

/** Browse facet: all representations in the same identity group. */
export function allRepresentationsHref(identityGroupId: string): string {
  return `/ade/dashboard/catalog?identityGroupId=${encodeURIComponent(identityGroupId)}`;
}

export function linkSourceLabel(linkSource?: string | null): string {
  if (linkSource === 'conversion') return 'Converted';
  return 'Linked';
}
