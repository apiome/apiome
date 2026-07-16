/**
 * Best-effort mapping from a changelog entry's JSON Pointer to a line of the compare view's
 * rendered diff (CTG-3.2, #4476). The diff is a pretty-printed JSON document, so the pointer's
 * last meaningful key usually appears as a quoted object key on the line we want to scroll to.
 * This can only ever be a hint — a miss returns -1 and the compare view fails silently.
 */

/** Unescape one JSON Pointer segment (`~1` → `/`, then `~0` → `~`, per RFC 6901). */
function unescapePointerSegment(segment: string): string {
  return segment.replace(/~1/g, '/').replace(/~0/g, '~');
}

/**
 * Find the first diff line a JSON Pointer plausibly refers to.
 *
 * Takes the pointer's last non-numeric segment (array indices carry no searchable text) after
 * unescaping, then returns the index of the first line containing it as a quoted key
 * (`"<segment>"`), falling back to the first line containing the bare segment; -1 when the
 * pointer has no meaningful segment or nothing matches.
 */
export function findDiffLineIndexForPointer(diffLineTexts: string[], pointer: string): number {
  const segments = pointer
    .split('/')
    .filter((s) => s !== '')
    .map(unescapePointerSegment);

  let segment: string | undefined;
  for (let i = segments.length - 1; i >= 0; i--) {
    if (!/^\d+$/.test(segments[i])) {
      segment = segments[i];
      break;
    }
  }
  if (!segment) return -1;

  const quoted = `"${segment}"`;
  for (let i = 0; i < diffLineTexts.length; i++) {
    if (diffLineTexts[i].includes(quoted)) return i;
  }
  for (let i = 0; i < diffLineTexts.length; i++) {
    if (diffLineTexts[i].includes(segment)) return i;
  }
  return -1;
}
