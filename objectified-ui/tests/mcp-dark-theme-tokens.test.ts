/**
 * MCP dark-theme token regression guard (V2-MCP-24.10 / MCAT-10.10, #3941).
 *
 * The MCP catalog & detail screens render every color from the pure token mappings in
 * `mcpUiPrimitives`, `mcpVersionsUi`, `mcpLintUi`, the `McpBadge` cva, and the shared
 * `numeric-score-tier` bands — never from literals in the components. Those mappings already carry
 * a `dark:` variant for every on-surface tint, so the screens render correctly under the app's dark
 * theme (the theme switch applies the `.dark` class that the `dark:` utilities key off).
 *
 * This suite locks that in: it asserts every token that paints text/background/border/ring on a
 * surface carries a `dark:` variant (so a future edit can't silently drop one and re-introduce a
 * literal-color leak), that the diff add/remove/modify and grade colors stay legible on dark, and —
 * the "light theme is unchanged" criterion — that the original light utility is still present
 * alongside each dark variant. Solid, saturated chips/dots/bars (e.g. `bg-emerald-500 text-white`)
 * read in both themes by design and are asserted to stay saturated solids rather than needing a
 * dark override.
 */

import {
  mcpGradeGlyphStyle,
  mcpHealthMeta,
  type McpGradeLetter,
  type McpHealthStatus,
} from '../src/app/components/ade/dashboard/mcp/mcpUiPrimitives';
import { mcpBadgeVariants } from '../src/app/components/ui/mcp/McpBadge';
import type { McpBadgeTone } from '../src/app/components/ade/dashboard/mcp/mcpUiPrimitives';
import {
  mcpChangeStyle,
  mcpChangeCountParts,
  type McpVersionCompare,
} from '../src/app/components/ade/dashboard/mcp/mcpVersionsUi';
import {
  mcpLintTierMeta,
  mcpLintSeverityBarClass,
  MCP_LINT_TIER_ORDER,
} from '../src/app/components/ade/dashboard/mcp/mcpLintUi';
import {
  getNumericScoreTier,
  NUMERIC_SCORE_TIER_LEGEND,
} from '../src/app/utils/numeric-score-tier';

/** A `dark:`-prefixed Tailwind utility appears somewhere in the class string. */
function hasDarkVariant(className: string): boolean {
  return /(^|\s)dark:/.test(className);
}

/** A solid, saturated fill (`bg-*-400/500/600`) — readable on both themes without a dark override. */
function isSaturatedSolidBg(className: string): boolean {
  return /\bbg-[a-z]+-(400|500|600)\b/.test(className);
}

const GRADE_LETTERS: McpGradeLetter[] = ['A', 'B', 'C', 'D', 'F'];
const HEALTH_STATUSES: McpHealthStatus[] = ['healthy', 'degraded', 'unreachable', 'unknown'];
const BADGE_TONES: McpBadgeTone[] = ['indigo', 'green', 'amber', 'red', 'blue', 'slate', 'violet'];
const CHANGE_TYPES = ['added', 'removed', 'modified'] as const;

describe('grade glyph dark-theme tokens', () => {
  it.each(GRADE_LETTERS)('paints a saturated solid chip for grade %s (legible on dark)', (letter) => {
    const style = mcpGradeGlyphStyle(letter);
    // The lead chip is a saturated fill with white text — it reads in both themes by design.
    expect(isSaturatedSolidBg(style.chipClass)).toBe(true);
    expect(style.chipClass).toContain('text-white');
  });

  it.each(GRADE_LETTERS)('gives grade %s on-surface text & ring a dark variant', (letter) => {
    const style = mcpGradeGlyphStyle(letter);
    // text / ring tints sit on the card or gauge surface, so they must adapt to dark.
    expect(hasDarkVariant(style.textClass)).toBe(true);
    expect(hasDarkVariant(style.ringClass)).toBe(true);
  });

  it('gives the neutral unscored glyph a dark variant on every surface tint', () => {
    const unscored = mcpGradeGlyphStyle(null);
    expect(hasDarkVariant(unscored.chipClass)).toBe(true);
    expect(hasDarkVariant(unscored.textClass)).toBe(true);
    expect(hasDarkVariant(unscored.ringClass)).toBe(true);
  });

  it('keeps the light grade tints (light theme is unchanged)', () => {
    expect(mcpGradeGlyphStyle('A').textClass).toContain('text-emerald-600');
    expect(mcpGradeGlyphStyle('A').textClass).toContain('dark:text-emerald-400');
    expect(mcpGradeGlyphStyle(null).chipClass).toContain('bg-slate-200');
  });
});

describe('health pill dark-theme tokens', () => {
  it.each(HEALTH_STATUSES)('gives the %s label text a dark variant', (status) => {
    expect(hasDarkVariant(mcpHealthMeta(status).textClass)).toBe(true);
  });

  it.each(HEALTH_STATUSES)('paints the %s status dot as a saturated solid', (status) => {
    // The dot is a small saturated swatch (e.g. bg-emerald-500) — readable on light & dark.
    expect(isSaturatedSolidBg(mcpHealthMeta(status).dotClass)).toBe(true);
  });

  it('keeps the light health text tint (light theme is unchanged)', () => {
    expect(mcpHealthMeta('healthy').textClass).toContain('text-emerald-700');
    expect(mcpHealthMeta('healthy').textClass).toContain('dark:text-emerald-300');
  });
});

describe('badge tone dark-theme tokens', () => {
  it.each(BADGE_TONES)('gives the %s badge a dark fill, text, and border', (tone) => {
    const className = mcpBadgeVariants({ tone });
    expect(hasDarkVariant(className)).toBe(true);
    expect(className).toMatch(/dark:bg-/);
    expect(className).toMatch(/dark:text-/);
    expect(className).toMatch(/dark:border-/);
  });

  it('keeps the soft light fills (light theme is unchanged)', () => {
    expect(mcpBadgeVariants({ tone: 'indigo' })).toContain('bg-indigo-50');
    expect(mcpBadgeVariants({ tone: 'green' })).toContain('bg-emerald-50');
    expect(mcpBadgeVariants({ tone: 'slate' })).toContain('bg-slate-50');
  });
});

describe('version diff dark-theme tokens', () => {
  it.each(CHANGE_TYPES)('gives the %s change row a tinted dark background', (changeType) => {
    const style = mcpChangeStyle(changeType);
    // The row's tinted background sits on the panel surface, so it must adapt to dark.
    expect(hasDarkVariant(style.rowClass)).toBe(true);
  });

  it('gives the unrecognized-change fallback row a dark variant', () => {
    expect(hasDarkVariant(mcpChangeStyle('mystery').rowClass)).toBe(true);
  });

  it('keeps the diff add/remove/modify count colors legible on dark', () => {
    const compare = {
      base: { id: 'a', version_seq: 1, version_tag: null, surface_fingerprint: null },
      target: { id: 'b', version_seq: 2, version_tag: null, surface_fingerprint: null },
      fingerprint_changed: true,
      counts: { added: 1, removed: 1, modified: 1, total: 3 },
      changes: [],
    } as McpVersionCompare;
    const parts = mcpChangeCountParts(compare);
    // added / removed / modified / fingerprint — every token carries a dark variant.
    for (const part of parts) {
      expect(hasDarkVariant(part.colorClass)).toBe(true);
    }
    const byKey = Object.fromEntries(parts.map((p) => [p.key, p.colorClass]));
    // The add=green / remove=red / modify=blue language is preserved on both themes.
    expect(byKey.added).toContain('text-green-600');
    expect(byKey.added).toContain('dark:text-green-400');
    expect(byKey.removed).toContain('text-red-600');
    expect(byKey.modified).toContain('text-blue-600');
  });

  it('keeps the light diff row tints (light theme is unchanged)', () => {
    expect(mcpChangeStyle('added').rowClass).toContain('bg-green-50');
    expect(mcpChangeStyle('removed').rowClass).toContain('bg-red-50');
    expect(mcpChangeStyle('modified').rowClass).toContain('bg-blue-50');
  });
});

describe('lint report dark-theme tokens', () => {
  it.each([...MCP_LINT_TIER_ORDER])('gives the %s finding row a tinted dark background', (tier) => {
    expect(hasDarkVariant(mcpLintTierMeta(tier).rowClass)).toBe(true);
  });

  it.each([...MCP_LINT_TIER_ORDER])('paints the %s count bar as a saturated solid', (tier) => {
    // The category/severity bars are saturated solids that read on both themes.
    expect(isSaturatedSolidBg(mcpLintTierMeta(tier).barClass)).toBe(true);
  });

  it('paints each severity bar as a saturated solid', () => {
    expect(isSaturatedSolidBg(mcpLintSeverityBarClass('error'))).toBe(true);
    expect(isSaturatedSolidBg(mcpLintSeverityBarClass('warning'))).toBe(true);
    expect(isSaturatedSolidBg(mcpLintSeverityBarClass('info'))).toBe(true);
  });

  it('keeps the light lint row tints (light theme is unchanged)', () => {
    expect(mcpLintTierMeta('must').rowClass).toContain('bg-red-50');
    expect(mcpLintTierMeta('should').rowClass).toContain('bg-amber-50');
  });
});

describe('numeric score-tier dark-theme tokens', () => {
  // One representative score per band (excellent / good / fair / poor).
  it.each([95, 80, 60, 20])('gives the score-%d tier text & gauge stroke a dark variant', (score) => {
    const tier = getNumericScoreTier(score);
    expect(hasDarkVariant(tier.textClass)).toBe(true);
    expect(hasDarkVariant(tier.gaugeStrokeClass)).toBe(true);
  });

  it('gives every legend band a dark variant on its surface tints', () => {
    for (const band of NUMERIC_SCORE_TIER_LEGEND) {
      expect(hasDarkVariant(band.textClass)).toBe(true);
      expect(hasDarkVariant(band.gaugeStrokeClass)).toBe(true);
    }
  });

  it('keeps the light score-tier tints (light theme is unchanged)', () => {
    expect(getNumericScoreTier(95).textClass).toContain('text-green-600');
    expect(getNumericScoreTier(95).textClass).toContain('dark:text-green-400');
  });
});
