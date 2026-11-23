'use client';

/**
 * The card an error boundary shows (DBP-1.16, #7199): what happened in one line, what to do, and a
 * button that renders the route again.
 *
 * It reuses the reader sign-in card's classes (`portal-*` in `globals.css`), which are plain
 * token-based card styles, so both themes follow the palette.
 */
export function ErrorPanel({
  title,
  body,
  onRetry,
}: {
  /** The headline, as a sentence. */
  title: string;
  /** What the visitor can do about it. */
  body: string;
  /** Renders the failed route again (Next's `reset`). */
  onRetry: () => void;
}) {
  return (
    <main className="portal-page" role="alert">
      <div className="portal-card">
        <p className="portal-eyebrow">Something went wrong</p>
        <h1 className="portal-title">{title}</h1>
        <p className="portal-body">{body}</p>
        <div className="portal-form">
          <button type="button" className="portal-button" onClick={onRetry}>
            Try again
          </button>
        </div>
      </div>
    </main>
  );
}
