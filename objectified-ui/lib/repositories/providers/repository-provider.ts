import type {
  BranchInfo,
  ListReposOpts,
  RepoDetail,
  RepoRef,
  RepoSummary,
  RepositoryProviderErrorCode,
  RepositoryProviderId,
  TreeEntry,
  WebhookTarget,
} from './types';

export class RepositoryProviderError extends Error {
  readonly code: RepositoryProviderErrorCode;
  readonly status?: number;

  constructor(code: RepositoryProviderErrorCode, message: string, status?: number, options?: ErrorOptions) {
    super(message, options);
    this.name = 'RepositoryProviderError';
    this.code = code;
    this.status = status;
  }
}

export interface RepositoryProvider {
  readonly id: RepositoryProviderId;

  listRepositories(token: string, opts?: ListReposOpts): AsyncIterable<RepoSummary>;
  getRepository(token: string, owner: string, name: string): Promise<RepoDetail>;
  listBranches(token: string, repo: RepoRef): AsyncIterable<BranchInfo>;
  getCommitSha(token: string, repo: RepoRef, branch: string): Promise<string>;
  walkTree(token: string, repo: RepoRef, branch: string, subpath?: string): AsyncIterable<TreeEntry>;
  readFile(
    token: string,
    repo: RepoRef,
    branch: string,
    path: string
  ): Promise<{ contentBase64: string; sha: string; sizeBytes: number }>;

  registerWebhook?(token: string, repo: RepoRef, target: WebhookTarget): Promise<{ id: string; secret: string }>;
  removeWebhook?(token: string, repo: RepoRef, id: string): Promise<void>;
  verifyWebhookSignature?(secret: string, headers: Headers, body: string): boolean;
}
