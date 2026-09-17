/**
 * Branch-to-draft binding surfaces — GNC-2.1 (#4737) and GNC-2.3 (#4739).
 *
 * The rules behind them (wire shapes, tones, sentences) live in `@lib/draft-bindings` and
 * `@lib/spec-sync`, which are framework-free and shared with the BFF routes.
 */

export { VersionBindingPanel } from './VersionBindingPanel';
export type { BindableVersion, VersionBindingPanelProps } from './VersionBindingPanel';
export { VersionSyncPanel } from './VersionSyncPanel';
export type { VersionSyncPanelProps } from './VersionSyncPanel';
