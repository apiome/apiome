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

    const userId = (session.user as any).user_id;

    if (!userId) {
      return NextResponse.json({ error: 'User ID not found in session' }, { status: 401 });
    }

    const searchParams = request.nextUrl.searchParams;
    const accountId = searchParams.get('accountId');
    const repo = searchParams.get('repo');
    const path = searchParams.get('path');
    const branch = searchParams.get('branch') || 'main';

    if (!accountId || !repo || !path) {
      return NextResponse.json({ error: 'Account ID, repo, and path are required' }, { status: 400 });
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

    // Call GitHub API to get file content
    const url = `https://api.github.com/repos/${repo}/contents/${path}?ref=${branch}`;

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
          { error: 'File not found' },
          { status: 404 }
        );
      }

      return NextResponse.json(
        { error: `GitHub API error: ${githubResponse.statusText}` },
        { status: githubResponse.status }
      );
    }

    const fileData = await githubResponse.json();

    // Check if it's a file (not a directory)
    if (fileData.type !== 'file') {
      return NextResponse.json(
        { error: 'The specified path is not a file' },
        { status: 400 }
      );
    }

    // GitHub API returns content as base64 encoded
    if (!fileData.content) {
      return NextResponse.json(
        { error: 'File content not available' },
        { status: 404 }
      );
    }

    // Decode base64 content
    const content = Buffer.from(fileData.content, 'base64').toString('utf-8');

    return NextResponse.json({
      content,
      name: fileData.name,
      path: fileData.path,
      size: fileData.size,
      sha: fileData.sha
    });
  } catch (error: any) {
    console.error('Error fetching GitHub file content:', error);
    return NextResponse.json(
      { error: error.message || 'Failed to fetch file content' },
      { status: 500 }
    );
  }
}

