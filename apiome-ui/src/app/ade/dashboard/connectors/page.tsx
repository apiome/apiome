import ConnectorsClient from './ConnectorsClient';

/**
 * `/ade/dashboard/connectors` — Bring in → Connectors (CDG-1.7, #5958).
 *
 * A thin route shell: the list needs the session, so the whole of it is a client component.
 *
 * @returns The connectors page.
 */
export default function ConnectorsPage() {
  return <ConnectorsClient />;
}
