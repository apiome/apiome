import {
  parseCssHexColor,
  resolveGroupFrameHex,
} from '@/app/utils/group-frame-colors';

const PRESETS = [
  { name: 'indigo', hex: '#6366f1', bg: '', border: '', text: '' },
  { name: 'blue', hex: '#3b82f6', bg: '', border: '', text: '' },
] as const;

describe('group-frame-colors', () => {
  describe('parseCssHexColor', () => {
    it('normalizes 6-digit hex', () => {
      expect(parseCssHexColor('#Aa00Ff')).toBe('#aa00ff');
    });

    it('expands 3-digit hex', () => {
      expect(parseCssHexColor('#abc')).toBe('#aabbcc');
    });

    it('returns null for invalid input', () => {
      expect(parseCssHexColor('')).toBeNull();
      expect(parseCssHexColor('indigo')).toBeNull();
      expect(parseCssHexColor('#gg0000')).toBeNull();
      expect(parseCssHexColor('#12345')).toBeNull();
    });
  });

  describe('resolveGroupFrameHex', () => {
    it('resolves preset by name', () => {
      const r = resolveGroupFrameHex('blue', PRESETS);
      expect(r.hex).toBe('#3b82f6');
      expect(r.preset?.name).toBe('blue');
    });

    it('resolves custom hex from DB', () => {
      const r = resolveGroupFrameHex('#EF4444', PRESETS);
      expect(r.hex).toBe('#ef4444');
      expect(r.preset).toBeNull();
    });

    it('falls back to first preset for unknown strings', () => {
      const r = resolveGroupFrameHex('not-a-color', PRESETS);
      expect(r.hex).toBe('#6366f1');
      expect(r.preset).toBe(PRESETS[0]);
    });
  });
});
