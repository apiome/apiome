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
    const repo = searchParams.get('repo');
    const path = searchParams.get('path') || '';
    const ref =
      searchParams.get('ref') ||
      searchParams.get('branch') ||
      '';

    if (!accountId || !repo) {
      return NextResponse.json({ error: 'Account ID and repo are required' }, { status: 400 });
    }

    // Get the linked account from database
    const accountResult = await getLinkedAccountById(accountId, userId);
    const accountData = JSON.parse(accountResult);

    if (!accountData.found || !accountData.account) {
      return NextResponse.json({ error: 'Linked account not found' }, { status: 404 });
    }

    const account = accountData.account;

    if (!account.access_token) {
      return NextResponse.json({ error: 'No access token found for this account' }, { status: 401 });
    }

    // Call GitHub API to get repository contents (ref = branch or tag name)
    const pathSegments = path
      ? path
          .split('/')
          .map((segment) => encodeURIComponent(segment))
          .join('/')
      : '';
    const pathPart = pathSegments ? `/${pathSegments}` : '';
    const refQuery = ref ? `?ref=${encodeURIComponent(ref)}` : '';
    const url = `https://api.github.com/repos/${repo}/contents${pathPart}${refQuery}`;

    const githubResponse = await fetch(url, {
      headers: {
        'Authorization': `Bearer ${account.access_token}`,
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28'
      }
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
        return NextResponse.json(
          { error: 'Repository or path not found' },
          { status: 404 }
        );
      }

      return NextResponse.json(
        { error: `GitHub API error: ${githubResponse.statusText}` },
        { status: githubResponse.status }
      );
    }

    const contents: unknown = await githubResponse.json();

    // GitHub API returns an array for directory contents, single object for file
    const rawList = Array.isArray(contents) ? contents : [contents];

    // Transform GitHub API response to our format
    const formattedFiles = rawList.map((item: Record<string, unknown>) => ({
      name: String(item.name ?? ''),
      path: String(item.path ?? ''),
      type: item.type === 'dir' ? 'dir' : 'file',
      size: item.size,
      sha: item.sha,
      url: item.url,
      html_url: item.html_url,
    }));

    return NextResponse.json({ files: formattedFiles });
  } catch (error: unknown) {
    console.error('Error fetching GitHub files:', error);
    const message = error instanceof Error ? error.message : 'Failed to fetch files';
    return NextResponse.json(
      { error: message },
      { status: 500 }
    );
  }
}

