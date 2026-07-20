/**
 * Slate deployment control-plane client — APX-3.1 (private-suite#2456).
 *
 * The Release Center's whole design premise is that a blocked action reaches the operator as
 * a sentence rather than as a greyed-out control. That makes the client's handling of a 409
 * the most important thing here: a refusal must survive the trip as a named reason with its
 * message intact, and must never be flattened into a generic error string.
 */

import {
  getSlateEnvironment,
  getSlateRelease,
  listSlateReleases,
  promoteSlateRelease,
  rollbackSlateEnvironment,
  runSlateRetention,
} from '@lib/api/slate-releases-client';

const DIGEST = `sha256:${'a'.repeat(64)}`;

function mockResponse(status: number, body: unknown): void {
  (global.fetch as jest.Mock).mockResolvedValueOnce({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  });
}

function lastCall(): [string, RequestInit | undefined] {
  const calls = (global.fetch as jest.Mock).mock.calls;
  return calls[calls.length - 1] as [string, RequestInit | undefined];
}

beforeEach(() => {
  global.fetch = jest.fn();
});

afterEach(() => {
  jest.resetAllMocks();
});

describe('reads', () => {
  it('lists releases through the slate proxy', async () => {
    mockResponse(200, { releases: [] });
    const result = await listSlateReleases('site-1');

    expect(result.success).toBe(true);
    expect(lastCall()[0]).toBe('/api/slate/sites/site-1/releases');
  });

  it('scopes the timeline to one environment when asked', async () => {
    mockResponse(200, { releases: [] });
    await listSlateReleases('site-1', 'env-1', 25);

    const [url] = lastCall();
    expect(url).toContain('environmentId=env-1');
    expect(url).toContain('limit=25');
  });

  it('omits the query string entirely when unfiltered', async () => {
    mockResponse(200, { releases: [] });
    await listSlateReleases('site-1');

    expect(lastCall()[0]).not.toContain('?');
  });

  it('encodes ids so a slash in an id cannot escape the path', async () => {
    mockResponse(200, { releases: [] });
    await listSlateReleases('site/../evil');

    expect(lastCall()[0]).toBe('/api/slate/sites/site%2F..%2Fevil/releases');
  });

  it('returns a release with its artifact facts', async () => {
    mockResponse(200, {
      id: 'rel-1',
      artifact: { digest: DIGEST, signatureVerified: true, retained: true },
    });
    const result = await getSlateRelease('rel-1');

    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.artifact.digest).toBe(DIGEST);
    }
  });

  it('returns lane state including rollout and SLO', async () => {
    mockResponse(200, {
      id: 'env-1',
      routingVersion: 4,
      rollout: { state: 'partial', outstanding: ['Virginia'] },
      activationSlo: { state: 'breaching' },
    });
    const result = await getSlateEnvironment('env-1');

    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.rollout.state).toBe('partial');
      expect(result.data.activationSlo.state).toBe('breaching');
    }
  });
});

describe('promotion', () => {
  it('posts the release id and defaults dryRun to false', async () => {
    mockResponse(200, { applied: true, dryRun: false, plan: { rebuilds: false } });
    await promoteSlateRelease('env-1', 'rel-1');

    const [url, init] = lastCall();
    expect(url).toBe('/api/slate/environments/env-1/promote');
    expect(init?.method).toBe('POST');
    expect(JSON.parse(String(init?.body))).toEqual({
      releaseId: 'rel-1',
      dryRun: false,
      requireApproval: false,
    });
  });

  it('passes dryRun and requireApproval through', async () => {
    mockResponse(200, { applied: false, dryRun: true, plan: { rebuilds: false } });
    await promoteSlateRelease('env-1', 'rel-1', { dryRun: true, requireApproval: true });

    const body = JSON.parse(String(lastCall()[1]?.body));
    expect(body.dryRun).toBe(true);
    expect(body.requireApproval).toBe(true);
  });

  it('surfaces that a promotion never rebuilds', async () => {
    mockResponse(200, {
      applied: true,
      dryRun: false,
      plan: { action: 'promotion', rebuilds: false, artifactDigest: DIGEST },
    });
    const result = await promoteSlateRelease('env-1', 'rel-1');

    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.plan.rebuilds).toBe(false);
      expect(result.data.plan.artifactDigest).toBe(DIGEST);
    }
  });
});

describe('refusals reach the operator as sentences', () => {
  it('preserves a named refusal reason and message from a 409', async () => {
    mockResponse(409, {
      detail: {
        reason: 'not-built',
        code: 'not-built',
        message: 'This release has no artifact, so there is nothing to route to.',
      },
    });
    const result = await promoteSlateRelease('env-1', 'rel-1');

    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.refusal?.reason).toBe('not-built');
      expect(result.refusal?.message).toContain('nothing to route to');
      // Crucially NOT collapsed into a generic error string.
      expect(result.error).toBeUndefined();
    }
  });

  it('carries both routing versions on a concurrency conflict', async () => {
    mockResponse(409, {
      detail: {
        reason: 'concurrent-activation',
        message: 'Routing changed while this activation was being prepared.',
        expectedRoutingVersion: 3,
        actualRoutingVersion: 5,
      },
    });
    const result = await promoteSlateRelease('env-1', 'rel-1');

    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.refusal?.expectedRoutingVersion).toBe(3);
      expect(result.refusal?.actualRoutingVersion).toBe(5);
    }
  });

  it('handles a 409 whose detail is not nested', async () => {
    mockResponse(409, { reason: 'already-active', message: 'Already serving.' });
    const result = await promoteSlateRelease('env-1', 'rel-1');

    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.refusal?.reason).toBe('already-active');
    }
  });

  it('still produces a sentence when the payload omits one', async () => {
    // A control disabled with nothing to say is the dead end this guards against.
    mockResponse(409, { detail: { reason: 'partial-region' } });
    const result = await promoteSlateRelease('env-1', 'rel-1');

    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.refusal?.message.length).toBeGreaterThan(0);
    }
  });

  it('falls back to the code when no reason is given', async () => {
    mockResponse(409, { detail: { code: 'stale-approval', message: 'Stale.' } });
    const result = await promoteSlateRelease('env-1', 'rel-1');

    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.refusal?.reason).toBe('stale-approval');
    }
  });
});

describe('rollback', () => {
  it('sends no release id, because the control plane picks the target', async () => {
    // The UI must not be able to ask for bytes retention has already reaped.
    mockResponse(200, { applied: true, dryRun: false, plan: { action: 'rollback' } });
    await rollbackSlateEnvironment('env-1');

    const body = JSON.parse(String(lastCall()[1]?.body));
    expect(body).toEqual({ dryRun: false });
    expect(body.releaseId).toBeUndefined();
  });

  it('supports a dry run', async () => {
    mockResponse(200, { applied: false, dryRun: true, plan: { action: 'rollback' } });
    await rollbackSlateEnvironment('env-1', { dryRun: true });

    expect(JSON.parse(String(lastCall()[1]?.body)).dryRun).toBe(true);
  });

  it('surfaces no-rollback-target as a refusal', async () => {
    mockResponse(409, {
      detail: { reason: 'no-rollback-target', message: 'No retained release is available.' },
    });
    const result = await rollbackSlateEnvironment('env-1');

    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.refusal?.reason).toBe('no-rollback-target');
    }
  });
});

describe('retention', () => {
  it('sweeps one lane and reports what it reaped', async () => {
    mockResponse(200, { reaped: 3, reapedReleaseIds: ['a', 'b', 'c'], retainedReleases: 2 });
    const result = await runSlateRetention('site-1', 'env-1');

    const [url, init] = lastCall();
    expect(url).toBe('/api/slate/sites/site-1/retention?environmentId=env-1');
    expect(init?.method).toBe('POST');
    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.reaped).toBe(3);
    }
  });
});

describe('failure handling', () => {
  it('reports a server error as an error, not a refusal', async () => {
    mockResponse(500, { detail: 'Internal Server Error' });
    const result = await getSlateRelease('rel-1');

    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.error).toBe('Internal Server Error');
      expect(result.refusal).toBeUndefined();
    }
  });

  it('reports a 404 as an error', async () => {
    mockResponse(404, { detail: { code: 'release_not_found', message: 'Release not found.' } });
    const result = await getSlateRelease('missing');

    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.error).toBe('Release not found.');
    }
  });

  it('survives a non-JSON response body', async () => {
    (global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: false,
      status: 502,
      json: async () => {
        throw new Error('not json');
      },
    });
    const result = await getSlateRelease('rel-1');

    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.error).toBe('HTTP 502');
    }
  });

  it('reports a network failure rather than throwing', async () => {
    (global.fetch as jest.Mock).mockRejectedValueOnce(new Error('offline'));
    const result = await listSlateReleases('site-1');

    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.error).toBe('offline');
    }
  });
});
