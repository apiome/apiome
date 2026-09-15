'use client';

/**
 * The sticky decision bar of the review page — COL-2.2 (#4518).
 *
 * It sits at the foot of the page's scroll container (`position: sticky`, like the style-guide save
 * bar), so the reviewer can decide from whichever tab they are reading without scrolling back.
 *
 * What it offers comes from `decisionBarModel` in `@lib/review-page`, which follows apiome-rest's
 * refusals: only a pending reviewer of a round that can still take decisions sees the form. Everyone
 * else sees one sentence saying why there is nothing to decide — already decided, the round was
 * decided by a change request, the spec changed, not a reviewer, or withdrawn.
 *
 * **Request changes needs a note.** Pressing it with a blank note puts the field in its error state
 * (announced through `FormField`'s alert) and moves focus into it instead of sending anything. The
 * BFF route checks the same rule, so a hand-built request cannot skip it.
 */

import * as React from 'react';
import {
  Check,
  CheckCircle2,
  CircleSlash,
  Clock,
  Eye,
  MessageSquareWarning,
  TriangleAlert,
  type LucideIcon,
} from 'lucide-react';

import { Alert } from '@/app/components/ui/Alert';
import { Button } from '@/app/components/ui/Button';
import { FormField } from '@/app/components/ui/FormField';
import { Spinner } from '@/app/components/ui/Spinner';
import { Textarea } from '@/app/components/ui/Textarea';
import {
  validateDecisionNote,
  type DecisionBarMode,
  type DecisionBarModel,
  type RecordableDecision,
} from '@lib/review-page';

/** The glyph beside each read-only sentence. */
const STATUS_GLYPH: Readonly<Record<Exclude<DecisionBarMode, 'decide'>, LucideIcon>> = {
  decided: CheckCircle2,
  'round-decided': Clock,
  stale: TriangleAlert,
  'not-reviewer': Eye,
  withdrawn: CircleSlash,
};

export interface ReviewDecisionBarProps {
  /** What the bar offers the viewer. */
  model: DecisionBarModel;
  /** Whether a decision is being recorded; the buttons wait for it. */
  submitting: boolean;
  /** Why the last decision was not recorded, when it was not. */
  error: string | null;
  /**
   * Record a decision.
   *
   * @returns True when it was recorded, which clears the note.
   */
  onSubmit: (decision: RecordableDecision, note: string) => Promise<boolean>;
}

/**
 * The decision bar.
 *
 * @param props - See {@link ReviewDecisionBarProps}.
 * @returns The bar.
 */
export function ReviewDecisionBar({ model, submitting, error, onSubmit }: ReviewDecisionBarProps) {
  const noteId = React.useId();
  const noteRef = React.useRef<HTMLTextAreaElement>(null);
  const [note, setNote] = React.useState('');
  const [noteError, setNoteError] = React.useState<string | null>(null);
  const [pending, setPending] = React.useState<RecordableDecision | null>(null);
  const [focusRequest, setFocusRequest] = React.useState(0);

  // Focus the note after the error has rendered: `FormField` re-clones its control to mark it
  // invalid, so a focus call made before that commit would land on a node that is then replaced.
  React.useEffect(() => {
    if (focusRequest > 0) noteRef.current?.focus();
  }, [focusRequest]);

  /**
   * Check the note, then record the decision.
   *
   * @param decision - The button pressed.
   */
  const submit = async (decision: RecordableDecision) => {
    const problem = validateDecisionNote(decision, note);
    if (problem) {
      setNoteError(problem);
      setFocusRequest((count) => count + 1);
      return;
    }
    setNoteError(null);
    setPending(decision);
    const recorded = await onSubmit(decision, note);
    setPending(null);
    if (recorded) setNote('');
  };

  const errorAlert = error ? (
    <Alert variant="error" data-testid="review-decision-error">
      {error}
    </Alert>
  ) : null;

  if (model.mode !== 'decide') {
    const Glyph =
      model.mode === 'decided' && model.mine?.decision === 'request_changes'
        ? MessageSquareWarning
        : STATUS_GLYPH[model.mode];
    return (
      <section
        className="rvw-decision"
        aria-label="Your decision"
        data-testid="review-decision-bar"
        data-mode={model.mode}
      >
        {errorAlert}
        <div className="rvw-decision__status" role="status">
          <Glyph aria-hidden className="rvw-decision__glyph" />
          <span className="rvw-decision__message" data-testid="review-decision-message">
            {model.message}
          </span>
        </div>
        {model.mode === 'decided' && model.mine?.note ? (
          <blockquote className="rvw-decision__quote" data-testid="review-decision-own-note">
            {model.mine.note}
          </blockquote>
        ) : null}
      </section>
    );
  }

  return (
    <section className="rvw-decision" aria-label="Your decision" data-testid="review-decision-bar" data-mode="decide">
      {errorAlert}
      <FormField
        label="Note"
        htmlFor={noteId}
        helperText="Optional when approving. Required when requesting changes."
        error={noteError ?? undefined}
        className="rvw-decision__field"
      >
        <Textarea
          ref={noteRef}
          id={noteId}
          rows={2}
          value={note}
          disabled={submitting}
          onChange={(event) => {
            setNote(event.target.value);
            if (noteError) setNoteError(null);
          }}
          data-testid="review-decision-note"
        />
      </FormField>
      <div className="rvw-decision__foot">
        <span className="rvw-decision__message" data-testid="review-decision-message">
          {model.message}
        </span>
        <div className="rvw-decision__actions">
          <Button
            variant="outline"
            disabled={submitting}
            onClick={() => void submit('request_changes')}
            data-testid="review-request-changes"
          >
            {pending === 'request_changes' ? <Spinner size="sm" aria-hidden /> : <MessageSquareWarning aria-hidden />}
            Request changes
          </Button>
          <Button disabled={submitting} onClick={() => void submit('approve')} data-testid="review-approve">
            {pending === 'approve' ? <Spinner size="sm" aria-hidden /> : <Check aria-hidden />}
            Approve
          </Button>
        </div>
      </div>
    </section>
  );
}
