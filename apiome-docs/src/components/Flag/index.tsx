import type {ReactNode} from 'react';

import styles from './styles.module.css';

/** Props for {@link Flag}. */
export interface FlagProps {
  /** The flag's name exactly as it appears in the code or environment, e.g. `FEATURE_GITLIKE`. */
  name: string;
  /** Whether the flag is on in shipped builds today. Defaults to `false`. */
  on?: boolean;
}

/**
 * A badge marking a feature-flagged surface (DOCS-1.5, #5622).
 *
 * Names the flag and says whether shipped builds have it on, so a reader can tell at a glance
 * that a section describes something they may not see.
 *
 * @param props - {@link FlagProps}
 * @returns An inline badge.
 */
export default function Flag({name, on = false}: FlagProps): ReactNode {
  return (
    <span className={on ? `${styles.flag} ${styles.on}` : styles.flag}>
      <span className={styles.label}>{on ? 'Flag on' : 'Flag off'}</span>
      <code className={styles.name}>{name}</code>
    </span>
  );
}
