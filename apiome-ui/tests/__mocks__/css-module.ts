/**
 * Jest stand-in for `*.module.css` imports (wired in jest.config.ts moduleNameMapper).
 *
 * Returns each requested class name as itself (identity-object pattern) so components can
 * render and assertions can match on stable class names without loading real CSS.
 */
export default new Proxy(
  {},
  {
    get: (_target, prop) => (prop === '__esModule' ? true : String(prop)),
  }
);
