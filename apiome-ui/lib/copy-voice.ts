/**
 * The DESIGN.md §10 voice, as code (HIVE-10.4, #5340).
 *
 * §10 asks four things of every empty, loading, error and gated state:
 *
 *   - titles are nouns ("Projects"), never "Manage …" / "Configure …";
 *   - buttons are verbs ("New project", not "OK");
 *   - descriptions answer "what is this for?" in **≤ 14 words**;
 *   - errors say what happened **and** what to do ("Slug is taken — try `acme-eu`").
 *
 * and §2 adds the voice rule behind the empty state: "Nothing published yet — publish a
 * version to see it here." not "No records found."
 *
 * The rules live here so the same predicate judges the shared error surfaces at runtime
 * ({@link withNextAction}, used by `ErrorState`, `ErrorBanner`, the app `toast` and the
 * imperative dialogs) and the source at test time (`tests/copy-voice-gate.test.ts`).
 * Everything here is pure and string-in / string-out.
 */

/** The §10 ceiling on a state's description, in words. */
export const MAX_DESCRIPTION_WORDS = 14;

/**
 * The next action appended to a failure that names none.
 *
 * Lower-case because it follows an em dash: "Couldn't load projects — try again."
 */
export const DEFAULT_NEXT_ACTION = 'try again.';

/** What a failure with no message at all says. */
export const UNKNOWN_FAILURE = 'Something went wrong — try again.';

/**
 * Count the words in a piece of copy.
 *
 * @param text The copy. `null`/`undefined` count as empty.
 * @returns The number of whitespace-separated words (0 for blank input).
 */
export function countWords(text: string | null | undefined): number {
  if (!text) return 0;
  const trimmed = text.trim();
  return trimmed ? trimmed.split(/\s+/).length : 0;
}

/**
 * Whether a description fits the §10 ceiling.
 *
 * @param text The description.
 * @param max The ceiling; defaults to {@link MAX_DESCRIPTION_WORDS}.
 * @returns `true` when the description has at most `max` words.
 */
export function fitsDescription(
  text: string | null | undefined,
  max = MAX_DESCRIPTION_WORDS
): boolean {
  return countWords(text) <= max;
}

/**
 * Copy that reports what a query returned instead of what the reader can do — the
 * "No records found" class §2 rules out. Anchored to the whole string so a sentence that merely
 * contains "found" ("Slug not found — try `acme-eu`") is not caught.
 */
const NO_RECORDS_PATTERNS: readonly RegExp[] = [
  /^no (records|results|data|items|entries|rows)( found| available| to (show|display))?[.!]?$/i,
  /^no [a-z][a-z -]{0,40} (were |was )?found[.!]?$/i,
  /^nothing found[.!]?$/i,
];

/**
 * Whether a string is "No records found"-class copy.
 *
 * @param text The copy to judge.
 * @returns `true` for copy that only says a lookup came back empty.
 */
export function isNoRecordsCopy(text: string | null | undefined): boolean {
  if (!text) return false;
  const trimmed = text.trim();
  return NO_RECORDS_PATTERNS.some((pattern) => pattern.test(trimmed));
}

/**
 * Whether a page title breaks §10 — a verb ("Manage users", "Configure SDKs") or the
 * same verb hiding as a noun ("User Management", "System Configuration").
 *
 * @param title The page or section title.
 * @returns `true` when the title should be rewritten as a plain noun.
 */
export function isBannedPageTitle(title: string | null | undefined): boolean {
  if (!title) return false;
  const trimmed = title.trim();
  return /^(manage|configure)\b/i.test(trimmed) || /\b(management|configuration)$/i.test(trimmed);
}

/**
 * The clause that only reports a failure. Removed before looking for a next action, so
 * "Failed to update version" does not count "update" as advice.
 */
const FAILURE_CLAUSE =
  /\b(failed to|could not|couldn't|cannot|can't|unable to|error while|error)\s+[a-z-]+/gi;

/**
 * Words and phrases that tell the reader what to do next. Deliberately broad: a false
 * "names an action" leaves a message as written, which is the safe direction.
 */
const NEXT_ACTION =
  /\b(try|retry|reload|refresh|check|select|choose|pick|enter|re-?enter|add|create|link|connect|reconnect|sign in|sign out|log in|contact|ask|open|go to|use|fix|remove|wait|enable|allow|publish|import|run|save|paste|upload|rename|resolve|review|verify|confirm|copy|install|switch|close|provide|give|type|request|edit|restore|upgrade|adjust|clear|change|make sure|please|required|must|should|need to|needs to)\b/i;

/**
 * Whether a failure message already names a next action.
 *
 * @param message The message to judge.
 * @returns `true` when, outside its failure clause, the message advises an action.
 */
export function namesNextAction(message: string | null | undefined): boolean {
  if (!message) return false;
  return NEXT_ACTION.test(message.replace(FAILURE_CLAUSE, ' '));
}

/**
 * Make a failure message say what to do, the way §10 does: "what happened — what to do".
 *
 * A message that already names an action is returned unchanged; one that does not gains
 * `— <nextAction>`, its own trailing punctuation dropped first. Blank input becomes
 * {@link UNKNOWN_FAILURE}, so an error surface never renders an empty sentence.
 *
 * @param message What happened, typically a caught error's message.
 * @param nextAction What to do; defaults to {@link DEFAULT_NEXT_ACTION}.
 * @returns The message, guaranteed to name a next action.
 */
export function withNextAction(
  message: string | null | undefined,
  nextAction: string = DEFAULT_NEXT_ACTION
): string {
  const trimmed = (message ?? '').trim();
  if (!trimmed) return UNKNOWN_FAILURE;
  if (namesNextAction(trimmed)) return trimmed;
  const action = nextAction.trim() || DEFAULT_NEXT_ACTION;
  return `${trimmed.replace(/[.!:;,\s]+$/, '')} — ${action}`;
}

/**
 * A message that reports an operation going wrong — the kind "try again" can fix — as opposed
 * to one that explains a rule ("System primitives cannot be edited", "That name is taken").
 * Appending "try again" to a rule would be advice that cannot work, so the rule-shaped
 * messages are left to say what they say.
 */
const OPERATIONAL_FAILURE =
  /\b(fail(ed|s|ure)?|could not|couldn't|unable to|error|unexpected|went wrong|timed out|time ?out|network|unavailable|unreachable|[45]\d\d)\b/i;

/**
 * Whether a message reports an operation going wrong (rather than a rule being enforced).
 *
 * @param message The message to judge.
 * @returns `true` for "Failed to …", "Could not …", "… error", HTTP status codes and the like.
 */
export function isOperationalFailure(message: string | null | undefined): boolean {
  if (!message) return false;
  return OPERATIONAL_FAILURE.test(message);
}

/**
 * {@link withNextAction} for surfaces that also carry rule and validation messages — toasts
 * and dialogs. An operational failure gains a next action; a message that explains a rule is
 * returned as written (trimmed); blank input becomes {@link UNKNOWN_FAILURE}.
 *
 * @param message What happened.
 * @param nextAction What to do; defaults to {@link DEFAULT_NEXT_ACTION}.
 * @returns The message, with a next action wherever retrying is the honest advice.
 */
export function voiceFailure(
  message: string | null | undefined,
  nextAction: string = DEFAULT_NEXT_ACTION
): string {
  const trimmed = (message ?? '').trim();
  if (!trimmed) return UNKNOWN_FAILURE;
  return isOperationalFailure(trimmed) ? withNextAction(trimmed, nextAction) : trimmed;
}
