/**
 * Unit tests for the pure MCP discovery-health client layer (V2-MCP-31.1 / MCAT-17.1, #4641).
 *
 * Exercises `mcpReliabilityUi` in isolation (no React): parsing the `health` block of an
 * `insight/reliability` payload into a defensive shape with re-derived tallies, the timeline
 * projection onto the `StackedTimeline` shape (oldest→newest, one unit per outcome band, per-code
 * failure breakdown), and the outcome/availability label helpers.
 */

import {
  mcpAvailabilityKind,
  mcpDiscoveryEventTime,
  mcpDiscoveryHealthTimeline,
  mcpDiscoveryOutcomeKind,
  mcpDiscoveryOutcomeLabel,
  mcpReliabilityHealthFromPayload,
} from '../src/app/components/ade/dashboard/mcp/mcpReliabilityUi';

function job(
  jobId: string,
  state: string,
  outcome: string,
  createdAt: string,
  errorCode: string | null = null,
) {
  return {
    job_id: jobId,
    state,
    trigger: 'sweep',
    outcome,
    error_code: errorCode,
    created_at: createdAt,
    started_at: createdAt,
    finished_at: createdAt,
    duration_ms: state === 'failed' ? null : 100,
  };
}

describe('mcpReliabilityHealthFromPayload', () => {
  it('parses the health block and re-derives tallies + availability from the events', () => {
    const health = mcpReliabilityHealthFromPayload({
      health: {
        timeline: [
          job('j5', 'running', 'pending', '2026-07-06T15:00:00Z'),
          job('j4', 'completed', 'ok', '2026-07-06T12:00:00Z'),
          job('j3', 'failed', 'auth_required', '2026-07-06T06:00:00Z', 'auth_required'),
          job('j2', 'completed', 'ok', '2026-07-06T00:00:00Z'),
          job('j1', 'completed', 'ok', '2026-07-05T18:00:00Z'),
        ],
        window: 50,
        last_status: 'unchanged',
        last_discovered_at: '2026-07-06T12:00:00Z',
      },
    });
    expect(health).not.toBeNull();
    expect(health!.event_count).toBe(5);
    expect(health!.ok_count).toBe(3);
    expect(health!.failed_count).toBe(1);
    expect(health!.pending_count).toBe(1);
    expect(health!.terminal_count).toBe(4);
    // 3 ok / (3 ok + 1 failed) = 75%
    expect(health!.availability_pct).toBe(75);
    expect(health!.last_status).toBe('unchanged');
  });

  it('returns null availability when there are no terminal jobs', () => {
    const health = mcpReliabilityHealthFromPayload({
      health: { timeline: [job('j1', 'running', 'pending', '2026-07-06T00:00:00Z')], window: 50 },
    });
    expect(health!.terminal_count).toBe(0);
    expect(health!.availability_pct).toBeNull();
  });

  it('parses the quarantine / backoff state', () => {
    const health = mcpReliabilityHealthFromPayload({
      health: {
        timeline: [],
        window: 50,
        quarantined: true,
        quarantined_at: '2026-07-06T12:00:00Z',
        quarantine_reason: 'connect_error: refused',
        consecutive_failures: 4,
        next_discovery_after: '2026-07-06T13:00:00Z',
      },
    });
    expect(health!.quarantined).toBe(true);
    expect(health!.quarantine_reason).toBe('connect_error: refused');
    expect(health!.consecutive_failures).toBe(4);
    expect(health!.next_discovery_after).toBe('2026-07-06T13:00:00Z');
  });

  it('drops events without a job id but keeps the rest', () => {
    const health = mcpReliabilityHealthFromPayload({
      health: {
        timeline: [
          { state: 'completed', outcome: 'ok' }, // no job_id → dropped
          job('j1', 'completed', 'ok', '2026-07-06T00:00:00Z'),
        ],
        window: 50,
      },
    });
    expect(health!.event_count).toBe(1);
    expect(health!.ok_count).toBe(1);
  });

  it('returns null for an absent or malformed health block', () => {
    expect(mcpReliabilityHealthFromPayload({})).toBeNull();
    expect(mcpReliabilityHealthFromPayload({ health: null })).toBeNull();
    expect(mcpReliabilityHealthFromPayload(undefined)).toBeNull();
  });
});

describe('mcpDiscoveryHealthTimeline', () => {
  it('reverses to oldest→newest and puts one unit in each outcome band', () => {
    const health = mcpReliabilityHealthFromPayload({
      health: {
        timeline: [
          job('j3', 'completed', 'ok', '2026-07-06T12:00:00Z'),
          job('j2', 'failed', 'connect_error', '2026-07-06T06:00:00Z', 'connect_error'),
          job('j1', 'completed', 'ok', '2026-07-06T00:00:00Z'),
        ],
        window: 50,
      },
    })!;
    const timeline = mcpDiscoveryHealthTimeline(health);
    // Oldest-first: j1 (ok), j2 (failed), j3 (ok).
    expect(timeline.events.map((e) => e.job_id)).toEqual(['j1', 'j2', 'j3']);
    expect(timeline.periods[0].values).toEqual({ ok: 1, failed: 0, pending: 0 });
    expect(timeline.periods[1].values).toEqual({ ok: 0, failed: 1, pending: 0 });
    expect(timeline.hasEvents).toBe(true);
  });

  it('tallies failures by their specific code, most frequent first', () => {
    const health = mcpReliabilityHealthFromPayload({
      health: {
        timeline: [
          job('j4', 'failed', 'connect_error', '2026-07-06T12:00:00Z', 'connect_error'),
          job('j3', 'failed', 'connect_error', '2026-07-06T06:00:00Z', 'connect_error'),
          job('j2', 'failed', 'auth_required', '2026-07-06T00:00:00Z', 'auth_required'),
          job('j1', 'completed', 'ok', '2026-07-05T18:00:00Z'),
        ],
        window: 50,
      },
    })!;
    const { failures } = mcpDiscoveryHealthTimeline(health);
    expect(failures).toEqual([
      { code: 'connect_error', label: 'Unreachable', count: 2 },
      { code: 'auth_required', label: 'Auth error', count: 1 },
    ]);
  });

  it('has no periods for an empty timeline', () => {
    const health = mcpReliabilityHealthFromPayload({ health: { timeline: [], window: 50 } })!;
    const timeline = mcpDiscoveryHealthTimeline(health);
    expect(timeline.periods).toEqual([]);
    expect(timeline.hasEvents).toBe(false);
    expect(timeline.failures).toEqual([]);
  });
});

describe('outcome + availability helpers', () => {
  it('classifies outcomes into bands', () => {
    expect(mcpDiscoveryOutcomeKind('ok')).toBe('ok');
    expect(mcpDiscoveryOutcomeKind('pending')).toBe('pending');
    expect(mcpDiscoveryOutcomeKind('connect_error')).toBe('failed');
    expect(mcpDiscoveryOutcomeKind('some_new_code')).toBe('failed');
  });

  it('labels known codes and title-cases unknown ones', () => {
    expect(mcpDiscoveryOutcomeLabel('connect_error')).toBe('Unreachable');
    expect(mcpDiscoveryOutcomeLabel('auth_required')).toBe('Auth error');
    expect(mcpDiscoveryOutcomeLabel('ok')).toBe('OK');
    expect(mcpDiscoveryOutcomeLabel('some_new_code')).toBe('Some New Code');
  });

  it('buckets availability into health bands', () => {
    expect(mcpAvailabilityKind(100)).toBe('healthy');
    expect(mcpAvailabilityKind(99)).toBe('healthy');
    expect(mcpAvailabilityKind(95)).toBe('degraded');
    expect(mcpAvailabilityKind(80)).toBe('poor');
    expect(mcpAvailabilityKind(null)).toBe('unknown');
  });

  it('formats a locale-free minute-precision timestamp', () => {
    expect(mcpDiscoveryEventTime('2026-07-06T12:34:56Z')).toBe('2026-07-06 12:34');
    expect(mcpDiscoveryEventTime(null)).toBe('—');
  });
});
