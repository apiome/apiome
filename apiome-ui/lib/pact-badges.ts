/**
 * The **Badges** panel of a pacticipant's Settings — PFX-8.11 (#7308).
 *
 * Pact badges are the public, anonymous routes of PFX-1.10 (#6923):
 * `GET /v1/browse/tenants/{tenant}/projects/{project}/pact-badges/…/badge.svg` (and its
 * `shields.json` twin) for a pacticipant bound to a **public** project, or for one pact pair with
 * a side bound to it. They show the latest pact's verification — `verified`, `failing` or
 * `unknown` — and nothing else.
 *
 * The panel picks what the badge is **for** (the pacticipant, or one pair), offers its Markdown in
 * each **style** (Apiome's SVG, or shields.io reading the `shields.json` endpoint) and the bare
 * image URL as the pills of a copyable block, previews the very SVG REST
 * serves (the `/api/pact/badges` proxy reads it), and copies the Markdown. A selector the broker
 * has (a branch, a tag, an environment) is not served — the broker's tag badges answer `501` —
 * and the panel says so instead of offering it.
 */

import type { CommandSurface } from '@lib/command-block';
import type { PacticipantPact } from '@lib/pact-detail';
import { isPacticipantHandle } from '@lib/pact-pacticipants';

/**
 * REST's base URL as a README reader reaches it (the build's `NEXT_PUBLIC_REST_API_BASE_URL`), for
 * the copied Markdown.
 */
export const PUBLIC_REST_BASE_URL = process.env.NEXT_PUBLIC_REST_API_BASE_URL || 'http://localhost:8000/v1';

/** What a badge is for. */
export type BadgeTarget =
  | { kind: 'pacticipant'; slug: string }
  | { kind: 'pair'; provider: string; consumer: string };

/** How the README shows it. */
export type BadgeStyle = 'svg' | 'shields';


/** What a badge says. */
export type BadgeStatus = 'verified' | 'failing' | 'unknown';

/** Why the panel offers no branch, tag or environment selector. */
export const SELECTOR_NOTE =
  'A badge shows the latest pact’s verification. A badge for a branch, a tag or an environment is not served: the Pact Broker’s tag badges answer 501 here.';

/** One choice of the **For** select. */
export interface BadgeChoice {
  /** A stable key: `pacticipant` or `pair:{provider}|{consumer}`. */
  id: string;
  label: string;
  target: BadgeTarget;
}

/**
 * What a badge can be for: the pacticipant itself (all its pacts), then every pair it is in.
 *
 * @param pacticipant - Its handle and name.
 * @param pacts - The integrations it is in.
 * @returns The choices, the pacticipant first.
 */
export function badgeChoices(pacticipant: { slug: string; name: string }, pacts: PacticipantPact[]): BadgeChoice[] {
  const choices: BadgeChoice[] = [
    {
      id: 'pacticipant',
      label: `${pacticipant.name} (all its pacts)`,
      target: { kind: 'pacticipant', slug: pacticipant.slug },
    },
  ];
  for (const pact of pacts) {
    const id = `pair:${pact.provider.slug}|${pact.consumer.slug}`;
    if (choices.some((choice) => choice.id === id)) continue;
    choices.push({
      id,
      label: `${pact.consumer.name} → ${pact.provider.name}`,
      target: { kind: 'pair', provider: pact.provider.slug, consumer: pact.consumer.slug },
    });
  }
  return choices;
}

/**
 * The badge's path below REST's `/v1`.
 *
 * @param tenant - The workspace handle.
 * @param project - The public project's slug.
 * @param target - What it is for.
 * @param file - `badge.svg` or `shields.json`.
 * @returns E.g. `/browse/tenants/acme/projects/ledger/pact-badges/pacticipants/ledger-api/badge.svg`.
 */
export function badgePath(
  tenant: string,
  project: string,
  target: BadgeTarget,
  file: 'badge.svg' | 'shields.json',
): string {
  const root = `/browse/tenants/${encodeURIComponent(tenant)}/projects/${encodeURIComponent(project)}/pact-badges`;
  const tail =
    target.kind === 'pacticipant'
      ? `pacticipants/${encodeURIComponent(target.slug)}`
      : `pacts/provider/${encodeURIComponent(target.provider)}/consumer/${encodeURIComponent(target.consumer)}`;
  return `${root}/${tail}/${file}`;
}

/**
 * The Markdown a README embeds.
 *
 * @param restBase - REST's public base URL, ending in `/v1` (no trailing slash).
 * @param tenant - The workspace handle.
 * @param project - The public project's slug.
 * @param target - What it is for.
 * @param style - Apiome's SVG, or shields.io reading the endpoint.
 * @returns E.g. `![pact](https://api.example.com/v1/browse/…/badge.svg)`.
 */
export function badgeMarkdown(
  restBase: string,
  tenant: string,
  project: string,
  target: BadgeTarget,
  style: BadgeStyle,
): string {
  const base = restBase.replace(/\/+$/, '');
  if (style === 'svg') return `![pact](${base}${badgePath(tenant, project, target, 'badge.svg')})`;
  const endpoint = `${base}${badgePath(tenant, project, target, 'shields.json')}`;
  return `![pact](https://img.shields.io/endpoint?url=${encodeURIComponent(endpoint)})`;
}

/**
 * The pills of the panel's copy block: the Markdown in each style, and the image URL.
 *
 * @param restBase - REST's public base URL, ending in `/v1`.
 * @param tenant - The workspace handle.
 * @param project - The public project's slug.
 * @param target - What it is for.
 * @returns The surfaces, Apiome's SVG first.
 */
export function badgeSurfaces(restBase: string, tenant: string, project: string, target: BadgeTarget): CommandSurface[] {
  const base = restBase.replace(/\/+$/, '');
  return [
    { id: 'svg', label: 'Markdown', text: badgeMarkdown(base, tenant, project, target, 'svg') },
    {
      id: 'shields',
      label: 'shields.io',
      text: badgeMarkdown(base, tenant, project, target, 'shields'),
      notes: ['shields.io draws the badge from the shields.json endpoint; style it with its query parameters.'],
    },
    { id: 'url', label: 'Image URL', text: `${base}${badgePath(tenant, project, target, 'badge.svg')}` },
  ];
}

/** A checked `/api/pact/badges` query, or why it is refused. */
export type BadgeQuery = { ok: true; project: string; target: BadgeTarget } | { ok: false; error: string };

/** The parameters the proxy accepts. */
const BADGE_PARAMS = ['project', 'pacticipant', 'provider', 'consumer'] as const;

/** A project slug REST could serve: lowercase letters, digits and `-` / `_` / `.`. */
const PROJECT_SLUG = /^[a-z0-9][a-z0-9._-]{0,127}$/;

/**
 * Read the proxy's query: `project` and either `pacticipant`, or `provider` and `consumer`.
 * Anything else, a repeated or malformed value, is refused with its name.
 *
 * @param params - The browser's query string.
 * @returns The project and target, or the refusal.
 */
export function parseBadgeQuery(params: URLSearchParams): BadgeQuery {
  const seen = new Set<string>();
  for (const key of params.keys()) {
    if (!(BADGE_PARAMS as readonly string[]).includes(key)) {
      return { ok: false, error: `Unsupported parameter ${key}: send project and pacticipant, or provider and consumer.` };
    }
    if (seen.has(key)) return { ok: false, error: `The ${key} parameter is given more than once.` };
    seen.add(key);
  }
  const project = params.get('project') ?? '';
  if (!PROJECT_SLUG.test(project)) return { ok: false, error: 'Give the slug of the project the badge is served for.' };
  const pacticipant = params.get('pacticipant');
  const provider = params.get('provider');
  const consumer = params.get('consumer');
  if (pacticipant !== null) {
    if (provider !== null || consumer !== null) {
      return { ok: false, error: 'Send pacticipant, or provider and consumer, not both.' };
    }
    if (!isPacticipantHandle(pacticipant)) return { ok: false, error: 'The pacticipant is not a handle.' };
    return { ok: true, project, target: { kind: 'pacticipant', slug: pacticipant } };
  }
  if (provider === null || consumer === null) {
    return { ok: false, error: 'Send pacticipant, or both provider and consumer.' };
  }
  if (!isPacticipantHandle(provider) || !isPacticipantHandle(consumer)) {
    return { ok: false, error: 'The provider and consumer must be handles.' };
  }
  return { ok: true, project, target: { kind: 'pair', provider, consumer } };
}

/** What `/api/pact/badges` answers: the SVG REST serves and the word it shows. */
export interface BadgeAnswer {
  /** The workspace handle the badge URL names. */
  tenant: string;
  status: BadgeStatus;
  /** The SVG document, exactly as REST served it. */
  svg: string;
}

/**
 * The word a `shields.json` document shows, as one of the three states.
 *
 * @param body - The parsed document.
 * @returns The state; `unknown` for anything else.
 */
export function statusFromShields(body: unknown): BadgeStatus {
  const message = body && typeof body === 'object' ? (body as Record<string, unknown>).message : undefined;
  return message === 'verified' || message === 'failing' ? message : 'unknown';
}

/**
 * An `<img>` source for an SVG document.
 *
 * @param svg - The document.
 * @returns A `data:` URL.
 */
export function svgDataUrl(svg: string): string {
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}

/** What the panel says when there is no badge to show. */
export const NO_PROJECT_NOTE =
  'Badges are served for a pacticipant linked to a public project. Link a project under General, and publish a public version of it.';

/** What the panel says when the linked project serves no badge. */
export function notPublicNote(projectName: string): string {
  return `${projectName} serves no badge: it has no published, public version. Publish one to turn its badges on.`;
}
