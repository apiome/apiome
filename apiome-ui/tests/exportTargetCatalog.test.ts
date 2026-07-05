/**
 * exportTargetCatalog — pure mapping helpers for the ExportDialog (MFX-6.1, #3855).
 *
 * Covers the response→card mapping (icon resolution, availability), the fidelity tier badge
 * classes, the count-chip derivation, and the flattening of a Pydantic-generated options
 * JSON Schema (MFX-1.4) into renderable primitive fields — including the `$ref`/`allOf`/`anyOf`
 * wrappers Pydantic emits for enums and Optional fields, and the skipping of complex types.
 */

import {
  changedOptions,
  exportTargetCards,
  fidelityChips,
  optionFieldsFromSchema,
  tierBadgeClass,
  type ExportTargetEntry,
  type ExportTargetsResponse,
  type TargetFidelitySummary,
} from '../src/app/components/ade/dashboard/export/exportTargetCatalog';

function makeEntry(overrides: Partial<ExportTargetEntry['descriptor']> = {}, fidelity: Partial<TargetFidelitySummary> = {}): ExportTargetEntry {
  return {
    descriptor: {
      key: 'openapi',
      format: 'openapi-3.1',
      label: 'OpenAPI 3.1',
      description: 'Export the canonical model as an OpenAPI 3.1 document.',
      icon: 'file-json',
      paradigm: 'rest',
      multi_file: false,
      needs_toolchain: false,
      available: true,
      unavailable_reason: null,
      ...overrides,
    },
    capability_profile: { operations: true },
    options_schema: {},
    default_options: {},
    fidelity: {
      tier: 'lossless',
      preserved_percent: 100,
      total: 42,
      preserved: 42,
      dropped: 0,
      approximated: 0,
      synthesized: 0,
      ...fidelity,
    },
  };
}

describe('exportTargetCards', () => {
  it('maps every valid entry to a card with a resolved icon and availability', () => {
    const response: ExportTargetsResponse = {
      artifact: 'proj-1',
      version: null,
      version_record_id: 'rev-1',
      version_label: '1.2.0',
      targets: [
        makeEntry(),
        makeEntry({ key: 'proto', label: 'gRPC / Protobuf', available: false, unavailable_reason: 'Requires buf' }),
      ],
    };

    const cards = exportTargetCards(response);
    expect(cards).toHaveLength(2);
    expect(cards[0].key).toBe('openapi');
    expect(cards[0].available).toBe(true);
    expect(typeof cards[0].icon).toBeTruthy();
    expect(cards[1].key).toBe('proto');
    expect(cards[1].available).toBe(false);
  });

  it('returns no cards for a missing response and skips keyless entries', () => {
    expect(exportTargetCards(null)).toEqual([]);
    expect(exportTargetCards(undefined)).toEqual([]);

    const broken = makeEntry();
    (broken.descriptor as { key: string }).key = '';
    const response: ExportTargetsResponse = {
      artifact: 'proj-1',
      version_record_id: 'rev-1',
      targets: [broken, makeEntry({ key: 'avro' })],
    };
    const cards = exportTargetCards(response);
    expect(cards).toHaveLength(1);
    expect(cards[0].key).toBe('avro');
  });

  it('treats an absent available flag (older REST) as available', () => {
    const entry = makeEntry();
    delete (entry.descriptor as { available?: boolean }).available;
    const response: ExportTargetsResponse = {
      artifact: 'proj-1',
      version_record_id: 'rev-1',
      targets: [entry],
    };
    expect(exportTargetCards(response)[0].available).toBe(true);
  });
});

describe('tierBadgeClass', () => {
  it('colors lossless green, lossy amber, and types-only red (mockup palette)', () => {
    expect(tierBadgeClass('lossless')).toContain('emerald');
    expect(tierBadgeClass('lossy')).toContain('amber');
    expect(tierBadgeClass('types-only')).toContain('rose');
  });
});

describe('fidelityChips', () => {
  it('drops empty loss buckets but always keeps the clean chip', () => {
    const chips = fidelityChips({
      tier: 'lossless',
      preserved_percent: 100,
      total: 10,
      preserved: 10,
      dropped: 0,
      approximated: 0,
      synthesized: 0,
    });
    expect(chips.map((chip) => chip.key)).toEqual(['preserved']);
    expect(chips[0].count).toBe(10);
  });

  it('orders loss chips worst-first: dropped, approximated, synthesized, clean', () => {
    const chips = fidelityChips({
      tier: 'lossy',
      preserved_percent: 64,
      total: 58,
      preserved: 51,
      dropped: 3,
      approximated: 2,
      synthesized: 2,
    });
    expect(chips.map((chip) => `${chip.count} ${chip.label}`)).toEqual([
      '3 dropped',
      '2 approximated',
      '2 synthesized',
      '51 clean',
    ]);
  });
});

describe('optionFieldsFromSchema', () => {
  // A realistic Pydantic v2 model_json_schema() shape: a boolean, an Optional[str] (anyOf with
  // null), an enum class (allOf → $ref → $defs), a Literal enum (inline enum), and a Dict field
  // that must be skipped.
  const SCHEMA = {
    $defs: {
      Syntax: {
        title: 'Syntax',
        enum: ['proto3', 'editions'],
        type: 'string',
      },
    },
    properties: {
      emit_services: {
        type: 'boolean',
        default: true,
        title: 'Emit Services',
        description: 'Emit service/rpc blocks.',
      },
      package: {
        anyOf: [{ type: 'string' }, { type: 'null' }],
        default: null,
        title: 'Package',
        description: 'Override the emitted package.',
      },
      syntax: {
        allOf: [{ $ref: '#/$defs/Syntax' }],
        default: 'proto3',
      },
      flavor: {
        enum: ['single-file', 'multi-file'],
        type: 'string',
        default: 'single-file',
        title: 'Flavor',
      },
      persisted_field_numbers: {
        type: 'object',
        additionalProperties: { type: 'integer' },
        default: {},
        title: 'Persisted Field Numbers',
      },
    },
    title: 'ProtoEmitOptions',
    type: 'object',
  };

  const DEFAULTS = {
    emit_services: true,
    package: null,
    syntax: 'proto3',
    flavor: 'single-file',
    persisted_field_numbers: {},
  };

  it('flattens booleans, optional strings, and enums; skips complex types', () => {
    const fields = optionFieldsFromSchema(SCHEMA, DEFAULTS);
    expect(fields.map((field) => field.key)).toEqual(['emit_services', 'package', 'syntax', 'flavor']);

    const byKey = new Map(fields.map((field) => [field.key, field]));
    expect(byKey.get('emit_services')).toMatchObject({
      kind: 'boolean',
      label: 'Emit Services',
      defaultValue: true,
    });
    expect(byKey.get('package')).toMatchObject({ kind: 'string', defaultValue: null });
    expect(byKey.get('syntax')).toMatchObject({
      kind: 'enum',
      enumValues: ['proto3', 'editions'],
      defaultValue: 'proto3',
    });
    expect(byKey.get('flavor')).toMatchObject({
      kind: 'enum',
      enumValues: ['single-file', 'multi-file'],
    });
  });

  it('humanizes a snake_case key when the schema has no title', () => {
    const fields = optionFieldsFromSchema(
      { properties: { emit_services: { type: 'boolean', default: true } } },
      { emit_services: true },
    );
    expect(fields[0].label).toBe('Emit services');
  });

  it('returns no fields for an absent or property-less schema', () => {
    expect(optionFieldsFromSchema(null, null)).toEqual([]);
    expect(optionFieldsFromSchema({}, {})).toEqual([]);
    expect(optionFieldsFromSchema({ type: 'object' }, {})).toEqual([]);
  });
});

describe('changedOptions', () => {
  const DEFAULTS = { emit_services: true, package: null, syntax: 'proto3' };

  it('returns null when every value matches the target defaults', () => {
    expect(changedOptions({ emit_services: true, package: null, syntax: 'proto3' }, DEFAULTS)).toBeNull();
  });

  it('returns only the values that differ from the defaults', () => {
    expect(
      changedOptions({ emit_services: false, package: null, syntax: 'proto3' }, DEFAULTS),
    ).toEqual({ emit_services: false });
    expect(
      changedOptions({ emit_services: true, package: 'com.example', syntax: 'editions' }, DEFAULTS),
    ).toEqual({ package: 'com.example', syntax: 'editions' });
  });
});
