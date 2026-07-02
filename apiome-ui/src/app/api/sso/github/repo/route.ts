import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '../../../auth/[...nextauth]/route';
import { getLinkedAccountById } from '@lib/db/helper';

/** GET single repository metadata (owner/repo from URL or list). */
export async function GET(request: NextRequest) {
  try {
    const session = await getServerSession(authOptions);

    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const userId = (session.user as { user_id?: string }).user_id;

    if (!userId) {
      return NextResponse.json({ error: 'User ID not found in session' }, { status: 401 });
    }

    const searchParams = request.nextUrl.searchParams;
    const accountId = searchParams.get('accountId');
    const repo = searchParams.get('repo');

    if (!accountId || !repo) {
      return NextResponse.json({ error: 'Account ID and repo (owner/name) are required' }, { status: 400 });
    }

    const repoParts = repo.split('/');
    if (repoParts.length !== 2 || !repoParts[0] || !repoParts[1]) {
      return NextResponse.json({ error: 'repo must be in owner/repo format' }, { status: 400 });
    }
    const [repoOwner, repoName] = repoParts;

    const accountResult = await getLinkedAccountById(accountId, userId);
    const accountData = JSON.parse(accountResult);

    if (!accountData.found || !accountData.account) {
      return NextResponse.json({ error: 'Linked account not found' }, { status: 404 });
    }

    const account = accountData.account;

    if (!account.access_token) {
      return NextResponse.json({ error: 'No access token found for this account' }, { status: 401 });
    }

    const url = `https://api.github.com/repos/${encodeURIComponent(repoOwner)}/${encodeURIComponent(repoName)}`;

    const githubResponse = await fetch(url, {
      headers: {
        Authorization: `Bearer ${account.access_token}`,
        Accept: 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
      },
    });

    if (!githubResponse.ok) {
      const errorText = await githubResponse.text();
      console.error('GitHub API error:', githubResponse.status, errorText);

      if (githubResponse.status === 401) {
        return NextResponse.json(
          { error: 'GitHub access token is invalid or expired. Please re-link your account.' },
          { status: 401 }
        );
      }

      if (githubResponse.status === 404) {
        return NextResponse.json({ error: 'Repository not found or no access' }, { status: 404 });
      }

      return NextResponse.json(
        { error: `GitHub API error: ${githubResponse.statusText}` },
        { status: githubResponse.status }
      );
    }

    const r = (await githubResponse.json()) as Record<string, unknown>;

    return NextResponse.json({
      repository: {
        id: r.id,
        name: r.name,
        full_name: r.full_name,
        description: r.description,
        private: r.private,
        default_branch: r.default_branch || 'main',
        html_url: r.html_url,
        updated_at: r.updated_at,
      },
    });
  } catch (error: unknown) {
    console.error('Error fetching GitHub repo:', error);
    const message = error instanceof Error ? error.message : 'Failed to fetch repository';
    return NextResponse.json(
      { error: message },
      { status: 500 }
    );
  }
}
