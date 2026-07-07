/**
 * Unit tests for the pure "changed since last view" digest helpers (V2-MCP-30.5 / MCAT-16.5).
 *
 * Covers the defensive parser (`mcpDigestFromPayload`) and the projections the panel renders
 * (`mcpDigestState`, `mcpDigestHasBreaking`, `mcpDigestSeenDate`) — the state machine (new / changed
 * / current), the derive-total-from-parts guarantee, and malformed-payload tolerance.
 */
import {
  mcpDigestFromPayload,
  mcpDigestHasBreaking,
  mcpDigestSeenDate,
  mcpDigestState,
} from '../src/app/components/ade/dashboard/mcp/mcpDigestUi';

const CHANGED_PAYLOAD = {
  success: true,
  endpoint_id: 'ep-1',
  new_to_you: false,
  has_changes: true,
  last_seen_version_id: 'v-2',
  last_seen_version_seq: 2,
  last_seen_at: '2026-06-01T10:00:00Z',
  current_version_id: 'v-3',
  current_version_seq: 3,
  current_version_tag: '2026-07-06',
  current_type_counts: { tools: 4, resources: 2, resource_templates: 0, prompts: 1, total: 99 },
  change_counts: { added: 1, removed: 1, modified: 0, total: 99 },
  severity_counts: { breaking: 1, additive: 1, review: 0, total: 99 },
  changes: [
    { change_type: 'added', item_type: 'tool', item_name: 'summarize', severity: 'additive' },
    { change_type: 'removed', item_type: 'tool', item_name: 'legacy', severity: 'breaking' },
  ],
};

describe('mcpDigestFromPayload', () => {
  it('parses a changed digest and re-derives every total from its parts', () => {
    const digest = mcpDigestFromPayload(CHANGED_PAYLOAD);
    expect(digest).not.toBeNull();
    expect(digest!.has_changes).toBe(true);
    expect(digest!.new_to_you).toBe(false);
    expect(digest!.last_seen_version_seq).toBe(2);
    expect(digest!.current_version_id).toBe('v-3');
    // Totals are derived, so the bogus 99s in the payload are ignored.
    expect(digest!.current_type_counts.total).toBe(7);
    expect(digest!.change_counts.total).toBe(2);
    expect(digest!.severity_counts.total).toBe(2);
    expect(digest!.changes).toHaveLength(2);
  });

  it('drops change entries with no item identity', () => {
    const digest = mcpDigestFromPayload({
      ...CHANGED_PAYLOAD,
      changes: [
        { change_type: 'added', item_type: 'tool', item_name: 'keep', severity: 'additive' },
        { change_type: 'added', item_type: 'tool', severity: 'additive' }, // no item_name
        'garbage',
      ],
    });
    expect(digest!.changes.map((c) => c.item_name)).toEqual(['keep']);
  });

  it('defaults missing change fields to safe values', () => {
    const digest = mcpDigestFromPayload({
      ...CHANGED_PAYLOAD,
      changes: [{ item_name: 'mystery' }],
    });
    expect(digest!.changes[0]).toEqual({
      change_type: 'modified',
      item_type: 'tool',
      item_name: 'mystery',
      severity: 'review',
    });
  });

  it('returns null for a payload with no endpoint_id, and for non-objects', () => {
    expect(mcpDigestFromPayload({ success: true })).toBeNull();
    expect(mcpDigestFromPayload(null)).toBeNull();
    expect(mcpDigestFromPayload('nope')).toBeNull();
  });

  it('degrades an empty/partial payload to a safe up-to-date digest', () => {
    const digest = mcpDigestFromPayload({ endpoint_id: 'ep-1' });
    expect(digest!.new_to_you).toBe(false);
    expect(digest!.has_changes).toBe(false);
    expect(digest!.last_seen_at).toBeNull();
    expect(digest!.current_type_counts.total).toBe(0);
    expect(digest!.changes).toEqual([]);
  });
});

describe('digest projections', () => {
  it('maps has_changes → changed (taking priority over new_to_you)', () => {
    const digest = mcpDigestFromPayload({ ...CHANGED_PAYLOAD, new_to_you: true, has_changes: true })!;
    expect(mcpDigestState(digest)).toBe('changed');
  });

  it('maps a first visit → new', () => {
    const digest = mcpDigestFromPayload({
      ...CHANGED_PAYLOAD,
      new_to_you: true,
      has_changes: false,
    })!;
    expect(mcpDigestState(digest)).toBe('new');
  });

  it('maps no changes and not new → current', () => {
    const digest = mcpDigestFromPayload({
      ...CHANGED_PAYLOAD,
      new_to_you: false,
      has_changes: false,
    })!;
    expect(mcpDigestState(digest)).toBe('current');
  });

  it('flags breaking changes and formats the last-seen date locale-free', () => {
    const digest = mcpDigestFromPayload(CHANGED_PAYLOAD)!;
    expect(mcpDigestHasBreaking(digest)).toBe(true);
    expect(mcpDigestSeenDate(digest)).toBe('2026-06-01');
    const noBreak = mcpDigestFromPayload({
      ...CHANGED_PAYLOAD,
      severity_counts: { breaking: 0, additive: 3, review: 1, total: 99 },
      last_seen_at: null,
    })!;
    expect(mcpDigestHasBreaking(noBreak)).toBe(false);
    expect(mcpDigestSeenDate(noBreak)).toBeNull();
  });
});
