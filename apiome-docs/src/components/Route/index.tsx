import type {ReactNode} from 'react';

import styles from './styles.module.css';

/** Props for {@link Route}. */
export interface RouteProps {
  /** The product route, as it appears in the address bar (e.g. `/projects/[id]/versions`). */
  path: string;
}

/**
 * A badge naming the product route a page or section describes.
 *
 * @param props - {@link RouteProps}
 * @returns An inline badge with the route in monospace.
 */
export default function Route({path}: RouteProps): ReactNode {
  return (
    <span className={styles.route}>
      <span className={styles.label}>Route</span>
      <code className={styles.path}>{path}</code>
    </span>
  );
}
