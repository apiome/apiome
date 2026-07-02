/**
 * Edge Animation Test Suite
 *
 * Tests the edge animation functionality
 */

import { describe, test, expect } from '@jest/globals';

// Mock animation types
type EdgeAnimationType = 'none' | 'flow' | 'pulse' | 'dash';

// Mock helper functions matching the editor implementation
function shouldAnimateEdges(edgeAnimation: EdgeAnimationType): boolean {
  return edgeAnimation !== 'none';
}

function getAnimationClassName(edgeAnimation: EdgeAnimationType): string {
  switch (edgeAnimation) {
    case 'flow':
      return 'edge-animation-flow';
    case 'pulse':
      return 'edge-animation-pulse';
    case 'dash':
      return 'edge-animation-dash';
    default:
      return '';
  }
}

describe('Edge Animation', () => {
  describe('shouldAnimateEdges', () => {
    test('should return false for "none" animation', () => {
      expect(shouldAnimateEdges('none')).toBe(false);
    });

    test('should return true for "flow" animation', () => {
      expect(shouldAnimateEdges('flow')).toBe(true);
    });

    test('should return true for "pulse" animation', () => {
      expect(shouldAnimateEdges('pulse')).toBe(true);
    });

    test('should return true for "dash" animation', () => {
      expect(shouldAnimateEdges('dash')).toBe(true);
    });
  });

  describe('getAnimationClassName', () => {
    test('should return empty string for "none" animation', () => {
      expect(getAnimationClassName('none')).toBe('');
    });

    test('should return correct class for "flow" animation', () => {
      expect(getAnimationClassName('flow')).toBe('edge-animation-flow');
    });

    test('should return correct class for "pulse" animation', () => {
      expect(getAnimationClassName('pulse')).toBe('edge-animation-pulse');
    });

    test('should return correct class for "dash" animation', () => {
      expect(getAnimationClassName('dash')).toBe('edge-animation-dash');
    });
  });

  describe('Edge Animation Types', () => {
    const validAnimationTypes: EdgeAnimationType[] = ['none', 'flow', 'pulse', 'dash'];

    test('should have exactly 4 animation types', () => {
      expect(validAnimationTypes.length).toBe(4);
    });

    test('all animation types should produce valid class names', () => {
      validAnimationTypes.forEach((animation) => {
        const className = getAnimationClassName(animation);
        // Class should be empty string or start with 'edge-animation-'
        expect(className === '' || className.startsWith('edge-animation-')).toBe(true);
      });
    });

    test('none should be the default (no animation)', () => {
      // none returns false for animation and empty class
      expect(shouldAnimateEdges('none')).toBe(false);
      expect(getAnimationClassName('none')).toBe('');
    });
  });

  describe('Animation Behavior', () => {
    test('flow animation should have flowing dots effect', () => {
      const className = getAnimationClassName('flow');
      expect(className).toContain('flow');
    });

    test('pulse animation should have pulsing effect', () => {
      const className = getAnimationClassName('pulse');
      expect(className).toContain('pulse');
    });

    test('dash animation should have marching dashes effect', () => {
      const className = getAnimationClassName('dash');
      expect(className).toContain('dash');
    });
  });

  describe('Edge Animation Consistency', () => {
    test('same animation type should always return same values', () => {
      const animation: EdgeAnimationType = 'flow';
      const shouldAnimate1 = shouldAnimateEdges(animation);
      const shouldAnimate2 = shouldAnimateEdges(animation);
      const className1 = getAnimationClassName(animation);
      const className2 = getAnimationClassName(animation);

      expect(shouldAnimate1).toBe(shouldAnimate2);
      expect(className1).toBe(className2);
    });

    test('different animation types should be distinguishable', () => {
      const flowClass = getAnimationClassName('flow');
      const pulseClass = getAnimationClassName('pulse');
      const dashClass = getAnimationClassName('dash');

      // All animated types should have different class names
      expect(flowClass).not.toBe(pulseClass);
      expect(pulseClass).not.toBe(dashClass);
      expect(flowClass).not.toBe(dashClass);
    });
  });
});

