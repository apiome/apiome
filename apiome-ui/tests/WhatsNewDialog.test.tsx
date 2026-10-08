/**
 * The What's New dialog — viewport-centred overlay (#2531), re-tokened onto the Hive
 * `Dialog` primitive by HIVE-3.4 (#5290).
 *
 * Two things are worth holding still here. The first is the bug #2531 fixed: the sheet is
 * fixed to the *viewport*, not to whatever scrolled or transformed container happened to
 * render it, which is why it is portalled out of the tree that opens it. The second is the
 * behaviour the ticket asks for: the notes are fetched from `/WHATS_NEW.md` when the
 * dialog opens and not before, and a fetch that fails says so rather than showing an empty
 * sheet.
 */

import React from 'react';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';

jest.mock('rehype-raw', () => ({
  __esModule: true,
  default: () => () => {},
}));

/**
 * A block-level stand-in for `react-markdown` (the real one is ESM-only under Jest, and the
 * shared mock flattens a document into one element). It renders headings, one level of nested
 * lists and paragraphs as the elements `react-markdown` would — through the caller's
 * `components` — so the docs fixture below looks
 * like the product's dialog. Inline markup is left as text.
 */
jest.mock('react-markdown', () => {
  const ReactActual = jest.requireActual<typeof import('react')>('react');
  const createElement = ReactActual.createElement;

  return {
    __esModule: true,
    default: function BlockMarkdown({
      children,
      components = {},
    }: {
      children: string;
      components?: Record<string, React.ElementType>;
    }) {
      // The caller's element overrides (`githubMarkdownComponents`), as react-markdown applies them.
      const h = (tag: string, props: Record<string, unknown> | null, ...kids: React.ReactNode[]) =>
        createElement(components[tag] ?? tag, props, ...kids);
      const blocks = children.trim().split(/\n{2,}/);
      return h(
        ReactActual.Fragment,
        null,
        blocks.map((block, index) => {
          const heading = /^(#{1,6}) (.*)$/.exec(block);
          if (heading) return h(`h${heading[1].length}`, { key: index }, heading[2]);
          if (!block.startsWith('- ')) return h('p', { key: index }, block);

          // Top-level items, each with its indented children as a nested list.
          const items: { text: string; children: string[] }[] = [];
          for (const line of block.split('\n')) {
            if (line.startsWith('- ')) items.push({ text: line.slice(2), children: [] });
            else items[items.length - 1]?.children.push(line.trim().replace(/^- /, ''));
          }
          return h(
            'ul',
            { key: index },
            items.map((item, itemIndex) =>
              h(
                'li',
                { key: itemIndex },
                item.text,
                item.children.length > 0 &&
                  h('ul', null, item.children.map((child, childIndex) => h('li', { key: childIndex }, child)))
              )
            )
          );
        })
      );
    },
  };
});

import WhatsNewDialog from '../src/app/components/ade/WhatsNewDialog';
import { RELEASE_NOTES_URL } from '../src/app/utils/docsLinks';
import { APP_VERSION_BADGE } from '../lib/app-version';
import { liveMarkup, writeA11yFixture } from './helpers/a11y-fixture-dump';

describe('WhatsNewDialog', () => {
  beforeEach(() => {
    global.fetch = jest.fn();
    (global.fetch as jest.Mock).mockResolvedValue({
      // No leading heading: the `react-markdown` mock folds a `# …` document into one
      // `<h1>`, which would make the assertion below about the mock rather than the fetch.
      text: () => Promise.resolve('Shiny new things.'),
    });
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  it('portals the sheet out of the opening tree, so it centres on the viewport', async () => {
    // A transformed ancestor is the exact condition that broke #2531: `position: fixed`
    // resolves against a transformed element rather than against the viewport.
    render(
      <div style={{ transform: 'translateX(10px)' }}>
        <WhatsNewDialog isOpen onClose={jest.fn()} />
      </div>
    );

    const sheet = await screen.findByTestId('whats-new-dialog');

    expect(sheet).toHaveClass('fixed');
    // Radix portals into `document.body`; the wrapper it creates is untransformed, so the
    // sheet still measures against the viewport. What matters is that neither the sheet
    // nor anything above it is the transformed div this test rendered it inside.
    let ancestor: HTMLElement | null = sheet.parentElement;
    while (ancestor && ancestor !== document.body) {
      expect(ancestor.style.transform).toBe('');
      ancestor = ancestor.parentElement;
    }
    expect(ancestor).toBe(document.body);
  });

  it('renders nothing, and fetches nothing, while closed', () => {
    render(<WhatsNewDialog isOpen={false} onClose={jest.fn()} />);

    expect(screen.queryByTestId('whats-new-dialog')).not.toBeInTheDocument();
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it('fetches the notes on open and stamps them with the running build', async () => {
    render(<WhatsNewDialog isOpen onClose={jest.fn()} />);

    expect(global.fetch).toHaveBeenCalledWith('/WHATS_NEW.md');
    expect(await screen.findByText('Shiny new things.')).toBeInTheDocument();
    expect(screen.getByTestId('whats-new-dialog')).toHaveTextContent(APP_VERSION_BADGE);
  });

  it('says so when the notes cannot be loaded', async () => {
    const consoleError = jest.spyOn(console, 'error').mockImplementation(() => {});
    (global.fetch as jest.Mock).mockRejectedValue(new Error('offline'));

    render(<WhatsNewDialog isOpen onClose={jest.fn()} />);

    expect(await screen.findByText(/couldn't load the release notes/i)).toBeInTheDocument();
    consoleError.mockRestore();
  });

  it('links to the full release notes on the documentation site, in a new tab (DOCS-1.12)', async () => {
    render(<WhatsNewDialog isOpen onClose={jest.fn()} />);

    const link = await screen.findByRole('link', { name: /full release notes/i });
    expect(link).toHaveAttribute('href', RELEASE_NOTES_URL);
    expect(RELEASE_NOTES_URL).toBe('https://apiome.github.io/apiome/release-notes');
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', expect.stringContaining('noopener'));
    expect(link).toHaveAccessibleName(/opens in a new tab/i);
  });

  it('keeps the link while the notes are loading and after they fail to load', async () => {
    const consoleError = jest.spyOn(console, 'error').mockImplementation(() => {});
    (global.fetch as jest.Mock).mockRejectedValue(new Error('offline'));

    render(<WhatsNewDialog isOpen onClose={jest.fn()} />);

    expect(screen.getByTestId('whats-new-full-notes')).toBeInTheDocument();
    await screen.findByText(/couldn't load the release notes/i);
    expect(screen.getByTestId('whats-new-full-notes')).toHaveAttribute('href', RELEASE_NOTES_URL);
    consoleError.mockRestore();
  });

  it('closes on Esc and on the close button, which a hand-rolled portal never did', async () => {
    const onClose = jest.fn();
    const user = userEvent.setup();
    render(<WhatsNewDialog isOpen onClose={onClose} />);

    await screen.findByTestId('whats-new-dialog');

    await user.click(screen.getByRole('button', { name: /close/i }));
    expect(onClose).toHaveBeenCalledTimes(1);

    await user.keyboard('{Escape}');
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(2));
  });
});

/* -------------------------------------------------------------------------
   The docs fixtures
   ------------------------------------------------------------------------- */

/**
 * The documentation site's Help & docs page shows this dialog (`apiome-docs/screens.json`
 * `whats-new`, DOCS-1.12), captured from this dump:
 * `A11Y_FIXTURE_DUMP=1 npx jest tests/WhatsNewDialog.test.tsx -t "docs fixtures"`.
 *
 * The suite's `react-markdown` is a mock that flattens a document, so the notes here are
 * rendered by the real library — the screenshot should look like the product.
 */
describe('the docs fixtures', () => {
  beforeEach(() => {
    global.fetch = jest.fn().mockResolvedValue({
      text: () =>
        Promise.resolve(
          [
            '# Apiome 08-2026 RC5',
            '',
            '## Features/Improvements',
            '',
            '- API Formats:',
            '  - Adds formats: MCP, Kong, Arazzo 1.1, OData v2/v3, CDDL and SQL DDL import',
            '  - Every format now declares which versions it reads and writes',
            '- Documentation:',
            '  - The user guide is now a searchable documentation site, grouped by job',
            '',
            '## Bug Fixes',
            '',
            '- Import: upload accepts every supported file extension',
          ].join('\n')
        ),
    });
  });

  it('renders the notes with the Full release notes link', async () => {
    render(<WhatsNewDialog isOpen onClose={jest.fn()} />);

    const sheet = await screen.findByTestId('whats-new-dialog');
    await within(sheet).findByRole('heading', { name: 'Bug Fixes' });
    expect(within(sheet).getByRole('link', { name: /full release notes/i })).toBeInTheDocument();
    writeA11yFixture('whats-new', liveMarkup(sheet));
  });
});
