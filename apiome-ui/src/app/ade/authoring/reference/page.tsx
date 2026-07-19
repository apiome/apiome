/**
 * `/ade/authoring/reference` — primitive reference gallery (UXE-1.3).
 *
 * A development and review aid rather than a product surface. It is not
 * registered in `AUTHORING_SURFACES`, so it stays out of the suite dropdown,
 * the secondary navigation and the command palette, and it needs no entitlement
 * of its own — it renders fixtures and reads no tenant data.
 */

import AuthoringReferenceGallery from '../components/AuthoringReferenceGallery';

export const metadata = {
  title: 'Apiome: Authoring primitives',
  description: 'Reference rendering of every shared Authoring primitive and state.',
};

export default function AuthoringReferencePage() {
  return <AuthoringReferenceGallery />;
}
