/**
 * Unit tests for the import-source card catalog merge logic (MFI-1.3, #3735).
 *
 * The merge is the heart of the acceptance criterion: a server-registered adapter must surface as a
 * new card, while the built-in cards stay exactly as they were and registry entries already covered
 * by a built-in must never produce a duplicate.
 */

import { FileCode, FileJson, Radio } from 'lucide-react';
import {
  REGISTRY_KEYS_COVERED_BY_BUILTINS,
  baseImportSourceCards,
  mergeImportSourceCards,
  panelForInputKinds,
  resolveLucideIcon,
  type ImportSourceDescriptor,
} from '../src/app/components/ade/dashboard/importSourceCatalog';

/** The AsyncAPI source as the REST registry advertises it (MFI-8.5, #3763). */
const ASYNCAPI_DESCRIPTOR: ImportSourceDescriptor = {
  key: 'asyncapi',
  label: 'AsyncAPI',
  description: 'Import an AsyncAPI 2.x or 3.x event-driven API description.',
  icon: 'radio',
  paradigm: 'event',
  input_kinds: ['file', 'url', 'paste'],
  supports_live_discovery: false,
  formats: ['asyncapi-2', 'asyncapi-3'],
};

const BUILTIN_KEYS = ['file', 'url', 'clipboard', 'git', 'swaggerhub', 'postman', 'mcp'];

function descriptor(overrides: Partial<ImportSourceDescriptor>): ImportSourceDescriptor {
  return {
    key: 'graphql',
    label: 'GraphQL',
    description: 'Import a GraphQL schema.',
    icon: 'file-json',
    paradigm: 'graphql',
    input_kinds: ['file', 'paste'],
    supports_live_discovery: false,
    formats: ['graphql'],
    ...overrides,
  };
}

describe('baseImportSourceCards', () => {
  it('returns the seven built-in cards in their original order', () => {
    expect(baseImportSourceCards().map((c) => c.key)).toEqual(BUILTIN_KEYS);
  });

  it('marks every built-in card as builtin with a routable panel', () => {
    for (const card of baseImportSourceCards()) {
      expect(card.builtin).toBe(true);
      expect(card.panel).not.toBeNull();
    }
  });

  it('returns a fresh copy each call (callers can mutate safely)', () => {
    const a = baseImportSourceCards();
    const b = baseImportSourceCards();
    expect(a).not.toBe(b);
    expect(a[0]).not.toBe(b[0]);
  });
});

describe('mergeImportSourceCards', () => {
  it('returns only the built-ins when the registry list is empty/undefined', () => {
    expect(mergeImportSourceCards(undefined).map((c) => c.key)).toEqual(BUILTIN_KEYS);
    expect(mergeImportSourceCards([]).map((c) => c.key)).toEqual(BUILTIN_KEYS);
  });

  it('keeps the built-in cards unchanged ahead of any registry cards', () => {
    const cards = mergeImportSourceCards([descriptor({})]);
    expect(cards.slice(0, BUILTIN_KEYS.length).map((c) => c.key)).toEqual(BUILTIN_KEYS);
  });

  it('appends a new adapter as a card with no other changes (acceptance criterion)', () => {
    const cards = mergeImportSourceCards([descriptor({ key: 'graphql' })]);
    const graphql = cards.find((c) => c.key === 'graphql');
    expect(graphql).toBeDefined();
    expect(graphql?.builtin).toBe(false);
    expect(graphql?.label).toBe('GraphQL');
    expect(graphql?.panel).toBe('file');
    expect(cards).toHaveLength(BUILTIN_KEYS.length + 1);
  });

  it('does NOT duplicate registry keys already covered by a built-in (openapi, sample)', () => {
    const cards = mergeImportSourceCards([
      descriptor({ key: 'openapi', label: 'OpenAPI / Swagger', input_kinds: ['file', 'url', 'paste'] }),
      descriptor({ key: 'sample', label: 'Sample', input_kinds: ['paste'] }),
    ]);
    expect(cards.map((c) => c.key)).toEqual(BUILTIN_KEYS);
    expect(REGISTRY_KEYS_COVERED_BY_BUILTINS.has('openapi')).toBe(true);
    expect(REGISTRY_KEYS_COVERED_BY_BUILTINS.has('sample')).toBe(true);
  });

  it('does not let a registry descriptor override a built-in card with the same key', () => {
    const cards = mergeImportSourceCards([
      descriptor({ key: 'file', label: 'HIJACKED', description: 'nope' }),
    ]);
    const file = cards.find((c) => c.key === 'file');
    expect(file?.label).toBe('File Upload');
    expect(file?.builtin).toBe(true);
    expect(cards).toHaveLength(BUILTIN_KEYS.length);
  });

  it('renders a discovery-only adapter as a disabled card (no generic panel yet)', () => {
    const cards = mergeImportSourceCards([
      descriptor({ key: 'grpc-reflect', input_kinds: ['discovery'], supports_live_discovery: true }),
    ]);
    const grpc = cards.find((c) => c.key === 'grpc-reflect');
    expect(grpc).toBeDefined();
    expect(grpc?.panel).toBeNull();
  });

  it('de-duplicates repeated registry keys and sorts appended cards by key', () => {
    const cards = mergeImportSourceCards([
      descriptor({ key: 'wsdl', label: 'WSDL' }),
      descriptor({ key: 'asyncapi', label: 'AsyncAPI' }),
      descriptor({ key: 'wsdl', label: 'WSDL again' }),
    ]);
    const appended = cards.slice(BUILTIN_KEYS.length).map((c) => c.key);
    expect(appended).toEqual(['asyncapi', 'wsdl']);
  });

  it('skips malformed descriptors (missing/empty key)', () => {
    const cards = mergeImportSourceCards([
      { key: '' } as ImportSourceDescriptor,
      undefined as unknown as ImportSourceDescriptor,
      descriptor({ key: 'smithy' }),
    ]);
    expect(cards.map((c) => c.key)).toEqual([...BUILTIN_KEYS, 'smithy']);
  });
});

describe('AsyncAPI source card (MFI-8.5)', () => {
  it('surfaces the registered AsyncAPI adapter as a usable file/url/paste card', () => {
    const cards = mergeImportSourceCards([ASYNCAPI_DESCRIPTOR]);
    const asyncapi = cards.find((c) => c.key === 'asyncapi');
    expect(asyncapi).toBeDefined();
    expect(asyncapi?.builtin).toBe(false);
    expect(asyncapi?.label).toBe('AsyncAPI');
    // file/url/paste inputs route to the generic file intake panel.
    expect(asyncapi?.panel).toBe('file');
    // AsyncAPI is its own registry source, not subsumed by a built-in card.
    expect(REGISTRY_KEYS_COVERED_BY_BUILTINS.has('asyncapi')).toBe(false);
  });

  it('resolves the descriptor `radio` icon to the Lucide Radio component', () => {
    expect(resolveLucideIcon(ASYNCAPI_DESCRIPTOR.icon)).toBe(Radio);
  });
});

describe('panelForInputKinds', () => {
  it('prefers file, then url, then paste', () => {
    expect(panelForInputKinds(['paste', 'url', 'file'])).toBe('file');
    expect(panelForInputKinds(['paste', 'url'])).toBe('url');
    expect(panelForInputKinds(['paste'])).toBe('clipboard');
  });

  it('returns null for discovery-only or empty input kinds', () => {
    expect(panelForInputKinds(['discovery'])).toBeNull();
    expect(panelForInputKinds([])).toBeNull();
    expect(panelForInputKinds(undefined)).toBeNull();
  });
});

describe('resolveLucideIcon', () => {
  it('resolves a kebab-case Lucide name to its component', () => {
    expect(resolveLucideIcon('file-json')).toBe(FileJson);
  });

  it('falls back to a neutral icon for unknown or empty names', () => {
    expect(resolveLucideIcon('definitely-not-an-icon')).toBe(FileCode);
    expect(resolveLucideIcon('')).toBe(FileCode);
    expect(resolveLucideIcon(undefined)).toBe(FileCode);
  });
});
