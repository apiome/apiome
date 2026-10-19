import SchemaRegistryClient from './SchemaRegistryClient';

/**
 * Workspace → Schema registry — `/ade/dashboard/schema-registry` (CDG-4.5, #5977).
 *
 * Thin server component: all state lives in the client component, matching the other dashboard
 * screens.
 */
export default function SchemaRegistryPage() {
  return <SchemaRegistryClient />;
}
