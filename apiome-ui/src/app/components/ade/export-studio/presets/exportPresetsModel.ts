/**
 * Export presets — the pure half (MFX-39.3, #4335).
 *
 * A preset saves an export's targets, each target's emit options (MFX-1.4) and up to five delivery
 * profiles (MFX-38.4; several since MFX-46.4, #4382) once per workspace, by name. These types mirror the REST model; the helpers turn the
 * studio's current selection into a preset, a preset back into the studio's selection, and the Presets
 * tab's edit form into the body `PATCH` takes. Option values are checked by the REST layer against each
 * emitter's schema; here only the shape (a JSON object) is checked.
 */

/** One target of a preset, with its emit options. */
export interface PresetTarget {
  target: string;
  options?: Record<string, unknown> | null;
}

/** A stored preset, as `GET /api/export/presets` returns it. */
export interface ExportPreset {
  id: string;
  name: string;
  description: string | null;
  targets: PresetTarget[];
  /** The first delivery profile (kept for older clients); {@link presetProfileIds} is the full list. */
  deliveryProfileId: string | null;
  deliveryProfileName: string | null;
  /** Every delivery profile, in the order the export is delivered with them (MFX-46.4). */
  deliveryProfileIds?: string[];
  /** Their names, in the same order. */
  deliveryProfileNames?: string[];
  updatedAt?: string | null;
}

/** The most delivery profiles one preset (and one export) may hold. */
export const MAX_PRESET_DELIVERY_PROFILES = 5;

/**
 * A preset's delivery profiles, in order: the list when the REST layer sent one, else the single profile.
 *
 * @param preset The preset.
 * @returns The profile ids (empty when it delivers nowhere).
 */
export function presetProfileIds(preset: Pick<ExportPreset, 'deliveryProfileId' | 'deliveryProfileIds'>): string[] {
  if (preset.deliveryProfileIds && preset.deliveryProfileIds.length > 0) return [...preset.deliveryProfileIds];
  return preset.deliveryProfileId ? [preset.deliveryProfileId] : [];
}

/**
 * The names of a preset's delivery profiles, for a summary line.
 *
 * @param preset The preset.
 * @returns The names (empty when it delivers nowhere, or the REST layer sent none).
 */
export function presetProfileNames(
  preset: Pick<ExportPreset, 'deliveryProfileName' | 'deliveryProfileNames'>,
): string[] {
  if (preset.deliveryProfileNames && preset.deliveryProfileNames.length > 0) return [...preset.deliveryProfileNames];
  return preset.deliveryProfileName ? [preset.deliveryProfileName] : [];
}

/** The most targets one preset may hold (the REST layer's limit). */
export const MAX_PRESET_TARGETS = 16;

/** The fields of a target card a preset target is matched against. */
export interface PresetCardLike {
  key: string;
  available?: boolean;
  entry: { descriptor: { key?: string; format?: string } };
}

/**
 * The card a preset target names: by registry key first, then by output format (`openapi-3.1`).
 *
 * @param cards The studio's target cards.
 * @param target The preset target's key or format.
 * @returns The card, or null when this source offers no such target.
 */
export function matchCard<T extends PresetCardLike>(cards: readonly T[], target: string): T | null {
  return (
    cards.find((card) => card.key === target) ??
    cards.find((card) => card.entry.descriptor.format === target) ??
    null
  );
}

/** What applying a preset does to the studio. */
export interface PresetApplication<T extends PresetCardLike> {
  /** One target: the card to select and the options to seed. */
  single: { card: T; options: Record<string, unknown> } | null;
  /** Several targets: the card keys to tick, and each one's options. */
  multi: { keys: string[]; options: Record<string, Record<string, unknown>> } | null;
  /** The delivery profiles to tick (the preset's, in order). */
  deliveryProfiles: string[];
  /** Preset targets this source cannot export to (unknown or unavailable here). */
  missing: string[];
}

/**
 * Work out how a preset applies to the studio's targets.
 *
 * @param preset The preset.
 * @param cards The studio's target cards.
 * @returns The selection to make, and any target that could not be matched.
 */
export function applyPresetToStudio<T extends PresetCardLike>(
  preset: ExportPreset,
  cards: readonly T[],
): PresetApplication<T> {
  const missing: string[] = [];
  const matched: { card: T; options: Record<string, unknown> }[] = [];
  for (const entry of preset.targets) {
    const card = matchCard(cards, entry.target);
    if (!card || card.available === false) missing.push(entry.target);
    else matched.push({ card, options: { ...(entry.options ?? {}) } });
  }
  const deliveryProfiles = presetProfileIds(preset);
  if (preset.targets.length === 1) {
    return { single: matched[0] ?? null, multi: null, deliveryProfiles, missing };
  }
  return {
    single: null,
    multi: {
      keys: matched.map((m) => m.card.key),
      options: Object.fromEntries(matched.map((m) => [m.card.key, m.options])),
    },
    deliveryProfiles,
    missing,
  };
}

/**
 * The `POST /api/export/presets` body for what the studio has selected.
 *
 * @param name The preset name.
 * @param description What it is for (blank sends none).
 * @param targets The selected targets with their changed options, in order.
 * @param deliveryProfileIds The delivery profiles, in order (at most five are sent).
 * @returns The body.
 */
export function presetBody(
  name: string,
  description: string,
  targets: PresetTarget[],
  deliveryProfileIds: readonly string[],
): Record<string, unknown> {
  const profiles = uniqueProfiles(deliveryProfileIds);
  return {
    name: name.trim(),
    ...(description.trim() ? { description: description.trim() } : {}),
    targets: targets.map((t) => ({ target: t.target, ...(t.options && Object.keys(t.options).length ? { options: t.options } : {}) })),
    ...(profiles.length ? { deliveryProfileIds: profiles } : {}),
  };
}

/** Non-empty profile ids, each once, in order, at most {@link MAX_PRESET_DELIVERY_PROFILES}. */
function uniqueProfiles(ids: readonly string[]): string[] {
  const out: string[] = [];
  for (const id of ids) {
    const value = id.trim();
    if (value && !out.includes(value)) out.push(value);
  }
  return out.slice(0, MAX_PRESET_DELIVERY_PROFILES);
}

/**
 * One line for a preset's targets: `openapi (openapi_version=3.0), protobuf`.
 *
 * @param targets The preset's targets.
 * @returns The summary.
 */
export function targetsSummary(targets: readonly PresetTarget[]): string {
  return targets
    .map((t) => {
      const options = Object.entries(t.options ?? {})
        .map(([key, value]) => `${key}=${typeof value === 'string' ? value : JSON.stringify(value)}`)
        .join(', ');
      return options ? `${t.target} (${options})` : t.target;
    })
    .join(', ');
}

/** The Presets tab's edit form. */
export interface PresetDraft {
  name: string;
  description: string;
  /** One row per target: its key, and its options as JSON text. */
  targets: { target: string; optionsText: string }[];
  /** The delivery profiles, in order. */
  deliveryProfileIds: string[];
}

/** A draft for editing a stored preset. */
export function draftFromPreset(preset: ExportPreset): PresetDraft {
  return {
    name: preset.name,
    description: preset.description ?? '',
    targets: preset.targets.map((t) => ({
      target: t.target,
      optionsText: t.options && Object.keys(t.options).length ? JSON.stringify(t.options, null, 2) : '',
    })),
    deliveryProfileIds: presetProfileIds(preset),
  };
}

/**
 * The `PATCH` body for an edited preset, or the problems that stop it being sent.
 *
 * @param draft The edited draft.
 * @returns `{ body }`, or `{ problems }` — one message per bad field.
 */
export function updateFromDraft(draft: PresetDraft): { body?: Record<string, unknown>; problems: string[] } {
  const problems: string[] = [];
  if (!draft.name.trim()) problems.push('Name the preset.');
  const rows = draft.targets.filter((row) => row.target.trim() || row.optionsText.trim());
  if (rows.length === 0) problems.push('Keep at least one target.');
  if (rows.length > MAX_PRESET_TARGETS) problems.push(`A preset holds at most ${MAX_PRESET_TARGETS} targets.`);
  const named = draft.deliveryProfileIds.map((id) => id.trim()).filter(Boolean);
  if (new Set(named).size < named.length) problems.push('Name each delivery profile once.');
  if (named.length > MAX_PRESET_DELIVERY_PROFILES) {
    problems.push(`A preset delivers with at most ${MAX_PRESET_DELIVERY_PROFILES} profiles.`);
  }
  const targets: PresetTarget[] = [];
  rows.forEach((row, index) => {
    const target = row.target.trim();
    if (!target) problems.push(`Target ${index + 1} needs a format.`);
    let options: Record<string, unknown> = {};
    if (row.optionsText.trim()) {
      try {
        const parsed: unknown = JSON.parse(row.optionsText);
        if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('not an object');
        options = parsed as Record<string, unknown>;
      } catch {
        problems.push(`The options of ${target || `target ${index + 1}`} must be a JSON object.`);
      }
    }
    targets.push({ target, options });
  });
  if (problems.length > 0) return { problems };
  return {
    problems,
    body: {
      name: draft.name.trim(),
      description: draft.description.trim(),
      targets: targets.map((t) => ({ target: t.target, options: t.options })),
      deliveryProfileIds: uniqueProfiles(draft.deliveryProfileIds),
    },
  };
}

/** A JSON value with object keys sorted, so two equal selections serialise alike. */
function canonical(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.keys(value as Record<string, unknown>)
        .sort()
        .map((key) => [key, canonical((value as Record<string, unknown>)[key])]),
    );
  }
  return value;
}

/**
 * A comparable fingerprint of an export selection (MFX-46.4): its targets in order with their options
 * (`null` and `{}` alike, keys in any order) and its delivery profiles in order.
 *
 * Export studio compares the fingerprint of what is selected with the one recorded when a preset was
 * applied or saved: while they match, that preset is *in play* — the one **Auto-export on publish**
 * subscribes the project to.
 *
 * @param targets The targets, in order.
 * @param deliveryProfileIds The delivery profiles, in order.
 * @returns The fingerprint.
 */
export function selectionSignature(targets: readonly PresetTarget[], deliveryProfileIds: readonly string[]): string {
  return JSON.stringify({
    targets: targets.map((t) => [t.target, canonical(t.options && Object.keys(t.options).length ? t.options : {})]),
    profiles: uniqueProfiles(deliveryProfileIds),
  });
}

/** The export preset Export studio's selection currently stands for, and the selection it stood for. */
export interface PresetInPlay {
  preset: ExportPreset;
  /** {@link selectionSignature} of the selection when the preset was applied or saved. */
  signature: string;
}
