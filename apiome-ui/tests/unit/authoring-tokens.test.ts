/**
 * Semantic token vocabulary (UXE-1.3).
 *
 * Covers the acceptance criterion "semantic status never depends on Scribe/
 * Slate brand accents or color alone" at its root: the tone scale and the
 * accent scale must remain disjoint, and a summary must never read calmer than
 * its worst member.
 */

import {
  AUTHORING_MOTION_MS,
  AUTHORING_TONES,
  authoringToneRank,
  mostUrgentAuthoringTone,
  type AuthoringAccent,
  type AuthoringTone,
} from '../../lib/authoring/tokens';

describe('AUTHORING_TONES', () => {
  it('orders tones from calmest to most urgent, so rank comparisons are meaningful', () => {
    expect(AUTHORING_TONES).toEqual(['neutral', 'success', 'info', 'warning', 'danger']);
  });

  it('ranks danger above every other tone', () => {
    const danger = authoringToneRank('danger');
    AUTHORING_TONES.filter((tone) => tone !== 'danger').forEach((tone) => {
      expect(authoringToneRank(tone)).toBeLessThan(danger);
    });
  });

  it('keeps product accents out of the semantic tone scale', () => {
    // The type system already forbids this; the test documents *why* the two
    // scales are separate, so a future merge of them fails loudly.
    const accents: AuthoringAccent[] = ['none', 'scribe', 'slate'];
    accents.forEach((accent) => {
      expect(AUTHORING_TONES).not.toContain(accent as unknown as AuthoringTone);
    });
  });
});

describe('mostUrgentAuthoringTone', () => {
  it('returns neutral for an empty set, so a silent group is not alarming', () => {
    expect(mostUrgentAuthoringTone([])).toBe('neutral');
  });

  it.each([
    [['success', 'success'], 'success'],
    [['success', 'warning'], 'warning'],
    [['danger', 'success', 'info'], 'danger'],
    [['neutral', 'info'], 'info'],
  ] as Array<[AuthoringTone[], AuthoringTone]>)(
    'reduces %p to %s',
    (tones, expected) => {
      expect(mostUrgentAuthoringTone(tones)).toBe(expected);
    }
  );

  it('never reports a group as calmer than its worst member', () => {
    const tones: AuthoringTone[] = ['success', 'success', 'success', 'danger'];
    expect(authoringToneRank(mostUrgentAuthoringTone(tones))).toBe(authoringToneRank('danger'));
  });
});

describe('AUTHORING_MOTION_MS', () => {
  it('keeps every duration inside the 120-180ms band from roadmap section 27.3', () => {
    Object.values(AUTHORING_MOTION_MS).forEach((duration) => {
      expect(duration).toBeGreaterThanOrEqual(120);
      expect(duration).toBeLessThanOrEqual(180);
    });
  });
});
