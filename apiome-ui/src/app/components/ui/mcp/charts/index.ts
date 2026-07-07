/**
 * Token-driven SVG chart kit (V2-MCP-28.3 / MCAT-14.3).
 *
 * A small, hand-rolled set of SVG chart primitives that every MCP insight panel reuses —
 * `Sparkline`, `BarSeries`, `Donut`, `StackedTimeline`, `Radar`, `Heatmap`, `Gauge`. They follow the
 * same design principle as the rest of the MCP UI primitives: consumers pass domain data and the
 * chart resolves its color from Tailwind tokens (see `chartTokens.ts`), so no hex/color literal ever
 * appears in a consumer. Every chart is accessible (`role="img"` + `<title>`/`<desc>` + an `sr-only`
 * data table), responsive (viewBox), SSR-safe, and renders a graceful empty state for empty data.
 *
 * Pure, React-free helpers live alongside so they can be unit-tested directly:
 * - `chartTokens.ts` — series-tone → Tailwind class mapping and the categorical palette order.
 * - `chartGeometry.ts` — coordinate math (sparkline points, arcs, radar/polygon points, intensity).
 *
 * Live gallery: `/design-system/mcp`. Docs: `docs/MCP_UI_PRIMITIVES.md`.
 */
export * from './chartTokens';
export * from './chartGeometry';
export * from './ChartFrame';
export * from './Sparkline';
export * from './BarSeries';
export * from './Donut';
export * from './StackedTimeline';
export * from './Radar';
export * from './Heatmap';
export * from './Gauge';
