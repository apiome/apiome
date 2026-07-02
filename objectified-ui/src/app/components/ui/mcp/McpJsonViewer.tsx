/**
 * Back-compat shim (MFI-28.7, #4123).
 *
 * `McpJsonViewer` was promoted to the format-neutral `ui/code/JsonViewer`. This module keeps the old
 * name and import path working for the MCP screens; new code should import `JsonViewer` from
 * `@/app/components/ui/code` instead.
 */
export { JsonViewer as McpJsonViewer } from '../code/JsonViewer';
export type { JsonViewerProps as McpJsonViewerProps } from '../code/JsonViewer';
