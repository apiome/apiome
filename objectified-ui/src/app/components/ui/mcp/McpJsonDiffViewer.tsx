/**
 * Back-compat shim (MFI-28.7, #4123).
 *
 * `McpJsonDiffViewer` was promoted to the format-neutral `ui/code/JsonDiffViewer`. This module keeps
 * the old name (and the `McpDiffMode` alias) working for the MCP screens; new code should import
 * `JsonDiffViewer` / `DiffMode` from `@/app/components/ui/code` instead.
 */
export { JsonDiffViewer as McpJsonDiffViewer } from '../code/JsonDiffViewer';
export type {
  JsonDiffViewerProps as McpJsonDiffViewerProps,
  DiffMode as McpDiffMode,
} from '../code/JsonDiffViewer';
