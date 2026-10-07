import MDXComponents from '@theme-original/MDXComponents';

import Flag from '@site/src/components/Flag';
import Kbd from '@site/src/components/Kbd';
import Route from '@site/src/components/Route';
import Screenshot from '@site/src/components/Screenshot';

/**
 * Registers the Apiome MDX components globally, so every page can use
 * `<Screenshot/>`, `<Route/>`, `<Kbd/>` and `<Flag/>` without importing them.
 */
export default {
  ...MDXComponents,
  Flag,
  Kbd,
  Route,
  Screenshot,
};
