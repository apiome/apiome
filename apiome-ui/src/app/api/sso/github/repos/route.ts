import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '../../../auth/[...nextauth]/route';
import { getLinkedAccountById } from '@lib/db/helper';

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

    if (!accountId) {
      return NextResponse.json({ error: 'Account ID is required' }, { status: 400 });
    }

    // Get the linked account from database (includes access token)
    const accountResult = await getLinkedAccountById(accountId, userId);
    const accountData = JSON.parse(accountResult);

    if (!accountData.found || !accountData.account) {
      return NextResponse.json({ error: 'Linked account not found' }, { status: 404 });
    }

    const account = accountData.account;

    if (!account.access_token) {
      return NextResponse.json({ error: 'No access token found for this account' }, { status: 401 });
    }

    const perPage = 100;
    const maxPages = 50;
    const rawRepos: unknown[] = [];

    for (let page = 1; page <= maxPages; page += 1) {
      const githubResponse = await fetch(
        `https://api.github.com/user/repos?sort=updated&per_page=${perPage}&page=${page}`,
        {
          headers: {
            Authorization: `Bearer ${account.access_token}`,
            Accept: 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28',
          },
        }
      );

      if (!githubResponse.ok) {
        const errorText = await githubResponse.text();
        console.error('GitHub API error:', githubResponse.status, errorText);

        if (githubResponse.status === 401) {
          return NextResponse.json(
            { error: 'GitHub access token is invalid or expired. Please re-link your account.' },
            { status: 401 }
          );
        }

        return NextResponse.json(
          { error: `GitHub API error: ${githubResponse.statusText}` },
          { status: githubResponse.status }
        );
      }

      const batch = (await githubResponse.json()) as unknown[];
      if (!Array.isArray(batch) || batch.length === 0) {
        break;
      }
      rawRepos.push(...batch);
      if (batch.length < perPage) {
        break;
      }
    }

    const formattedRepos = rawRepos.map((repo) => {
      const r = repo && typeof repo === 'object' ? (repo as Record<string, unknown>) : {};
      return {
        id: r.id,
        name: r.name,
        full_name: r.full_name,
        description: r.description,
        private: r.private,
        default_branch: r.default_branch || 'main',
        html_url: r.html_url,
        updated_at: r.updated_at,
      };
    });

    return NextResponse.json({ repositories: formattedRepos });
  } catch (error: unknown) {
    console.error('Error fetching GitHub repositories:', error);
    const message = error instanceof Error ? error.message : 'Failed to fetch repositories';
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

