import ShadowApisClient from './ShadowApisClient';

/**
 * `/ade/dashboard/connectors/shadow` — the shadow-API report (CDG-1.6, #5957).
 *
 * A thin route shell, like `notifications/page.tsx`: the report needs the session, so the whole of
 * it is a client component.
 *
 * @returns The shadow-API report page.
 */
export default function ShadowApisPage() {
  return <ShadowApisClient />;
}
