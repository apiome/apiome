/**
 * Mock for rehype-raw — the real module ships ESM and trips the ts-jest
 * transformer. Tests do not exercise raw HTML, so a no-op plugin is enough.
 */
export default function rehypeRaw() {
  return undefined;
}
