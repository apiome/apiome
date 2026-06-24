/**
 * Unit tests for the first-run checklist pure logic + dismissal storage (#3614).
 */

import {
  FIRST_RUN_DISMISS_KEY,
  TOTAL_STEPS,
  allComplete,
  completedCount,
  deriveCompletion,
  isDismissed,
  setDismissed,
  type ChecklistSignal,
} from '@/app/components/ade/dashboard/firstRunChecklist';

const empty: ChecklistSignal = {
  total_projects: 0,
  total_classes: 0,
  total_versions: 0,
  published_versions: 0,
};

/** Minimal in-memory Storage stand-in. */
function fakeStorage(): Storage {
  const map = new Map<string, string>();
  return {
    get length() {
      return map.size;
    },
    clear: () => map.clear(),
    getItem: (k: string) => (map.has(k) ? (map.get(k) as string) : null),
    key: (i: number) => Array.from(map.keys())[i] ?? null,
    removeItem: (k: string) => map.delete(k),
    setItem: (k: string, v: string) => map.set(k, v),
  } as Storage;
}

describe('deriveCompletion', () => {
  it('marks nothing done for an empty tenant', () => {
    expect(deriveCompletion(empty)).toEqual({
      project: false,
      class: false,
      version: false,
      publish: false,
      browse: false,
    });
    expect(completedCount(empty)).toBe(0);
    expect(allComplete(empty)).toBe(false);
  });

  it('marks each step done as its underlying count crosses zero', () => {
    expect(deriveCompletion({ ...empty, total_projects: 1 }).project).toBe(true);
    expect(deriveCompletion({ ...empty, total_classes: 2 }).class).toBe(true);
    expect(deriveCompletion({ ...empty, total_versions: 1 }).version).toBe(true);
    const published = deriveCompletion({ ...empty, published_versions: 1 });
    expect(published.publish).toBe(true);
    // "View in Browse" unlocks together with the first published version.
    expect(published.browse).toBe(true);
  });

  it('treats a fully-populated tenant (the seeded sample) as complete', () => {
    const seeded: ChecklistSignal = {
      total_projects: 1,
      total_classes: 3,
      total_versions: 1,
      published_versions: 1,
    };
    expect(completedCount(seeded)).toBe(TOTAL_STEPS);
    expect(allComplete(seeded)).toBe(true);
  });
});

describe('dismissal storage', () => {
  it('round-trips the dismissed flag', () => {
    const storage = fakeStorage();
    expect(isDismissed(storage)).toBe(false);
    setDismissed(storage);
    expect(storage.getItem(FIRST_RUN_DISMISS_KEY)).toBe('1');
    expect(isDismissed(storage)).toBe(true);
  });

  it('is safe when storage throws', () => {
    const throwing = {
      getItem: () => {
        throw new Error('blocked');
      },
      setItem: () => {
        throw new Error('blocked');
      },
    } as unknown as Storage;
    expect(isDismissed(throwing)).toBe(false);
    expect(() => setDismissed(throwing)).not.toThrow();
  });
});
