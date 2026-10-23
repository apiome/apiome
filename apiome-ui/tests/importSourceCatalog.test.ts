/**
 * Unit tests for the import-source card catalog merge logic (MFI-1.3, #3735).
 *
 * The merge is the heart of the acceptance criterion: a server-registered adapter must surface as a
 * new card, while the built-in cards stay exactly as they were and registry entries already covered
 * by a built-in must never produce a duplicate.
 */

import { Bot, BotMessageSquare, Cloud, FileCode, FileJson, Globe, Radio, Share2, Waypoints } from 'lucide-react';
import {
  REGISTRY_KEYS_COVERED_BY_BUILTINS,
  baseImportSourceCards,
  baseIntakeTiles,
  mergeImportSourceCards,
  filterCardsForVariant,
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

/** The GraphQL source as the REST registry advertises it (MFI-10.6, #3775). */
const GRAPHQL_DESCRIPTOR: ImportSourceDescriptor = {
  key: 'graphql',
  label: 'GraphQL',
  description: 'Import a GraphQL schema from SDL or live endpoint introspection.',
  icon: 'waypoints',
  paradigm: 'graph',
  input_kinds: ['file', 'url', 'paste', 'discovery'],
  supports_live_discovery: true,
  formats: ['graphql'],
};

/** The gRPC / Protobuf source as the REST registry advertises it (MFI-9.6, #3769). */
const GRPC_DESCRIPTOR: ImportSourceDescriptor = {
  key: 'grpc',
  label: 'gRPC / Protobuf',
  description: 'Import a gRPC / Protocol Buffers API from a .proto file or live server reflection.',
  icon: 'share-2',
  paradigm: 'rpc',
  input_kinds: ['file', 'url', 'paste', 'discovery'],
  supports_live_discovery: true,
  formats: ['protobuf'],
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

describe('GraphQL source card (MFI-10.6)', () => {
  it('surfaces the registered GraphQL adapter as a usable file/url/paste/discovery card', () => {
    const cards = mergeImportSourceCards([GRAPHQL_DESCRIPTOR]);
    const graphql = cards.find((c) => c.key === 'graphql');
    expect(graphql).toBeDefined();
    expect(graphql?.builtin).toBe(false);
    expect(graphql?.label).toBe('GraphQL');
    // file/url/paste/discovery inputs route to the generic file intake panel (file wins).
    expect(graphql?.panel).toBe('file');
    // GraphQL is its own registry source, not subsumed by a built-in card.
    expect(REGISTRY_KEYS_COVERED_BY_BUILTINS.has('graphql')).toBe(false);
  });

  it('resolves the descriptor `waypoints` icon to the Lucide Waypoints component', () => {
    expect(resolveLucideIcon(GRAPHQL_DESCRIPTOR.icon)).toBe(Waypoints);
  });
});

/** The A2A Agent Card source as the REST registry advertises it (MFI-18.1, #3974). */
const A2A_DESCRIPTOR: ImportSourceDescriptor = {
  key: 'a2a',
  label: 'A2A Agent Card',
  description:
    "Import an A2A (Agent2Agent) Agent Card — the agent's skills, tags, input / output modes, " +
    "capabilities and security schemes — from a file, a URL, or live from the agent's " +
    '/.well-known/agent-card.json.',
  icon: 'bot-message-square',
  paradigm: 'agent',
  input_kinds: ['file', 'url', 'paste', 'discovery', 'fileset'],
  supports_live_discovery: true,
  formats: ['a2a'],
};

describe('A2A Agent Card source card (MFI-18.1)', () => {
  it('surfaces the registered A2A adapter as a usable Catalog card', () => {
    const a2a = mergeImportSourceCards([A2A_DESCRIPTOR]).find((c) => c.key === 'a2a');
    expect(a2a).toBeDefined();
    expect(a2a?.builtin).toBe(false);
    expect(a2a?.label).toBe('A2A Agent Card');
    expect(a2a?.panel).toBe('file');
    expect(a2a?.scope).toBe('alternative');
    expect(REGISTRY_KEYS_COVERED_BY_BUILTINS.has('a2a')).toBe(false);
  });

  it('resolves the descriptor `bot-message-square` icon to the Lucide component', () => {
    expect(resolveLucideIcon(A2A_DESCRIPTOR.icon)).toBe(BotMessageSquare);
  });
});

/** The ACP agent-manifest source as the REST registry advertises it (MFI-18.2, #3975). */
const ACP_DESCRIPTOR: ImportSourceDescriptor = {
  key: 'acp',
  label: 'ACP Agent Manifest',
  description:
    'Import ACP (Agent Communication Protocol) agent metadata — an agent manifest or a ' +
    "server's GET /agents listing, with capabilities, content types, tags and domains — " +
    'from a file, a URL, or live from the server.',
  icon: 'bot',
  paradigm: 'agent',
  input_kinds: ['file', 'url', 'paste', 'discovery', 'fileset'],
  supports_live_discovery: true,
  formats: ['acp'],
};

describe('ACP agent manifest source card (MFI-18.2)', () => {
  it('appears beside the A2A card as a usable Catalog card', () => {
    const cards = mergeImportSourceCards([A2A_DESCRIPTOR, ACP_DESCRIPTOR]);
    const keys = cards.filter((c) => !c.builtin).map((c) => c.key);
    expect(keys).toEqual(['a2a', 'acp']);
    const acp = cards.find((c) => c.key === 'acp');
    expect(acp?.panel).toBe('file');
    expect(acp?.scope).toBe('alternative');
    expect(resolveLucideIcon(ACP_DESCRIPTOR.icon)).toBe(Bot);
  });
});

/** The agentic-web site-manifest source as the REST registry advertises it (MFI-18.3, #3976). */
const AGENTS_MANIFEST_DESCRIPTOR: ImportSourceDescriptor = {
  key: 'agents-manifest',
  label: 'Agentic-web Site Manifest',
  description:
    "Import a site's agentic-web manifest — agents.json, agent.json (Agent Web Protocol), " +
    'agents.txt or llms.txt — cataloging the agent protocols and endpoints it declares and ' +
    'listing the A2A, ACP and MCP descriptors to discover next.',
  icon: 'globe',
  paradigm: 'agent',
  input_kinds: ['file', 'url', 'paste', 'discovery', 'fileset'],
  supports_live_discovery: true,
  formats: ['agents-manifest'],
};

describe('Agentic-web site manifest source card (MFI-18.3)', () => {
  it('appears beside the A2A and ACP cards as a usable Catalog card', () => {
    const cards = mergeImportSourceCards([AGENTS_MANIFEST_DESCRIPTOR, ACP_DESCRIPTOR, A2A_DESCRIPTOR]);
    const keys = cards.filter((c) => !c.builtin).map((c) => c.key);
    expect(keys).toEqual(['a2a', 'acp', 'agents-manifest']);
    const manifest = cards.find((c) => c.key === 'agents-manifest');
    expect(manifest?.panel).toBe('file');
    expect(manifest?.scope).toBe('alternative');
    expect(resolveLucideIcon(AGENTS_MANIFEST_DESCRIPTOR.icon)).toBe(Globe);
  });
});

describe('gRPC / Protobuf source card (MFI-9.6)', () => {
  it('surfaces the registered gRPC adapter as a usable file/url/paste/discovery card', () => {
    const cards = mergeImportSourceCards([GRPC_DESCRIPTOR]);
    const grpc = cards.find((c) => c.key === 'grpc');
    expect(grpc).toBeDefined();
    expect(grpc?.builtin).toBe(false);
    expect(grpc?.label).toBe('gRPC / Protobuf');
    // file/url/paste/discovery inputs route to the generic file intake panel (file wins), so a
    // `.proto` upload works; the discovery (reflection) input is advertised on the descriptor.
    expect(grpc?.panel).toBe('file');
    expect(GRPC_DESCRIPTOR.supports_live_discovery).toBe(true);
    // gRPC is its own registry source, not subsumed by a built-in card.
    expect(REGISTRY_KEYS_COVERED_BY_BUILTINS.has('grpc')).toBe(false);
  });

  it('resolves the descriptor `share-2` icon to the Lucide Share2 component', () => {
    expect(resolveLucideIcon(GRPC_DESCRIPTOR.icon)).toBe(Share2);
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

describe('card scopes (MFI-23.12)', () => {
  it('scopes the generic intake methods to both surfaces', () => {
    const cards = baseImportSourceCards();
    for (const key of ['file', 'url', 'clipboard', 'git']) {
      expect(cards.find((c) => c.key === key)?.scope).toBe('both');
    }
  });

  it('keeps SwaggerHub native and Postman/MCP alternative', () => {
    const cards = baseImportSourceCards();
    expect(cards.find((c) => c.key === 'swaggerhub')?.scope).toBe('native');
    expect(cards.find((c) => c.key === 'postman')?.scope).toBe('alternative');
    expect(cards.find((c) => c.key === 'mcp')?.scope).toBe('alternative');
  });

  it('marks every registry-contributed adapter as an alternative-format card', () => {
    const cards = mergeImportSourceCards([GRPC_DESCRIPTOR, ASYNCAPI_DESCRIPTOR, GRAPHQL_DESCRIPTOR]);
    for (const key of ['grpc', 'asyncapi', 'graphql']) {
      const card = cards.find((c) => c.key === key);
      expect(card?.builtin).toBe(false);
      expect(card?.scope).toBe('alternative');
    }
  });
});

describe('filterCardsForVariant (MFI-23.12)', () => {
  const merged = () => mergeImportSourceCards([GRPC_DESCRIPTOR, ASYNCAPI_DESCRIPTOR]);

  it('projects variant keeps the native OpenAPI/Swagger intake and drops alternative formats', () => {
    const keys = filterCardsForVariant(merged(), 'projects').map((c) => c.key);
    expect(keys).toEqual(['file', 'url', 'clipboard', 'git', 'swaggerhub']);
    // No alternative-format cards leak into the Projects importer.
    expect(keys).not.toContain('postman');
    expect(keys).not.toContain('mcp');
    expect(keys).not.toContain('grpc');
    expect(keys).not.toContain('asyncapi');
  });

  it('catalog variant keeps the alternative formats plus the generic intake, minus SwaggerHub', () => {
    const keys = filterCardsForVariant(merged(), 'catalog').map((c) => c.key);
    expect(keys).toEqual(['file', 'url', 'clipboard', 'git', 'postman', 'mcp', 'asyncapi', 'grpc']);
    expect(keys).not.toContain('swaggerhub');
  });

  it('all variant is a pass-through (returns every card, order preserved)', () => {
    const all = merged();
    expect(filterCardsForVariant(all, 'all').map((c) => c.key)).toEqual(all.map((c) => c.key));
  });

  it('returns fresh card copies (callers can mutate safely)', () => {
    const src = merged();
    const out = filterCardsForVariant(src, 'catalog');
    const file = out.find((c) => c.key === 'file');
    const srcFile = src.find((c) => c.key === 'file');
    expect(file).not.toBe(srcFile);
  });
});

describe('baseIntakeTiles (MFI-26.1, MFI-29.3)', () => {
  // The Compass tile is held back with the other catalog entity kinds in RC6 (lib/feature-release.ts).
  beforeEach(() => {
    process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES = 'catalog-entities';
  });
  afterEach(() => {
    delete process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES;
  });

  it('returns the base intake tiles in fixed order from the catalog cards', () => {
    const cards = filterCardsForVariant(mergeImportSourceCards([ASYNCAPI_DESCRIPTOR]), 'catalog');
    const tiles = baseIntakeTiles(cards);

    // File / URL / Clipboard(paste) / Git / Compass only, in fixed order — never a per-format or
    // discovery tile. Git joined the base methods with MFI-29.3 (repo path/glob → fileset), and the
    // Compass export with CDG-5.5 (staged as an import report, not stored as a spec).
    expect(tiles.map((t) => t.method)).toEqual(['file', 'url', 'paste', 'git', 'compass']);
    expect(tiles.map((t) => t.card.key)).toEqual(['file', 'url', 'clipboard', 'git', 'compass']);
    expect(tiles.map((t) => t.card.label)).toEqual([
      'File Upload',
      'URL Import',
      'Clipboard Paste',
      'Git Repository',
      'Compass export',
    ]);
  });

  it('excludes registry-contributed cards', () => {
    const cards = mergeImportSourceCards([ASYNCAPI_DESCRIPTOR, GRAPHQL_DESCRIPTOR]);
    const keys = baseIntakeTiles(cards).map((t) => t.card.key);
    expect(keys).not.toContain('asyncapi');
    expect(keys).not.toContain('graphql');
  });

  it('omits a base tile whose backing card is absent', () => {
    const withoutUrl = baseImportSourceCards().filter((c) => c.key !== 'url');
    expect(baseIntakeTiles(withoutUrl).map((t) => t.method)).toEqual(['file', 'paste', 'git', 'compass']);
  });

  it('leaves the Compass tile out while catalog entity kinds are held back (RC6)', () => {
    delete process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES;
    expect(baseIntakeTiles(baseImportSourceCards()).map((t) => t.method)).toEqual(['file', 'url', 'paste', 'git']);
  });

  it('keeps the Compass tile out of every other import surface (CDG-5.5)', () => {
    expect(baseImportSourceCards().map((c) => c.key)).not.toContain('compass');
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

/** The xRegistry source as the REST registry advertises it (MFI-19.2, #3980). */
const XREGISTRY_DESCRIPTOR: ImportSourceDescriptor = {
  key: 'xregistry',
  label: 'CNCF xRegistry',
  description:
    'Import a CNCF xRegistry document — CloudEvents schema groups, message definitions and ' +
    'endpoints over MQTT, AMQP, Kafka, NATS or HTTP — as one event catalog entry.',
  icon: 'cloud',
  paradigm: 'event',
  input_kinds: ['file', 'url', 'paste', 'fileset'],
  supports_live_discovery: false,
  formats: ['xregistry', 'cloudevents-registry'],
};

describe('CNCF xRegistry source card (MFI-19.2)', () => {
  it('is a usable Catalog file card with the cloud icon', () => {
    const cards = mergeImportSourceCards([XREGISTRY_DESCRIPTOR]);
    const card = cards.find((c) => c.key === 'xregistry');
    expect(card?.builtin).toBeFalsy();
    expect(card?.panel).toBe('file');
    expect(card?.scope).toBe('alternative');
    expect(card?.label).toBe('CNCF xRegistry');
    expect(resolveLucideIcon(XREGISTRY_DESCRIPTOR.icon)).toBe(Cloud);
  });
});
