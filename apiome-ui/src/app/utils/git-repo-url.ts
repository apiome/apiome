/**
 * Parse a GitHub repository URL or "owner/repo" into owner and repo name.
 * Supports https://github.com/org/repo, .git suffix, and git@github.com:org/repo.git
 */
export function parseGitHubRepoUrl(input: string): { owner: string; repo: string; fullName: string } | null {
  const trimmed = input.trim();
  if (!trimmed) return null;

  const sshForm = /^git@github\.com:([a-zA-Z0-9_.-]+)\/([a-zA-Z0-9_.-]+)(?:\.git)?$/i.exec(trimmed);
  if (sshForm) {
    const owner = sshForm[1];
    const repo = sshForm[2].replace(/\.git$/i, '');
    if (owner && repo) {
      return { owner, repo, fullName: `${owner}/${repo}` };
    }
  }

  const slashForm = /^([a-zA-Z0-9_.-]+)\/([a-zA-Z0-9_.-]+)$/.exec(trimmed);
  if (slashForm) {
    const owner = slashForm[1];
    const repo = slashForm[2].replace(/\.git$/i, '');
    return { owner, repo, fullName: `${owner}/${repo}` };
  }

  try {
    const withScheme = trimmed.includes('://') ? trimmed : `https://${trimmed}`;
    const u = new URL(withScheme);
    const host = u.hostname.toLowerCase();
    if (host !== 'github.com' && host !== 'www.github.com') {
      return null;
    }
    const parts = u.pathname.replace(/^\/+/, '').split('/').filter(Boolean);
    if (parts.length < 2) return null;
    const owner = parts[0];
    const repo = parts[1].replace(/\.git$/i, '');
    if (!owner || !repo) return null;
    return { owner, repo, fullName: `${owner}/${repo}` };
  } catch {
    return null;
  }
}
