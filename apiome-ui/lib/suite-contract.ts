/**
 * OSS contract between apiome-ui (host) and @suite/* commercial packages.
 * Contains types and constants only — no suite implementation.
 */

export type SuiteNavItem = {
  label: string;
  href: string;
  enabled?: boolean;
  opensNewBrowser?: boolean;
  /** When set, overrides default prefix matching for active nav state. */
  isActive?: (pathname: string) => boolean;
  /** Maps to apiome.feature_flags.name for runtime tenant gating. */
  featureFlag?: string;
};

/** Icon slugs resolved to Lucide components in the host shell. */
export type SuiteHomeCardIcon = 'palette' | 'route';

export type SuiteHomeCard = {
  id: string;
  name: string;
  tagline: string;
  description: string;
  href: string;
  enabled: boolean;
  external?: boolean;
  icon: SuiteHomeCardIcon;
  accent: string;
  glow: string;
  featureFlag?: string;
};

export type SuiteHostApi = {
  getSuiteNavItems: () => SuiteNavItem[];
  getSuiteHomeCards: () => SuiteHomeCard[];
  /** Primary designer entry path, or null when suite is not installed. */
  getSuiteDesignerHref: () => string | null;
  /** Deep link into the schema editor after import, or null when suite is not installed. */
  getSuiteEditorHref: (projectId: string, versionId: string) => string | null;
};
