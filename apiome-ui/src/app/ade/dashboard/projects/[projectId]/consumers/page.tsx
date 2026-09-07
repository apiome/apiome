import ConsumersClient from './ConsumersClient';

/**
 * Consumer registry route (CTG-4.1, #4479):
 * `/ade/dashboard/projects/{projectId}/consumers`.
 *
 * A thin server wrapper that unwraps the dynamic segment and renders the client screen,
 * mirroring the other dashboard detail routes. The segment carries whatever the caller linked
 * with — a project id from the projects list, or a slug from a bookmark — and REST resolves
 * either, so no lookup happens here.
 *
 * @param props.params The route's dynamic segments.
 * @returns The consumers screen.
 */
export default async function ProjectConsumersPage({
  params,
}: {
  params: Promise<{ projectId: string }>;
}) {
  const { projectId } = await params;
  return <ConsumersClient projectRef={projectId} />;
}
