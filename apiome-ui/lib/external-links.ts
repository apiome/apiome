import type { LucideIcon } from 'lucide-react';
import {
  Box,
  Globe,
  LayoutDashboard,
  Palette,
  Route,
  Sparkles,
  Layers,
  PenTool,
  Workflow,
} from 'lucide-react';
import rawConfig from '../config/external-links.json';
import { UI_STUDIO_ROUTES } from './studio-routes';

/** One commercial or partner application surfaced in nav and/or the ADE home grid. */
export type ExternalLinkEntry = {
  id: string;
  /** Label in the top platform bar (TopHeader). */
  navLabel: string;
  /** Primary title on the home application card. */
  name: string;
  /** Short category line on the home card. */
  tagline: string;
  description: string;
  href: string;
  /** Optional deep link base for post-import "open in editor" flows. */
  editorHref?: string;
  icon: string;
  accent: string;
  glow: string;
  enabled?: boolean;
  external?: boolean;
  opensNewBrowser?: boolean;
  showInNav?: boolean;
  showOnHome?: boolean;
  featureFlag?: string;
};

export type ExternalLinksConfig = {
  links: ExternalLinkEntry[];
};

export type ExternalNavItem = {
  id: string;
  label: string;
  href: string;
  enabled?: boolean;
  external?: boolean;
  opensNewBrowser?: boolean;
  featureFlag?: string;
  isActive?: (pathname: string) => boolean;
};

export type ExternalHomeCard = {
  id: string;
  name: string;
  tagline: string;
  description: string;
  href: string;
  enabled: boolean;
  external?: boolean;
  opensNewBrowser?: boolean;
  icon: LucideIcon;
  accent: string;
  glow: string;
  featureFlag?: string;
};

const KNOWN_ICONS: Record<string, LucideIcon> = {
  Box,
  Globe,
  LayoutDashboard,
  Palette,
  Route,
  Sparkles,
  Layers,
  PenTool,
  Workflow,
};

function normalizeEntry(entry: ExternalLinkEntry): ExternalLinkEntry {
  return {
    ...entry,
    enabled: entry.enabled !== false,
    external: entry.external !== false,
    showInNav: entry.showInNav !== false,
    showOnHome: entry.showOnHome !== false,
  };
}

function loadLinks(): ExternalLinkEntry[] {
  if (process.env.NODE_ENV === 'test' && testLinkOverride !== null) {
    return testLinkOverride.map(normalizeEntry).filter((link) => link.enabled);
  }
  const config = rawConfig as ExternalLinksConfig;
  if (!config?.links || !Array.isArray(config.links)) {
    return [];
  }
  return config.links.map(normalizeEntry).filter((link) => link.enabled);
}

/** @internal Jest-only override for config/external-links.json */
let testLinkOverride: ExternalLinkEntry[] | null = null;

export function __setExternalLinksForTests(links: ExternalLinkEntry[] | null): void {
  testLinkOverride = links;
}

export function resolveExternalLinkIcon(iconName: string): LucideIcon {
  return KNOWN_ICONS[iconName] ?? Box;
}

export function getExternalLinkEntries(): ExternalLinkEntry[] {
  return loadLinks();
}

export function getExternalLinkById(id: string): ExternalLinkEntry | undefined {
  return loadLinks().find((link) => link.id === id);
}

export function getExternalNavItems(): ExternalNavItem[] {
  return loadLinks()
    .filter((link) => link.showInNav)
    .map((link) => ({
      id: link.id,
      label: link.navLabel,
      href: link.href,
      enabled: link.enabled,
      external: link.external,
      opensNewBrowser: link.opensNewBrowser,
      featureFlag: link.featureFlag,
      isActive: () => false,
    }));
}

export function getExternalHomeCards(): ExternalHomeCard[] {
  return loadLinks()
    .filter((link) => link.showOnHome)
    .map((link) => ({
      id: link.id,
      name: link.name,
      tagline: link.tagline,
      description: link.description,
      href: link.href,
      enabled: link.enabled ?? true,
      external: link.external,
      opensNewBrowser: link.opensNewBrowser,
      icon: resolveExternalLinkIcon(link.icon),
      accent: link.accent,
      glow: link.glow,
      featureFlag: link.featureFlag,
    }));
}

/** Home/checklist entry for the designer app, when configured. */
export function getDesignerHomeHref(): string | null {
  const designer = getExternalLinkById('designer');
  if (designer?.href) return designer.href;
  if (process.env.NEXT_PUBLIC_STUDIO_URL?.trim()) {
    return UI_STUDIO_ROUTES.editor;
  }
  return null;
}

/** Deep link into a commercial studio editor after import completes. */
export function buildDesignerEditorHref(projectId: string, versionId: string): string | null {
  const designer = getExternalLinkById('designer');
  const base = designer?.editorHref ?? designer?.href ?? (process.env.NEXT_PUBLIC_STUDIO_URL?.trim() ? UI_STUDIO_ROUTES.editor : null);
  if (!base) {
    return null;
  }
  try {
    const url = base.startsWith('http://') || base.startsWith('https://')
      ? new URL(base)
      : new URL(base, 'http://local.invalid');
    url.searchParams.set('projectId', projectId);
    url.searchParams.set('versionId', versionId);
    return base.startsWith('http://') || base.startsWith('https://')
      ? url.toString()
      : `${url.pathname}${url.search}`;
  } catch {
    return null;
  }
}
