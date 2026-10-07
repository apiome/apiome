import {Fragment, type ReactNode} from 'react';

import {splitChord} from './chord';
import styles from './styles.module.css';

/** Props for {@link Kbd}. */
export interface KbdProps {
  /**
   * A key or chord, keys joined by `+` (e.g. `Mod+K`, `Shift+?`). `Mod` reads as
   * “Ctrl / ⌘”. Ignored when `children` is given.
   */
  keys?: string;
  /** A single key label, for when the chord form is not wanted. */
  children?: ReactNode;
}

/**
 * Keyboard key(s), rendered as `<kbd>` elements.
 *
 * @param props - {@link KbdProps}
 * @returns One `<kbd>` per key, joined by `+`.
 */
export default function Kbd({keys, children}: KbdProps): ReactNode {
  if (children !== undefined && children !== null) {
    return <kbd className={styles.key}>{children}</kbd>;
  }
  const labels = splitChord(keys ?? '');
  return (
    <span className={styles.chord}>
      {labels.map((label, index) => (
        <Fragment key={`${label}-${index}`}>
          {index > 0 ? <span className={styles.plus}>+</span> : null}
          <kbd className={styles.key}>{label}</kbd>
        </Fragment>
      ))}
    </span>
  );
}
