/**
 * `/ade/authoring` — Authoring Overview (UXE-1.2).
 *
 * The readiness and work-queue blueprint is UXE-2.1; this route delivers the
 * shell-level Overview: resume, scope selection and destinations.
 */

import AuthoringOverview from './components/AuthoringOverview';

export default function AuthoringOverviewPage() {
  return <AuthoringOverview />;
}
