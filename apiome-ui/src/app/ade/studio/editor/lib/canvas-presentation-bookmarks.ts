/**
 * Local persistence for canvas presentation slides (viewport bookmarks + speaker notes).
 * Scoped per schema version.
 */

export type CanvasPresentationViewport = { x: number; y: number; zoom: number };

export type CanvasPresentationBookmark = {
  id: string;
  title: string;
  viewport: CanvasPresentationViewport;
  speakerNote: string;
};

const STORAGE_PREFIX = 'apiome:canvas-presentation:';

export function presentationBookmarksStorageKey(versionId: string): string {
  return `${STORAGE_PREFIX}${versionId}`;
}

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

const MIN_ZOOM = 0.1;
const MAX_ZOOM = 2;

function isViewport(v: unknown): v is CanvasPresentationViewport {
  if (!isPlainObject(v)) return false;
  return (
    typeof v.x === 'number' &&
    typeof v.y === 'number' &&
    typeof v.zoom === 'number' &&
    Number.isFinite(v.x) &&
    Number.isFinite(v.y) &&
    Number.isFinite(v.zoom) &&
    v.zoom >= MIN_ZOOM &&
    v.zoom <= MAX_ZOOM
  );
}

/** Clamp a raw viewport's zoom into the ReactFlow allowed range [0.1, 2]. */
export function clampViewportZoom(vp: CanvasPresentationViewport): CanvasPresentationViewport {
  return { ...vp, zoom: Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, vp.zoom)) };
}

export function isPresentationBookmark(v: unknown): v is CanvasPresentationBookmark {
  if (!isPlainObject(v)) return false;
  return (
    typeof v.id === 'string' &&
    v.id.length > 0 &&
    typeof v.title === 'string' &&
    typeof v.speakerNote === 'string' &&
    isViewport(v.viewport)
  );
}

export function loadPresentationBookmarks(versionId: string): CanvasPresentationBookmark[] {
  if (typeof window === 'undefined') return [];
  try {
    const raw = localStorage.getItem(presentationBookmarksStorageKey(versionId));
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(isPresentationBookmark);
  } catch {
    return [];
  }
}

export function savePresentationBookmarks(
  versionId: string,
  bookmarks: CanvasPresentationBookmark[]
): void {
  if (typeof window === 'undefined') return;
  try {
    localStorage.setItem(presentationBookmarksStorageKey(versionId), JSON.stringify(bookmarks));
  } catch {
    // quota or private mode
  }
}

export function newPresentationBookmarkId(): string {
  return `slide-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}
