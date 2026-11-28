import { MigrateWizardClient } from '@/app/components/ade/pactMigrate';

/**
 * `/ade/dashboard/pacts/migrate` — **Migrate from a broker** (PFX-8.16, #7313): the four-step wizard
 * for `apiome pact migrate` — Connect, Choose, Copy, Switch over — and the **Past migrations** drawer.
 * The migration runs on the server (`POST /v1/tenants/{t}/pact-migration/runs`); the wizard reads it
 * through the `/api/pact/migrations*` proxies. A thin server wrapper.
 *
 * @returns The page.
 */
export default function PactMigratePage() {
  return <MigrateWizardClient />;
}
