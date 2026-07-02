/** Staged map-to-project selection for a repository file (Map & import flow, not yet started). */
export type RepositoryFileStagedImportTarget = {
  repositoryId: string;
  fileId: string;
  branch: string;
  blobSha: string | null;
  targetMode: 'existing' | 'new';
  existingProject?: { id: string; name: string; slug: string };
  newProject?: { name: string; slug: string };
};
