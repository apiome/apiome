/**
 * Export presets — the pure half (MFX-39.3, #4335).
 *
 * A preset saves an export's targets, each target's emit options (MFX-1.4) and an optional delivery
 * profile (MFX-38.4) once per workspace, by name. These types mirror the REST model; the helpers turn the
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
  deliveryProfileId: string | null;
  deliveryProfileName: string | null;
  updatedAt?: string | null;
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
  /** The delivery profiles to tick (the preset's, when it has one). */
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
  const deliveryProfiles = preset.deliveryProfileId ? [preset.deliveryProfileId] : [];
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
 * @param deliveryProfileId The delivery profile, or null.
 * @returns The body.
 */
export function presetBody(
  name: string,
  description: string,
  targets: PresetTarget[],
  deliveryProfileId: string | null,
): Record<string, unknown> {
  return {
    name: name.trim(),
    ...(description.trim() ? { description: description.trim() } : {}),
    targets: targets.map((t) => ({ target: t.target, ...(t.options && Object.keys(t.options).length ? { options: t.options } : {}) })),
    ...(deliveryProfileId ? { deliveryProfileId } : {}),
  };
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
  deliveryProfileId: string;
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
    deliveryProfileId: preset.deliveryProfileId ?? '',
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
      deliveryProfileId: draft.deliveryProfileId || null,
    },
  };
}
