/** Server-log wording for email sign-up failures (`email-signup-actions.ts`). */

/**
 * A sign-up failure for the server log: the error's name and message, with any email address
 * replaced, so the log says what went wrong without recording who was signing up.
 *
 * @param error What the sign-up threw.
 * @returns For example `Error: user insert failed: User with this email already exists`.
 */
export function describeSignupError(error: unknown): string {
  if (!(error instanceof Error)) return 'unknown error';
  const message = error.message.replace(/[^\s@<>()"',;:]+@[^\s@<>()"',;:]+/g, '<email>');
  return message ? `${error.name}: ${message}` : error.name;
}
