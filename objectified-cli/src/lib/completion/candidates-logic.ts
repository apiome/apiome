import type { Config } from "@oclif/core";

import {
  configLayerForProfile,
  listAvailableProfileNames,
  resolveEffectiveProfile,
} from "../cli-context.js";
import type { ObjectifiedApi } from "../client.js";
import type { ParsedTomlConfig } from "../config.js";
import { withCompletionCache } from "./cache.js";
import { extractProfileFromWords, matchesPrefix, splitCommandTokens } from "./parse-line.js";

const GLOBAL_FLAG_TOKENS = [
  "--api-key",
  "--base-url",
  "--config",
  "--json",
  "--no-json",
  "--color",
  "--no-color",
  "--profile",
  "--quiet",
  "--no-quiet",
  "-q",
  "--verbose",
  "--no-verbose",
  "--help",
  "-h",
];

/** Roadmap commands not yet registered — still complete for power users (#3193). */
const EXTRA_SUBCOMMANDS: Record<string, string[]> = {
  projects: ["show"],
  versions: ["list", "show"],
  classes: ["show"],
  primitives: ["show"],
  tenants: ["use"],
};

function uniqSorted(values: string[]): string[] {
  return [...new Set(values)].sort((a, b) => a.localeCompare(b));
}

function tenantSlugsFromConfig(doc: ParsedTomlConfig): string[] {
  const s = new Set<string>();
  if (doc.default.tenantSlug) s.add(doc.default.tenantSlug);
  for (const p of Object.values(doc.profiles)) {
    const slug = p.tenantSlug;
    if (slug) s.add(slug);
  }
  return uniqSorted([...s]);
}

function resolveCommandId(config: Config, cmdParts: string[]): string | undefined {
  for (let len = cmdParts.length; len >= 1; len--) {
    const id = cmdParts.slice(0, len).join(":");
    if (config.commands.some((c) => c.id === id)) return id;
  }
  return undefined;
}

function flagsForResolvedCommand(config: Config, cmdId: string | undefined): string[] {
  const out = new Set<string>(GLOBAL_FLAG_TOKENS);
  if (cmdId === undefined) return uniqSorted([...out]);
  const cmd = config.commands.find((c) => c.id === cmdId);
  if (!cmd) return uniqSorted([...out]);
  for (const name of Object.keys(cmd.flags)) {
    const f = cmd.flags[name];
    if (!f || f.hidden) continue;
    if ("char" in f && typeof f.char === "string") out.add(`-${f.char}`);
    out.add(`--${name}`);
  }
  return uniqSorted([...out]);
}

function nextStaticSegments(config: Config, cmdParts: string[]): string[] {
  const seen = new Set<string>();
  const prefix = cmdParts.length === 0 ? "" : `${cmdParts.join(":")}:`;

  if (cmdParts.length === 0) {
    for (const c of config.commands) {
      if (c.hidden) continue;
      const head = c.id.split(":")[0];
      if (head) seen.add(head);
    }
  } else {
    for (const c of config.commands) {
      if (c.hidden) continue;
      const id = c.id;
      if (!id.startsWith(prefix)) continue;
      const rest = id.slice(prefix.length);
      const seg = rest.split(":")[0];
      if (seg !== undefined && seg !== "") seen.add(seg);
    }
  }

  const topicHead = cmdParts[0];
  if (topicHead !== undefined && cmdParts.length === 1 && EXTRA_SUBCOMMANDS[topicHead]) {
    for (const x of EXTRA_SUBCOMMANDS[topicHead]) seen.add(x);
  }

  return uniqSorted([...seen]);
}

function filterByPrefix(values: string[], partial: string): string[] {
  return values.filter((v) => matchesPrefix(v, partial));
}

async function loadProjectSlugIdRows(
  api: ObjectifiedApi,
  profileCacheKey: string,
  tenantSlug: string,
): Promise<Array<{ slug: string; id: string }>> {
  const rows = await withCompletionCache(profileCacheKey, ["projects-map", tenantSlug], async () => {
    const list = await api.listProjects(tenantSlug);
    return list.map((p) => `${p.slug}\t${p.id}`);
  });
  const out: Array<{ slug: string; id: string }> = [];
  for (const row of rows) {
    const tab = row.indexOf("\t");
    if (tab <= 0) continue;
    const slug = row.slice(0, tab);
    const id = row.slice(tab + 1);
    if (slug !== "" && id !== "") out.push({ slug, id });
  }
  return out;
}

async function resolveProjectIdBySlug(
  api: ObjectifiedApi,
  profileCacheKey: string,
  tenantSlug: string,
  projectSlug: string,
): Promise<string | undefined> {
  const rows = await loadProjectSlugIdRows(api, profileCacheKey, tenantSlug);
  return rows.find((r) => r.slug === projectSlug)?.id;
}

async function tryDynamicCandidates(opts: {
  api: ObjectifiedApi;
  tenantSlug: string | undefined;
  profileCacheKey: string;
  configDoc: ParsedTomlConfig;
  cmdParts: string[];
  current: string;
}): Promise<string[] | undefined> {
  const { api, tenantSlug, profileCacheKey, configDoc, cmdParts, current } = opts;

  if (cmdParts[0] === "tenants" && cmdParts[1] === "use" && cmdParts.length === 2) {
    return filterByPrefix(tenantSlugsFromConfig(configDoc), current);
  }

  if (!tenantSlug || tenantSlug === "") return undefined;

  if (cmdParts[0] === "projects" && cmdParts[1] === "show" && cmdParts.length === 2) {
    const rows = await loadProjectSlugIdRows(api, profileCacheKey, tenantSlug);
    return filterByPrefix(
      uniqSorted(rows.map((r) => r.slug)),
      current,
    );
  }

  if (cmdParts[0] === "versions" && cmdParts[1] === "list" && cmdParts.length === 2) {
    const rows = await loadProjectSlugIdRows(api, profileCacheKey, tenantSlug);
    return filterByPrefix(
      uniqSorted(rows.map((r) => r.slug)),
      current,
    );
  }

  if (cmdParts[0] === "versions" && cmdParts[1] === "list" && cmdParts.length === 3) {
    const projectSlug = cmdParts[2];
    if (projectSlug === undefined || projectSlug === "") return [];
    const projectId = await resolveProjectIdBySlug(api, profileCacheKey, tenantSlug, projectSlug);
    if (projectId === undefined) return [];
    const values = await withCompletionCache(
      profileCacheKey,
      ["versions", tenantSlug, projectId],
      async () => {
        const rows = await api.listVersions(tenantSlug, projectId);
        const ids = rows.flatMap((v) => [v.version_id, v.id]);
        return uniqSorted(ids);
      },
    );
    return filterByPrefix(values, current);
  }

  if (cmdParts[0] === "versions" && cmdParts[1] === "show" && cmdParts.length === 2) {
    const rows = await loadProjectSlugIdRows(api, profileCacheKey, tenantSlug);
    return filterByPrefix(
      uniqSorted(rows.map((r) => r.slug)),
      current,
    );
  }

  if (cmdParts[0] === "versions" && cmdParts[1] === "show" && cmdParts.length === 3) {
    const projectSlug = cmdParts[2];
    if (projectSlug === undefined || projectSlug === "") return [];
    const projectId = await resolveProjectIdBySlug(api, profileCacheKey, tenantSlug, projectSlug);
    if (projectId === undefined) return [];
    const values = await withCompletionCache(
      profileCacheKey,
      ["versions", tenantSlug, projectId],
      async () => {
        const rows = await api.listVersions(tenantSlug, projectId);
        const ids = rows.flatMap((v) => [v.version_id, v.id]);
        return uniqSorted(ids);
      },
    );
    return filterByPrefix(values, current);
  }

  if (cmdParts[0] === "classes" && cmdParts[1] === "show" && cmdParts.length === 2) {
    const values = await withCompletionCache(profileCacheKey, ["classes", tenantSlug], async () => {
      const rows = await api.listClasses(tenantSlug);
      return uniqSorted(rows.map((c) => c.name));
    });
    return filterByPrefix(values, current);
  }

  if (cmdParts[0] === "primitives" && cmdParts[1] === "show" && cmdParts.length === 2) {
    const values = await withCompletionCache(profileCacheKey, ["primitives", tenantSlug], async () => {
      const rows = await api.listPrimitives(tenantSlug);
      return uniqSorted(rows.map((p) => p.name));
    });
    return filterByPrefix(values, current);
  }

  return undefined;
}

export async function computeCompletionCandidates(opts: {
  config: Config;
  api: ObjectifiedApi;
  baseUrl: string;
  configDoc: ParsedTomlConfig;
  env: NodeJS.ProcessEnv;
  words: string[];
  cword: number;
}): Promise<string[]> {
  const { config, api, baseUrl, configDoc, env, words, cword } = opts;
  const stdinProfile = extractProfileFromWords(words, cword);
  const effectiveProfile = resolveEffectiveProfile(stdinProfile, env, configDoc);
  const layer = configLayerForProfile(configDoc, effectiveProfile);
  const tenantSlug =
    typeof env.OBJECTIFIED_TENANT === "string" && env.OBJECTIFIED_TENANT !== ""
      ? env.OBJECTIFIED_TENANT
      : layer.tenantSlug;

  const profileCacheKey = `${baseUrl}|${effectiveProfile}|${tenantSlug ?? ""}`;

  const prev = cword > 0 ? words[cword - 1] : undefined;
  const { cmdParts, current } = splitCommandTokens(words, cword);

  if (prev === "--profile") {
    return filterByPrefix(listAvailableProfileNames(configDoc), current);
  }

  if (current.startsWith("--profile=")) {
    const rest = current.slice("--profile=".length);
    return filterByPrefix(listAvailableProfileNames(configDoc), rest).map((p) => `--profile=${p}`);
  }

  if (current.startsWith("-")) {
    const cmdId = resolveCommandId(config, cmdParts);
    return filterByPrefix(flagsForResolvedCommand(config, cmdId), current);
  }

  try {
    const dyn = await tryDynamicCandidates({
      api,
      tenantSlug,
      profileCacheKey,
      configDoc,
      cmdParts,
      current,
    });
    if (dyn !== undefined) return dyn;
  } catch {
    /* offline / auth — fall through */
  }

  const next = nextStaticSegments(config, cmdParts);
  return filterByPrefix(next, current);
}
