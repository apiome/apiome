import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '../../auth/[...nextauth]/route';
import { parseGitHubRepoUrl } from '@/app/utils/git-repo-url';

const UA = 'Apiome-RepositoryUrlTest/1.0';

function parseGitLabProjectPath(input: string): { apiOrigin: string; projectPath: string } | null {
  try {
    const u = new URL(input.trim());
    const host = u.hostname.toLowerCase();
    if (!host) return null;
    const path = u.pathname
      .replace(/^\/+/, '')
      .replace(/\.git$/i, '')
      .replace(/\/$/, '');
    if (!path || path.split('/').length < 2) return null;
    const origin = `${u.protocol}//${u.host}`;
    return { apiOrigin: origin, projectPath: path };
  } catch {
    return null;
  }
}

function parseBitbucketRepo(input: string): { workspace: string; repo: string } | null {
  try {
    const u = new URL(input.trim());
    const host = u.hostname.toLowerCase();
    if (host !== 'bitbucket.org' && host !== 'www.bitbucket.org') return null;
    const parts = u.pathname.split('/').filter(Boolean);
    if (parts.length < 2) return null;
    const workspace = parts[0];
    const repo = parts[1].replace(/\.git$/i, '');
    if (!workspace || !repo) return null;
    return { workspace, repo };
  } catch {
    return null;
  }
}

async function tryHeadOrGet(url: string): Promise<{ ok: boolean; message: string }> {
  const signal = AbortSignal.timeout(12_000);
  let res = await fetch(url, {
    method: 'HEAD',
    redirect: 'follow',
    signal,
    headers: { 'User-Agent': UA },
  }).catch(() => null as Response | null);

  if (res && (res.status === 405 || res.status === 501)) {
    res = await fetch(url, {
      method: 'GET',
      redirect: 'follow',
      signal,
      headers: { 'User-Agent': UA, Range: 'bytes=0-0' },
    }).catch(() => null);
  }

  if (!res) {
    return { ok: false, message: 'Could not reach this URL (network error or timeout).' };
  }
  if (res.ok || res.status === 206) {
    return { ok: true, message: 'URL responded successfully (reachability check only).' };
  }
  if (res.status >= 400 && res.status < 500) {
    return { ok: false, message: `Server returned HTTP ${res.status}. The URL may be private or invalid.` };
  }
  return { ok: false, message: `Unexpected HTTP ${res.status} from server.` };
}

export async function POST(request: NextRequest) {
  const session = await getServerSession(authOptions);
  const userId = (session?.user as { user_id?: string } | undefined)?.user_id;
  if (!userId) {
    return NextResponse.json({ ok: false, message: 'Unauthorized' }, { status: 401 });
  }

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ ok: false, message: 'Invalid JSON body' }, { status: 400 });
  }
  const urlStr = typeof body === 'object' && body && 'url' in body ? String((body as { url: unknown }).url).trim() : '';
  if (!urlStr) {
    return NextResponse.json({ ok: false, message: 'URL is required.' }, { status: 400 });
  }
  if (!/^https:\/\//i.test(urlStr)) {
    return NextResponse.json({ ok: false, message: 'Only HTTPS clone URLs are supported for public registration.' }, { status: 400 });
  }

  try {
    void new URL(urlStr);
  } catch {
    return NextResponse.json({ ok: false, message: 'Invalid URL format.' }, { status: 400 });
  }

  const gh = parseGitHubRepoUrl(urlStr);
  if (gh) {
    const apiUrl = `https://api.github.com/repos/${encodeURIComponent(gh.owner)}/${encodeURIComponent(gh.repo)}`;
    const r = await fetch(apiUrl, {
      headers: {
        Accept: 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
        'User-Agent': UA,
      },
    });
    if (r.status === 200) {
      const j = (await r.json()) as { full_name?: string; private?: boolean; default_branch?: string };
      const vis = j.private ? 'private' : 'public';
      return NextResponse.json({
        ok: true,
        message: `GitHub repository found: ${j.full_name ?? gh.fullName} (${vis}). Default branch: ${j.default_branch ?? 'main'}.`,
      });
    }
    if (r.status === 404) {
      return NextResponse.json({
        ok: false,
        message: 'GitHub returned 404 — repository may not exist, may be private, or may require authentication.',
      });
    }
    if (r.status === 403) {
      return NextResponse.json({
        ok: false,
        message: 'GitHub blocked the request (rate limit or forbidden). Try again in a minute or use a linked account.',
      });
    }
    return NextResponse.json({ ok: false, message: `GitHub API error: HTTP ${r.status}` });
  }

  const bb = parseBitbucketRepo(urlStr);
  if (bb) {
    const apiUrl = `https://api.bitbucket.org/2.0/repositories/${encodeURIComponent(bb.workspace)}/${encodeURIComponent(bb.repo)}`;
    const r = await fetch(apiUrl, { headers: { 'User-Agent': UA } });
    if (r.status === 200) {
      const j = (await r.json()) as { full_name?: string; is_private?: boolean };
      return NextResponse.json({
        ok: true,
        message: `Bitbucket repository found: ${j.full_name ?? `${bb.workspace}/${bb.repo}`} (${j.is_private ? 'private' : 'public'}).`,
      });
    }
    if (r.status === 404) {
      return NextResponse.json({
        ok: false,
        message: 'Bitbucket returned 404 — repository may not exist or may be private.',
      });
    }
    return NextResponse.json({ ok: false, message: `Bitbucket API error: HTTP ${r.status}` });
  }

  const gl = parseGitLabProjectPath(urlStr);
  if (gl && /gitlab/i.test(new URL(urlStr).hostname)) {
    const apiUrl = `${gl.apiOrigin}/api/v4/projects/${encodeURIComponent(gl.projectPath)}`;
    const r = await fetch(apiUrl, { headers: { 'User-Agent': UA } });
    if (r.status === 200) {
      const j = (await r.json()) as { path_with_namespace?: string; visibility?: string; default_branch?: string };
      return NextResponse.json({
        ok: true,
        message: `GitLab project found: ${j.path_with_namespace ?? gl.projectPath} (${j.visibility ?? 'unknown'}). Default branch: ${j.default_branch ?? 'main'}.`,
      });
    }
    if (r.status === 404) {
      return NextResponse.json({
        ok: false,
        message: 'GitLab returned 404 — project may not exist or may be private.',
      });
    }
    return NextResponse.json({ ok: false, message: `GitLab API error: HTTP ${r.status}` });
  }

  const generic = await tryHeadOrGet(urlStr);
  return NextResponse.json(generic);
}
