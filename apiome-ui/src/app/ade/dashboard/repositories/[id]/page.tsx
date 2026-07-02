import { redirect } from 'next/navigation';

/** Repository id root redirects to the default detail route (`preview` tab). */
export default async function RepositoryIdPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  redirect(`/ade/dashboard/repositories/${id}/preview`);
}
