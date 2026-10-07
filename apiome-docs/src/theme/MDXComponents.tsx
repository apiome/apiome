import MDXComponents from '@theme-original/MDXComponents';

import Kbd from '@site/src/components/Kbd';
import Route from '@site/src/components/Route';
import Screenshot from '@site/src/components/Screenshot';

/**
 * Registers the Apiome MDX components globally, so every page can use
 * `<Screenshot/>`, `<Route/>` and `<Kbd/>` without importing them.
 */
export default {
  ...MDXComponents,
  Kbd,
  Route,
  Screenshot,
};
