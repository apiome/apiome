import type { Theme } from '@/app/config/themes';
import type { ThemePaletteOverrides } from '@lib/theme/types';

/**
 * Applies design tokens under `--obj-*` for colors, spacing, radius, typography, and shadow.
 * Color slots may be overridden by the user's custom palette; structural tokens are static.
 */
export function applyObjTokens(
  target: HTMLElement,
  theme: Theme,
  overrides: ThemePaletteOverrides
): void {
  const c = theme.colors;

  const primary = overrides.primary ?? c.primary;
  const secondary = overrides.secondary ?? c.secondary;
  const accent = overrides.accent ?? c.accent;
  const background = overrides.background ?? c.background;
  const surface = overrides.surface ?? c.card;
  const text = overrides.text ?? c.foreground;

  target.style.setProperty('--obj-color-primary', primary);
  target.style.setProperty('--obj-color-primary-fg', c.primaryForeground);
  target.style.setProperty('--obj-color-secondary', secondary);
  target.style.setProperty('--obj-color-secondary-fg', c.secondaryForeground);
  target.style.setProperty('--obj-color-accent', accent);
  target.style.setProperty('--obj-color-accent-fg', c.accentForeground);
  target.style.setProperty('--obj-color-background', background);
  target.style.setProperty('--obj-color-surface', surface);
  target.style.setProperty('--obj-color-text', text);
  target.style.setProperty('--obj-color-muted', c.muted);
  target.style.setProperty('--obj-color-muted-fg', c.mutedForeground);
  target.style.setProperty('--obj-color-border', c.border);
  target.style.setProperty('--obj-color-destructive', c.destructive);
  target.style.setProperty('--obj-color-destructive-fg', c.destructiveForeground);
  target.style.setProperty('--obj-color-card', c.card);
  target.style.setProperty('--obj-color-card-fg', c.cardForeground);
  target.style.setProperty('--obj-color-popover', c.popover);
  target.style.setProperty('--obj-color-popover-fg', c.popoverForeground);

  /* Structural tokens (issue: spacing, radius, typography, shadow) */
  target.style.setProperty('--obj-space-1', '0.25rem');
  target.style.setProperty('--obj-space-2', '0.5rem');
  target.style.setProperty('--obj-space-3', '0.75rem');
  target.style.setProperty('--obj-space-4', '1rem');
  target.style.setProperty('--obj-space-5', '1.25rem');
  target.style.setProperty('--obj-space-6', '1.5rem');
  target.style.setProperty('--obj-space-8', '2rem');

  target.style.setProperty('--obj-radius-sm', '0.25rem');
  target.style.setProperty('--obj-radius-md', '0.5rem');
  target.style.setProperty('--obj-radius-lg', '0.75rem');
  target.style.setProperty('--obj-radius-xl', '1rem');

  target.style.setProperty('--obj-font-size-xs', '0.75rem');
  target.style.setProperty('--obj-font-size-sm', '0.875rem');
  target.style.setProperty('--obj-font-size-base', '1rem');
  target.style.setProperty('--obj-font-size-lg', '1.125rem');
  target.style.setProperty('--obj-font-size-xl', '1.25rem');
  target.style.setProperty('--obj-font-size-2xl', '1.5rem');

  target.style.setProperty('--obj-line-tight', '1.25');
  target.style.setProperty('--obj-line-normal', '1.45');
  target.style.setProperty('--obj-line-relaxed', '1.6');

  target.style.setProperty('--obj-shadow-sm', '0 1px 2px rgb(15 23 42 / 0.06)');
  target.style.setProperty('--obj-shadow-md', '0 4px 6px -1px rgb(15 23 42 / 0.08)');
  target.style.setProperty('--obj-shadow-lg', '0 10px 15px -3px rgb(15 23 42 / 0.08)');
}
