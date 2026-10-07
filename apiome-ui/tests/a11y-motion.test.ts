/**
 * Reduced motion for script-driven motion — HIVE-10.2 (#5338), `lib/motion.ts`.
 */

import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';

import { motionDuration, prefersReducedMotion, scrollBehavior } from '../lib/motion';

/** Every `.ts` / `.tsx` file under a directory. */
function sources(directory: string): string[] {
  return readdirSync(directory).flatMap((entry) => {
    const path = join(directory, entry);
    if (statSync(path).isDirectory()) return sources(path);
    return /\.tsx?$/.test(entry) ? [path] : [];
  });
}

function mockMediaQuery(matches: boolean): void {
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    writable: true,
    value: jest.fn().mockImplementation((query: string) => ({
      matches: query === '(prefers-reduced-motion: reduce)' ? matches : false,
      media: query,
      addEventListener: jest.fn(),
      removeEventListener: jest.fn(),
    })),
  });
}

afterEach(() => {
  delete document.documentElement.dataset.motion;
});

describe('prefersReducedMotion', () => {
  it('follows the stored preference on <html>', () => {
    mockMediaQuery(false);
    document.documentElement.dataset.motion = 'reduce';
    expect(prefersReducedMotion()).toBe(true);
  });

  it('falls back to the operating system setting', () => {
    document.documentElement.dataset.motion = 'auto';
    mockMediaQuery(true);
    expect(prefersReducedMotion()).toBe(true);
    mockMediaQuery(false);
    expect(prefersReducedMotion()).toBe(false);
  });
});

describe('scrollBehavior / motionDuration', () => {
  it('jump and zero under reduced motion', () => {
    mockMediaQuery(false);
    document.documentElement.dataset.motion = 'reduce';
    expect(scrollBehavior()).toBe('auto');
    expect(motionDuration(400)).toBe(0);
  });

  it('smooth and full length otherwise', () => {
    mockMediaQuery(false);
    expect(scrollBehavior()).toBe('smooth');
    expect(motionDuration(400)).toBe(400);
  });
});

describe('call sites', () => {
  it('no component hard-codes smooth scrolling any more', () => {
    const smooth = /behavior:\s*['"]smooth['"]/;
    const offenders = sources(join(__dirname, '..', 'src')).filter((file) => smooth.test(readFileSync(file, 'utf8')));
    expect(offenders).toEqual([]);
  });
});
