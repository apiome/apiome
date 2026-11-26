/**
 * Turn a caught failure into the sentence to show (PFX-5.1, #6945).
 *
 * @param error - Whatever was caught.
 * @param fallback - What to say when the failure carried no message.
 * @returns The sentence.
 */
export function describeFailure(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}
