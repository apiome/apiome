/**
 * Shared MCP UI primitives (V2-MCP-24.7 / MCAT-10.7).
 *
 * The token-driven component library every MCP catalog screen reuses — the grade glyph, the
 * tone-based badge, health & recency pills, the finding-severity chip, and the detail tab shell.
 * Pair these React components with the pure mapping helpers in
 * `@/app/components/ade/dashboard/mcp/mcpUiPrimitives` (tones, grade styles, health/recency, tab
 * definitions) so consumers pass domain values, never colors or spacing.
 */
export * from './GradeGlyph';
export * from './McpBadge';
export * from './HealthPill';
export * from './RecencyPill';
export * from './ServerProfileCard';
export * from './FindingSeverity';
export * from './DetailTabs';
export * from './McpJsonViewer';
export * from './McpJsonDiffViewer';
export * from './McpDisclosure';
// Token-driven SVG chart kit (V2-MCP-28.3): Sparkline, BarSeries, Donut, StackedTimeline, Radar,
// Heatmap, Gauge + their pure token/geometry helpers.
export * from './charts';
