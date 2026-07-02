/**
 * @jest-environment jsdom
 */
import {
  getCanvasSurfaceFromPathname,
  getCachedInitialCanvasPrefsBundle,
  loadCanvasPrefsBundle,
  migrateLegacyCanvasPrefsToDesignerNamespace,
  resetCachedInitialCanvasPrefsBundleForTests,
  studioCanvasPrefStorageKey,
  seedPathsCanvasPrefsFromDesignerIfEmpty,
} from '../src/app/ade/studio/lib/studio-canvas-prefs-storage';

describe('studio-canvas-prefs-storage', () => {
  beforeEach(() => {
    localStorage.clear();
    resetCachedInitialCanvasPrefsBundleForTests();
  });

  it('maps /ade/studio/paths to paths surface', () => {
    expect(getCanvasSurfaceFromPathname('/ade/studio/paths')).toBe('paths');
  });

  it('maps editor routes to designer surface', () => {
    expect(getCanvasSurfaceFromPathname('/ade/studio/editor')).toBe('designer');
    expect(getCanvasSurfaceFromPathname('/ade/studio/code')).toBe('designer');
  });

  it('migrates legacy keys into studio.designer namespace', () => {
    localStorage.setItem('gridSize', '24');
    localStorage.setItem('snapToGrid', 'false');
    migrateLegacyCanvasPrefsToDesignerNamespace(localStorage);
    expect(localStorage.getItem(studioCanvasPrefStorageKey('designer', 'gridSize'))).toBe('24');
    expect(localStorage.getItem(studioCanvasPrefStorageKey('designer', 'snapToGrid'))).toBe('false');
  });

  it('seeds paths from designer when paths has no prefs', () => {
    localStorage.setItem(studioCanvasPrefStorageKey('designer', 'gridSize'), '32');
    seedPathsCanvasPrefsFromDesignerIfEmpty(localStorage);
    expect(localStorage.getItem(studioCanvasPrefStorageKey('paths', 'gridSize'))).toBe('32');
  });

  it('does not seed paths on designer surface load, so paths gets current designer prefs on first paths visit', () => {
    // Simulate: user opens Designer surface first (no prefs yet) — seeding should NOT happen
    const designerBundle = getCachedInitialCanvasPrefsBundle('/ade/studio/editor', localStorage);
    expect(designerBundle.gridSize).toBe(20); // default

    // User then changes Designer settings (persisted externally)
    localStorage.setItem(studioCanvasPrefStorageKey('designer', 'gridSize'), '32');

    // First visit to Paths — seeding should happen now and pick up the updated Designer value
    resetCachedInitialCanvasPrefsBundleForTests();
    const pathsBundle = getCachedInitialCanvasPrefsBundle('/ade/studio/paths', localStorage);
    expect(pathsBundle.gridSize).toBe(32);
    expect(localStorage.getItem(studioCanvasPrefStorageKey('paths', 'gridSize'))).toBe('32');
  });

  it('loadCanvasPrefsBundle reads namespaced values', () => {
    localStorage.setItem(studioCanvasPrefStorageKey('paths', 'gridSize'), '40');
    localStorage.setItem(studioCanvasPrefStorageKey('paths', 'snapToGrid'), 'true');
    const bundle = loadCanvasPrefsBundle('paths', localStorage);
    expect(bundle.gridSize).toBe(40);
    expect(bundle.snapToGrid).toBe(true);
  });
});
