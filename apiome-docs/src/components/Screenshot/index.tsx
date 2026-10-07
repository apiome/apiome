import type {ReactNode} from 'react';

import styles from './styles.module.css';

/** Props for {@link Screenshot}. */
export interface ScreenshotProps {
  /** Manifest id in `apiome-docs/screens.json` (e.g. `projects-list`). */
  id: string;
  /** Alternative text describing what the screen shows. Required for accessibility. */
  alt: string;
  /** Optional caption shown under the image. */
  caption?: string;
}

/**
 * A product screenshot, referenced by its manifest id.
 *
 * Placeholder until the screenshot pipeline lands (DOCS-1.3, #5620): it renders a framed
 * box that names the id, so pages can reference screens now and pick up the light and
 * dark captures later without an edit.
 *
 * @param props - {@link ScreenshotProps}
 * @returns A `<figure>` holding the placeholder and optional caption.
 */
export default function Screenshot({id, alt, caption}: ScreenshotProps): ReactNode {
  return (
    <figure className={styles.figure} data-screenshot-id={id}>
      <div className={styles.placeholder} role="img" aria-label={alt}>
        <span className={styles.label}>Screenshot</span>
        <code className={styles.id}>{id}</code>
      </div>
      {caption ? <figcaption className={styles.caption}>{caption}</figcaption> : null}
    </figure>
  );
}
