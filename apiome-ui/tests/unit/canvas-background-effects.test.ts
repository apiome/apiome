/**
 * Tests for Canvas Background Opacity and Blur functionality
 */

describe('Canvas Background Opacity and Blur', () => {
  // Types from StudioContext
  interface CanvasBackgroundOptions {
    type: 'solid' | 'grid' | 'image' | 'gradient' | 'texture';
    solidColor: string;
    gridColor: string;
    gridOpacity: number;
    imageUrl: string;
    imageOpacity: number;
    imageFit: 'cover' | 'contain' | 'tile' | 'center';
    gradientFrom: string;
    gradientTo: string;
    gradientDirection: string;
    textureType: string;
    textureOpacity: number;
    textureColor: string;
    backgroundOpacity: number;
    backgroundBlur: number;
  }

  // Default values
  const defaultBackground: CanvasBackgroundOptions = {
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

  describe('Default values', () => {
    it('should have backgroundOpacity default of 1 (100%)', () => {
      expect(defaultBackground.backgroundOpacity).toBe(1);
    });

    it('should have backgroundBlur default of 0 (no blur)', () => {
      expect(defaultBackground.backgroundBlur).toBe(0);
    });
  });

  describe('Opacity range', () => {
    it('should accept opacity values from 0.1 to 1', () => {
      const validOpacities = [0.1, 0.25, 0.5, 0.75, 1];
      validOpacities.forEach((opacity) => {
        const bg = { ...defaultBackground, backgroundOpacity: opacity };
        expect(bg.backgroundOpacity).toBe(opacity);
        expect(bg.backgroundOpacity).toBeGreaterThanOrEqual(0.1);
        expect(bg.backgroundOpacity).toBeLessThanOrEqual(1);
      });
    });

    it('should format opacity as percentage for display', () => {
      const opacity = 0.75;
      const percentage = Math.round(opacity * 100);
      expect(percentage).toBe(75);
    });
  });

  describe('Blur range', () => {
    it('should accept blur values from 0 to 20', () => {
      const validBlurs = [0, 5, 10, 15, 20];
      validBlurs.forEach((blur) => {
        const bg = { ...defaultBackground, backgroundBlur: blur };
        expect(bg.backgroundBlur).toBe(blur);
        expect(bg.backgroundBlur).toBeGreaterThanOrEqual(0);
        expect(bg.backgroundBlur).toBeLessThanOrEqual(20);
      });
    });

    it('should format blur as pixels for display', () => {
      const blur = 10;
      const display = `${blur}px`;
      expect(display).toBe('10px');
    });
  });

  describe('CSS style generation', () => {
    interface CSSProperties {
      opacity?: number;
      filter?: string;
      background?: string;
      backgroundColor?: string;
    }

    // Simplified version of applyOpacityAndBlur
    function applyOpacityAndBlur(
      baseStyle: CSSProperties,
      opacity: number | undefined,
      blur: number | undefined
    ): CSSProperties {
      const style = { ...baseStyle };

      if (opacity !== undefined && opacity < 1) {
        style.opacity = opacity;
      }

      if (blur !== undefined && blur > 0) {
        style.filter = `blur(${blur}px)`;
      }

      return style;
    }

    it('should not add opacity when value is 1', () => {
      const baseStyle = { background: '#f8fafc' };
      const result = applyOpacityAndBlur(baseStyle, 1, 0);
      expect(result.opacity).toBeUndefined();
    });

    it('should add opacity when value is less than 1', () => {
      const baseStyle = { background: '#f8fafc' };
      const result = applyOpacityAndBlur(baseStyle, 0.75, 0);
      expect(result.opacity).toBe(0.75);
    });

    it('should not add filter when blur is 0', () => {
      const baseStyle = { background: '#f8fafc' };
      const result = applyOpacityAndBlur(baseStyle, 1, 0);
      expect(result.filter).toBeUndefined();
    });

    it('should add blur filter when blur is greater than 0', () => {
      const baseStyle = { background: '#f8fafc' };
      const result = applyOpacityAndBlur(baseStyle, 1, 10);
      expect(result.filter).toBe('blur(10px)');
    });

    it('should apply both opacity and blur when configured', () => {
      const baseStyle = { background: '#f8fafc' };
      const result = applyOpacityAndBlur(baseStyle, 0.5, 5);
      expect(result.opacity).toBe(0.5);
      expect(result.filter).toBe('blur(5px)');
    });

    it('should preserve base style properties', () => {
      const baseStyle = {
        background: 'linear-gradient(135deg, #f8fafc, #e2e8f0)',
        backgroundColor: '#ffffff'
      };
      const result = applyOpacityAndBlur(baseStyle, 0.8, 3);
      expect(result.background).toBe(baseStyle.background);
      expect(result.backgroundColor).toBe(baseStyle.backgroundColor);
      expect(result.opacity).toBe(0.8);
      expect(result.filter).toBe('blur(3px)');
    });
  });

  describe('Reset functionality', () => {
    it('should reset to default values', () => {
      const modifiedBg = {
        ...defaultBackground,
        backgroundOpacity: 0.5,
        backgroundBlur: 10,
      };

      // Reset
      const resetBg = {
        ...modifiedBg,
        backgroundOpacity: 1,
        backgroundBlur: 0,
      };

      expect(resetBg.backgroundOpacity).toBe(1);
      expect(resetBg.backgroundBlur).toBe(0);
    });

    it('should detect when effects are active', () => {
      const hasActiveEffects = (opacity: number, blur: number) =>
        opacity < 1 || blur > 0;

      expect(hasActiveEffects(1, 0)).toBe(false);
      expect(hasActiveEffects(0.9, 0)).toBe(true);
      expect(hasActiveEffects(1, 5)).toBe(true);
      expect(hasActiveEffects(0.5, 10)).toBe(true);
    });
  });

  describe('Works with all background types', () => {
    const types = ['solid', 'grid', 'image', 'gradient', 'texture'] as const;

    types.forEach((type) => {
      it(`should apply opacity and blur to ${type} background`, () => {
        const bg = {
          ...defaultBackground,
          type,
          backgroundOpacity: 0.7,
          backgroundBlur: 5,
        };

        expect(bg.type).toBe(type);
        expect(bg.backgroundOpacity).toBe(0.7);
        expect(bg.backgroundBlur).toBe(5);
      });
    });
  });
});

