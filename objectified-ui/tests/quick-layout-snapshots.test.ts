import {
  appendQuickLayoutSnapshot,
  buildQuickLayoutShareEnvelope,
  cloneQuickLayoutSnapshotForImport,
  loadQuickLayoutSnapshots,
  parseQuickLayoutShareText,
  quickLayoutSnapshotsStorageKey,
  isQuickLayoutSnapshot,
  DEFAULT_MAX_QUICK_LAYOUT_SNAPSHOTS,
  formatQuickSnapshotCaption,
  quickSnapshotCountsSummary,
  quickSnapshotListLabel,
  quickSnapshotMatchesSearch,
  quickSnapshotOptionLabel,
  stringifyQuickLayoutShareEnvelope,
  QUICK_LAYOUT_SHARE_KIND,
  TEAM_QUICK_SNAPSHOT_PINNED_LAYOUT_NAME,
  type QuickLayoutSnapshot,
} from '@/app/ade/studio/editor/lib/quick-layout-snapshots';

const samplePayload = {
  schemaVersion: 1 as const,
  viewport: { x: 0, y: 0, zoom: 1 },
  nodes: [],
  edges: [],
  groups: [],
};

function makeSnapshot(id: string, createdAt: string): QuickLayoutSnapshot {
  return {
    id,
    createdAt,
    thumbnailDataUrl: 'data:image/png;base64,AA==',
    payload: { ...samplePayload },
  };
}

describe('quick-layout-snapshots', () => {
  it('TEAM_QUICK_SNAPSHOT_PINNED_LAYOUT_NAME is a stable reserved layout name', () => {
    expect(TEAM_QUICK_SNAPSHOT_PINNED_LAYOUT_NAME).toMatch(/quick snapshot/i);
    expect(TEAM_QUICK_SNAPSHOT_PINNED_LAYOUT_NAME.trim().length).toBeGreaterThan(0);
  });

  const versionId = 'ver-quick-snap-1';
  const userId = 'user-42';

  beforeEach(() => {
    localStorage.clear();
  });

  it('builds a stable storage key including version and user', () => {
    expect(quickLayoutSnapshotsStorageKey(versionId, userId)).toBe(
      `objectified.quickCanvasSnapshots.v1:${versionId}:${userId}`
    );
  });

  it('uses anonymous bucket when userId is null', () => {
    expect(quickLayoutSnapshotsStorageKey(versionId, null)).toContain('anonymous');
  });

  it('round-trips snapshots through localStorage', () => {
    const s = makeSnapshot('a', new Date().toISOString());
    const { snapshots, persisted } = appendQuickLayoutSnapshot(versionId, userId, s);
    expect(persisted).toBe(true);
    expect(snapshots).toHaveLength(1);
    const loaded = loadQuickLayoutSnapshots(versionId, userId);
    expect(loaded).toHaveLength(1);
    expect(loaded[0].id).toBe('a');
    expect(loaded[0].payload.viewport.zoom).toBe(1);
  });

  it('returns persisted:false and retries without thumbnails when setItem throws', () => {
    const s = makeSnapshot('quota-test', new Date().toISOString());
    let callCount = 0;
    const original = Storage.prototype.setItem;
    Storage.prototype.setItem = (key: string, value: string) => {
      callCount += 1;
      // First call fails (simulates quota exceeded), second call succeeds.
      if (callCount === 1) throw new DOMException('QuotaExceededError');
      original.call(localStorage, key, value);
    };
    try {
      const { persisted } = appendQuickLayoutSnapshot(versionId, userId, s);
      // Second attempt (stripped thumbnails) should succeed.
      expect(persisted).toBe(true);
      expect(callCount).toBe(2);
      // Thumbnail should be stripped in the persisted data.
      const loaded = loadQuickLayoutSnapshots(versionId, userId);
      expect(loaded).toHaveLength(1);
      expect(loaded[0].thumbnailDataUrl).toBeUndefined();
    } finally {
      Storage.prototype.setItem = original;
    }
  });

  it('returns persisted:false when both setItem attempts throw', () => {
    const s = makeSnapshot('always-fails', new Date().toISOString());
    const original = Storage.prototype.setItem;
    Storage.prototype.setItem = () => {
      throw new DOMException('QuotaExceededError');
    };
    try {
      const { snapshots, persisted } = appendQuickLayoutSnapshot(versionId, userId, s);
      expect(persisted).toBe(false);
      // In-memory list is still returned.
      expect(snapshots).toHaveLength(1);
      // Nothing written to storage.
      expect(loadQuickLayoutSnapshots(versionId, userId)).toHaveLength(0);
    } finally {
      Storage.prototype.setItem = original;
    }
  });

  it('prepends newest snapshots', () => {
    const first = makeSnapshot('first', '2026-01-01T00:00:00.000Z');
    const second = makeSnapshot('second', '2026-01-02T00:00:00.000Z');
    appendQuickLayoutSnapshot(versionId, userId, first);
    appendQuickLayoutSnapshot(versionId, userId, second);
    const loaded = loadQuickLayoutSnapshots(versionId, userId);
    expect(loaded.map((x) => x.id)).toEqual(['second', 'first']);
  });

  it('caps snapshot count', () => {
    const max = DEFAULT_MAX_QUICK_LAYOUT_SNAPSHOTS;
    for (let i = 0; i < max + 5; i += 1) {
      appendQuickLayoutSnapshot(versionId, userId, makeSnapshot(`id-${i}`, `2026-01-01T00:00:0${i}.000Z`), {
        maxSnapshots: max,
      });
    }
    expect(loadQuickLayoutSnapshots(versionId, userId)).toHaveLength(max);
    expect(loadQuickLayoutSnapshots(versionId, userId)[0].id).toBe(`id-${max + 4}`);
  });

  it('returns empty array for invalid JSON in storage', () => {
    localStorage.setItem(quickLayoutSnapshotsStorageKey(versionId, userId), 'not-json');
    expect(loadQuickLayoutSnapshots(versionId, userId)).toEqual([]);
  });

  it('filters out invalid snapshot entries', () => {
    const ok = makeSnapshot('ok', '2026-01-01T00:00:00.000Z');
    localStorage.setItem(
      quickLayoutSnapshotsStorageKey(versionId, userId),
      JSON.stringify([ok, { id: '', createdAt: 'x', payload: {} }])
    );
    expect(loadQuickLayoutSnapshots(versionId, userId)).toHaveLength(1);
    expect(loadQuickLayoutSnapshots(versionId, userId)[0].id).toBe('ok');
  });

  it('isQuickLayoutSnapshot rejects wrong schema version', () => {
    expect(
      isQuickLayoutSnapshot({
        id: '1',
        createdAt: '2026-01-01T00:00:00.000Z',
        payload: { schemaVersion: 0, viewport: { x: 0, y: 0, zoom: 1 }, nodes: [], edges: [], groups: [] },
      })
    ).toBe(false);
  });

  it('isQuickLayoutSnapshot accepts snapshot without thumbnail', () => {
    expect(
      isQuickLayoutSnapshot({
        id: '1',
        createdAt: '2026-01-01T00:00:00.000Z',
        payload: samplePayload,
      })
    ).toBe(true);
  });

  it('isQuickLayoutSnapshot accepts snapshot with metadata strings', () => {
    expect(
      isQuickLayoutSnapshot({
        id: '1',
        createdAt: '2026-01-01T00:00:00.000Z',
        author: 'Ada',
        summary: 'Baseline',
        description: 'Before edits',
        payload: samplePayload,
      })
    ).toBe(true);
  });

  it('isQuickLayoutSnapshot rejects non-string metadata fields', () => {
    expect(
      isQuickLayoutSnapshot({
        id: '1',
        createdAt: '2026-01-01T00:00:00.000Z',
        author: 1,
        payload: samplePayload,
      })
    ).toBe(false);
  });

  it('formatQuickSnapshotCaption handles invalid dates', () => {
    expect(formatQuickSnapshotCaption('not-a-date')).toBe('Unknown time');
  });

  it('quickSnapshotCountsSummary reflects payload arrays', () => {
    const snap: QuickLayoutSnapshot = {
      id: 'x',
      createdAt: '2026-01-01T00:00:00.000Z',
      payload: {
        schemaVersion: 1,
        viewport: { x: 0, y: 0, zoom: 1 },
        nodes: [{ id: 'a' }, { id: 'b' }],
        edges: [{ id: 'e1' }],
        groups: [{ id: 'g1' }, { id: 'g2' }, { id: 'g3' }],
      },
    };
    expect(quickSnapshotCountsSummary(snap)).toBe('2 nodes · 1 edges · 3 groups');
  });

  it('quickSnapshotMatchesSearch matches id, iso time, and count tokens', () => {
    const snap = makeSnapshot('abc-unique-id', '2026-06-15T12:30:00.000Z');
    snap.payload = {
      ...samplePayload,
      nodes: [{ id: 'n1' }, { id: 'n2' }, { id: 'n3' }],
    };
    expect(quickSnapshotMatchesSearch(snap, '')).toBe(true);
    expect(quickSnapshotMatchesSearch(snap, 'unique')).toBe(true);
    expect(quickSnapshotMatchesSearch(snap, '2026-06-15')).toBe(true);
    expect(quickSnapshotMatchesSearch(snap, '3 nodes')).toBe(true);
    expect(quickSnapshotMatchesSearch(snap, '2026-06-15 3 nodes')).toBe(true);
    expect(quickSnapshotMatchesSearch(snap, 'nomatch-xyz-123')).toBe(false);
  });

  it('quickSnapshotMatchesSearch matches author, summary, and description', () => {
    const snap = makeSnapshot('x', '2026-01-01T00:00:00.000Z');
    snap.author = 'River Tam';
    snap.summary = 'Auth refactor';
    snap.description = 'Moved guards to middleware';
    expect(quickSnapshotMatchesSearch(snap, 'river')).toBe(true);
    expect(quickSnapshotMatchesSearch(snap, 'refactor')).toBe(true);
    expect(quickSnapshotMatchesSearch(snap, 'middleware')).toBe(true);
  });

  it('quickSnapshotListLabel prefers trimmed summary over formatted time', () => {
    const snap = makeSnapshot('x', '2026-06-15T12:30:00.000Z');
    snap.summary = '  My label  ';
    expect(quickSnapshotListLabel(snap)).toBe('My label');
    delete snap.summary;
    expect(quickSnapshotListLabel(snap)).toBe(formatQuickSnapshotCaption(snap.createdAt));
  });

  it('quickSnapshotOptionLabel joins summary and caption', () => {
    const snap = makeSnapshot('x', '2026-06-15T12:30:00.000Z');
    const cap = formatQuickSnapshotCaption(snap.createdAt);
    snap.summary = 'Beta';
    expect(quickSnapshotOptionLabel(snap)).toBe(`Beta · ${cap}`);
    delete snap.summary;
    expect(quickSnapshotOptionLabel(snap)).toBe(cap);
  });

  it('buildQuickLayoutShareEnvelope includes kind and version', () => {
    const snap = makeSnapshot('snap-1', '2026-01-01T00:00:00.000Z');
    const env = buildQuickLayoutShareEnvelope('ver-a', snap);
    expect(env.kind).toBe(QUICK_LAYOUT_SHARE_KIND);
    expect(env.versionId).toBe('ver-a');
    expect(env.snapshot.id).toBe('snap-1');
  });

  it('stringifyQuickLayoutShareEnvelope round-trips with parseQuickLayoutShareText', () => {
    const snap = makeSnapshot('snap-1', '2026-01-01T00:00:00.000Z');
    const text = stringifyQuickLayoutShareEnvelope('ver-a', snap);
    const parsed = parseQuickLayoutShareText(text);
    expect(parsed.ok).toBe(true);
    if (!parsed.ok) throw new Error('expected ok');
    expect(parsed.versionId).toBe('ver-a');
    expect(parsed.snapshot.id).toBe('snap-1');
  });

  it('parseQuickLayoutShareText rejects empty or wrong kind', () => {
    expect(parseQuickLayoutShareText('').ok).toBe(false);
    expect(parseQuickLayoutShareText('{}').ok).toBe(false);
    expect(parseQuickLayoutShareText('{"kind":"other"}').ok).toBe(false);
  });

  it('cloneQuickLayoutSnapshotForImport assigns a new id', () => {
    const snap = makeSnapshot('old-id', '2026-01-01T00:00:00.000Z');
    const c = cloneQuickLayoutSnapshotForImport(snap);
    expect(c.id).not.toBe('old-id');
    expect(c.createdAt).toBe(snap.createdAt);
  });
});
