import type {ReactNode} from 'react';

import Link from '@docusaurus/Link';
import useBaseUrl from '@docusaurus/useBaseUrl';
import Layout from '@theme/Layout';

import Screenshot from '@site/src/components/Screenshot';
import SectionCards from '@site/src/components/SectionCards';

import styles from './index.module.css';

/**
 * The site's home page at `/`: what Apiome is, which guide to open, and the things most visitors
 * come to do, then Home as the app shows it (`home`).
 */

/** The page's `<title>` and meta description. */
export const HOME_TITLE = 'Apiome documentation';
export const HOME_DESCRIPTION = 'Guides for using, administering and scripting Apiome — design, govern and ship APIs.';

/** A quick link: a task most visitors arrive to do, and the page that starts it. */
export interface QuickLink {
  /** The task, as a verb phrase. */
  label: string;
  /** One line on what the page covers. */
  description: string;
  /** The site route that starts it. */
  to: string;
}

/** The quick links, in the order a new installation needs them. */
export const QUICK_LINKS: readonly QuickLink[] = [
  {
    label: 'Run Apiome locally',
    description: 'Bring up the stack on your own machine.',
    to: '/getting-started/run-locally',
  },
  {
    label: 'Import your first project',
    description: 'Bring in a spec and see it as a project.',
    to: '/getting-started/first-project',
  },
  {
    label: 'Install the CLI',
    description: 'Export and lint from a terminal or CI.',
    to: '/reference/cli-quickstart',
  },
];

/**
 * The hero: the bee, the title, the tagline, and one paragraph on the spine.
 *
 * @returns The page's header.
 */
function Hero(): ReactNode {
  return (
    <header className={styles.hero}>
      <img className={styles.logo} src={useBaseUrl('/img/bee-logo.png')} alt="" width={96} height={96} />
      <h1 className={styles.title}>Apiome documentation</h1>
      <p className={styles.tagline}>Design, govern and ship APIs</p>
      <p className={styles.lead}>
        Apiome is where teams design, govern and ship APIs. Import a spec, edit its classes and paths, lint
        it against your style guide, cut a version and publish it. Then browse it, export it with the CLI
        and query it with MCP.
      </p>
    </header>
  );
}

/**
 * The quick links, as a list of linked tasks.
 *
 * @returns The quick-links section.
 */
function QuickLinks(): ReactNode {
  return (
    <section className={styles.section} aria-labelledby="quick-links">
      <h2 id="quick-links" className={styles.sectionTitle}>
        Quick links
      </h2>
      <ul className={styles.quickLinks}>
        {QUICK_LINKS.map((link) => (
          <li key={link.to}>
            <Link to={link.to} className={styles.quickLink}>
              <span className={styles.quickLinkLabel}>{link.label} →</span>
              <span className={styles.quickLinkDescription}>{link.description}</span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

/**
 * The home page.
 *
 * @returns The page, inside the site's layout (navbar, footer).
 */
export default function Home(): ReactNode {
  return (
    <Layout title={HOME_TITLE} description={HOME_DESCRIPTION}>
      <main className={styles.page}>
        <Hero />
        <section className={styles.section} aria-labelledby="sections">
          <h2 id="sections" className={styles.sectionTitle}>
            Find your way
          </h2>
          <SectionCards />
        </section>
        <QuickLinks />
        <section className={styles.section}>
          <Screenshot
            id="home"
            alt="Home: a getting-started checklist, six workspace statistics, Pick up where you left off, Quick actions and Needs attention"
          />
        </section>
      </main>
    </Layout>
  );
}
