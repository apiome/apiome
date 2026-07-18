/**
 * Global setup for the OLO-7.4 journey suite (#4226): fail fast, with actionable
 * messages, when the non-mocked half of the stack is missing. The journey needs the
 * real REST API and Postgres (docker compose spine) — without them every test would
 * fail later with opaque UI timeouts.
 */
import { Client } from 'pg';
import { databaseUrl, restApiBaseUrl } from './env';

/** Probe REST readiness and database connectivity before any test runs. */
export default async function globalSetup(): Promise<void> {
  const restRoot = restApiBaseUrl().replace(/\/v1\/?$/, '');
  try {
    const response = await fetch(`${restRoot}/readyz`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
  } catch (error) {
    throw new Error(
      `apiome-rest is not reachable at ${restRoot} (${String(error)}). ` +
        'Start the spine first: `docker compose up --wait` from the repo root.'
    );
  }

  const client = new Client({ connectionString: databaseUrl() });
  try {
    await client.connect();
    await client.query('SELECT 1');
  } catch (error) {
    throw new Error(
      `Postgres is not reachable via DATABASE_URL (${String(error)}). ` +
        'Start the spine first: `docker compose up --wait` from the repo root.'
    );
  } finally {
    await client.end().catch(() => undefined);
  }
}
