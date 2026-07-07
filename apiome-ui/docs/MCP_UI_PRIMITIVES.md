# MCP UI primitives (V2-MCP-24.7 / MCAT-10.7)

The shared, **token-driven** component library every MCP catalog screen reuses — the grade glyph,
the tone-based badge, health & recency pills, the finding-severity chip, the detail tab shell, and
the empty / loading / error states. These primitives exist **before** the screens that consume them
(10.1 nav + import source, 10.2 Overview + Capabilities, 10.4 Lint & Score, 10.8 Catalog grid) so
those screens never re-implement the visual atoms or scatter color/spacing literals — which is what
keeps a central dark theme (10.10) addable in one place.

> **Live gallery:** run the app and open [`/design-system/mcp`](../src/app/design-system/mcp/page.tsx)
> to see every primitive in every variant (the Storybook-equivalent for this codebase).

## Where things live

| Layer | Path | What |
| --- | --- | --- |
| Pure helpers (React-free, unit-tested) | `src/app/components/ade/dashboard/mcp/mcpUiPrimitives.ts` | Grade styles, badge-tone resolvers, health/recency, tab definitions |
| React components | `src/app/components/ui/mcp/` | `GradeGlyph`, `McpBadge`, `HealthPill`, `RecencyPill`, `FindingSeverity`, `DetailTabs` |
| Shared states | `src/app/components/ui/{EmptyState,LoadingState,ErrorState}.tsx` | empty / loading / error placeholders |
| Barrel | `@/app/components/ui/mcp` (also re-exported from `@/app/components/ui`) | one import for all MCP primitives |

**Design principle:** consumers pass *domain values* (a transport string, a discovery status, an ISO
timestamp) and the primitive picks the color, never the other way round. Colors are Tailwind utility
classes — the project's token layer, mapped centrally (with `dark:` variants) in `globals.css`. No
hex or spacing literal ever appears in a consumer.

## Components

### `<GradeGlyph>`

The A–F + 0–100 grade signal — the lead glyph on cards, headers, and the lint gauge.

```tsx
<GradeGlyph grade="B" score={82} />                    {/* solid chip: B · 82 */}
<GradeGlyph score={94} />                               {/* letter derived from score → A */}
<GradeGlyph variant="gauge" size="lg" grade="A" score={91} /> {/* 0–100 ring */}
<GradeGlyph />                                          {/* unscored → neutral chip */}
```

| Prop | Type | Notes |
| --- | --- | --- |
| `grade` | `string \| null` | A–F; derived from `score` when omitted |
| `score` | `number \| null` | 0–100; shown unless `showScore={false}` |
| `variant` | `'glyph' \| 'gauge'` | square chip (default) or ring |
| `size` | `'sm' \| 'md' \| 'lg'` | |

### `<McpBadge tone=…>`

The seven-tone badge (`indigo`, `green`, `amber`, `red`, `blue`, `slate`, `violet`) backing the
transport / visibility / auth / capability-annotation chips. Resolve a domain value with the helpers,
then render:

```tsx
const t = mcpTransportBadge(endpoint.transport);   // { tone, label }
<McpBadge tone={t.tone}>{t.label}</McpBadge>

const a = mcpAnnotationHints(item)                 // existing helper
  .map((h) => mcpCapabilityAnnotationBadge(h.key, h.value))
  .filter(Boolean);                                // only asserted hints
```

Resolvers (in `mcpUiPrimitives.ts`): `mcpTransportBadge`, `mcpVisibilityBadge`, `mcpAuthBadge`,
`mcpCapabilityAnnotationBadge`.

### `<HealthPill>`

Endpoint reachability as a colored dot + label: `healthy` (green), `degraded` (amber),
`unreachable` (red), `unknown` (slate). Pass an explicit `status`, or a raw `discoveryStatus` to
have it resolved via `mcpHealthFromDiscoveryStatus`.

```tsx
<HealthPill status="healthy" />
<HealthPill discoveryStatus="unchanged" /> {/* → Healthy (successful auto-refresh) */}
<HealthPill discoveryStatus="changed" />   {/* → Healthy (surface updated) */}
<HealthPill discoveryStatus="failed" />    {/* → Unreachable */}
<HealthPill status="degraded" dotOnly />   {/* dot only, label kept for screen readers */}
```

### `<RecencyPill>`

The "Last discovered …" chip: a clock icon + a short relative span (`just now` / `5m ago` /
`2h ago` / `3d ago`), falling back to an absolute date past ~30 days. Formatting is delegated to the
unit-tested `mcpRelativeTime(iso, nowMs)` helper.

```tsx
<RecencyPill timestamp={endpoint.last_discovered_at} />
<RecencyPill timestamp={ts} prefix="Discovered" hideIcon />
```

### `<FindingSeverity>`

The shared MUST / SHOULD / Advisory chip used by the Lint & Score tab and inline hints. It renders
through the project `Badge` in the tier's variant, reading label + variant from the single source of
truth in `mcpLintUi` so styling never drifts.

```tsx
<FindingSeverity tier="must" />
<FindingSeverity severity="warning" count={5} />   {/* "SHOULD 5" */}
```

### `<DetailTabs>`

The mockup's underline detail strip (vs. the segmented `Tabs` primitive). Built on Radix tabs, so
it stays keyboard-accessible and controllable. The canonical seven-tab set is `MCP_DETAIL_TABS`
(Overview · Capabilities · Versions · Lint & Score · Test · Credentials · Settings); a screen may
auto-render the full set or any subset.

```tsx
<DetailTabs value={tab} onValueChange={setTab}>
  <DetailTabsList items={MCP_DETAIL_TABS} only={['capabilities', 'lint', 'versions']} />
  <DetailTabsContent value="capabilities">…</DetailTabsContent>
  <DetailTabsContent value="lint">…</DetailTabsContent>
  <DetailTabsContent value="versions">…</DetailTabsContent>
</DetailTabs>
```

### Empty / loading / error states

`<EmptyState>`, `<LoadingState>`, and the new `<ErrorState>` (red-tinted, with an optional
`onRetry`) complete the placeholder trio for any panel that has no data, is loading, or failed.

## Chart kit (V2-MCP-28.3 / MCAT-14.3)

A small, hand-rolled **SVG** primitive set in `src/app/components/ui/mcp/charts/` (re-exported from
`@/app/components/ui/mcp`) so every insight panel gets charts without a heavyweight dependency
(`mermaid` remains the only chart-ish dep; revisit Recharts/visx only if a panel outgrows SVG). Each
chart follows the same principle as the rest of this kit — **consumers pass domain data, the chart
picks the color from Tailwind tokens** — and is:

- **Accessible** — the SVG is `role="img"` with a `<title>`/`<desc>`, and a visually-hidden
  (`sr-only`) `<table>` carries the underlying numbers for screen readers / no-CSS.
- **Responsive** — sized by `viewBox`; set height/size with a `className` on the chart.
- **SSR-safe** — no DOM/`window` access; gradient ids come from `React.useId`.
- **Empty-safe** — empty / degenerate data renders a small empty state, never a crash.

| Component | Shape | Typical use |
| --- | --- | --- |
| `<Sparkline data tone domainMax area />` | axis-free trend line + area | grade/latency over time (inline) |
| `<BarSeries data tone domainMax />` | vertical bars (per-bar `tone` override) | capability counts by type, findings by severity |
| `<Donut segments centerLabel />` | proportional ring | transport / auth-scheme share |
| `<StackedTimeline series periods />` | stacked bars over an ordered axis | per-version churn (added/changed/removed) |
| `<Radar axes max tone />` | multi-axis profile (≥ 3 axes) | documentation / annotation / safety coverage |
| `<Heatmap matrix rowLabels colLabels tone />` | intensity grid (opacity = magnitude) | activity by day×hour, error rate by tool×version |
| `<Gauge value min max tone centerLabel />` | 270° dial | a bounded score; `0–100` auto-colors by score band |

```tsx
import { Sparkline, Donut, Gauge } from '@/app/components/ui/mcp';

<Sparkline data={[62, 65, 61, 70, 80]} tone="emerald" />
<Donut segments={[{ label: 'http', value: 12 }, { label: 'sse', value: 8 }]} centerLabel="20" />
<Gauge value={94} />                                   {/* 0–100 → colored by score band */}
<Gauge value={420} min={0} max={1000} tone="blue" centerLabel="420ms" />
```

**Color is never a literal.** Series colors resolve through `chartTokens.ts`: a semantic
`ChartSeriesTone` (`indigo`, `emerald`, `amber`, `red`, `blue`, `violet`, `green`, `orange`, `cyan`,
`pink`, `neutral`) → `fill-*` / `stroke-*` / `text-*` utilities with `dark:` variants, plus a stable
categorical order (`chartCategoricalTone`) for series that don't pin a tone. The pure coordinate math
lives in `chartGeometry.ts` (sparkline points, donut/gauge arcs, radar polygons, cell intensity).

## Theming (10.10)

Every color is a Tailwind class with a `dark:` counterpart, resolved centrally. A new theme adds its
variant in `globals.css` / Tailwind config — never by touching a primitive or a consumer. Because no
consumer hard-codes a color, a dark variant lands in one place.

## Tests

- `tests/mcp-ui-primitives.test.ts` — the pure mappings (grade, badge tones, health, recency, tabs).
- `tests/mcp-primitives-components.test.tsx` — render coverage for every component variant.
- `tests/mcp-chart-tokens.test.ts` — chart tone → class mapping (no color literals, cyclic palette).
- `tests/mcp-chart-geometry.test.ts` — the pure chart coordinate math (arcs, points, intensity).
- `tests/mcp-charts.test.tsx` — render + snapshot coverage for every chart, incl. empty states.
