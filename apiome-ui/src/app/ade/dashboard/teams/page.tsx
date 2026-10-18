import TeamsClient from './TeamsClient';

/**
 * Workspace → Teams — `/ade/dashboard/teams` (CDG-2.4, #5963).
 *
 * Thin server component: all state lives in the client component, matching the other dashboard
 * screens.
 */
export default function TeamsPage() {
  return <TeamsClient />;
}
