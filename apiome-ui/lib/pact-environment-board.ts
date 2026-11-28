/**
 * The **Environments** page's two views — PFX-8.13 (#7310): the what-is-where **Board** and the
 * **History**. The shapes REST answers, the proxy paths and query checks, and the pure helpers the
 * page draws with.
 *
 * REST (`/v1/tenants/{t}/pact-environments`, OpenAPI 1.705.0):
 * * `GET board` — pacticipants × environments (non-production first, production last); each cell the
 *   running version(s) with can-i-deploy's verdict, and `next`: the newer version in the nearest
 *   environment to the left, with its verdict (the deploy simulator's answer). At most 100 verdicts;
 *   the rest say `checked: false` and why.
 * * `GET history` — deployed / undeployed / released / support-ended events, newest first, with who
 *   and can-i-deploy's answer when it was recorded.
 *
 * Authority: `docs/mockups/contracts/environments.html` (`v-board`, `v-time`).
 */

import { MAX_CURSOR_LENGTH, MAX_FILTER_LENGTH } from '@lib/pact-pacticipants';
import type { EnvironmentFacts, NamedPacticipant } from '@lib/pact-environments';

// --- shapes -------------------------------------------------------------------------------------

/** A verdict on the board: asked (`checked`), or not and why. */
export type BoardVerdict =
  | { checked: true; deployable: boolean | null; reason: string; counts: Record<string, number> }
  | { checked: false; notChecked: string };

/** A version running in one environment (every instance it runs in). */
export interface BoardVersion {
  version: string;
  applicationInstances: (string | null)[];
  deployedAt: string | null;
  verdict: BoardVerdict;
}

/** The version that could go into an environment next. */
export interface BoardNext {
  version: string;
  /** The name of the environment it runs in now (the nearest one to the left). */
  from: string;
  verdict: BoardVerdict;
}

/** One pacticipant in one environment. */
export interface BoardCell {
  /** The environment's uuid. */
  environment: string;
  deployed: BoardVersion[];
  next: BoardNext | null;
}

/** A release a pacticipant supports. */
export interface BoardRelease {
  version: string;
  /** The environment's name. */
  environment: string;
  releasedAt: string | null;
  verdict: BoardVerdict;
}

/** One pacticipant's row. */
export interface BoardRow {
  pacticipant: NamedPacticipant;
  /** Nothing of it is deployed or released anywhere. */
  idle: boolean;
  cells: BoardCell[];
  released: BoardRelease[];
}

/** `GET pact-environments/board`. */
export interface Board {
  environments: EnvironmentFacts[];
  rows: BoardRow[];
  truncated: boolean;
  checks: number;
  notChecked: number;
  evaluatedAt: string;
}

/** What happened. */
export type HistoryKind = 'deployed' | 'undeployed' | 'released' | 'support-ended';

/** One event of the history. */
export interface HistoryEvent {
  kind: HistoryKind;
  uuid: string;
  at: string;
  pacticipant: NamedPacticipant;
  version: string;
  environment: EnvironmentFacts;
  applicationInstance: string | null;
  actor: string | null;
  /** can-i-deploy's answer when it was recorded (`deployed` / `released`); `null`: not known. */
  verdict: 'deployable' | 'not-deployable' | 'unknown' | null;
  /** The version a deployment replaced. */
  replaces: string | null;
}

/** `GET pact-environments/history`. */
export interface EventsPage {
  events: HistoryEvent[];
  nextCursor: string | null;
}

// --- proxy paths and checks ---------------------------------------------------------------------

/** The REST path of the board. */
export const BOARD_PROXY_PATH = 'pact-environments/board';
/** The REST path of the history. */
export const EVENTS_PROXY_PATH = 'pact-environments/history';
/** The history's page size. */
export const EVENTS_PAGE = 25;
/** The parameters the history accepts. */
export const EVENTS_PARAMETERS = ['environment', 'pacticipant', 'cursor'] as const;

/** A checked history question, or why it is refused. */
export type PickedEvents = { ok: true; query: URLSearchParams } | { ok: false; error: string };

/**
 * Check a history question before forwarding it: `environment`, `pacticipant` and `cursor` are
 * optional; any other, repeated, empty or over-long parameter is refused with a sentence naming it.
 * The page size is the proxy's (`limit` is not the browser's to set).
 *
 * @param params - The browser's query string.
 * @returns The parameters to forward (with `limit`), or the reason for a 400.
 */
export function pickEventsQuery(params: URLSearchParams): PickedEvents {
  const query = new URLSearchParams();
  for (const [key, raw] of params.entries()) {
    if (!(EVENTS_PARAMETERS as readonly string[]).includes(key)) {
      return { ok: false, error: `Unsupported parameter ${key}: the history accepts ${EVENTS_PARAMETERS.join(', ')}.` };
    }
    if (query.has(key)) return { ok: false, error: `The ${key} parameter is given more than once.` };
    const value = raw.trim();
    if (!value) return { ok: false, error: `The ${key} parameter is empty.` };
    const most = key === 'cursor' ? Math.min(200, MAX_CURSOR_LENGTH) : MAX_FILTER_LENGTH;
    if (value.length > most) return { ok: false, error: `The ${key} parameter is longer than ${most} characters.` };
    query.set(key, value);
  }
  query.set('limit', String(EVENTS_PAGE));
  return { ok: true, query };
}

// --- drawing the board --------------------------------------------------------------------------

/** A dot's tone: verified with everything beside it, unverified, failing, or not checked. */
export type DotTone = 'ok' | 'warn' | 'danger' | 'neutral';

/**
 * The dot of a verdict.
 *
 * @param verdict - The verdict.
 * @returns `ok` (deployable), `danger` (not), `warn` (a verification is missing), `neutral` (not asked).
 */
export function dotTone(verdict: BoardVerdict): DotTone {
  if (!verdict.checked) return 'neutral';
  if (verdict.deployable === true) return 'ok';
  if (verdict.deployable === false) return 'danger';
  return 'warn';
}

/** The words a dot's tone stands for (the legend, and what a screen reader hears). */
export const DOT_WORDS: Record<DotTone, string> = {
  ok: 'verified with everything beside it',
  warn: 'unverified',
  danger: 'failing',
  neutral: 'not checked',
};

/**
 * The line under a running version: its instances, and what is wrong when it is not verified.
 *
 * @param version - The version.
 * @returns E.g. `eu-west · us-east`, `1 failing pact`, `unverified`, or `''`.
 */
export function versionNote(version: BoardVersion): string {
  const parts: string[] = [];
  const named = version.applicationInstances.filter((instance): instance is string => Boolean(instance));
  if (named.length) parts.push(named.join(' · '));
  const verdict = version.verdict;
  if (!verdict.checked) parts.push('not checked');
  else if (verdict.deployable === false) {
    const failed = verdict.counts.failed ?? 0;
    parts.push(failed ? `${failed} failing ${failed === 1 ? 'pact' : 'pacts'}` : 'not deployable');
  } else if (verdict.deployable === null) parts.push('unverified');
  return parts.join(' · ');
}

/** What the board says about a cell's next version. */
export interface NextLabel {
  text: string;
  tone: 'ok' | 'danger' | 'neutral';
  /** Whether it can be recorded straight away (a "yes"). */
  canGo: boolean;
}

/**
 * The words for a cell's next version.
 *
 * @param next - The next version.
 * @returns `2.7.0 can go`, `2.7.0 blocked`, `2.7.0 unverified` or `2.7.0 not checked`.
 */
export function nextLabel(next: BoardNext): NextLabel {
  const verdict = next.verdict;
  if (!verdict.checked) return { text: `${next.version} not checked`, tone: 'neutral', canGo: false };
  if (verdict.deployable === true) return { text: `${next.version} can go`, tone: 'ok', canGo: true };
  if (verdict.deployable === false) return { text: `${next.version} blocked`, tone: 'danger', canGo: false };
  return { text: `${next.version} unverified`, tone: 'neutral', canGo: false };
}

/** The facts strip over the board. */
export interface BoardFacts {
  environments: number;
  services: number;
  running: number;
  blocked: number;
}

/**
 * Count what the facts strip shows.
 *
 * @param board - The board.
 * @returns Environments, services (rows), versions running (deployed per cell, plus releases), and
 *   blocked promotions (next versions can-i-deploy said no to).
 */
export function boardFacts(board: Board): BoardFacts {
  let running = 0;
  let blocked = 0;
  for (const row of board.rows) {
    running += row.released.length;
    for (const cell of row.cells) {
      running += cell.deployed.length;
      if (cell.next && cell.next.verdict.checked && cell.next.verdict.deployable === false) blocked += 1;
    }
  }
  return { environments: board.environments.length, services: board.rows.length, running, blocked };
}

/**
 * The environment the legend's **Open the deploy simulator** link opens: the first production
 * environment, else the last column.
 *
 * @param board - The board.
 * @returns The environment's name, or `null` when there is none.
 */
export function simulatorEnvironment(board: Board): string | null {
  const production = board.environments.find((environment) => environment.production);
  return (production ?? board.environments[board.environments.length - 1])?.name ?? null;
}

/**
 * The services deployed to an environment, for **Record an undeployment** — each once, by name,
 * with the instances it runs in.
 *
 * @param board - The board.
 * @param environmentUuid - The environment's uuid.
 * @returns The services and their instances (`null` is the unnamed one).
 */
export function deployedIn(
  board: Board,
  environmentUuid: string,
): { pacticipant: NamedPacticipant; versions: { version: string; instance: string | null }[] }[] {
  const index = board.environments.findIndex((environment) => environment.uuid === environmentUuid);
  if (index < 0) return [];
  return board.rows
    .filter((row) => row.cells[index]?.deployed.length)
    .map((row) => ({
      pacticipant: row.pacticipant,
      versions: row.cells[index].deployed.flatMap((version) =>
        version.applicationInstances.map((instance) => ({ version: version.version, instance })),
      ),
    }));
}

// --- drawing the history ------------------------------------------------------------------------

/**
 * An event as the timeline's title says it.
 *
 * @param event - The event.
 * @returns E.g. `Billing Service 2.7.0 deployed to Staging`, `Mobile App 1.7.4 — support ended`.
 */
export function eventTitle(event: HistoryEvent): string {
  const what = `${event.pacticipant.name} ${event.version}`;
  const where = event.environment.displayName || event.environment.name;
  if (event.kind === 'deployed') return `${what} deployed to ${where}`;
  if (event.kind === 'undeployed') return `${what} undeployed from ${where}`;
  if (event.kind === 'released') return `${what} released to ${where}`;
  return `${what} — support ended in ${where}`;
}

/**
 * The line under an event's title.
 *
 * @param event - The event.
 * @returns E.g. `Replaced 2.6.1 · instance eu-west`, `Its pacts no longer hold providers back`.
 */
export function eventDetail(event: HistoryEvent): string {
  const parts: string[] = [];
  if (event.replaces) parts.push(`Replaced ${event.replaces}`);
  if (event.applicationInstance) parts.push(`instance ${event.applicationInstance}`);
  if (event.kind === 'undeployed') parts.push('No longer running there');
  if (event.kind === 'support-ended') parts.push('Its pacts no longer hold its counterparts back');
  return parts.join(' · ');
}

/**
 * The badge an event carries about its verdict at the time.
 *
 * @param event - The event.
 * @returns `Not verified at the time` (a "no" or not known yet when recorded), `Verified at the time`,
 *   or `null` (an ending, or a record made before Apiome kept the verdict).
 */
export function eventBadge(event: HistoryEvent): { label: string; variant: 'ok' | 'warn' } | null {
  if (event.verdict === 'deployable') return { label: 'Verified at the time', variant: 'ok' };
  if (event.verdict === 'not-deployable' || event.verdict === 'unknown') return { label: 'Not verified at the time', variant: 'warn' };
  return null;
}
