/**
 * The launcher's "Recently shipped" entries, read from the What's new notes (HIVE-12.6, #5613).
 *
 * Authority: `docs/mockups/proposals/launcher-focused.html`, callout 4. The card it feeds
 * replaced a hand-written "On the roadmap" panel that went stale the release Access audit
 * shipped. Reading the same `public/WHATS_NEW.md` the What's new dialog renders means the
 * launcher can never advertise something the notes — and the rail — have not caught up with.
 *
 * The notes are written for people, not parsers, so this module reads only the shape every
 * release has kept:
 *
 * ```md
 * # Apiome 11-2026 RC8          ← the release label
 * ## Features/Improvements      ← the section entries come from
 * - **Title** — one line        ← an entry (the bold lead is the title)
 * - Group:                      ← a group heading, never an entry itself
 *   - Plain sentence: more      ← an entry (text before ": " / " — " is the title)
 * ```
 *
 * Entries come out in document order, which is newest first: each release prepends its lines.
 * No React here, so the parse is unit tested without rendering a page.
 */

/** Where the notes are served from — the same file `WhatsNewDialog` fetches. */
export const WHATS_NEW_SOURCE_URL = '/WHATS_NEW.md';

/** How many entries the card shows. */
export const RECENTLY_SHIPPED_LIMIT = 3;

/** The section of the notes whose bullets are entries. Bug fixes are not "shipped". */
const FEATURES_HEADING = /^##\s+Features\b/i;

/** One row of the "Recently shipped" card. */
export interface ShippedEntry {
  /** The entry's title: its bold lead, or the text before its first separator. */
  title: string;
  /** The rest of the entry as one plain-text line; empty when the entry was only a title. */
  summary: string;
  /** The release the entry shipped in, e.g. `11-2026 RC8`; empty when the notes name none. */
  version: string;
}

/**
 * Strip the inline markdown and HTML a notes line may carry, leaving the words.
 *
 * The result is rendered as a React text node, so nothing here is a sanitiser — it only keeps
 * `**bold**`, backticks and link syntax from showing up as punctuation.
 *
 * @param text One line of markdown.
 * @returns The same line as plain text, whitespace collapsed.
 */
export function plainText(text: string): string {
  return text
    .replace(/<[^>]+>/g, '')
    .replace(/!?\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/\*\*|__|`/g, '')
    .replace(/(^|\s)[*_]([^*_]+)[*_](?=\s|$|[.,;:])/g, '$1$2')
    .replace(/\s+/g, ' ')
    .trim();
}

/**
 * Upper-case the first letter, so a summary that started mid-sentence still reads as a line.
 *
 * @param text Plain text.
 * @returns The text with its first character capitalised.
 */
function capitalise(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/**
 * Split one bullet's markdown into a title and a one-line summary.
 *
 * A bold lead (`**Consumer feedback** — readers can…`) is the title, and whatever follows its
 * dash or colon is the summary. Without one, the text before the first `: ` or ` — ` is the
 * title; a bullet with neither is all title.
 *
 * @param markdown The bullet's text, without its `- ` marker.
 * @returns The title and summary, both plain text.
 */
export function splitEntry(markdown: string): Pick<ShippedEntry, 'title' | 'summary'> {
  const lead = /^\*\*(.+?)\*\*\s*(?:[—–:-]\s*)?(.*)$/.exec(markdown.trim());
  if (lead) {
    return { title: plainText(lead[1]), summary: capitalise(plainText(lead[2])) };
  }
  const text = plainText(markdown);
  const match = /: | — /.exec(text);
  if (!match) return { title: text, summary: '' };
  return {
    title: text.slice(0, match.index).trim(),
    summary: capitalise(text.slice(match.index + match[0].length).trim()),
  };
}

/**
 * The release label from the notes' first `#` heading.
 *
 * @param markdown The whole notes file.
 * @returns e.g. `11-2026 RC8` for `# Apiome 11-2026 RC8`, or `''` when there is no heading.
 */
export function releaseLabel(markdown: string): string {
  const heading = /^#\s+(.+)$/m.exec(markdown);
  if (!heading) return '';
  return plainText(heading[1]).replace(/^Apiome\s+/i, '');
}

/**
 * The newest entries in the notes, newest first.
 *
 * Reads the bullets of the *Features/Improvements* section, top level and nested alike, and
 * skips group headings (a bullet that ends in `:`, like `- Look and feel:`). Anything that is
 * not shaped like the notes — an error page, an empty file — yields no entries, which is the
 * card's cue to leave the row to Resources.
 *
 * @param markdown The whole notes file, as fetched.
 * @param limit How many entries to return. Defaults to {@link RECENTLY_SHIPPED_LIMIT}.
 * @returns Up to `limit` entries; possibly none.
 */
export function parseRecentlyShipped(
  markdown: string,
  limit: number = RECENTLY_SHIPPED_LIMIT
): ShippedEntry[] {
  const version = releaseLabel(markdown);
  const entries: ShippedEntry[] = [];
  let inFeatures = false;

  for (const line of markdown.split(/\r?\n/)) {
    if (entries.length >= limit) break;
    if (/^##\s/.test(line)) {
      inFeatures = FEATURES_HEADING.test(line);
      continue;
    }
    if (!inFeatures) continue;

    const bullet = /^\s*[-*]\s+(.+)$/.exec(line);
    if (!bullet) continue;
    const text = bullet[1].trim();
    if (text.endsWith(':')) continue;

    const { title, summary } = splitEntry(text);
    if (title) entries.push({ title, summary, version });
  }

  return entries;
}
