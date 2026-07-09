import PublishedVersions from './PublishedVersions';

// Resolve the REST API base URL on the SERVER at request time and pass it to the
// client component. `NEXT_PUBLIC_*` values are inlined into client bundles at build
// time, so a client component cannot pick up a runtime override — when the Docker
// image is built without the var, the client would forever use the localhost
// fallback (the bug behind "Swagger UI" / "View" links pointing at localhost:8000).
// `force-dynamic` guarantees this runs per-request rather than being prerendered
// (and frozen) at build time.
export const dynamic = 'force-dynamic';

export default function PublishedVersionsPage() {
  const restApiBaseUrl =
    process.env.NEXT_PUBLIC_REST_API_BASE_URL || 'http://localhost:8000/v1';
  // Same env var and default the REST service uses to compute mock URLs (#4422, SIM-2.1),
  // so the published page can show each row's stable mock base URL without extra REST calls.
  const mockApiBaseUrl =
    process.env.APIOME_MOCK_PUBLIC_BASE_URL || 'http://localhost:8775';
  return <PublishedVersions restApiBaseUrl={restApiBaseUrl} mockApiBaseUrl={mockApiBaseUrl} />;
}
