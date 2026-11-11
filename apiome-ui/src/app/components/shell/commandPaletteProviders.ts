'use client';

import * as React from 'react';
import type { PaletteCommandGroup } from './commandPaletteModel';

/**
 * Contributions to the one command palette from the surfaces that mount it (SUX-4.5,
 * apiome#6770; apiome/private-suite#2904).
 *
 * `CommandPaletteHost` knows the platform's own rows — Favorites, Recent, Jump to and Actions.
 * A surface with commands of its own (the commercial Designer's canvas, its git verbs, its
 * workspace search) used to answer by mounting a *second* palette on the same chord, and two
 * palettes on `⌘K` is one too many. This module is the alternative: a surface registers a
 * **provider** — a few headed groups of {@link PaletteCommandGroup} rows — and the host draws
 * them in the same list, with the same keyboard, filter, footer and focus handling.
 *
 * Two halves, both external stores so the host and a provider can sit in unrelated trees:
 *
 * | Half | Written by | Read by |
 * | --- | --- | --- |
 * | **Providers** — what each surface contributes | {@link useCommandPaletteProvider} | the host |
 * | **Session** — whether the palette is open, and what is typed | the host | {@link useCommandPaletteSession} |
 *
 * The session half is what lets a provider answer from a server search: it reads the query,
 * asks its own API while the palette is open, and hands back rows marked
 * {@link PaletteCommand.prematched} so the palette's fuzzy filter does not second-guess them.
 *
 * ### Rules a provider follows
 *
 * - **Command ids are namespaced here**, as `<provider id>:<command id>`, so two providers can
 *   both have a `commit` row without colliding in cmdk's value space. Group ids are namespaced
 *   the same way.
 * - **The last registration for an id wins**, which is what a remount relies on; registering
 *   under a fresh id adds a provider rather than replacing one.
 * - **A provider never opens the palette itself** — it calls `openCommandPalette()` like any
 *   other entry point, optionally with a query (`{ query: 'git' }`).
 */

/** A provider's contribution: its groups, already gated by whatever the surface knows. */
export interface CommandPaletteProviderEntry {
  /** Stable id; prefixes every command and group id this provider contributes. */
  id: string;
  /** The groups to draw, in the provider's own order. Empty groups are dropped by the host. */
  groups: readonly PaletteCommandGroup[];
}

/** Registered providers, in registration order. */
const providers = new Map<string, readonly PaletteCommandGroup[]>();

/** Watchers of {@link providers} — the host. */
const providerListeners = new Set<() => void>();

/** The flattened, namespaced groups, cached so `useSyncExternalStore` sees a stable value. */
let providerSnapshot: readonly PaletteCommandGroup[] = Object.freeze([]);

/** What the server renders: no provider has registered during SSR. */
const NO_GROUPS: readonly PaletteCommandGroup[] = Object.freeze([]);

/**
 * Prefix a provider's group and command ids with the provider id.
 *
 * @param providerId The provider the groups came from.
 * @param groups Its groups, as it declared them.
 * @returns The same groups with namespaced ids; everything else is untouched.
 */
export function namespaceProviderGroups(
  providerId: string,
  groups: readonly PaletteCommandGroup[]
): PaletteCommandGroup[] {
  return groups.map((group) => ({
    ...group,
    id: `${providerId}:${group.id}`,
    commands: group.commands.map((command) => ({
      ...command,
      id: `${providerId}:${command.id}`,
      group: `${providerId}:${group.id}`,
    })),
  }));
}

/** Rebuild the snapshot and tell the host. */
function notifyProviders(): void {
  providerSnapshot = Object.freeze(
    [...providers.entries()].flatMap(([id, groups]) => namespaceProviderGroups(id, groups))
  );
  for (const listener of providerListeners) listener();
}

/**
 * Register (or replace) one provider's groups.
 *
 * @param entry The provider id and its groups.
 * @returns The unregister function. It removes the provider only while the registration it
 *   made is still the current one, so a stale cleanup cannot remove a newer registration.
 */
export function registerCommandPaletteProvider(entry: CommandPaletteProviderEntry): () => void {
  const groups = entry.groups;
  providers.set(entry.id, groups);
  notifyProviders();
  return () => {
    if (providers.get(entry.id) !== groups) return;
    providers.delete(entry.id);
    notifyProviders();
  };
}

/**
 * Every provider's groups, namespaced, in registration order.
 *
 * @returns A stable array until a provider registers, updates or leaves.
 */
export function getCommandPaletteProviderGroups(): readonly PaletteCommandGroup[] {
  return providerSnapshot;
}

/**
 * Watch the provider registry.
 *
 * @param listener Called whenever a provider registers, updates or leaves.
 * @returns The unsubscribe function.
 */
export function subscribeCommandPaletteProviders(listener: () => void): () => void {
  providerListeners.add(listener);
  return () => {
    providerListeners.delete(listener);
  };
}

/**
 * Contribute groups to the palette for as long as the calling component is mounted.
 *
 * Pass a memoised array: every new array re-publishes the provider, which re-renders the host.
 * That is cheap — the host is a closed dialog most of the time — but a provider that rebuilds
 * its groups on every render of a busy component would re-render the palette with it.
 *
 * @param id The provider id — see {@link CommandPaletteProviderEntry.id}.
 * @param groups The groups to draw. An empty array contributes nothing but keeps the id held.
 */
export function useCommandPaletteProvider(
  id: string,
  groups: readonly PaletteCommandGroup[]
): void {
  React.useEffect(() => registerCommandPaletteProvider({ id, groups }), [id, groups]);
}

/**
 * The host's providers, as React state.
 *
 * @returns Every provider's namespaced groups. Empty during SSR.
 */
export function useCommandPaletteProviderGroups(): readonly PaletteCommandGroup[] {
  return React.useSyncExternalStore(
    subscribeCommandPaletteProviders,
    getCommandPaletteProviderGroups,
    () => NO_GROUPS
  );
}

/** Clear every provider. For tests. */
export function resetCommandPaletteProviders(): void {
  providers.clear();
  notifyProviders();
}

/* -------------------------------------------------------------------------
   The session
   ------------------------------------------------------------------------- */

/** What a provider may know about the palette right now. */
export interface CommandPaletteSession {
  /** Whether the palette is open. A provider does no work for a closed palette. */
  open: boolean;
  /** The input exactly as typed, `>` prefix included. Parse it with `parseCommandQuery`. */
  query: string;
}

/** The session before any host has published one. */
const CLOSED_SESSION: CommandPaletteSession = Object.freeze({ open: false, query: '' });

let session: CommandPaletteSession = CLOSED_SESSION;
const sessionListeners = new Set<() => void>();

/**
 * Publish the palette's open flag and query. Called by the host only.
 *
 * @param next The host's current state.
 */
export function publishCommandPaletteSession(next: CommandPaletteSession): void {
  if (next.open === session.open && next.query === session.query) return;
  session = Object.freeze({ open: next.open, query: next.query });
  for (const listener of sessionListeners) listener();
}

/**
 * The current session.
 *
 * @returns The latest published session; closed and empty until a host publishes one.
 */
export function getCommandPaletteSession(): CommandPaletteSession {
  return session;
}

/**
 * Watch the session.
 *
 * @param listener Called whenever the palette opens, closes or its query changes.
 * @returns The unsubscribe function.
 */
export function subscribeCommandPaletteSession(listener: () => void): () => void {
  sessionListeners.add(listener);
  return () => {
    sessionListeners.delete(listener);
  };
}

/**
 * The palette's open flag and query, as React state — for a provider that searches as the
 * reader types.
 *
 * @returns The current session. Closed and empty during SSR.
 */
export function useCommandPaletteSession(): CommandPaletteSession {
  return React.useSyncExternalStore(
    subscribeCommandPaletteSession,
    getCommandPaletteSession,
    () => CLOSED_SESSION
  );
}

/** Forget the session. For tests. */
export function resetCommandPaletteSession(): void {
  publishCommandPaletteSession(CLOSED_SESSION);
}
