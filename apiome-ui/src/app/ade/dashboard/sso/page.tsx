import SsoClient from './SsoClient';

/**
 * Workspace → Single sign-on — `/ade/dashboard/sso` (EID-1.2, #5012).
 *
 * Thin server component: all state lives in the client component, matching the other dashboard
 * screens.
 */
export default function SsoPage() {
  return <SsoClient />;
}
