import AddConnectorClient from './AddConnectorClient';

/**
 * `/ade/dashboard/connectors/new` — the add-connector wizard (CDG-1.7, #5958).
 *
 * @returns The wizard page.
 */
export default function AddConnectorPage() {
  return <AddConnectorClient />;
}
