import GuideEditorClient from './GuideEditorClient';

/**
 * Guide editor route (GOV-2.2, #4434): `/ade/dashboard/style-guides/{guideId}`.
 *
 * A thin server wrapper that unwraps the dynamic `guideId` and renders the client editor,
 * mirroring the other dashboard detail routes. The editor's rule catalog tab renders from
 * the `/api/style-guides/{guideId}/rules` proxy.
 */
export default async function GuideEditorPage({
  params,
}: {
  params: Promise<{ guideId: string }>;
}) {
  const { guideId } = await params;
  return <GuideEditorClient guideId={guideId} />;
}
