/**
 * The launcher's "Recently shipped" parse (HIVE-12.6, #5613).
 *
 * `recentlyShippedModel.ts` reads `public/WHATS_NEW.md`, which is written for people. These cases
 * pin the shapes the notes actually use — and run the parse over the real file, so a release
 * that changes the notes' shape fails here rather than emptying the card in production.
 */

import fs from 'node:fs';
import path from 'node:path';

import {
  parseRecentlyShipped,
  plainText,
  RECENTLY_SHIPPED_LIMIT,
  releaseLabel,
  splitEntry,
} from '../src/app/components/ade/launcher/recentlyShippedModel';

describe('plainText', () => {
  it('drops bold, code, links and tags, keeping the words', () => {
    expect(plainText('**Members** use `apiome x` — see [docs](https://x.test) <br/> *now*')).toBe(
      'Members use apiome x — see docs now'
    );
  });

  it('leaves snake_case identifiers alone', () => {
    expect(plainText('set include_registry=true')).toBe('set include_registry=true');
  });
});

describe('splitEntry', () => {
  it('takes a bold lead as the title and what follows its dash as the line', () => {
    expect(splitEntry('**SDK compatibility** — a new **Export studio** tab')).toEqual({
      title: 'SDK compatibility',
      summary: 'A new Export studio tab',
    });
  });

  it('splits a plain sentence at its first colon', () => {
    expect(splitEntry('Readers can sign in to Browse: an organization page has a chip')).toEqual({
      title: 'Readers can sign in to Browse',
      summary: 'An organization page has a chip',
    });
  });

  it('keeps an entry with no separator as all title', () => {
    expect(splitEntry('Faster imports')).toEqual({ title: 'Faster imports', summary: '' });
  });

  it('accepts a bold lead with nothing after it', () => {
    expect(splitEntry('**Uptime**')).toEqual({ title: 'Uptime', summary: '' });
  });
});

describe('releaseLabel', () => {
  it('reads the release from the first heading, without the product name', () => {
    expect(releaseLabel('# Apiome 11-2026 RC8\n\n## Features')).toBe('11-2026 RC8');
  });

  it('is empty when the notes have no heading', () => {
    expect(releaseLabel('- an entry')).toBe('');
  });
});

describe('parseRecentlyShipped', () => {
  const notes = [
    '# Apiome 11-2026 RC8',
    '## Features/Improvements',
    '- **One** — first',
    '- Group:',
    '  - **Two** — nested',
    '- Three: third',
    '- **Four** — fourth',
    '## Bug Fixes',
    '- **Fix** — not an entry',
  ].join('\n');

  it('returns the first three entries in document order, skipping group headings', () => {
    expect(parseRecentlyShipped(notes).map((entry) => entry.title)).toEqual([
      'One',
      'Two',
      'Three',
    ]);
  });

  it('stamps every entry with the release', () => {
    expect(parseRecentlyShipped(notes).every((entry) => entry.version === '11-2026 RC8')).toBe(
      true
    );
  });

  it('honours a limit', () => {
    expect(parseRecentlyShipped(notes, 4).map((entry) => entry.title)).toContain('Four');
    expect(parseRecentlyShipped(notes, 10).map((entry) => entry.title)).not.toContain('Fix');
  });

  it('finds nothing in text that is not shaped like the notes', () => {
    expect(parseRecentlyShipped('')).toEqual([]);
    expect(parseRecentlyShipped('<!doctype html><p>Not found</p>')).toEqual([]);
    expect(parseRecentlyShipped('- **Orphan** — outside any section')).toEqual([]);
  });

  it('reads titled entries out of the shipped public/WHATS_NEW.md', () => {
    const shipped = fs.readFileSync(path.join(__dirname, '..', 'public', 'WHATS_NEW.md'), 'utf8');
    const entries = parseRecentlyShipped(shipped);

    // A release candidate's notes start again when it opens (RC9 opened with one entry), so the
    // card shows between one entry and its limit.
    expect(entries.length).toBeGreaterThanOrEqual(1);
    expect(entries.length).toBeLessThanOrEqual(RECENTLY_SHIPPED_LIMIT);
    for (const entry of entries) {
      expect(entry.title.length).toBeGreaterThan(0);
      expect(entry.title).not.toMatch(/\*\*|`/);
      expect(entry.version).not.toBe('');
    }
  });
});
