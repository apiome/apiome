import Admonition from '@theme/Admonition';
import type {ReactNode} from 'react';

/** The issue that schedules the redesign of every legacy surface (HIVE-EPIC-9). */
const REDESIGN_ISSUE = 5272;

/**
 * The callout on a page that documents a surface older than the Hive redesign (DOCS-1.10, #5627).
 *
 * Every page that shows a screenshot tagged `legacy` in `screens.json` must carry it —
 * `yarn docs:check` fails otherwise — so a reader is told the screen will change, and why it
 * looks unlike the rest of the product.
 *
 * @returns A note admonition naming the redesign issue.
 */
export default function Legacy(): ReactNode {
  return (
    <Admonition type="note" title="Legacy screen">
      This surface predates the Hive redesign; it is scheduled under{' '}
      <a href={`https://github.com/apiome/apiome/issues/${REDESIGN_ISSUE}`}>#{REDESIGN_ISSUE}</a>.
    </Admonition>
  );
}
