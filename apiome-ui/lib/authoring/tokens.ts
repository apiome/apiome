/**
 * Semantic vocabulary for the Authoring experience (UXE-1.3).
 *
 * Every Authoring primitive describes itself in the terms declared here rather
 * than in raw colours. That is what makes the roadmap's §27.1 rule enforceable
 * instead of aspirational: **violet identifies Scribe and cyan identifies
 * Slate, but neither ever means "this succeeded" or "this failed"**. Product
 * accent and semantic tone are separate axes in the type system, so a screen
 * cannot accidentally spell a failure in Slate cyan.
 *
 * This module is deliberately DOM-free and React-free. It holds the meanings;
 * `src/app/ade/authoring/authoringClasses.ts` holds the one mapping from those
 * meanings to classes, and every renderer goes through it.
 */

import type { AuthoringStateTone } from './state-badges';

/**
 * Semantic tone shared by every Authoring primitive.
 *
 * Reuses the shell's state-badge tones (UXE-1.2) rather than introducing a
 * second, subtly different scale — a status must look identical whether it is
 * reported by the shell header or by a release row.
 *
 * Tone is always a *redundant* cue. Primitives that carry a tone also carry a
 * text label and an icon, so meaning survives greyscale, high contrast and
 * colour-blind vision (WCAG 2.2 SC 1.4.1, roadmap §27.4).
 */
export type AuthoringTone = AuthoringStateTone;

/** Every tone, in increasing order of urgency. Used to sort mixed summaries. */
export const AUTHORING_TONES: readonly AuthoringTone[] = [
  'neutral',
  'success',
  'info',
  'warning',
  'danger',
] as const;

/**
 * Product identity accent.
 *
 * `none` is the default and the correct choice for anything operational. An
 * accent decorates ownership — which product a surface belongs to — and is
 * never a status signal.
 */
export type AuthoringAccent = 'none' | 'scribe' | 'slate';

/** Layout density. Dense tables stay legible instead of becoming marketing cards (§27.1). */
export type AuthoringDensity = 'comfortable' | 'compact';

/** Surface elevation. Overlays stay low-elevation with minimal shadow (§27.1). */
export type AuthoringElevation = 'flat' | 'raised' | 'overlay';

/**
 * Motion durations in milliseconds (§27.3).
 *
 * The band is 120–180ms, long enough to carry spatial continuity and short
 * enough not to delay an operator. Anything outside it needs a deliberate
 * justification, which is why there is no "slow" entry to reach for.
 */
export const AUTHORING_MOTION_MS = {
  /** Selection, hover and badge changes. */
  quick: 120,
  /** Drawers, inspectors and panel transitions. */
  standard: 160,
  /** Release progression and chart updates. */
  deliberate: 180,
} as const;

/** Name of a motion duration token. */
export type AuthoringMotionToken = keyof typeof AUTHORING_MOTION_MS;

/**
 * Rank a tone by urgency.
 *
 * @param tone - Tone to rank.
 * @returns Index in {@link AUTHORING_TONES}; higher is more urgent.
 */
export function authoringToneRank(tone: AuthoringTone): number {
  return AUTHORING_TONES.indexOf(tone);
}

/**
 * Reduce several tones to the one that should represent the group.
 *
 * A summary must never look calmer than its worst member: one failed check in
 * a passing run still reads as a failure.
 *
 * @param tones - Tones being summarised. May be empty.
 * @returns The most urgent tone, or `neutral` when there is nothing to report.
 */
export function mostUrgentAuthoringTone(tones: readonly AuthoringTone[]): AuthoringTone {
  return tones.reduce<AuthoringTone>(
    (worst, tone) => (authoringToneRank(tone) > authoringToneRank(worst) ? tone : worst),
    'neutral'
  );
}
