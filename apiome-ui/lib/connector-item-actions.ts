/**
 * The row actions REST accepts on a connector inventory item (CDG-1.6, #5957).
 *
 * Kept apart from `@lib/connectors-proxy` (which imports `next/server`) so the browser hook and its
 * tests can name the actions without pulling in server code.
 */

/** Link, ignore, unignore, import — `POST …/connectors/{id}/items/{itemId}/{action}`. */
export const CONNECTOR_ITEM_ACTIONS = ['link', 'ignore', 'unignore', 'import'] as const;

/** One of {@link CONNECTOR_ITEM_ACTIONS}. */
export type ConnectorItemAction = (typeof CONNECTOR_ITEM_ACTIONS)[number];

/**
 * Whether `value` names a row action REST accepts.
 *
 * @param value - The `[action]` route segment.
 */
export function isConnectorItemAction(value: string): value is ConnectorItemAction {
  return (CONNECTOR_ITEM_ACTIONS as readonly string[]).includes(value);
}
