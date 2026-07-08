import { Palette } from 'lucide-react';
import {
  __setExternalLinksForTests,
  buildDesignerEditorHref,
  getDesignerHomeHref,
  getExternalHomeCards,
  getExternalNavItems,
  resolveExternalLinkIcon,
  type ExternalLinkEntry,
} from '../../lib/external-links';

const COMMERCIAL_LINKS: ExternalLinkEntry[] = [
  {
    id: 'designer',
    navLabel: 'Designer',
    name: 'Data Designer',
    tagline: 'Schema design',
    description: 'Model classes on an interactive canvas.',
    href: 'https://studio.apiome.app',
    editorHref: 'https://studio.apiome.app/editor',
    icon: 'Palette',
    accent: 'from-violet-500 to-fuchsia-600',
    glow: 'group-hover:shadow-fuchsia-500/20',
  },
];

describe('external-links (OSS default config)', () => {
  afterEach(() => {
    __setExternalLinksForTests(null);
  });

  it('returns no nav items when config is empty', () => {
    expect(getExternalNavItems()).toEqual([]);
  });

  it('returns no home cards when config is empty', () => {
    expect(getExternalHomeCards()).toEqual([]);
  });

  it('returns null designer helpers when designer is not configured', () => {
    expect(getDesignerHomeHref()).toBeNull();
    expect(buildDesignerEditorHref('p', 'v')).toBeNull();
  });

  it('resolves known lucide icon names', () => {
    expect(resolveExternalLinkIcon('Palette')).toBe(Palette);
  });
});

describe('external-links (configured commercial links)', () => {
  beforeEach(() => {
    __setExternalLinksForTests(COMMERCIAL_LINKS);
  });

  afterEach(() => {
    __setExternalLinksForTests(null);
  });

  it('exposes nav and home cards from config', () => {
    expect(getExternalNavItems()).toEqual([
      expect.objectContaining({ id: 'designer', label: 'Designer', href: 'https://studio.apiome.app', external: true }),
    ]);
    expect(getExternalHomeCards()[0]).toEqual(
      expect.objectContaining({ id: 'designer', name: 'Data Designer' })
    );
  });

  it('builds designer deep links with query params', () => {
    expect(getDesignerHomeHref()).toBe('https://studio.apiome.app');
    expect(buildDesignerEditorHref('proj-1', 'ver-2')).toBe(
      'https://studio.apiome.app/editor?projectId=proj-1&versionId=ver-2'
    );
  });
});
