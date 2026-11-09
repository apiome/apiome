import McpOAuthCallbackClient from './McpOAuthCallbackClient';

/**
 * MCP → OAuth callback (V2-MCP-20.4 / MCAT-6.4, #3680).
 *
 * The page an authorization server sends the user back to after they consent. Thin server
 * component: the client finishes the connection and returns to the endpoint's Settings tab.
 */
export default function McpOAuthCallbackPage() {
  return <McpOAuthCallbackClient />;
}
