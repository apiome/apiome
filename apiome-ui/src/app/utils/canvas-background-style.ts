import type { CSSProperties } from 'react';
import type { CanvasBackgroundOptions } from '../ade/studio/StudioContext';

/** Normalize to a valid 6-digit hex color for use in CSS and inputs. */
export function normalizeHex(s: string | undefined, fallback = '#f8fafc'): string {
  if (!s) return fallback;
  const hex = s.replace(/^#/, '');
  if (/^[0-9A-Fa-f]{6}$/.test(hex)) return '#' + hex;
  if (/^[0-9A-Fa-f]{3}$/.test(hex)) return '#' + hex[0] + hex[0] + hex[1] + hex[1] + hex[2] + hex[2];
  return fallback;
}

const GRADIENT_DIRECTION_MAP: Record<string, string> = {
  'to-r': '90deg',
  'to-l': '270deg',
  'to-t': '0deg',
  'to-b': '180deg',
  'to-tr': '45deg',
  'to-tl': '315deg',
  'to-br': '135deg',
  'to-bl': '225deg',
};

/**
 * Apply opacity and blur to the base style.
 * Opacity is applied via the opacity CSS property.
 * Blur is applied via the backdrop-filter property for a frosted glass effect.
 */
function applyOpacityAndBlur(
  baseStyle: CSSProperties,
  opacity: number | undefined,
  blur: number | undefined
): CSSProperties {
  const style = { ...baseStyle };

  // Apply opacity (default is 1)
  if (opacity !== undefined && opacity < 1) {
    style.opacity = opacity;
  }

  // Apply blur effect via filter (backdrop-filter for frosted glass effect)
  if (blur !== undefined && blur > 0) {
    // Use a combination of filter for the background itself
    // Note: backdrop-filter would blur content behind, but we want to blur the background
    // So we use filter to create a soft/blurred background effect
    style.filter = `blur(${blur}px)`;
  }

  return style;
}

/**
 * Returns CSS style object for the canvas background based on options and theme.
 * Used by both the main canvas and the Canvas Settings preview.
 */
export function getCanvasBackgroundStyle(
  canvasBackground: CanvasBackgroundOptions,
  isDark: boolean
): CSSProperties {
  let baseStyle: CSSProperties;

  switch (canvasBackground.type) {
    case 'solid':
      baseStyle = {
        background: isDark ? '#0f172a' : normalizeHex(canvasBackground.solidColor),
      };
      break;
    case 'gradient': {
      const direction = GRADIENT_DIRECTION_MAP[canvasBackground.gradientDirection] ?? '135deg';
      baseStyle = {
        background: isDark
          ? `linear-gradient(${direction}, #0f172a 0%, #1e293b 50%, #0f172a 100%)`
          : `linear-gradient(${direction}, ${normalizeHex(canvasBackground.gradientFrom)} 0%, ${normalizeHex(canvasBackground.gradientTo)} 100%)`,
      };
      break;
    }
    case 'image':
      if (canvasBackground.imageUrl) {
        const fitStyles: Record<string, string> = {
          cover: 'cover',
          contain: 'contain',
          tile: 'auto',
          center: 'auto',
        };
        const repeatStyles: Record<string, string> = {
          cover: 'no-repeat',
          contain: 'no-repeat',
          tile: 'repeat',
          center: 'no-repeat',
        };
        const positionStyles: Record<string, string> = {
          cover: 'center',
          contain: 'center',
          tile: 'top left',
          center: 'center',
        };
        baseStyle = {
          backgroundImage: `url(${canvasBackground.imageUrl})`,
          backgroundSize: fitStyles[canvasBackground.imageFit],
          backgroundRepeat: repeatStyles[canvasBackground.imageFit],
          backgroundPosition: positionStyles[canvasBackground.imageFit],
          backgroundColor: isDark ? '#0f172a' : '#f8fafc',
        };
      } else {
        baseStyle = { background: isDark ? '#0f172a' : '#f8fafc' };
      }
      break;
    case 'texture': {
      const texColor = normalizeHex(canvasBackground.textureColor);
      const texturePatterns: Record<string, string> = {
        noise: `url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noiseFilter'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.65' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noiseFilter)'/%3E%3C/svg%3E")`,
        paper: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='100' height='100' viewBox='0 0 100 100'%3E%3Cg fill-rule='evenodd'%3E%3Cg fill='${encodeURIComponent(texColor)}' fill-opacity='${canvasBackground.textureOpacity}'%3E%3Cpath opacity='.5' d='M96 95h4v1h-4v4h-1v-4h-9v4h-1v-4h-9v4h-1v-4h-9v4h-1v-4h-9v4h-1v-4h-9v4h-1v-4h-9v4h-1v-4h-9v4h-1v-4h-9v4h-1v-4H0v-1h15v-9H0v-1h15v-9H0v-1h15v-9H0v-1h15v-9H0v-1h15v-9H0v-1h15v-9H0v-1h15v-9H0v-1h15v-9H0v-1h15V0h1v15h9V0h1v15h9V0h1v15h9V0h1v15h9V0h1v15h9V0h1v15h9V0h1v15h9V0h1v15h4v1h-4v9h4v1h-4v9h4v1h-4v9h4v1h-4v9h4v1h-4v9h4v1h-4v9h4v1h-4v9h4v1h-4v9zm-1 0v-9h-9v9h9zm-10 0v-9h-9v9h9zm-10 0v-9h-9v9h9zm-10 0v-9h-9v9h9zm-10 0v-9h-9v9h9zm-10 0v-9h-9v9h9zm-10 0v-9h-9v9h9zm-10 0v-9h-9v9h9zm-9-10h9v-9h-9v9zm10 0h9v-9h-9v9zm10 0h9v-9h-9v9zm10 0h9v-9h-9v9zm10 0h9v-9h-9v9zm10 0h9v-9h-9v9zm10 0h9v-9h-9v9zm10 0h9v-9h-9v9zm10 0h9v-9h-9v9zm-9-10h9v-9h-9v9zm10 0h9v-9h-9v9zm10 0h9v-9h-9v9zm10 0h9v-9h-9v9zm10 0h9v-9h-9v9zm10 0h9v-9h-9v9zm10 0h9v-9h-9v9z'/%3E%3C/g%3E%3C/g%3E%3C/svg%3E")`,
        fabric: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='20' height='20' viewBox='0 0 20 20'%3E%3Cg fill='${encodeURIComponent(texColor)}' fill-opacity='${canvasBackground.textureOpacity}'%3E%3Cpath d='M0 0h10v10H0zM10 10h10v10H10z'/%3E%3C/g%3E%3C/svg%3E")`,
        carbon: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='8' height='8' viewBox='0 0 8 8'%3E%3Cg fill='${encodeURIComponent(texColor)}' fill-opacity='${canvasBackground.textureOpacity}'%3E%3Cpath d='M0 0h4v4H0V0zm4 4h4v4H4V4z'/%3E%3C/g%3E%3C/svg%3E")`,
        concrete: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='40' height='40' viewBox='0 0 40 40'%3E%3Cg fill-rule='evenodd'%3E%3Cg fill='${encodeURIComponent(texColor)}' fill-opacity='${canvasBackground.textureOpacity}'%3E%3Cpath d='M0 38.59l2.83-2.83 1.41 1.41L1.41 40H0v-1.41zM0 1.4l2.83 2.83 1.41-1.41L1.41 0H0v1.41zM38.59 40l-2.83-2.83 1.41-1.41L40 38.59V40h-1.41zM40 1.41l-2.83 2.83-1.41-1.41L38.59 0H40v1.41zM20 18.6l2.83-2.83 1.41 1.41L21.41 20l2.83 2.83-1.41 1.41L20 21.41l-2.83 2.83-1.41-1.41L18.59 20l-2.83-2.83 1.41-1.41L20 18.59z'/%3E%3C/g%3E%3C/g%3E%3C/svg%3E")`,
        wood: `url("data:image/svg+xml,%3Csvg width='42' height='44' viewBox='0 0 42 44' xmlns='http://www.w3.org/2000/svg'%3E%3Cg fill='none' fill-rule='evenodd'%3E%3Cg fill='${encodeURIComponent(texColor)}' fill-opacity='${canvasBackground.textureOpacity}'%3E%3Cpath d='M0 0h42v44H0V0zm1 1h40v20H1V1zM0 23h20v20H0V23zm22 0h20v20H22V23z'/%3E%3C/g%3E%3C/g%3E%3C/svg%3E")`,
      };
      baseStyle = {
        backgroundColor: isDark ? '#0f172a' : normalizeHex(canvasBackground.solidColor),
        backgroundImage: texturePatterns[canvasBackground.textureType] ?? texturePatterns.noise,
      };
      break;
    }
    case 'grid':
    default:
      baseStyle = {
        background: isDark
          ? 'linear-gradient(135deg, #0f172a 0%, #1e293b 50%, #0f172a 100%)'
          : `linear-gradient(135deg, ${normalizeHex(canvasBackground.solidColor)} 0%, #f1f5f9 50%, #e2e8f0 100%)`,
      };
      break;
  }

  // Apply opacity and blur if configured
  return applyOpacityAndBlur(
    baseStyle,
    canvasBackground.backgroundOpacity,
    canvasBackground.backgroundBlur
  );
}
