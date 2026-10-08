import {themes as prismThemes} from 'prism-react-renderer';
import type {Config} from '@docusaurus/types';
import type * as Preset from '@docusaurus/preset-classic';

// This runs in Node.js - don't use client-side code here (browser APIs, JSX...).

/**
 * Where the site is served from.
 *
 * Defaults to the GitHub Pages project site (`https://apiome.github.io/apiome/`). Override
 * with `DOCS_URL` / `DOCS_BASE_URL` to serve it from a custom domain or a sub-path; the
 * base URL must start and end with `/`.
 */
const SITE_URL = process.env.DOCS_URL ?? 'https://apiome.github.io';
const BASE_URL = process.env.DOCS_BASE_URL ?? '/apiome/';

/** The repository the "Edit this page" links and the navbar point at. */
const REPO_URL = 'https://github.com/apiome/apiome';

const config: Config = {
  title: 'Apiome',
  tagline: 'Design, govern and ship APIs — the Apiome documentation',
  favicon: 'img/bee-logo.png',

  future: {
    v4: true,
  },

  url: SITE_URL,
  baseUrl: BASE_URL,
  // GitHub Pages serves `/page` from `page.html`, so URLs carry no trailing slash.
  trailingSlash: false,

  organizationName: 'apiome',
  projectName: 'apiome',

  onBrokenLinks: 'throw',
  onBrokenAnchors: 'throw',
  markdown: {
    // `.md` pages are CommonMark and `.mdx` pages are MDX. The guides migrated from `docs/guide/`
    // (and the pages the REST generators write) are plain Markdown with inline HTML comments
    // (`42<!--format-count:importable-->`) and `<a id>` anchors, which MDX would reject; pages that
    // use components (`<Screenshot/>`, `<Route/>`) are `.mdx`.
    format: 'detect',
    hooks: {
      onBrokenMarkdownLinks: 'throw',
    },
  },

  i18n: {
    defaultLocale: 'en',
    locales: ['en'],
  },

  // Inter + JetBrains Mono, self-hosted (no request to a font CDN).
  clientModules: ['./src/fonts.ts'],

  presets: [
    [
      'classic',
      {
        docs: {
          // The guide is the site: docs are served from the root.
          routeBasePath: '/',
          sidebarPath: './sidebars.ts',
          editUrl: `${REPO_URL}/tree/main/apiome-docs/`,
        },
        // The blog instance is the release notes (DOCS-1.12).
        blog: {
          path: 'release-notes',
          routeBasePath: 'release-notes',
          blogTitle: 'Release notes',
          blogDescription: 'What changed in each Apiome release.',
          blogSidebarTitle: 'Releases',
          blogSidebarCount: 'ALL',
          showReadingTime: false,
          authorsMapPath: 'authors.yml',
          feedOptions: {
            type: ['rss', 'atom'],
            title: 'Apiome release notes',
          },
          editUrl: `${REPO_URL}/tree/main/apiome-docs/`,
          onInlineTags: 'throw',
          onInlineAuthors: 'throw',
          onUntruncatedBlogPosts: 'ignore',
        },
        theme: {
          customCss: './src/css/custom.css',
        },
      } satisfies Preset.Options,
    ],
  ],

  themes: [
    [
      '@easyops-cn/docusaurus-search-local',
      {
        hashed: true,
        docsRouteBasePath: '/',
        blogRouteBasePath: '/release-notes',
        blogDir: 'release-notes',
        indexBlog: true,
        highlightSearchTermsOnTargetPage: true,
      },
    ],
  ],

  themeConfig: {
    image: 'img/bee-logo.png',
    colorMode: {
      defaultMode: 'light',
      disableSwitch: false,
      respectPrefersColorScheme: true,
    },
    navbar: {
      title: 'Apiome',
      logo: {
        alt: 'Apiome bee',
        src: 'img/bee-logo.png',
      },
      items: [
        {type: 'docSidebar', sidebarId: 'guide', position: 'left', label: 'Guide'},
        {to: '/reference', label: 'Reference', position: 'left'},
        {to: '/release-notes', label: 'Release notes', position: 'left'},
        {href: REPO_URL, label: 'GitHub', position: 'right'},
      ],
    },
    footer: {
      style: 'light',
      links: [
        {
          title: 'Guide',
          items: [
            {label: 'Getting started', to: '/'},
            {label: 'Build', to: '/build'},
            {label: 'Ship', to: '/ship'},
          ],
        },
        {
          title: 'Reference',
          items: [
            {label: 'Reference', to: '/reference'},
            {label: 'Release notes', to: '/release-notes'},
          ],
        },
        {
          title: 'Project',
          items: [{label: 'GitHub', href: REPO_URL}],
        },
      ],
      copyright: `Copyright © 2021 - 2026 NobuData LLC`,
    },
    prism: {
      theme: prismThemes.github,
      darkTheme: prismThemes.dracula,
      additionalLanguages: ['bash', 'json', 'yaml'],
    },
  } satisfies Preset.ThemeConfig,
};

export default config;
