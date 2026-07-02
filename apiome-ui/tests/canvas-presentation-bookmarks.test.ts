import {
  loadPresentationBookmarks,
  savePresentationBookmarks,
  isPresentationBookmark,
  presentationBookmarksStorageKey,
  clampViewportZoom,
} from '@/app/ade/studio/editor/lib/canvas-presentation-bookmarks';

describe('canvas-presentation-bookmarks', () => {
  const versionId = 'version-test-517';

  beforeEach(() => {
    localStorage.clear();
  });

  it('uses a stable storage key per version', () => {
    expect(presentationBookmarksStorageKey(versionId)).toContain(versionId);
  });

  it('round-trips bookmarks through localStorage', () => {
    const slides = [
      {
        id: 'a',
        title: 'One',
        viewport: { x: 0, y: 1, zoom: 0.5 },
        speakerNote: 'hello',
      },
    ];
    savePresentationBookmarks(versionId, slides);
    expect(loadPresentationBookmarks(versionId)).toEqual(slides);
  });

  it('rejects invalid stored JSON', () => {
    localStorage.setItem(presentationBookmarksStorageKey(versionId), 'not-json');
    expect(loadPresentationBookmarks(versionId)).toEqual([]);
  });

  it('filters out invalid items in array', () => {
    localStorage.setItem(
      presentationBookmarksStorageKey(versionId),
      JSON.stringify([
        { id: 'ok', title: 'x', viewport: { x: 0, y: 0, zoom: 1 }, speakerNote: '' },
        { bad: true },
      ])
    );
    expect(loadPresentationBookmarks(versionId)).toHaveLength(1);
    expect(loadPresentationBookmarks(versionId)[0].id).toBe('ok');
  });

  it('isPresentationBookmark validates shape', () => {
    expect(
      isPresentationBookmark({
        id: '1',
        title: 't',
        speakerNote: '',
        viewport: { x: 0, y: 0, zoom: 1 },
      })
    ).toBe(true);
    expect(isPresentationBookmark({ id: '' })).toBe(false);
    expect(isPresentationBookmark(null)).toBe(false);
  });

  it('isPresentationBookmark rejects zoom out of [0.1, 2] bounds', () => {
    const base = { id: '1', title: 't', speakerNote: '' };
    expect(isPresentationBookmark({ ...base, viewport: { x: 0, y: 0, zoom: 0 } })).toBe(false);
    expect(isPresentationBookmark({ ...base, viewport: { x: 0, y: 0, zoom: -1 } })).toBe(false);
    expect(isPresentationBookmark({ ...base, viewport: { x: 0, y: 0, zoom: 3 } })).toBe(false);
    expect(isPresentationBookmark({ ...base, viewport: { x: 0, y: 0, zoom: 0.1 } })).toBe(true);
    expect(isPresentationBookmark({ ...base, viewport: { x: 0, y: 0, zoom: 2 } })).toBe(true);
  });

  it('filters out slides with out-of-range zoom from localStorage', () => {
    localStorage.setItem(
      presentationBookmarksStorageKey(versionId),
      JSON.stringify([
        { id: 'ok', title: 'x', viewport: { x: 0, y: 0, zoom: 1 }, speakerNote: '' },
        { id: 'bad-zoom', title: 'y', viewport: { x: 0, y: 0, zoom: 0 }, speakerNote: '' },
        { id: 'bad-zoom2', title: 'z', viewport: { x: 0, y: 0, zoom: 5 }, speakerNote: '' },
      ])
    );
    const loaded = loadPresentationBookmarks(versionId);
    expect(loaded).toHaveLength(1);
    expect(loaded[0].id).toBe('ok');
  });

  it('clampViewportZoom clamps zoom to [0.1, 2]', () => {
    expect(clampViewportZoom({ x: 0, y: 0, zoom: 0 }).zoom).toBeCloseTo(0.1);
    expect(clampViewportZoom({ x: 0, y: 0, zoom: -5 }).zoom).toBeCloseTo(0.1);
    expect(clampViewportZoom({ x: 0, y: 0, zoom: 5 }).zoom).toBeCloseTo(2);
    expect(clampViewportZoom({ x: 0, y: 0, zoom: 1 }).zoom).toBeCloseTo(1);
    expect(clampViewportZoom({ x: 10, y: 20, zoom: 1.5 })).toEqual({ x: 10, y: 20, zoom: 1.5 });
  });
});
