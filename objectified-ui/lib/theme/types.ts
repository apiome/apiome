export type ThemeModeName = 'light' | 'dark' | 'system';

/** Optional overrides for the six primary palette tokens from the issue spec. */
export interface ThemePaletteOverrides {
  primary?: string;
  secondary?: string;
  accent?: string;
  background?: string;
  surface?: string;
  text?: string;
}

export interface ThemePreferencePayload {
  theme: ThemeModeName;
  overrides?: ThemePaletteOverrides;
}

export const THEME_CHANGED_EVENT = 'theme-changed';

export type ThemeChangedDetail = {
  theme: ThemeModeName;
  /** Effective light/dark when mode is system */
  resolved: 'light' | 'dark';
  overrides: ThemePaletteOverrides;
};
