import StyleGuidesClient from './StyleGuidesClient';

/**
 * Control Panel → Governance → Style Guides (GOV-2.1, #4433).
 *
 * Thin server component: all state lives in the client component, matching the other
 * dashboard screens (see roles/page.tsx).
 */
export default function StyleGuidesPage() {
  return <StyleGuidesClient />;
}
