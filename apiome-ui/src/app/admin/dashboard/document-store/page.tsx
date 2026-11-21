import DocumentStoreClient from './DocumentStoreClient';

/**
 * Document store (`/admin/dashboard/document-store`, COA-5.9, #7085).
 *
 * Auth gating happens in the shared dashboard layout (`../layout.tsx` redirects to `/admin`
 * without a valid signed session), and every read goes through the super-admin proxy routes
 * (`/api/admin/document-store`), which verify the session again.
 */
export default function AdminDocumentStorePage() {
  return <DocumentStoreClient />;
}
