/**
 * Export presets — the pure half (MFX-39.3, #4335).
 *
 * Matching a preset's targets to the studio's cards (by key, then by format), what applying a one- or
 * multi-target preset selects, the body Save as preset sends, the summary line, and the Presets tab's
 * edit form (JSON options checked, every problem listed).
 */

import {
  applyPresetToStudio,
  draftFromPreset,
  matchCard,
  presetBody,
  targetsSummary,
  updateFromDraft,
  type ExportPreset,
} from '../src/app/components/ade/export-studio/presets/exportPresetsModel';

const CARDS = [
  { key: 'openapi', available: true, entry: { descriptor: { key: 'openapi', format: 'openapi-3.1' } } },
  { key: 'protobuf', available: true, entry: { descriptor: { key: 'protobuf', format: 'proto3' } } },
  { key: 'wsdl', available: false, entry: { descriptor: { key: 'wsdl', format: 'wsdl-1.1' } } },
];

function preset(partial: Partial<ExportPreset> = {}): ExportPreset {
  return {
    id: 'x1', name: 'nightly-sync', description: null,
    targets: [{ target: 'openapi-3.1', options: { openapi_version: '3.0' } }],
    deliveryProfileId: 'p1', deliveryProfileName: 'lake', ...partial,
  };
}

describe('applying a preset', () => {
  it('matches cards by key, then by format', () => {
    expect(matchCard(CARDS, 'openapi')?.key).toBe('openapi');
    expect(matchCard(CARDS, 'openapi-3.1')?.key).toBe('openapi');
    expect(matchCard(CARDS, 'graphql')).toBeNull();
  });

  it('selects a one-target preset with its options and delivery', () => {
    const applied = applyPresetToStudio(preset(), CARDS);
    expect(applied.single?.card.key).toBe('openapi');
    expect(applied.single?.options).toEqual({ openapi_version: '3.0' });
    expect(applied.multi).toBeNull();
    expect(applied.deliveryProfiles).toEqual(['p1']);
    expect(applied.missing).toEqual([]);
  });

  it('ticks a multi-target preset and names what this source cannot export to', () => {
    const applied = applyPresetToStudio(
      preset({ deliveryProfileId: null, targets: [{ target: 'openapi' }, { target: 'protobuf', options: { package: 'a.v1' } },
        { target: 'wsdl' }, { target: 'graphql' }] }),
      CARDS,
    );
    expect(applied.single).toBeNull();
    expect(applied.multi).toEqual({ keys: ['openapi', 'protobuf'], options: { openapi: {}, protobuf: { package: 'a.v1' } } });
    expect(applied.missing).toEqual(['wsdl', 'graphql']);
    expect(applied.deliveryProfiles).toEqual([]);
  });
});

describe('saving a preset', () => {
  it('sends only what is set', () => {
    expect(presetBody(' nightly ', '', [{ target: 'openapi', options: null }, { target: 'protobuf', options: { a: 1 } }], null))
      .toEqual({ name: 'nightly', targets: [{ target: 'openapi' }, { target: 'protobuf', options: { a: 1 } }] });
    expect(presetBody('n', ' Nightly ', [{ target: 'openapi', options: {} }], 'p1'))
      .toEqual({ name: 'n', description: 'Nightly', targets: [{ target: 'openapi' }], deliveryProfileId: 'p1' });
  });

  it('summarises targets with their options', () => {
    expect(targetsSummary([{ target: 'openapi', options: { openapi_version: '3.0', include_paths: false } }, { target: 'protobuf' }]))
      .toBe('openapi (openapi_version=3.0, include_paths=false), protobuf');
  });
});

describe('the Presets tab form', () => {
  it('round-trips a preset into the PATCH body', () => {
    const draft = draftFromPreset(preset());
    expect(draft.targets[0].optionsText).toContain('"openapi_version": "3.0"');
    expect(updateFromDraft({ ...draft, deliveryProfileId: '' })).toEqual({
      problems: [],
      body: { name: 'nightly-sync', description: '', targets: [{ target: 'openapi-3.1', options: { openapi_version: '3.0' } }],
        deliveryProfileId: null },
    });
  });

  it('lists every problem', () => {
    const { body, problems } = updateFromDraft({
      name: ' ', description: '', deliveryProfileId: '',
      targets: [{ target: '', optionsText: '{}' }, { target: 'openapi', optionsText: '[1]' }, { target: 'x', optionsText: '{' }],
    });
    expect(body).toBeUndefined();
    expect(problems).toEqual([
      'Name the preset.', 'Target 1 needs a format.', 'The options of openapi must be a JSON object.',
      'The options of x must be a JSON object.',
    ]);
    expect(updateFromDraft({ name: 'n', description: '', deliveryProfileId: '', targets: [{ target: '', optionsText: '' }] }).problems)
      .toEqual(['Keep at least one target.']);
  });
});
