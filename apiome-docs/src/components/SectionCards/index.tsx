import type {ReactNode} from 'react';

import Link from '@docusaurus/Link';

import styles from './styles.module.css';

/** One card: a page to go to and why. */
export interface SectionCard {
  /** The card's heading. */
  title: string;
  /** One sentence on what is there. */
  description: string;
  /** Where the card goes — a site route (`/reference/cli-quickstart`) or a full URL. */
  to: string;
}

/** Props for {@link SectionCards}. */
export interface SectionCardsProps {
  /** The cards, in order. Leave out for the site's four guides and the release notes. */
  cards?: readonly SectionCard[];
}

/** The four guides and the release notes, in the order of the top bar — the default set. */
export const SECTION_CARDS: readonly SectionCard[] = [
  {
    title: 'User guide',
    description: 'Work in Apiome: build, bring in, ship and govern your APIs.',
    to: '/getting-started',
  },
  {
    title: 'Administration',
    description: 'Run an installation: the admin console, sign-in providers, migrations and hosting.',
    to: '/admin',
  },
  {
    title: 'CLI',
    description: 'Work from a terminal or CI with the apiome command: the quick-start and every command.',
    to: '/reference/cli-quickstart',
  },
  {
    title: 'Reference',
    description: 'The REST API, the MCP server, the mock runtime and the CI actions.',
    to: '/reference',
  },
  {
    title: 'Release notes',
    description: 'What changed in each Apiome release.',
    to: '/release-notes',
  },
];

/**
 * A grid of linked cards, for the landing page.
 *
 * @param props - {@link SectionCardsProps}
 * @returns The grid, one link per card.
 * @throws {Error} When given an empty list — an empty grid is an authoring mistake.
 */
export default function SectionCards({cards = SECTION_CARDS}: SectionCardsProps): ReactNode {
  if (cards.length === 0) throw new Error('<SectionCards> needs at least one card');
  return (
    <div className={styles.grid}>
      {cards.map((card) => (
        <Link key={card.to} to={card.to} className={styles.card}>
          <span className={styles.title}>{card.title}</span>
          <span className={styles.description}>{card.description}</span>
        </Link>
      ))}
    </div>
  );
}
