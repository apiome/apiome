/**
 * Branch-to-draft binding surfaces — GNC-2.1 (#4737).
 *
 * The rules behind them (wire shapes, tones, sentences) live in `@lib/draft-bindings`, which is
 * framework-free and shared with the BFF routes.
 */

export { VersionBindingPanel } from './VersionBindingPanel';
export type { BindableVersion, VersionBindingPanelProps } from './VersionBindingPanel';
