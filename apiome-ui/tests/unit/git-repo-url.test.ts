import { parseGitHubRepoUrl } from '@/app/utils/git-repo-url';

describe('parseGitHubRepoUrl', () => {
  it('parses owner/repo', () => {
    expect(parseGitHubRepoUrl('octocat/Hello-World')).toEqual({
      owner: 'octocat',
      repo: 'Hello-World',
      fullName: 'octocat/Hello-World',
    });
  });

  it('strips .git from slash form', () => {
    expect(parseGitHubRepoUrl('org/api-specs.git')).toEqual({
      owner: 'org',
      repo: 'api-specs',
      fullName: 'org/api-specs',
    });
  });

  it('parses https github URL', () => {
    expect(parseGitHubRepoUrl('https://github.com/org/api-specs')).toEqual({
      owner: 'org',
      repo: 'api-specs',
      fullName: 'org/api-specs',
    });
  });

  it('parses URL without scheme', () => {
    expect(parseGitHubRepoUrl('github.com/org/api-specs')).toEqual({
      owner: 'org',
      repo: 'api-specs',
      fullName: 'org/api-specs',
    });
  });

  it('parses git@ form', () => {
    expect(parseGitHubRepoUrl('git@github.com:org/api-specs.git')).toEqual({
      owner: 'org',
      repo: 'api-specs',
      fullName: 'org/api-specs',
    });
  });

  it('rejects SSH git@ form with extra path segments', () => {
    expect(parseGitHubRepoUrl('git@github.com:org/a/b.git')).toBeNull();
  });

  it('returns null for non-GitHub hosts', () => {
    expect(parseGitHubRepoUrl('https://gitlab.com/org/repo')).toBeNull();
  });

  it('returns null for empty input', () => {
    expect(parseGitHubRepoUrl('')).toBeNull();
    expect(parseGitHubRepoUrl('   ')).toBeNull();
  });
});
