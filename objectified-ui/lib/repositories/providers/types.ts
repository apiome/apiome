export type RepositoryProviderId = 'github' | 'gitlab' | 'bitbucket' | 'azure_devops';

export interface ListReposOpts {
  perPage?: number;
  page?: number;
  sort?: 'created' | 'updated' | 'pushed' | 'full_name';
  visibility?: 'all' | 'public' | 'private';
}

export interface RepoRef {
  owner: string;
  name: string;
}

export interface RepoSummary {
  id: string;
  name: string;
  fullName: string;
  description: string | null;
  isPrivate: boolean;
  defaultBranch: string;
  htmlUrl: string;
  updatedAt: string | null;
}

export interface RepoDetail extends RepoSummary {}

export interface BranchInfo {
  name: string;
  commitSha: string;
  isProtected: boolean;
}

export interface TreeEntry {
  path: string;
  type: 'file' | 'dir' | 'symlink' | 'submodule';
  sha: string;
  sizeBytes: number;
}

export interface WebhookTarget {
  url: string;
  events: string[];
}

export type RepositoryProviderErrorCode =
  | 'RATE_LIMITED'
  | 'UNAUTHORIZED'
  | 'NOT_FOUND'
  | 'NETWORK'
  | 'UNKNOWN';
