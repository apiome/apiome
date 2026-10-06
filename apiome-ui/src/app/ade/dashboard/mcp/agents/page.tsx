import AgentAccessClient from './AgentAccessClient';

/**
 * MCP → Agent access (AGX-3.4, #4540).
 *
 * Thin server component: every piece of state lives in the client component, matching the other
 * MCP section screens (see `../analytics/page.tsx`).
 */
export default function AgentAccessPage() {
  return <AgentAccessClient />;
}
