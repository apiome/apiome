/**
 * The one callout a Contracts settings tab shows when the caller lacks the Contracts admin permission
 * (`pacts:delete`) — every control on the tab is then read-only (mockup Notes → States).
 *
 * @param props - What the tab would let an admin change, for the sentence.
 * @returns The callout.
 */
export function ReadOnlyNote({
  what = 'these settings',
  testId = 'pcx-read-only',
}: {
  what?: string;
  testId?: string;
}) {
  return (
    <div className="pcx-callout" role="note" data-testid={testId}>
      You can read {what}. Changing them needs the Contracts admin permission (pacts:delete).
    </div>
  );
}

export default ReadOnlyNote;
