/**
 * Back-compat shim (MFI-28.7, #4123).
 *
 * `McpDisclosure` was promoted to the format-neutral `ui/code/Disclosure`. This module keeps the old
 * name and import path working for the MCP screens; new code should import `Disclosure` from
 * `@/app/components/ui/code` instead.
 */
export { Disclosure as McpDisclosure } from '../code/Disclosure';
export type { DisclosureProps as McpDisclosureProps } from '../code/Disclosure';
