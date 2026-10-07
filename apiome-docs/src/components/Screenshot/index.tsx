import type {ReactNode} from 'react';

import {useColorMode} from '@docusaurus/theme-common';
import useBaseUrl from '@docusaurus/useBaseUrl';
import ThemedImage from '@theme/ThemedImage';

import manifest from '@site/screens.json';
import Route from '@site/src/components/Route';

import {resolveScreenshot} from './resolve';
import styles from './styles.module.css';

/** Props for {@link Screenshot}. */
export interface ScreenshotProps {
  /** Manifest id in `apiome-docs/screens.json` (e.g. `catalog`). */
  id: string;
  /** Alternative text describing what the screen shows. Required: a blank value fails the build. */
  alt: string;
  /** Optional caption shown under the image. */
  caption?: string;
}

/**
 * A product screenshot, referenced by its manifest id (DOCS-1.3, #5620).
 *
 * Shows the light capture, or the dark one when the site is in dark mode, lazy-loaded at its
 * capture size so the page does not jump. The image links to the full-size file for the current
 * theme, and the caption carries a badge naming the product route. The images are produced by
 * `yarn docs:screenshots`; an unknown id fails the build.
 *
 * @param props - {@link ScreenshotProps}
 * @returns A `<figure>` with the linked image and its caption.
 */
export default function Screenshot({id, alt, caption}: ScreenshotProps): ReactNode {
  const resolved = resolveScreenshot(manifest.screens, id, alt);
  const light = useBaseUrl(resolved.sources.light);
  const dark = useBaseUrl(resolved.sources.dark);
  const {colorMode} = useColorMode();

  return (
    <figure className={styles.figure} data-screenshot-id={id}>
      <a className={styles.link} href={colorMode === 'dark' ? dark : light}>
        <ThemedImage
          className={styles.image}
          sources={{light, dark}}
          alt={alt}
          width={resolved.width}
          height={resolved.height}
          loading="lazy"
          decoding="async"
        />
      </a>
      <figcaption className={styles.caption}>
        <Route path={resolved.route} />
        {caption ? <span className={styles.text}>{caption}</span> : null}
      </figcaption>
    </figure>
  );
}
