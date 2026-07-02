/**
 * Namespaced localStorage keys for Studio canvas preferences (#2641).
 * Keep in sync with Designer defaults in StudioContext — if Designer defaults change, update Paths seeding and this comment.
 *
 * | Preference              | Designer key                         | Paths key                         |
 * |-------------------------|--------------------------------------|-----------------------------------|
 * | Grid size (px)          | studio.designer.gridSize             | studio.paths.gridSize             |
 * | Snap to grid            | studio.designer.snapToGrid           | studio.paths.snapToGrid           |
 * | Grid style              | studio.designer.gridStyle            | studio.paths.gridStyle            |
 * | Show grid               | studio.designer.showGrid             | studio.paths.showGrid             |
 * | Smart guides            | studio.designer.smartGuidesEnabled   | studio.paths.smartGuidesEnabled   |
 * | Click-to-focus          | studio.designer.clickToFocusEnabled  | studio.paths.clickToFocusEnabled  |
 * | LOD                     | studio.designer.lodEnabled           | studio.paths.lodEnabled           |
 * | Auto-save layout        | studio.designer.autoSaveLayoutEnabled| studio.paths.autoSaveLayoutEnabled|
 * | Auto-save interval (s)  | studio.designer.autoSaveLayoutIntervalSeconds | studio.paths.autoSaveLayoutIntervalSeconds |
 * | Edge styling (JSON)     | studio.designer.edgeStyling          | studio.paths.edgeStyling          |
 * | Edge routing            | studio.designer.edgeRouting          | studio.paths.edgeRouting          |
 * | Edge animation          | studio.designer.edgeAnimation        | studio.paths.edgeAnimation        |
 * | Canvas background (JSON)| studio.designer.canvasBackground     | studio.paths.canvasBackground     |
 */

import type {
  CanvasBackgroundOptions,
  EdgeAnimationType,
  EdgeRoutingType,
  EdgeStylingOptions,
} from '../StudioContext';

export type StudioCanvasSurface = 'designer' | 'paths';

export const STUDIO_DESIGNER_PREFIX = 'studio.designer';
export const STUDIO_PATHS_PREFIX = 'studio.paths';

/** Legacy keys (pre-#2641) shared by Designer and Paths — migrate into studio.designer.* once. */
export const LEGACY_CANVAS_PREF_KEYS = [
  'gridSize',
  'snapToGrid',
  'gridStyle',
  'showGrid',
  'smartGuidesEnabled',
  'clickToFocusEnabled',
  'lodEnabled',
  'autoSaveLayoutEnabled',
  'autoSaveLayoutIntervalSeconds',
  'edgeStyling',
  'edgeRouting',
  'edgeAnimation',
  'canvasBackground',
] as const;

const MIGRATION_FLAG_KEY = 'studio.designer.migratedFromLegacyV1';

export function getCanvasSurfaceFromPathname(pathname: string | null): StudioCanvasSurface {
  if (pathname?.includes('/paths')) {
    return 'paths';
  }
  return 'designer';
}

export function studioCanvasPrefStorageKey(surface: StudioCanvasSurface, suffix: string): string {
  return surface === 'paths' ? `${STUDIO_PATHS_PREFIX}.${suffix}` : `${STUDIO_DESIGNER_PREFIX}.${suffix}`;
}

function nsKey(surface: StudioCanvasSurface, suffix: string): string {
  return studioCanvasPrefStorageKey(surface, suffix);
}

function defaultEdgeStyling(): EdgeStylingOptions {
  return {
    directReferences: 'solid',
    optionalReferences: 'dashed',
    weakReferences: 'dotted',
    bidirectional: 'double',
    directColor: '#64748b',
    optionalColor: '#f97316',
    weakColor: '#8b5cf6',
    bidirectionalColor: '#ec4899',
    directArrowStyle: 'arrow',
    optionalArrowStyle: 'arrow',
    weakArrowStyle: 'arrow',
    bidirectionalArrowStyle: 'arrow',
  };
}

function defaultCanvasBackground(): CanvasBackgroundOptions {
  return {
    type: 'grid',
    solidColor: '#f8fafc',
    gridColor: '#6366f1',
    gridOpacity: 0.15,
    imageUrl: '',
    imageOpacity: 0.5,
    imageFit: 'cover',
    gradientFrom: '#f8fafc',
    gradientTo: '#e2e8f0',
    gradientDirection: 'to-br',
    textureType: 'noise',
    textureOpacity: 0.1,
    textureColor: '#64748b',
    backgroundOpacity: 1,
    backgroundBlur: 0,
  };
}

export interface LoadedCanvasPrefsBundle {
  gridSize: number;
  snapToGrid: boolean;
  gridStyle: 'dots' | 'lines' | 'cross';
  showGrid: boolean;
  smartGuidesEnabled: boolean;
  clickToFocusEnabled: boolean;
  lodEnabled: boolean;
  autoSaveLayoutEnabled: boolean;
  autoSaveLayoutIntervalSeconds: number;
  edgeStyling: EdgeStylingOptions;
  edgeRouting: EdgeRoutingType;
  edgeAnimation: EdgeAnimationType;
  canvasBackground: CanvasBackgroundOptions;
}

export const DEFAULT_LOADED_CANVAS_PREFS: LoadedCanvasPrefsBundle = {
  gridSize: 20,
  snapToGrid: true,
  gridStyle: 'dots',
  showGrid: true,
  smartGuidesEnabled: true,
  clickToFocusEnabled: true,
  lodEnabled: false,
  autoSaveLayoutEnabled: false,
  autoSaveLayoutIntervalSeconds: 30,
  edgeStyling: defaultEdgeStyling(),
  edgeRouting: 'bezier',
  edgeAnimation: 'none',
  canvasBackground: defaultCanvasBackground(),
};

function parseBool(raw: string | null, fallback: boolean): boolean {
  if (raw == null) return fallback;
  try {
    return JSON.parse(raw);
  } catch {
    return fallback;
  }
}

function readEdgeStyling(storage: Storage, surface: StudioCanvasSurface): EdgeStylingOptions {
  const defaults = defaultEdgeStyling();
  const raw = storage.getItem(nsKey(surface, 'edgeStyling'));
  if (!raw) return defaults;
  try {
    const parsed = JSON.parse(raw);
    return { ...defaults, ...parsed };
  } catch {
    return defaults;
  }
}

function readCanvasBackground(storage: Storage, surface: StudioCanvasSurface): CanvasBackgroundOptions {
  const defaults = defaultCanvasBackground();
  const raw = storage.getItem(nsKey(surface, 'canvasBackground'));
  if (!raw) return defaults;
  try {
    const parsed = JSON.parse(raw);
    return { ...defaults, ...parsed };
  } catch {
    return defaults;
  }
}

/** One-time copy from legacy keys into studio.designer.* (browser only). */
export function migrateLegacyCanvasPrefsToDesignerNamespace(storage: Storage = localStorage): void {
  if (typeof window === 'undefined') return;
  try {
    if (storage.getItem(MIGRATION_FLAG_KEY) === '1') return;
    if (storage.getItem(nsKey('designer', 'gridSize'))) {
      storage.setItem(MIGRATION_FLAG_KEY, '1');
      return;
    }
    const hasLegacy = LEGACY_CANVAS_PREF_KEYS.some((k) => storage.getItem(k) != null);
    if (!hasLegacy) {
      storage.setItem(MIGRATION_FLAG_KEY, '1');
      return;
    }

    const g = storage.getItem('gridSize');
    if (g) storage.setItem(nsKey('designer', 'gridSize'), g);
    const sg = storage.getItem('snapToGrid');
    if (sg != null) storage.setItem(nsKey('designer', 'snapToGrid'), sg);
    const gs = storage.getItem('gridStyle');
    if (gs) storage.setItem(nsKey('designer', 'gridStyle'), gs);
    const sh = storage.getItem('showGrid');
    if (sh != null) storage.setItem(nsKey('designer', 'showGrid'), sh);
    const sm = storage.getItem('smartGuidesEnabled');
    if (sm != null) storage.setItem(nsKey('designer', 'smartGuidesEnabled'), sm);
    const cf = storage.getItem('clickToFocusEnabled');
    if (cf != null) storage.setItem(nsKey('designer', 'clickToFocusEnabled'), cf);
    const lod = storage.getItem('lodEnabled');
    if (lod != null) storage.setItem(nsKey('designer', 'lodEnabled'), lod);
    const as = storage.getItem('autoSaveLayoutEnabled');
    if (as != null) storage.setItem(nsKey('designer', 'autoSaveLayoutEnabled'), as);
    const asi = storage.getItem('autoSaveLayoutIntervalSeconds');
    if (asi) storage.setItem(nsKey('designer', 'autoSaveLayoutIntervalSeconds'), asi);
    const es = storage.getItem('edgeStyling');
    if (es) storage.setItem(nsKey('designer', 'edgeStyling'), es);
    const er = storage.getItem('edgeRouting');
    if (er) storage.setItem(nsKey('designer', 'edgeRouting'), er);
    const ea = storage.getItem('edgeAnimation');
    if (ea) storage.setItem(nsKey('designer', 'edgeAnimation'), ea);
    const cb = storage.getItem('canvasBackground');
    if (cb) storage.setItem(nsKey('designer', 'canvasBackground'), cb);

    storage.setItem(MIGRATION_FLAG_KEY, '1');
  } catch {
    /* ignore quota / private mode */
  }
}

/**
 * If Paths has no saved prefs, copy Designer namespace so first visit matches Designer (#2641).
 */
export function seedPathsCanvasPrefsFromDesignerIfEmpty(storage: Storage = localStorage): void {
  if (typeof window === 'undefined') return;
  try {
    if (storage.getItem(nsKey('paths', 'gridSize')) != null) return;

    const suffixes = [
      'gridSize',
      'snapToGrid',
      'gridStyle',
      'showGrid',
      'smartGuidesEnabled',
      'clickToFocusEnabled',
      'lodEnabled',
      'autoSaveLayoutEnabled',
      'autoSaveLayoutIntervalSeconds',
      'edgeStyling',
      'edgeRouting',
      'edgeAnimation',
      'canvasBackground',
    ] as const;

    for (const s of suffixes) {
      const fromDesigner = storage.getItem(nsKey('designer', s));
      if (fromDesigner != null) {
        storage.setItem(nsKey('paths', s), fromDesigner);
      }
    }
  } catch {
    /* ignore */
  }
}

export function loadCanvasPrefsBundle(
  surface: StudioCanvasSurface,
  storage: Storage = localStorage
): LoadedCanvasPrefsBundle {
  const base = DEFAULT_LOADED_CANVAS_PREFS;

  const gridSizeRaw = storage.getItem(nsKey(surface, 'gridSize'));
  const gridSize = gridSizeRaw ? parseInt(gridSizeRaw, 10) : base.gridSize;
  const snapToGrid = parseBool(storage.getItem(nsKey(surface, 'snapToGrid')), base.snapToGrid);
  const gridStyleRaw = storage.getItem(nsKey(surface, 'gridStyle'));
  const gridStyle =
    gridStyleRaw === 'dots' || gridStyleRaw === 'lines' || gridStyleRaw === 'cross'
      ? gridStyleRaw
      : base.gridStyle;
  const showGrid = parseBool(storage.getItem(nsKey(surface, 'showGrid')), base.showGrid);
  const smartGuidesEnabled = parseBool(
    storage.getItem(nsKey(surface, 'smartGuidesEnabled')),
    base.smartGuidesEnabled
  );
  const clickToFocusEnabled = parseBool(
    storage.getItem(nsKey(surface, 'clickToFocusEnabled')),
    base.clickToFocusEnabled
  );
  const lodEnabled = parseBool(storage.getItem(nsKey(surface, 'lodEnabled')), base.lodEnabled);
  const autoSaveLayoutEnabled = parseBool(
    storage.getItem(nsKey(surface, 'autoSaveLayoutEnabled')),
    base.autoSaveLayoutEnabled
  );
  const intervalRaw = storage.getItem(nsKey(surface, 'autoSaveLayoutIntervalSeconds'));
  let autoSaveLayoutIntervalSeconds = base.autoSaveLayoutIntervalSeconds;
  if (intervalRaw) {
    const parsed = parseInt(intervalRaw, 10);
    if (Number.isFinite(parsed)) {
      autoSaveLayoutIntervalSeconds = Math.min(300, Math.max(10, parsed));
    }
  }

  const edgeStyling = readEdgeStyling(storage, surface);

  const erRaw = storage.getItem(nsKey(surface, 'edgeRouting'));
  const edgeRouting: EdgeRoutingType =
    erRaw && ['straight', 'bezier', 'orthogonal', 'smart'].includes(erRaw)
      ? (erRaw as EdgeRoutingType)
      : base.edgeRouting;

  const eaRaw = storage.getItem(nsKey(surface, 'edgeAnimation'));
  const edgeAnimation: EdgeAnimationType =
    eaRaw && ['none', 'flow', 'pulse', 'dash'].includes(eaRaw)
      ? (eaRaw as EdgeAnimationType)
      : base.edgeAnimation;

  const canvasBackground = readCanvasBackground(storage, surface);

  return {
    gridSize: Number.isFinite(gridSize) ? gridSize : base.gridSize,
    snapToGrid,
    gridStyle,
    showGrid,
    smartGuidesEnabled,
    clickToFocusEnabled,
    lodEnabled,
    autoSaveLayoutEnabled,
    autoSaveLayoutIntervalSeconds,
    edgeStyling,
    edgeRouting,
    edgeAnimation,
    canvasBackground,
  };
}

let cachedInitialBundle: LoadedCanvasPrefsBundle | null = null;

export function getCachedInitialCanvasPrefsBundle(
  pathname: string | null,
  storage: Storage = localStorage
): LoadedCanvasPrefsBundle {
  if (cachedInitialBundle) return cachedInitialBundle;
  if (typeof window === 'undefined') {
    cachedInitialBundle = DEFAULT_LOADED_CANVAS_PREFS;
    return cachedInitialBundle;
  }
  migrateLegacyCanvasPrefsToDesignerNamespace(storage);
  const surface = getCanvasSurfaceFromPathname(pathname ?? window.location.pathname);
  if (surface === 'paths') {
    seedPathsCanvasPrefsFromDesignerIfEmpty(storage);
  }
  cachedInitialBundle = loadCanvasPrefsBundle(surface, storage);
  return cachedInitialBundle;
}

export function resetCachedInitialCanvasPrefsBundleForTests(): void {
  cachedInitialBundle = null;
}
