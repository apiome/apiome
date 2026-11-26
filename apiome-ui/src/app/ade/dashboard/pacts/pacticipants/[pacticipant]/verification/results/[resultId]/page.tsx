import { VerificationResultClient } from '@/app/components/ade/pactVerification';

/**
 * `/ade/dashboard/pacts/pacticipants/{provider}/verification/results/{id}` — one verification
 * result: each interaction's expected and actual values, the requests sent, the raw log with Copy
 * and Download, and **Re-run verification** (PFX-5.5, #6949). A thin server wrapper that unwraps
 * the handle and the result id.
 *
 * @param props - The route params.
 * @returns The page.
 */
export default async function VerificationResultPage({
  params,
}: {
  params: Promise<{ pacticipant: string; resultId: string }>;
}) {
  const { pacticipant, resultId } = await params;
  return <VerificationResultClient slug={pacticipant} resultId={resultId} />;
}
